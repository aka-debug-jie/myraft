"""Focused synthetic UI regressions; these are not Raft consensus evidence."""
import json
import unittest
import dashboard_ui_test as base
from playwright.sync_api import expect

class PolishTests(base.DashboardBrowserTests):
    def test_live_detail_summary_keeps_keyboard_focus(self):
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page);page.goto(base.BASE_URL);self.wait_for_synthetic_stream(page)
            page.locator('.stage-node').first.click()
            summary=page.locator('#node-detail summary');summary.focus()
            page.evaluate("() => {const f=JSON.parse(window.__lastSyntheticFrame);f.snapshot.completed_at=new Date(Date.now()-800).toISOString();window.__emitSyntheticFrame(f)}")
            self.assertEqual(page.evaluate("document.activeElement.closest('#node-detail')!==null && document.activeElement.tagName"),'SUMMARY')
        finally:context.close()

    def test_initial_leader_slot_and_single_relation_focus(self):
        context,page=self.new_page(width=1440,height=900)
        try:
            self.intercept_synthetic_api(page);page.goto(base.BASE_URL);self.wait_for_synthetic_stream(page)
            frame=base.stage_fixture(100,leader_id=37)
            frame['snapshot']['seq']=41;page.evaluate('f => window.__emitSyntheticFrame(f)',frame)
            # First valid observation seeds a display slot, not confirmed protocol state.
            self.assertEqual(page.locator('.stage-node.center-slot').get_attribute('data-node'),'37')
            frame['snapshot']['seq']=42;page.evaluate('f => window.__emitSyntheticFrame(f)',frame)
            page.locator('.stage-node[data-node="37"]').click()
            self.assertEqual(page.locator('.stage-reported-edge.selected').count(),0,'Leader selection highlights all edges')
            page.locator('#node-detail .detail-close').click()
            edge=page.locator('.stage-reported-edge[data-from="2"]')
            point=edge.evaluate('e=>{const p=e.getPointAtLength(e.getTotalLength()*.25),m=e.getScreenCTM();return{x:m.a*p.x+m.c*p.y+m.e,y:m.b*p.x+m.d*p.y+m.f}}')
            page.mouse.move(point['x'],point['y'])
            self.assertEqual(page.locator('.stage-reported-edge.selected').count(),1)
            expect(page.locator('.stage-relation-note')).to_contain_text('#2')
            expect(page.locator('.stage-relation-note')).to_contain_text('非实测链路')
        finally:context.close()

    def test_workflow_button_focus_stays_on_same_step(self):
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page,control_enabled=True);page.goto(base.BASE_URL);self.wait_for_synthetic_stream(page)
            page.locator('.demo-trigger').click()
            buttons=page.locator('#demo-drawer [data-act=verify]');self.assertEqual(buttons.count(),2)
            buttons.nth(1).focus()
            page.evaluate("() => {const f=JSON.parse(window.__lastSyntheticFrame);f.current_verification={state:'failed'};window.__emitSyntheticFrame(f)}")
            self.assertTrue(buttons.nth(1).evaluate('e=>e===document.activeElement'))
        finally:context.close()

    def test_expanded_receipt_scroll_survives_live_update(self):
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page,control_enabled=True);page.goto(base.BASE_URL);self.wait_for_synthetic_stream(page)
            frame=base.frame_fixture();frame['control_enabled']=True
            frame['operations']=[{'id':'scroll-op','kind':'generate','state':'running','accepted':True,'result':{'large':list(range(200))}}]
            page.evaluate('f=>window.__emitSyntheticFrame(f)',frame)
            page.locator('#task-tray').evaluate('e=>e.open=true')
            detail=page.locator('#task-body details[data-receipt]');detail.evaluate('e=>e.open=true')
            pre=detail.locator('.json-view');expect(pre).to_contain_text('199')
            pre.evaluate('e=>e.scrollTop=180')
            frame['operations'][0]['result']['progress']=1
            page.evaluate('f=>window.__emitSyntheticFrame(f)',frame)
            expect(pre).to_contain_text('progress')
            self.assertEqual(pre.evaluate('e=>e.scrollTop'),180)
            self.assertTrue(detail.evaluate('e=>e.open'))
        finally:context.close()

    def test_disconnected_node_detail_clears_cached_sample(self):
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page);page.goto(base.BASE_URL);self.wait_for_synthetic_stream(page)
            page.locator('.stage-node').first.click()
            page.evaluate("() => window.__syntheticSources.at(-1).onerror(new Event('error'))")
            expect(page.locator('#node-detail')).to_contain_text('未知 / 不可达')
            self.assertEqual(page.locator('.stage-reported-edge').count(),0)
            expect(page.locator('#node-detail [data-act=stop]')).to_be_disabled()
            self.assertNotIn('可达性\n可达',page.locator('#node-detail').inner_text())
        finally:context.close()

    def test_new_commit_after_restore_does_not_erase_completed_fault_step(self):
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page,control_enabled=True);page.goto(base.BASE_URL);self.wait_for_synthetic_stream(page)
            frame=base.stage_fixture(3);frame['control_enabled']=True;frame['target']=1
            frame['operations']=[{'kind':'stop','state':'succeeded'},{'kind':'restart','state':'succeeded'},{'kind':'generate','committed':True,'result':{'last_index':1}}]
            frame['checkpoint']={'index':1};frame['current_verification']={'state':'passed'};frame['history_verification']={'state':'passed'}
            page.evaluate('f=>window.__emitSyntheticFrame(f)',frame)
            expect(page.locator('.lesson-step')).to_have_text('本轮课堂流程完成')
        finally:context.close()

    def test_dense_path_picking_uses_closest_geometry(self):
        context,page=self.new_page(width=1440,height=900)
        try:
            self.intercept_synthetic_api(page);page.goto(base.BASE_URL);self.wait_for_synthetic_stream(page)
            frame=base.stage_fixture(100,leader_id=37);frame['snapshot']['seq']=10
            page.evaluate('f=>window.__emitSyntheticFrame(f)',frame)
            frame['snapshot']['seq']=11;page.evaluate('f=>window.__emitSyntheticFrame(f)',frame)
            points=page.locator('.stage-reported-edge').evaluate_all("es=>es.flatMap(e=>[.25,.5,.75].map(t=>{const p=e.getPointAtLength(e.getTotalLength()*t),m=e.getScreenCTM();return{id:e.dataset.from,x:m.a*p.x+m.c*p.y+m.e,y:m.b*p.x+m.d*p.y+m.f}}))")
            page.evaluate("""async()=>{const {Stage}=await import('/stage.js'),original=Stage.prototype.inspectEdge;window.__pickCosts=[];Stage.prototype.inspectEdge=function(e){const t=performance.now();original.call(this,e);window.__pickCosts.push(performance.now()-t)}}""")
            misses=[]
            for i,point in enumerate(points):
                if i%30==0:
                    page.evaluate("f=>{f.snapshot.completed_at=new Date().toISOString();window.__emitSyntheticFrame(f)}",frame)
                page.mouse.move(point['x'],point['y'])
                selected=page.locator('.stage-reported-edge.selected').evaluate_all('es=>es.map(e=>e.dataset.from)')
                if selected!=[point['id']]:misses.append({'wanted':point['id'],'selected':selected})
            (base.OUTPUT/'picking.json').write_text(json.dumps({'samples':len(points),'misses':misses,'picking_ms':page.evaluate('window.__pickCosts')}))
            self.assertEqual(misses,[])
        finally:context.close()

if __name__=='__main__':
    names=[name for name in PolishTests.__dict__ if name.startswith('test_')]
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(PolishTests(name) for name in names))
    raise SystemExit(not result.wasSuccessful())
