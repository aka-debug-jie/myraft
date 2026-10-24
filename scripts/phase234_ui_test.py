"""Phase 2–4 browser regressions using synthetic API/SSE only."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from prototype_ui_test import SETUP, fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='base URL serving the built app')
    parser.add_argument('--output', required=True, type=Path, help='new directory for result and failure screenshots')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'mode': 'SYNTHETIC', 'checks': [], 'result': 'FAIL'}
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def run_check(name, action, *, count=11, viewport=(1440, 900), renderer='svg'):
            frame, bootstrap = fixture(count)
            context = browser.new_context(
                viewport={'width': viewport[0], 'height': viewport[1]},
                has_touch=viewport[0] < 600,
                reduced_motion='reduce',
            )
            context.add_init_script('(' + SETUP + ')(' + json.dumps(frame) + ')')
            operations = []

            def api_route(route):
                path = route.request.url.split('?', 1)[0]
                if path.endswith('/api/session'):
                    route.fulfill(json=bootstrap)
                elif path.endswith('/api/operations'):
                    operations.append({'method': route.request.method, 'url': route.request.url})
                    route.fulfill(json={
                        'id': 'synthetic-operation', 'kind': 'stop', 'state': 'queued',
                        'accepted': True, 'committed': False,
                        'session_id': 'synthetic', 'generation': 1,
                    })
                else:
                    route.fulfill(status=200, body='{}')

            context.route('**/api/**', api_route)
            page = context.new_page()
            page.set_default_timeout(4500)
            page.on('pageerror', lambda error: page_errors.append(f'{name}: {error}'))
            try:
                page.goto(args.url.rstrip('/') + f'/prototype/?renderer={renderer}')
                page.wait_for_function('(n)=>document.querySelectorAll("[data-node]").length>=n', arg=count)
                action(page, context, operations)
                result['checks'].append({'name': name, 'result': 'PASS'})
            except Exception as error:
                evidence = {
                    'name': name,
                    'result': 'FAIL',
                    'error': f'{type(error).__name__}: {error}',
                    'operations': operations,
                    'active_element': page.evaluate('()=>document.activeElement.outerHTML'),
                }
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
            def mobile_detail(page, _context, operations):
                node = page.locator('[data-node="3"]')
                node.click()
                page.wait_for_function('()=>document.querySelector("[data-node=\\"3\\"]")?.getAttribute("aria-pressed")==="true"')
                assert page.get_by_label('节点 3 详情').count() == 0, 'selecting a mobile node must not immediately show its details'
                detail_trigger = page.get_by_label('查看节点详情')
                assert detail_trigger.is_visible()

                canvas_state = page.evaluate('''()=>{
                  const host=document.querySelector('.canvas-host');
                  const r=host.getBoundingClientRect();
                  const viewport=host.querySelector('.node-layer, .react-flow__viewport');
                  return {bbox:{x:r.x,y:r.y,width:r.width,height:r.height},transform:getComputedStyle(viewport).transform};
                }''')
                sse_before = page.evaluate('()=>window.__streams.size')
                page.screenshot(path=str(args.output / f'{page.url.split("renderer=")[-1]}-mobile-relation.png'))
                detail_trigger.click()
                dialog = page.locator('.mobile-detail')
                assert dialog.is_visible() and dialog.get_attribute('role') == 'dialog'
                assert dialog.get_by_label('节点 3 详情').is_visible()
                page.screenshot(path=str(args.output / f'{page.url.split("renderer=")[-1]}-mobile-detail.png'))

                page.keyboard.press('Control+k')
                assert dialog.evaluate('(e)=>e.contains(document.activeElement)'), 'Ctrl+K moved focus behind the modal detail'
                assert page.evaluate('()=>document.activeElement.getAttribute("aria-label")') != '搜索节点'
                for _ in range(8):
                    page.keyboard.press('Tab')
                    assert dialog.evaluate('(e)=>e.contains(document.activeElement)'), 'Tab escaped the detail dialog'

                dialog.get_by_role('button', name='停止节点').click()
                confirmation = page.locator('.dialog-content')
                assert confirmation.is_visible()
                page.get_by_role('button', name='取消', exact=True).click()
                assert dialog.is_visible() and dialog.get_by_role('button', name='停止节点').is_visible()

                page.get_by_role('button', name='返回拓扑', exact=True).click()
                assert page.get_by_label('节点 3 详情').count() == 0
                selected = page.locator('[data-node="3"]').get_attribute('aria-pressed') == 'true'
                after = page.evaluate('''()=>{
                  const host=document.querySelector('.canvas-host');
                  const r=host.getBoundingClientRect();
                  const viewport=host.querySelector('.node-layer, .react-flow__viewport');
                  return {bbox:{x:r.x,y:r.y,width:r.width,height:r.height},transform:getComputedStyle(viewport).transform};
                }''')
                assert selected and after == canvas_state, {'selected': selected, 'before': canvas_state, 'after': after}
                assert page.evaluate('()=>window.__streams.size') == sse_before == 1

                page.get_by_label('查看节点详情').click()
                page.keyboard.press('Escape')
                assert page.locator('.mobile-detail').count() == 0
                assert page.locator('[data-node][aria-pressed="true"]').count() == 0
                assert operations == [], 'canceling stop must not submit an operation'
                page.wait_for_function("()=>document.activeElement.dataset.node === '3'")
                node.click(); page.get_by_label('查看节点详情').click()
                unknown_requests = []
                def abort_write(route):
                    unknown_requests.append(route.request.method)
                    route.abort()
                _context.route('**/api/operations', abort_write)
                page.locator('.mobile-detail [data-act=stop]').click()
                page.get_by_test_id('confirm').click()
                page.locator('.mobile-detail [role=alert]').wait_for()
                assert '结果未知' in page.locator('.mobile-detail [role=alert]').inner_text()
                assert page.locator('.mobile-detail [aria-label="关闭错误提示"]').count() == 0
                page.evaluate('()=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;f.snapshot.completed_at=new Date().toISOString();window.__send(f)}')
                assert unknown_requests == ['POST'], 'uncertain write was automatically repeated' 

            for renderer in ('svg', 'flow'):
                run_check(f'mobile-node-detail-{renderer}', mobile_detail, count=11, viewport=(390, 844), renderer=renderer)

            def mobile_exclusive(page, _context, _operations):
                page.get_by_label('打开工作区导航').click()
                assert page.get_by_label('手机工作区').is_visible()
                page.get_by_role('button', name='一致性证据', exact=True).click()
                assert page.locator('.mobile-navigation').count() == 0
                assert page.get_by_text('提交与验证', exact=True).is_visible()
                page.get_by_role('button', name='返回拓扑', exact=True).click()
                page.locator('.task-trigger').click()
                assert page.locator('.mobile-navigation').count() == 0
                assert page.locator('.evidence-inspector').count() == 0
                assert page.locator('.task-panel').is_visible()
                page.get_by_role('button', name='返回拓扑', exact=True).click()
                page.get_by_label('打开工作区导航').click()
                assert page.locator('.task-panel').count() == 0
                assert page.get_by_label('手机工作区').is_visible()

            run_check('mobile-navigation-evidence-tasks-exclusive', mobile_exclusive, viewport=(390, 844))

            def compare_focus(page, _context, _operations):
                page.get_by_role('button', name='并排比较', exact=True).click()
                page.wait_for_function('()=>document.querySelectorAll("[data-node]").length===22')
                flow_node = page.locator('.react-flow [data-node]').first
                flow_node.click()
                page.get_by_label('查看节点详情').click()
                page.get_by_role('button', name='返回拓扑', exact=True).click()
                active_in_svg = page.evaluate('()=>!!document.activeElement.closest(".svg-canvas, .svg-canvas [data-node]")')
                active_in_flow = page.evaluate('()=>!!document.activeElement.closest(".react-flow")')
                focused_flow_entry = page.evaluate('''()=>{
                  const active=document.activeElement;
                  return active.getAttribute('aria-label')==='查看节点详情';
                }''')
                assert not active_in_svg and (active_in_flow or focused_flow_entry), {
                    'active_in_svg': active_in_svg,
                    'active_in_flow': active_in_flow,
                    'focused_flow_entry': focused_flow_entry,
                    'active_label': page.evaluate('()=>document.activeElement.getAttribute("aria-label")'),
                }

            run_check('compare-flow-detail-return-focus-owner', compare_focus, viewport=(390, 844), renderer='compare')

            def leader_focus_edges(page, _context, _operations):
                page.locator('[data-node="1"]').click()
                assert page.get_by_text('前五项来自 Leader #1', exact=False).is_visible()
                assert page.locator('.relation.is-focused').count() == 0
                page.locator('[data-node="2"]').focus()
                page.wait_for_function('()=>document.querySelectorAll(".relation.is-focused").length===1')
                assert page.locator('.relation.is-focused').count() == 1

            run_check('desktop-leader-summary-focus-edge', leader_focus_edges, count=11, viewport=(1440, 900), renderer='svg')

            def labels_restore(page, _context, _operations):
                ids = page.locator('.node-badge__id')
                assert ids.count() == 100
                for _ in range(3):
                    page.get_by_label('放大').click()
                desktop_zoom_classes = page.locator('.node-badge').evaluate_all('(nodes)=>nodes.map(node=>node.className)')
                assert page.locator('.node-badge__id').count() == 100
                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_timeout(150)
                mobile_classes = page.locator('.node-badge').evaluate_all('(nodes)=>nodes.map(node=>node.className)')
                assert page.locator('.node-badge__id').count() == 100
                page.set_viewport_size({'width': 1440, 'height': 900})
                page.wait_for_timeout(150)
                restored_classes = page.locator('.node-badge').evaluate_all('(nodes)=>nodes.map(node=>node.className)')
                assert restored_classes == desktop_zoom_classes, {
                    'desktop_zoom': desktop_zoom_classes[:5],
                    'mobile': mobile_classes[:5],
                    'restored': restored_classes[:5],
                }
                assert mobile_classes != desktop_zoom_classes, '100-node badge levels should respond to the narrower viewport'
                assert page.locator('.node-badge__id').count() == 100

            run_check('hundred-node-label-level-restores-after-resize', labels_restore, count=100, viewport=(1440, 900), renderer='svg')

            def receipt_states(page, _context, _operations):
                page.evaluate("""()=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;f.operations=[true,false,null].map((v,i)=>({id:'receipt-'+i,kind:'generate',state:'succeeded',accepted:v,committed:v,session_id:f.session.id,generation:f.generation}));window.__send(f)}""")
                page.locator('.task-trigger').click()
                for index, text in enumerate(['提交已确认', '本次未确认提交', '提交状态未知']):
                    assert text in page.locator(f'[data-operation="receipt-{index}"]').inner_text()
                assert page.locator('[data-verification]').count() == 0
            run_check('receipt-commit-three-states', receipt_states)

            def panel_lifecycle(page, context, _operations):
                cdp=context.new_cdp_session(page);cdp.send('Performance.enable')
                page.locator('[data-node="3"]').click()
                def cycle():
                    page.evaluate('()=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;f.snapshot.completed_at=new Date().toISOString();window.__send(f)}')
                    page.get_by_label('查看节点详情').click()
                    page.get_by_role('button',name='返回拓扑',exact=True).click()
                    page.wait_for_function("()=>document.activeElement.getAttribute('aria-label')==='查看节点详情'")
                cycle();cycle();samples=[]
                for i in range(9):
                    if i:
                        for _ in range(5):cycle()
                    cdp.send('HeapProfiler.collectGarbage')
                    metrics={m['name']:m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                    samples.append({key:metrics[key] for key in ['Nodes','JSEventListeners','JSHeapUsedSize']})
                result.setdefault('panel_lifecycle',[]).append({'renderer':page.url.split('renderer=')[-1],'samples':samples,'warmup_cycles':2,'measured_cycles':40})
                assert samples[-1]['JSEventListeners']==samples[0]['JSEventListeners'],samples
                assert samples[-1]['Nodes']==samples[0]['Nodes'],samples
                assert page.evaluate('()=>window.__streams.size===1&&window.__created===1')
            for renderer in ('svg','flow'):
                run_check(f'mobile-panel-lifecycle-{renderer}',panel_lifecycle,count=11,viewport=(390,844),renderer=renderer)

            result['page_errors'] = page_errors
            result['result'] = 'PASS' if all(item['result'] == 'PASS' for item in result['checks']) and not page_errors else 'FAIL'
        finally:
            (args.output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            browser.close()

    print(json.dumps({
        'result': result['result'],
        'checks': len(result['checks']),
        'failed': sum(item['result'] == 'FAIL' for item in result['checks']),
        'page_errors': len(page_errors),
    }, ensure_ascii=False))
    if result['result'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
