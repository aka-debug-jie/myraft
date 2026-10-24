"""Phase 1 browser regressions using synthetic API/SSE only."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from prototype_ui_test import SETUP, fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'mode': 'SYNTHETIC', 'checks': [], 'result': 'FAIL'}
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        def run_check(name, action, count=11, viewport=(1440, 900), renderer='svg', setup=None):
            frame, bootstrap = fixture(count)
            if setup:
                setup(frame, bootstrap)
            context = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]}, has_touch=viewport[0] < 600, reduced_motion='reduce')
            context.add_init_script('(' + SETUP + ')(' + json.dumps(frame) + ')')
            requests = []
            def api_route(route):
                path = route.request.url.split('?', 1)[0]
                if path.endswith('/api/session'):
                    route.fulfill(json=bootstrap)
                elif path.endswith('/api/operations'):
                    requests.append(route.request)
                    route.fulfill(json={'id': 'op-queued-1', 'kind': 'generate', 'state': 'queued', 'accepted': True, 'committed': False, 'session_id': 'synthetic', 'generation': 1})
                else:
                    route.fulfill(status=200, body='{}')
            context.route('**/api/**', api_route)
            page = context.new_page()
            page.set_default_timeout(4000)
            page.on('pageerror', lambda error: errors.append(f'{name}: {error}'))
            try:
                page.goto(args.url.rstrip('/') + f'/prototype/?renderer={renderer}')
                page.wait_for_function('(n)=>document.querySelectorAll("[data-node]").length>=n', arg=count)
                action(page, context, requests)
                result['checks'].append({'name': name, 'result': 'PASS'})
            except Exception as error:
                evidence = {'name': name, 'result': 'FAIL', 'error': f'{type(error).__name__}: {error}'}
                try:
                    evidence['url'] = page.url
                    evidence['body'] = page.locator('body').inner_text()[:4000]
                    page.screenshot(path=str(args.output / f'{name}.png'), full_page=True)
                except Exception as capture_error:
                    evidence['evidence_error'] = str(capture_error)
                result['checks'].append(evidence)
            finally:
                context.close()

        try:
            def session_menu(page, _ctx, _requests):
                trigger = page.get_by_label('会话操作')
                trigger.click()
                page.get_by_text('会话控制').wait_for()
                page.keyboard.press('Escape')
                escape_closed = page.locator('.session-popover').count() == 0
                escape_focus = page.evaluate('()=>document.activeElement.getAttribute("aria-label")') == '会话操作'
                trigger.click(); page.mouse.click(5, 5)
                outside_closed = page.locator('.session-popover').count() == 0
                assert escape_closed and outside_closed and escape_focus, {'escape_closed': escape_closed, 'outside_closed': outside_closed, 'escape_focus': escape_focus}
            run_check('session-menu-close-focus', session_menu)

            def mobile_navigation(page, _ctx, _requests):
                page.get_by_label('会话操作').click()
                page.get_by_label('打开工作区导航').click()
                assert page.locator('.session-popover').count() == 0
                assert page.get_by_label('手机工作区').is_visible()
                page.keyboard.press('Escape')
                assert page.locator('.mobile-navigation').count() == 0
            run_check('mobile-navigation-escape-exclusive', mobile_navigation, viewport=(390, 844))

            def cancel_dialog(page, _ctx, _requests):
                submit = page.locator('[data-act=generate]')
                submit.click()
                page.get_by_role('button', name='取消', exact=True).click()
                page.wait_for_function('()=>!document.querySelector("[role=dialog]") && document.activeElement===document.querySelector("[data-act=generate]")')
                assert submit.is_enabled()
            run_check('cancel-restores-submit-focus', cancel_dialog)

            def evidence_verify(page, _ctx, _requests):
                page.get_by_label('打开工作区导航').click()
                page.get_by_role('button', name='一致性证据', exact=True).click()
                assert page.locator('[data-act=verify]').count() == 1
            run_check('evidence-single-verify-entry', evidence_verify, viewport=(390, 844))

            def compare_focus(page, _ctx, _requests):
                page.get_by_role('button', name='并排比较', exact=True).click()
                page.wait_for_function('()=>document.querySelectorAll("[data-node]").length===22')
                stops = page.locator('[data-node][tabindex="0"]').count()
                flow_node = page.locator('.react-flow [data-node]').first
                flow_node.click()
                focus_transferred = page.evaluate('()=>document.activeElement.closest(".react-flow")!==null')
                assert stops == 1 and focus_transferred and page.locator('[data-node][tabindex="0"]').count() == 1, {'tab_stops_before': stops, 'focus_transferred': focus_transferred}
            run_check('compare-single-tab-stop-flow-focus', compare_focus)

            def queued_receipt(page, _ctx, requests):
                page.locator('[data-act=generate]').click()
                page.get_by_test_id('confirm').click()
                page.wait_for_function('()=>document.querySelector(".task-trigger").textContent.includes("已登记")')
                assert len(requests) == 1
                taskbar = page.locator('.task-trigger').inner_text()
                taskbar_queued = '已登记' in taskbar
                page.locator('.task-trigger').click()
                card = page.locator('[data-operation="op-queued-1"]')
                list_queued = card.count() == 1 and '已登记' in card.inner_text()
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq++; f.snapshot.completed_at=new Date().toISOString(); f.operations=[{id:'op-queued-1',kind:'generate',state:'succeeded',accepted:true,committed:true,session_id:'synthetic',generation:1}]; window.__send(f)}''')
                page.wait_for_function('()=>document.querySelector(".task-trigger").textContent.includes("任务完成")')
                list_succeeded = page.locator('[data-operation="op-queued-1"]').count() == 1 and '任务完成' in page.locator('[data-operation="op-queued-1"]').inner_text()
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq++; f.snapshot.completed_at=new Date().toISOString(); f.operations=[]; window.__send(f)}''')
                page.wait_for_function('()=>!document.querySelector(".task-trigger").textContent.includes("任务完成")')
                no_old_queued = '已登记' not in page.locator('.task-trigger').inner_text() and page.locator('[data-operation="op-queued-1"]').count() == 0
                assert taskbar_queued and list_queued and list_succeeded and no_old_queued and len(requests) == 1, {'taskbar_queued': taskbar_queued, 'list_queued': list_queued, 'list_succeeded': list_succeeded, 'no_old_queued': no_old_queued, 'post_count': len(requests)}
            run_check('queued-receipt-sse-reconcile-no-resurrection', queued_receipt)

            def keyboard_session(page, ctx, _requests):
                trigger = page.get_by_label('会话操作')
                trigger.focus(); page.keyboard.press('Enter')
                popover = page.locator('#session-popover')
                assert popover.is_visible()
                page.wait_for_function("()=>document.querySelector('#session-popover')?.contains(document.activeElement)")
                enable = popover.locator('[data-act=enable_control]')
                create = popover.locator('[data-act=create_session]')
                assert enable.is_enabled() and create.is_disabled(), 'creation must remain disabled until control is explicitly enabled'
                page.keyboard.press('Tab')
                page.wait_for_function("()=>document.querySelector('#session-popover')?.contains(document.activeElement)")
                page.keyboard.press('Escape')
                assert popover.count() == 0 and page.evaluate("()=>document.activeElement.getAttribute('aria-label')==='会话操作'")
            def control_available(frame, bootstrap):
                frame['control_enabled'] = False
                bootstrap['control_enabled'] = False
                bootstrap['control_allowed'] = True
            run_check('session-keyboard-entry-trap-escape', keyboard_session, setup=control_available)

            def mobile_keyboard_session(page, ctx, _requests):
                trigger = page.get_by_label('会话操作')
                trigger.focus(); page.keyboard.press('Enter')
                popover = page.locator('#session-popover')
                page.wait_for_function("()=>document.querySelector('#session-popover')?.contains(document.activeElement)")
                page.keyboard.press('Tab')
                page.wait_for_function("()=>document.querySelector('#session-popover')?.contains(document.activeElement)")
                page.keyboard.press('Escape')
                assert popover.count() == 0 and page.evaluate("()=>document.activeElement.getAttribute('aria-label')==='会话操作'")
            run_check('mobile-session-keyboard-entry-trap-escape', mobile_keyboard_session, viewport=(390, 844), setup=control_available)

            def kpi_stream(page, _ctx, _requests):
                value = lambda name: page.locator(f'[data-kpi="{name}"]').inner_text()
                assert [value(k) for k in ['leader','term','commit','applied','x','rpc']] == ['#1','1','2102','2102','0','—']
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq=2; f.snapshot.completed_at=new Date(Date.parse(f.snapshot.completed_at)+1000).toISOString(); f.snapshot.monitor_rpcs+=11; window.__send(f)}''')
                page.wait_for_function('()=>document.querySelector("[data-kpi=rpc]").textContent==="11.0"')
                page.evaluate('()=>window.__send(structuredClone(window.__fixture))')
                page.get_by_label('节点状态筛选').select_option('Leader')
                assert value('rpc') == '11.0'
                page.get_by_label('节点状态筛选').select_option('all')
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.session={...f.session,id:'session-C'}; f.snapshot.session_id='session-C'; f.generation=2; f.snapshot.generation=2; f.snapshot.seq=1; window.__send(f)}''')
                page.wait_for_function('()=>document.querySelector("[data-kpi=rpc]").textContent==="—"')
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq=2; f.snapshot.completed_at=new Date(Date.parse(f.snapshot.completed_at)+1000).toISOString(); f.snapshot.monitor_rpcs+=11; window.__send(f)}''')
                page.wait_for_function('()=>document.querySelector("[data-kpi=rpc]").textContent==="11.0"')
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq=3; f.snapshot.completed_at=new Date(Date.parse(f.snapshot.completed_at)+1000).toISOString(); f.snapshot.monitor_rpcs-=1; window.__send(f)}''')
                page.wait_for_function('()=>document.querySelector("[data-kpi=rpc]").textContent==="—"')
            run_check('kpi-values-rate-scope-reset-counter-rollback', kpi_stream)

            def summary_state(page, _ctx, _requests):
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq++; f.snapshot.nodes[1].status.state='Leader'; f.snapshot.completed_at=new Date().toISOString(); window.__send(f)}''')
                page.wait_for_function('()=>document.querySelector("[data-kpi=leader]").textContent==="—"')
                assert all(page.locator(f'[data-kpi="{k}"]').inner_text() == '—' for k in ['leader','term','commit','applied','x'])
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq++; f.snapshot.completed_at=new Date(Date.now()-30000).toISOString(); window.__send(f)}''')
                page.wait_for_function('()=>document.querySelector("[data-kpi=leader]").textContent==="—"')
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq++; f.snapshot.completed_at=new Date().toISOString(); f.snapshot.nodes[1].status.state='Follower'; f.snapshot.nodes[0].identity_ok=false; window.__send(f)}''')
                page.wait_for_function('()=>document.querySelector("[data-kpi=leader]").textContent==="—"')
                assert all(page.locator(f'[data-kpi="{k}"]').inner_text() == '—' for k in ['leader','term','commit','applied','x'])
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq++; f.snapshot.nodes[0].identity_ok=true; f.snapshot.nodes[2].reachable=false; f.snapshot.completed_at=new Date().toISOString(); window.__send(f)}''')
                page.wait_for_function('()=>document.querySelector("[data-observation-state]").textContent.includes("部分节点未响应")')
            run_check('kpi-multiple-leader-expiry-identity-offline', summary_state)

            def exact_large_integer(page, _ctx, _requests):
                frame, _ = fixture(11)
                frame['snapshot']['seq'] = 2
                frame['snapshot']['completed_at'] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
                frame['snapshot']['nodes'][0]['status']['x'] = 9223372036854775807
                raw = json.dumps(frame, separators=(',', ':'))
                page.evaluate('(raw)=>{for(const s of window.__streams)s.dispatchEvent(new MessageEvent("frame",{data:raw}))}', raw)
                page.wait_for_function('()=>document.querySelector("[data-kpi=x]").textContent==="9223372036854775807"')
            run_check('kpi-exact-int64-json-raw', exact_large_integer)

            def responsive_kpi_scroll(page, _ctx, _requests):
                for width in [390, 800, 1024]:
                    page.set_viewport_size({'width': width, 'height': 844})
                    assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth && document.body.scrollWidth<=innerWidth'), {'width': width, 'document': page.evaluate('()=>document.documentElement.scrollWidth'), 'viewport': width}
                page.set_viewport_size({'width': 390, 'height': 844})
                strip = page.locator('.kpi-strip')
                strip.evaluate('(e)=>{e.scrollLeft=e.scrollWidth}')
                page.wait_for_function('()=>{const e=document.querySelector("[data-kpi=rpc]").getBoundingClientRect();return e.left>=0&&e.right<=innerWidth}')
                before = strip.evaluate('(e)=>e.scrollLeft')
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.session={...f.session,id:'session-C'}; f.snapshot.session_id='session-C'; f.generation=2; f.snapshot.generation=2; f.snapshot.seq=1; f.snapshot.completed_at=new Date().toISOString(); window.__send(f)}''')
                page.wait_for_function('(before)=>document.querySelector("[data-kpi=leader]").textContent==="#1" && document.querySelector(".kpi-strip").scrollLeft===before', arg=before)
                page.evaluate('''()=>{const f=structuredClone(window.__fixture); f.snapshot.seq++; f.snapshot.completed_at=new Date().toISOString(); window.__send(f)}''')
                page.wait_for_function('(before)=>document.querySelector(".kpi-strip").scrollLeft===before', arg=before)
            run_check('kpi-responsive-overflow-scroll-preserved', responsive_kpi_scroll)

            assert not errors, errors
            result['result'] = 'PASS' if all(c['result'] == 'PASS' for c in result['checks']) else 'FAIL'
        finally:
            (args.output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            browser.close()
    print(json.dumps({'result': result['result'], 'checks': len(result['checks']), 'failed': sum(c['result'] == 'FAIL' for c in result['checks'])}, ensure_ascii=False))
    if result['result'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
