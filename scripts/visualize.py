"""Render benchmark timing and observed event timelines as standalone SVG."""
import argparse
import html
import json
from pathlib import Path
import re
import textwrap


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_rows(input_dir):
    rows = load_json(input_dir / "results.json")
    if isinstance(rows, dict):
        rows = rows.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("benchmark/results.json must contain a row list")
    return rows


def batch_label(row):
    return f" · batch {row['batch_size']}" if "batch_size" in row else ""


def group_rows(rows):
    groups = {}
    for row in rows:
        key = (str(row.get("scenario", "unknown")), int(row.get("nodes", 0)), row.get("batch_size"))
        groups.setdefault(key, []).append(row)
    return groups


def svg_text(x, y, value, size=14, anchor="start", fill="#243447", weight="normal"):
    return (f'<text x="{x}" y="{y}" font-family="Arial, Noto Sans CJK SC, sans-serif" '
            f'font-size="{size}" text-anchor="{anchor}" fill="{fill}" font-weight="{weight}">'
            f'{html.escape(str(value))}</text>')


def performance_svg(rows, environment):
    groups = group_rows(rows)
    scenarios = sorted({key[0] for key in groups})
    width, panel_h, left, right, top = 900, 270, 90, 35, 55
    height = top + max(1, len(scenarios)) * panel_h + 45
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           svg_text(width / 2, 28, "Benchmark performance · successful elapsed time only", 19, "middle", weight="bold")]
    env_note = ""
    if environment:
        env_note = "Environment: " + ", ".join(str(environment[k]) for k in ("platform", "go", "python") if k in environment)
        env_note = textwrap.shorten(env_note, width=110, placeholder="...")
    out.append(svg_text(left, 48, env_note, 11, fill="#536273"))
    for si, scenario in enumerate(scenarios):
        base_y = top + si * panel_h
        xs = sorted({key[1] for key in groups if key[0] == scenario})
        series = sorted({key[2] for key in groups if key[0] == scenario}, key=lambda x: -1 if x is None else int(x))
        max_time = max((float(r["elapsed_seconds"]) for key, rs in groups.items() if key[0] == scenario for r in rs
                        if r.get("result") == "PASS" and isinstance(r.get("elapsed_seconds"), (int, float))), default=1) or 1
        max_time *= 1.15
        y0, plot_h = base_y + 34, 165
        out.append(svg_text(left, base_y + 20, scenario, 15, weight="bold"))
        out.append(f'<line x1="{left}" y1="{y0 + plot_h}" x2="{width-right}" y2="{y0 + plot_h}" stroke="#526273"/>')
        out.append(f'<line x1="{left}" y1="{y0}" x2="{left}" y2="{y0 + plot_h}" stroke="#526273"/>')
        for tick in range(4):
            value = max_time * tick / 3
            y = y0 + plot_h - plot_h * tick / 3
            out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e3e8ed"/>')
            out.append(svg_text(left-9, y+4, f"{value:.3g}", 10, "end", "#536273"))
        out.append(svg_text(18, y0 + plot_h / 2, "seconds", 11, "middle", "#536273"))
        slots = max(1, len(xs) * len(series)); cell = (width-left-right) / slots
        for ni, nodes in enumerate(xs):
            for bi, batch in enumerate(series):
                key = (scenario, nodes, batch)
                trials = groups.get(key, [])
                ok = [float(r["elapsed_seconds"]) for r in trials if r.get("result") == "PASS" and isinstance(r.get("elapsed_seconds"), (int, float))]
                center = left + (ni * len(series) + bi + .5) * cell
                if ok:
                    mean = sum(ok) / len(ok); low, high = min(ok), max(ok)
                    bar_h = plot_h * mean / max_time
                    color = ["#337ab7", "#39a27a", "#d28a33", "#8956a3"][bi % 4]
                    out.append(f'<rect x="{center-cell*.27:.1f}" y="{y0+plot_h-bar_h:.1f}" width="{cell*.54:.1f}" height="{bar_h:.1f}" fill="{color}"/>')
                    out.append(svg_text(center, max(y0+12, y0+plot_h-bar_h-7), f'{mean:.3f}s', 10, 'middle'))
                    ylow, yhigh = y0+plot_h-plot_h*low/max_time, y0+plot_h-plot_h*high/max_time
                    out.append(f'<line x1="{center:.1f}" y1="{yhigh:.1f}" x2="{center:.1f}" y2="{ylow:.1f}" stroke="#202b36" stroke-width="2"/><line x1="{center-4:.1f}" y1="{yhigh:.1f}" x2="{center+4:.1f}" y2="{yhigh:.1f}" stroke="#202b36"/><line x1="{center-4:.1f}" y1="{ylow:.1f}" x2="{center+4:.1f}" y2="{ylow:.1f}" stroke="#202b36"/>')
                else:
                    out.append(svg_text(center, y0+plot_h-7, "no successful timing", 9, "middle", "#9b3232"))
                out.append(svg_text(center, y0+plot_h+17, f"{nodes} nodes", 10, "middle"))
                batch_txt = f" b{batch}" if batch is not None else ""
                out.append(svg_text(center, y0+plot_h+31, f"{len(ok)}/{len(trials)} pass{batch_txt}", 9, "middle", "#536273"))
        out.append(svg_text(width-right, base_y+20, "bar = mean; whisker = min–max; n = pass/attempts", 10, "end", "#536273"))
    out.append("</svg>")
    return "\n".join(out)


