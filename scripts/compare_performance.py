"""Compare performance.py records in the same environment; never modify input evidence."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import statistics


def load(folder):
    return (json.loads((folder/'environment.json').read_text(encoding='utf-8-sig')),
            json.loads((folder/'results.json').read_text(encoding='utf-8-sig')))


def compare(before, after):
    a, ar = before
    b, br = after
    for key in ('platform', 'go', 'gomaxprocs', 'measurement'):
        if key not in a or key not in b or a[key] != b[key]:
            raise ValueError(f'incomparable or missing environment: {key}')
    for key in ('samples', 'warmup', 'batch', 'no_collector'):
        if key not in a['parameters'] or key not in b['parameters'] or a['parameters'][key] != b['parameters'][key]:
            raise ValueError(f'incomparable or missing parameter: {key}')
    key = lambda r: (r['nodes'], r['browsers'], r['batch'], r['collector'])
    rows = []
    for group in sorted({key(r) for r in ar+br}):
        row = dict(zip(('nodes', 'browsers', 'batch', 'collector'), group))
        for label, env, data in [('baseline', a, ar), ('candidate', b, br)]:
            trials = [r for r in data if key(r) == group]
            complete = [r for r in trials if r['result'] == 'PASS' and r.get('attempts') == env['parameters']['samples']
                        and r.get('successes') == r['attempts'] and not r.get('failures')]
            row[label] = {'attempted_rounds': len(trials), 'planned_rounds': env['parameters']['rounds'],
                          'passed_rounds': len(complete), 'failed_rounds': sum(r['result'] == 'FAIL' for r in trials),
                          'interrupted_rounds': sum(r['result'] == 'INTERRUPTED' for r in trials),
                          'successful_requests': sum(r.get('successes', 0) for r in trials)}
            for metric in ('p50_seconds', 'p95_seconds'):
                values = [r[metric] for r in complete if r.get(metric) is not None]
                row[label][metric] = statistics.median(values) if values else None
                if metric == 'p95_seconds':
                    row[label]['p95_range_seconds'] = [min(values), max(values)] if values else None
        rows.append(row)
    return rows


def render(rows):
    lines = ['# 同环境延迟比较', '',
             '表内为各完整成功轮次的 P50/P95 中位数（毫秒），不是合并样本分位数。P95 仅针对成功请求；失败与中断单列。少量轮次不构成稳定加速或可靠 p99 结论。', '',
             '|节点/浏览器|基线成功/尝试/计划轮次|候选成功/尝试/计划轮次|基线 P50 / P95 ms|候选 P50 / P95 ms|失败 / 中断（基线；候选）|',
             '|---|---|---|---|---|---|']
    def rounds(v):
        return f"{v['passed_rounds']}/{v['attempted_rounds']}/{v['planned_rounds']}"
    def metrics(v):
        return ' / '.join('未记录' if v[k] is None else f'{v[k]*1000:.3f}' for k in ('p50_seconds','p95_seconds'))
    for r in rows:
        a, b = r['baseline'], r['candidate']
        lines.append(f"|{r['nodes']} / {r['browsers']}|{rounds(a)}|{rounds(b)}|{metrics(a)}|{metrics(b)}|{a['failed_rounds']} / {a['interrupted_rounds']}；{b['failed_rounds']} / {b['interrupted_rounds']}|")
    maximum = max((v['p95_range_seconds'][1] for r in rows for v in [r['baseline'],r['candidate']] if v['p95_range_seconds']), default=1) or 1
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="420" viewBox="0 0 1100 420">',
           '<rect width="1100" height="420" fill="#f5f7f5"/>',
           '<g font-family="sans-serif" fill="#263c35" font-size="13">',
           '<text x="40" y="28">每轮 P95 的中位数；范围为轮次最小/最大。纵轴毫秒，横轴节点数/浏览器数。</text>',
           '<text x="40" y="50">基线：灰蓝 · 候选：青绿 · 缺失结果不绘点</text>']
    for i in range(5):
        y = 350-i*65
        svg.append(f'<path d="M70 {y}H1060" stroke="#dbe1dd"/><text x="5" y="{y+5}">{maximum*1000*i/4:.1f}</text>')
    for i, r in enumerate(rows):
        x = 100+i*930/max(1,len(rows)-1)
        svg.append(f'<text x="{x}" y="380" text-anchor="middle">{r["nodes"]}/{r["browsers"]}</text>')
        for delta, label, color in [(-6,'baseline','#728499'),(6,'candidate','#268b6b')]:
            v = r[label]
            if v['p95_seconds'] is None:
                continue
            y = lambda seconds: 350-seconds/maximum*260
            low, high = v['p95_range_seconds']
            svg.append(f'<path d="M{x+delta} {y(low)}V{y(high)}" stroke="{color}"/><circle cx="{x+delta}" cy="{y(v["p95_seconds"])}" r="4" fill="{color}"><title>{html.escape(label)}: {v["p95_seconds"]*1000:.3f} ms</title></circle>')
    svg.append('</g></svg>')
    return '\n'.join(lines)+'\n', '\n'.join(svg)+'\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    before, after = load(args.baseline), load(args.candidate)
    rows = compare(before, after)
    args.output.mkdir(parents=True, exist_ok=False)
    sources = {label: {'environment_sha256': hashlib.sha256((folder/'environment.json').read_bytes()).hexdigest(),
                       'results_sha256': hashlib.sha256((folder/'results.json').read_bytes()).hexdigest()}
               for label, folder in [('baseline',args.baseline),('candidate',args.candidate)]}
    (args.output/'comparison.json').write_text(json.dumps({'sources':sources,'groups':rows}, indent=2), encoding='utf-8')
    markdown, svg = render(rows)
    (args.output/'comparison.md').write_text(markdown, encoding='utf-8')
    (args.output/'comparison.svg').write_text(svg, encoding='utf-8')
    flat = [{**{k:v for k,v in r.items() if k not in ('baseline','candidate')},
             **{label+'_'+k:v for label in ('baseline','candidate') for k,v in r[label].items()}} for r in rows]
    with (args.output/'comparison.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(flat[0]) if flat else [])
        writer.writeheader(); writer.writerows(flat)


if __name__ == '__main__':
    main()
