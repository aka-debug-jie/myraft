"""Repeatable synthetic UI measurements for same-host frontend comparisons."""
import argparse
import json
import statistics
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from prototype_ui_test import SETUP, fixture


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {
        'mode': 'SYNTHETIC',
        'viewport': {'width': 1440, 'height': 900},
        'reduced_motion': 'no-preference',
        'rounds_per_case': 3,
        'runs': [],
        'result': 'FAIL',
    }
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = None
            try:
                for count in (11, 100):
                    for renderer in ('svg', 'flow'):
                        for trial in range(1, 4):
                            frame, bootstrap = fixture(count)
                            context = browser.new_context(
                                viewport={'width': 1440, 'height': 900},
                                reduced_motion='no-preference',
                            )
                            context.add_init_script('(' + SETUP + ')(' + json.dumps(frame) + ')')
                            context.route(
                                '**/api/session',
                                lambda route, _request, body=bootstrap: route.fulfill(json=body),
                            )
                            context.route('**/api/operations', lambda route, _request: route.abort())
                            page = context.new_page()
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            cdp = context.new_cdp_session(page)
                            cdp.send('Performance.enable')
                            run = {'nodes': count, 'renderer': renderer, 'trial': trial}
                            result['runs'].append(run)

                            started = time.perf_counter()
                            page.goto(args.url.rstrip('/') + f'/prototype/?renderer={renderer}')
                            page.wait_for_function(
                                '(n)=>document.querySelectorAll("[data-node]").length===n&&document.querySelectorAll("[data-relation]").length===n-1',
                                arg=count,
                            )
                            run['ready_ms'] = (time.perf_counter() - started) * 1000
                            page.locator('[data-node="1"]').click()
                            page.get_by_label('节点 1 详情').wait_for()
                            run['first_node_details_ms'] = (time.perf_counter() - started) * 1000
                            page.get_by_label('关闭节点详情').click()
                            page.keyboard.press('Escape')
                            page.get_by_label('返回全景').click()

                            if count == 100:
                                before = {m['name']: m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                                update = page.evaluate('''async()=>{
                                  const times=[];
                                  for(let i=0;i<120;i++){
                                    const f=structuredClone(window.__fixture);
                                    f.snapshot.seq++;
                                    f.snapshot.completed_at=new Date(Math.max(Date.now(),Date.parse(f.snapshot.completed_at)+1)).toISOString();
                                    f.snapshot.nodes.forEach(n=>{n.status.commit_index++;n.status.last_log_index++;n.status.last_applied++});
                                    const start=performance.now();
                                    window.__send(f);
                                    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
                                    times.push(performance.now()-start);
                                  }
                                  return {times,long_tasks:window.__long,heap:performance.memory?.usedJSHeapSize??null,active_sse:window.__streams.size};
                                }''')
                                values = update['times']
                                update.update(
                                    samples=len(values),
                                    p50_ms=statistics.median(values),
                                    p95_ms=percentile(values, .95),
                                    maximum_ms=max(values),
                                )
                                after = {m['name']: m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                                update['task_cpu_ms'] = (after['TaskDuration'] - before['TaskDuration']) * 1000
                                update['script_cpu_ms'] = (after['ScriptDuration'] - before['ScriptDuration']) * 1000
                                update['js_heap_bytes'] = after['JSHeapUsedSize']
                                run['sse_updates'] = update

                            page.evaluate('''()=>{
                              window.__frames=[];window.__record=true;
                              let last=performance.now();
                              function tick(now){if(!window.__record)return;window.__frames.push(now-last);last=now;requestAnimationFrame(tick)}
                              requestAnimationFrame(tick);
                            }''')
                            box = page.locator('.canvas-host').bounding_box()
                            x, y = box['x'] + box['width'] * .46, box['y'] + box['height'] * .35
                            page.mouse.move(x, y)
                            page.mouse.down()
                            page.mouse.move(box['x'] + box['width'] * .66, box['y'] + box['height'] * .48, steps=40)
                            page.mouse.move(x, y, steps=40)
                            page.mouse.up()
                            frames = page.evaluate('()=>{window.__record=false;return window.__frames.slice(1)}')
                            run['drag'] = {
                                'steps': 80,
                                'samples': len(frames),
                                'frame_times_ms': frames,
                                'p50_ms': statistics.median(frames),
                                'p95_ms': percentile(frames, .95),
                            }
                            run['active_sse'] = page.evaluate('()=>window.__streams.size')
                            context.close()
                            context = None
                assert not errors, errors
                result['page_errors'] = errors
                result['result'] = 'PASS'
            finally:
                if context is not None:
                    context.close()
                browser.close()
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
        result['page_errors'] = errors
        raise
    finally:
        (args.output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'result': result['result'], 'runs': len(result['runs'])}))


if __name__ == '__main__':
    main()