def event_rows(input_dir, rows):
    found = []
    for path in sorted(input_dir.glob("*/events.json")):
        parent = path.parent
        result_path = parent / "result.json"
        row = load_json(result_path) if result_path.exists() else None
        if row is None:
            match = re.fullmatch(r"(.+)-(\d+)-r(\d+)", parent.name)
            if match:
                scenario, nodes, rnd = match.group(1), int(match.group(2)), int(match.group(3))
                row = next((r for r in rows if str(r.get("scenario")) == scenario and int(r.get("nodes", -1)) == nodes and int(r.get("round", -1)) == rnd), None)
        if row is None:
            continue
        events = load_json(path)
        if isinstance(events, dict):
            events = events.get("events", [])
        if isinstance(events, list):
            found.append((row, events))
    return found


def timeline_svg(items):
    if not items:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="120"><rect width="100%" height="100%" fill="white"/><text x="450" y="58" text-anchor="middle" font-family="Arial, Noto Sans CJK SC, sans-serif" font-size="18">Timeline: no events recorded</text><text x="450" y="86" text-anchor="middle" font-family="Arial, Noto Sans CJK SC, sans-serif" font-size="13" fill="#536273">Wall-clock logs are not used to infer event times.</text></svg>'
    ordered = sorted(items, key=lambda pair: (str(pair[0].get("scenario", "")), int(pair[0].get("nodes", 0)), pair[0].get("batch_size", 128), int(pair[0].get("round", 0))))
    width, left, right = 1120, 350, 1050
    max_t = max((float(e["offset_seconds"]) for _, events in ordered for e in events), default=1) or 1
    heights = [70 + 17 * ((len(events)+1)//2) for _, events in ordered]
    height = 125 + sum(heights)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/>',
           svg_text(width/2, 27, "Observed event timeline · monotonic offsets", 18, "middle", weight="bold"),
           svg_text(width/2, 48, "Offsets from first process launch; not protocol-exact event times.", 12, "middle", "#536273")]
    for tick in range(5):
        out.append(svg_text(left+(right-left)*tick/4, 75, f'{max_t*tick/4:.2f}s', 10, 'middle'))
    y = 132
    for (row, events), panel_h in zip(ordered, heights):
        label = f"{row.get('scenario')} · {row.get('nodes')} nodes · r{row.get('round')}{batch_label(row)}"
        out.append(svg_text(24, y+4, label, 11, weight='bold'))
        out.append(f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="#c2cbd4"/>')
        for j, event in enumerate(events):
            offset = float(event["offset_seconds"])
            x = left + (right-left)*offset/max_t
            mark_y = y-13-(j%3)*13
            out.append(f'<line x1="{x:.1f}" y1="{y}" x2="{x:.1f}" y2="{mark_y}" stroke="#337ab7"/>')
            out.append(f'<circle cx="{x:.1f}" cy="{mark_y}" r="7" fill="#337ab7"><title>{html.escape(str(event["event"]))} {offset:.3f}s</title></circle>')
            out.append(svg_text(x, mark_y+3, j+1, 9, 'middle', 'white'))
            legend = f'{j+1}. {event["event"]}: {offset:.3f}s'
            out.append(svg_text(32+(j%2)*535, y+25+(j//2)*17, legend, 11))
        out.append(f'<line x1="20" y1="{y+panel_h-50}" x2="1100" y2="{y+panel_h-50}" stroke="#edf0f3"/>')
        y += panel_h
    out.append("</svg>")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"output directory already exists: {args.output}")
    source = args.input if (args.input / "results.json").exists() else args.input / "benchmark"
    rows = read_rows(source)
    env_path = source / "environment.json"
    environment = load_json(env_path) if env_path.exists() else None
    timelines = event_rows(source, rows)
    args.output.mkdir(parents=True)
    (args.output / "performance.svg").write_text(performance_svg(rows, environment), encoding="utf-8")
    (args.output / "timeline.svg").write_text(timeline_svg(timelines), encoding="utf-8")
    (args.output / "index.md").write_text("# Benchmark visualizations\n\n- [Performance](performance.svg)\n- [Observed event timeline](timeline.svg)\n\nPerformance summarizes successful elapsed times only. Failures are counted as attempts and are never treated as zero seconds. Timeline points use recorded monotonic `offset_seconds`; when events are absent, the timeline says they were not recorded and does not infer times from wall-clock logs.\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
