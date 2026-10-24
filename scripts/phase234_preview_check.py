"""Read-only preview links, medium-width geometry and visual evidence."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from prototype_ui_test import GEOMETRY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--hundred-url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'mode': 'REAL_READ_ONLY', 'checks': [], 'result': 'FAIL'}
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for count, url in [(11, args.url), (100, args.hundred_url)]:
                for renderer in ['svg', 'flow']:
                    page = browser.new_page(reduced_motion='no-preference')
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(url.rstrip('/') + '/prototype/?renderer=' + renderer)
                    page.wait_for_function('(n)=>document.querySelectorAll("[data-relation]").length===n-1', arg=count)
                    for width in [800, 1024]:
                        page.set_viewport_size({'width': width, 'height': 900})
                        page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                        for details in [False, True]:
                            if details: page.locator('[data-node="3"]').click()
                            page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                            stats = page.evaluate(GEOMETRY)
                            assert stats['hit'] == count and not any(stats[k] for k in ['overlap', 'outside', 'crossings', 'edge_crossings', 'visual_errors']), stats
                            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth')
                            result['checks'].append({'renderer': renderer, 'nodes': count, 'width': width, 'inspector': details, **stats})
                            page.screenshot(path=str(args.output / f'{renderer}-{count}-{width}-detail-{details}.png'))
                            if details: page.get_by_label('关闭节点详情').click(); page.keyboard.press('Escape')
                    page.set_viewport_size({'width': 1440, 'height': 900})
                    page.get_by_role('button', name='并排比较', exact=True).click()
                    page.wait_for_function('(n)=>document.querySelectorAll("[data-node]").length===n*2', arg=count)
                    assert page.locator('[data-node][tabindex="0"]').count() == 1
                    page.screenshot(path=str(args.output / f'compare-{count}.png'))
                    page.close()
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            for label, route in [('日志实验室（原版）', 'logs'), ('故障实验（原版）', 'faults'), ('性能实验（原版）', 'experiments'), ('会话设置（原版）', 'settings')]:
                page.goto(args.url.rstrip('/') + '/prototype/')
                page.get_by_label(label, exact=True).click()
                page.locator(f'[data-page="{route}"][aria-current="page"]').wait_for()
                result['checks'].append({'legacy_link': route, 'result': 'PASS'})
            assert not errors, errors
            result.update(result='PASS', page_errors=errors)
        except Exception as error:
            result['error'] = str(error)
            page.screenshot(path=str(args.output / 'failure.png'))
            raise
        finally:
            browser.close()
            (args.output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'result': result['result'], 'checks': len(result['checks'])}))


if __name__ == '__main__':
    main()
