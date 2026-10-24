"""Synthetic recovery and operation-receipt UI checks; all API calls are intercepted."""
import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from prototype_ui_test import SETUP, fixture


def operation(op_id, kind, state, session_id='synthetic', generation=1):
    return {
        'id': op_id,
        'session_id': session_id,
        'generation': generation,
        'kind': kind,
        'state': state,
        'created_at': '2026-10-24T00:00:00Z',
        'accepted': True if state == 'succeeded' else None,
        'committed': True if state == 'succeeded' else None,
    }


def frame_for(count=11):
    frame, bootstrap = fixture(count)
    frame['snapshot']['completed_at'] = '2026-10-24T00:00:00Z'
    return frame, bootstrap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'mode': 'SYNTHETIC', 'cases': [], 'result': 'FAIL'}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        def open_page(renderer):
            frame, bootstrap = frame_for()
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            context.add_init_script('(' + SETUP + ')(' + json.dumps(frame) + ')')
            page = context.new_page()
            page.set_default_timeout(2500)
            return context, page

        def navigate(page, renderer):
            page.goto(args.url.rstrip('/') + f'/prototype/?renderer={renderer}')
            page.wait_for_function('()=>document.querySelectorAll("[data-node]").length===11')

        def record_case(name, renderer, run):
            context = None
            case = {'name': name, 'renderer': renderer, 'result': 'FAIL'}
            try:
                context, page = open_page(renderer)
                details = run(context, page, renderer)
                case.update(details=details, result='PASS')
            except Exception as error:
                case['error'] = f'{type(error).__name__}: {error}'
                if context is not None:
                    try:
                        context.pages[0].screenshot(path=str(args.output / f'failure-{name}-{renderer}.png'), full_page=True)
                        case['screenshot'] = f'failure-{name}-{renderer}.png'
                    except Exception as screenshot_error:
                        case['screenshot_error'] = str(screenshot_error)
            finally:
                if context is not None:
                    context.close()
                result['cases'].append(case)

        def controller_recovery(context, page, renderer):
            frame, _ = frame_for()
            frame['controller_id'] = 'controller-B'
            frame['session']['name'] = '恢复后的合成会话'
            frame['snapshot']['seq'] = 2
            bootstrap_calls = []
            switched = False
            _, initial_bootstrap = frame_for()
            initial_bootstrap['session']['name'] = '控制器 A 会话'

            def session_route(route):
                body = json.loads(json.dumps(initial_bootstrap))
                if switched:
                    bootstrap_calls.append(time.perf_counter())
                    body['controller_id'] = 'controller-B'
                    body['session']['name'] = '恢复后的合成会话'
                    time.sleep(0.25)  # Inject a read slower than the SSE interval.
                route.fulfill(json=body)

            context.route('**/api/session', session_route)
            context.route('**/api/operations', lambda route: route.abort())
            navigate(page, renderer)
            page.wait_for_function('()=>window.__streams.size===1&&!document.querySelector("[data-act=generate]").disabled')
            switched = True
            page.evaluate('''frame=>{
              let seq=frame.snapshot.seq;
              window.__auditTimer=setInterval(()=>{
                const f=structuredClone(frame);f.snapshot.seq=++seq;
                f.snapshot.completed_at=new Date().toISOString();window.__send(f);
              },100);
            }''', frame)
            started = time.perf_counter()
            page.wait_for_function('()=>document.querySelector(".session-switch")?.textContent.includes("恢复后的合成会话")&&!document.querySelector("[data-act=generate]")?.disabled', timeout=1400)
            elapsed_ms = (time.perf_counter() - started) * 1000
            page.wait_for_timeout(1400)
            # Keep the synthetic stream running while checking counts.
            assert page.evaluate('()=>window.__streams.size') == 1
            assert len(bootstrap_calls) <= 2, f'too many /api/session requests: {len(bootstrap_calls)}'
            assert elapsed_ms < 1400, f'bootstrap recovery took {elapsed_ms:.1f} ms'
            return {'bootstrap_requests': len(bootstrap_calls), 'recovery_ms': round(elapsed_ms, 1), 'stream_still_open': True}

        def unknown_write(context, page, renderer):
            _, bootstrap = frame_for()
            calls = {'generate': 0, 'verify': 0}

            def session_route(route):
                route.fulfill(json=bootstrap)

            def operation_route(route):
                payload = route.request.post_data_json
                if payload['kind'] == 'generate':
                    calls['generate'] += 1
                    if calls['generate'] == 1:
                        route.abort()
                    else:
                        route.fulfill(json=operation('audit-queued', 'generate', 'queued'))
                elif payload['kind'] == 'verify':
                    calls['verify'] += 1
                    if calls['verify'] == 1:
                        route.fulfill(status=400, content_type='application/json', body=json.dumps({'error': 'synthetic verify rejection'}))
                    else:
                        route.fulfill(json=operation('audit-queued', 'verify', 'queued'))
                else:
                    route.abort()

            context.route('**/api/session', session_route)
            context.route('**/api/operations', operation_route)
            navigate(page, renderer)
            page.locator('[data-act="generate"]').click()
            page.get_by_test_id('confirm').click()
            page.get_by_role('alert').get_by_text('结果未知，请先核查回执，勿重复发送。').wait_for()
            assert page.get_by_role('alert').get_by_label('关闭错误提示').count() == 0
            page.wait_for_timeout(350)
            assert calls['generate'] == 1, f'generate was automatically resent: {calls}'
            page.locator('[data-act="verify"]').click()
            page.wait_for_function('()=>document.querySelector("[data-act=verify]")!==null')
            page.wait_for_timeout(100)
            assert calls['verify'] == 1
            assert page.get_by_role('alert').get_by_text('结果未知，请先核查回执，勿重复发送。').count() == 1
            assert page.get_by_role('alert').get_by_label('关闭错误提示').count() == 0
            page.locator('[data-act="verify"]').click()
            page.locator('.task-trigger').click()
            page.locator('[data-operation="audit-queued"]').wait_for()
            assert page.locator('[data-operation="audit-queued"]').inner_text().find('已登记') >= 0
            assert calls == {'generate': 1, 'verify': 2}, calls
            assert page.get_by_role('alert').get_by_text('结果未知，请先核查回执，勿重复发送。').count() == 1
            return {'generate_posts': calls['generate'], 'verify_posts': calls['verify'], 'unknown_warning_persistent': True, 'close_button_absent': True}

        def evicted_receipt(context, page, renderer):
            _, bootstrap = frame_for()
            held = []
            payloads = []

            def session_route(route):
                route.fulfill(json=bootstrap)

            def operation_route(route):
                payloads.append(route.request.post_data_json)
                held.append(route)

            context.route('**/api/session', session_route)
            context.route('**/api/operations', operation_route)
            navigate(page, renderer)
            page.locator('[data-act="generate"]').click()
            page.get_by_test_id('confirm').click()
            page.wait_for_function('()=>window.__fixture!==null')
            deadline = time.perf_counter() + 3
            while not held and time.perf_counter() < deadline:
                page.wait_for_timeout(20)
            assert len(held) == 1, 'generate request did not reach the held route'
            old = operation('audit-old', 'generate', 'succeeded')
            page.evaluate('''op=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;f.operations=[op];f.snapshot.completed_at=new Date().toISOString();window.__send(f)}''', old)
            page.wait_for_function('()=>document.querySelector(".task-trigger")?.textContent.includes("提交命令")')
            recent = [operation(f'audit-new-{i}', 'verify', 'succeeded') for i in range(20)]
            page.evaluate('''ops=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;f.operations=ops;f.snapshot.completed_at=new Date().toISOString();window.__send(f)}''', recent)
            page.wait_for_function('()=>document.querySelector(".task-trigger")?.textContent.includes("校验当前")')
            held[0].fulfill(json=operation('audit-old', 'generate', 'queued'))
            page.wait_for_function('()=>!document.querySelector("[data-testid=confirm]")')
            page.wait_for_timeout(150)
            assert page.locator('.task-trigger').inner_text().find('校验当前') >= 0, page.locator('.task-trigger').inner_text()
            assert page.locator('.task-trigger').inner_text().find('提交命令') < 0
            page.locator('.task-trigger').click()
            page.locator('[data-operation="audit-new-19"]').wait_for()
            assert page.locator('[data-operation="audit-old"]').count() == 0
            assert len(payloads) == 1 and payloads[0]['kind'] == 'generate'
            return {'pending_operation': 'audit-old', 'evicting_operations': 20, 'footer_keeps_latest_verify': True, 'stale_receipt_absent': True}

        try:
            for renderer in ('svg', 'flow'):
                record_case('controller-recovery', renderer, controller_recovery)
                record_case('unknown-write', renderer, unknown_write)
                record_case('evicted-receipt', renderer, evicted_receipt)
            result['result'] = 'PASS' if all(case['result'] == 'PASS' for case in result['cases']) else 'FAIL'
        finally:
            browser.close()
            (args.output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'result': result['result'], 'cases': len(result['cases'])}))
    if result['result'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
