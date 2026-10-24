"""Check a real empty controller plus separately labelled synthetic sample times.

The supplied URL must be a new controller with no selected session. No writes
are sent; synthetic cases intercept all API requests.
"""
import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from prototype_ui_test import SETUP, fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'cases': [], 'result': 'FAIL'}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for renderer in ('svg', 'flow', 'compare'):
            for width, height in ((1440, 900), (390, 844)):
                case = {'mode': 'REAL_EMPTY_CONTROLLER', 'renderer': renderer,
                        'viewport': [width, height], 'result': 'FAIL'}
                context = browser.new_context(viewport={'width': width, 'height': height})
                page = context.new_page()
                errors, writes = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: writes.append(request.method)
                        if request.method not in ('GET', 'HEAD') else None)
                try:
                    frame = context.request.get(args.url + '/api/snapshot').json()
                    assert frame['session'] is None, 'requires a new empty controller'
                    assert frame['snapshot']['completed_at'].startswith('0001')
                    page.goto(args.url + f'/prototype/?renderer={renderer}')
                    expect(page.locator('.statusbar').get_by_text('REAL', exact=True)).to_be_visible()
                    expect(page.locator('.hero-status')).to_contain_text('等待首次采样')
                    expect(page.locator('.sample-age')).to_have_text('等待首次采样')
                    expect(page.locator('[data-kpi=leader]')).to_have_text('—')
                    expect(page.locator('[data-act=generate]')).to_be_disabled()
                    assert not errors and not writes, (errors, writes)
                    case['result'] = 'PASS'
                except Exception as error:
                    case['error'] = f'{type(error).__name__}: {error}'
                finally:
                    name = f'empty-{renderer}-{width}.png'
                    page.screenshot(path=str(args.output / name), full_page=True)
                    case['screenshot'] = name
                    case['hero'] = page.locator('.hero-status').inner_text()
                    case['footer'] = page.locator('.sample-age').inner_text()
                    result['cases'].append(case)
                    context.close()

            case = {'mode': 'SYNTHETIC_INVALID_AND_STALE', 'renderer': renderer, 'result': 'FAIL'}
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            frame, bootstrap = fixture(11)
            context.add_init_script('(' + SETUP + ')(' + json.dumps(frame) + ')')
            context.route('**/api/**', lambda route: route.abort())
            context.route('**/api/session', lambda route: route.fulfill(json=bootstrap))
            context.route('**/api/operations', lambda route: route.abort())
            page = context.new_page()
            try:
                page.goto(args.url + f'/prototype/?renderer={renderer}')
                expect(page.locator('[data-kpi=leader]')).to_have_text('#1')
                page.evaluate('''()=>{const f=structuredClone(window.__fixture);
                  f.snapshot.seq++;f.snapshot.completed_at='invalid';window.__send(f)}''')
                expect(page.locator('.hero-status')).to_contain_text('等待首次采样')
                expect(page.locator('.sample-age')).to_have_text('等待首次采样')
                expect(page.locator('[data-kpi=leader]')).to_have_text('—')
                page.evaluate('''()=>{const f=structuredClone(window.__fixture);
                  f.snapshot.seq++;f.snapshot.completed_at=new Date(Date.now()-120000).toISOString();window.__send(f)}''')
                expect(page.locator('.hero-status')).to_contain_text(re.compile(r'上次采样 12\d\.\ds 前'))
                expect(page.locator('[data-kpi=leader]')).to_have_text('—')
                expect(page.locator('[data-act=generate]')).to_be_disabled()
                assert page.evaluate('()=>window.__streams.size') == 1
                case.update(result='PASS', single_subscription=True)
            except Exception as error:
                case['error'] = f'{type(error).__name__}: {error}'
            finally:
                result['cases'].append(case)
                context.close()
        browser.close()
    if all(case['result'] == 'PASS' for case in result['cases']):
        result['result'] = 'PASS'
    (args.output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'result': result['result'], 'cases': len(result['cases'])}))
    raise SystemExit(0 if result['result'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
