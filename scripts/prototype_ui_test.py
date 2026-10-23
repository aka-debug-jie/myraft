"""Browser-only synthetic comparison. Never sends a real control operation.

Serve a production Go build, then run with --url and a new --output directory.
Synthetic SSE and request interception are installed by Playwright, not shipped
as a demo mode in the product. Screenshots are labelled in the result manifest.
"""
import argparse, json, time, statistics
from pathlib import Path
from playwright.sync_api import sync_playwright


def fixture(count):
    nodes=[]
    for node in range(1,count+1):
        nodes.append(dict(id=node,reachable=True,identity_ok=True,owned=True,sampled_at='',status=dict(
            id=node,state='Leader' if node==1 else 'Follower',term=1,leader_id=1,instance_id=f'instance-{node}',
            cluster_id='synthetic',membership_hash='synthetic-members',revision=1,last_log_index=2102,
            commit_index=2102,last_applied=2102,committed_commands=2101,applied_commands=2101,x=0,
            log_hash='synthetic-log',committed_hash='synthetic-committed',dropped_events=0)))
    session=dict(id='synthetic',name=f'合成检查 · {count} 节点',managed=True,batch_size=128,created_at='',
                 config=dict(cluster_id='synthetic',nodes=[dict(id=n['id'],addr=f'127.0.0.1:{50000+n["id"]}') for n in nodes]))
    check=dict(state='not_run',kind='',fingerprint='',target=0,at='',completed_at='')
    frame=dict(controller_id='synthetic-controller',mode='REAL',session=session,generation=1,
               snapshot=dict(session_id='synthetic',generation=1,seq=1,completed_at='',nodes=nodes,fingerprint='synthetic',monitor_rpcs=0),
               events=[],event_seq=0,gap=False,stream_dropped=0,operations=[],current_verification=check,
               history_verification=check,checkpoint=None,target=2102,control_enabled=True,busy=False)
    bootstrap=dict(controller_id=frame['controller_id'],mode='REAL',csrf_token='synthetic-only',session=session,sessions=[session],
                   generation=1,control_allowed=True,control_enabled=True,poll_ms=1000,network_partition_supported=False)
    return frame,bootstrap


SETUP="""frame=>{
window.__fixture=frame;window.__streams=new Set();window.__created=0;
window.__send=(update)=>{window.__fixture=update;for(const stream of window.__streams)stream.dispatchEvent(new MessageEvent('frame',{data:JSON.stringify(update)}));};
window.EventSource=class extends EventTarget{
 constructor(){super();window.__created++;window.__streams.add(this);queueMicrotask(()=>{if(window.__streams.has(this)){window.__fixture.snapshot.completed_at=new Date().toISOString();this.dispatchEvent(new MessageEvent('frame',{data:JSON.stringify(window.__fixture)}));}});}
 close(){window.__streams.delete(this);} onerror=null;
};
window.__long=[];new PerformanceObserver(list=>window.__long.push(...list.getEntries().map(e=>e.duration))).observe({type:'longtask',buffered:true});
}"""


GEOMETRY="""()=>{
const host=document.querySelector('.canvas-host'),box=host.getBoundingClientRect();
const nodes=[...host.querySelectorAll('[data-node]')].map(e=>{const r=e.getBoundingClientRect();return {id:+e.dataset.node,x:r.x+r.width/2,y:r.y+r.height/2,r:r.width/2,hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),label:getComputedStyle(e.querySelector('.node-badge__id')).display!=='none'};});
let overlap=[],outside=[],crossings=[];
for(let i=0;i<nodes.length;i++){const a=nodes[i];if(a.x-a.r<box.x-1||a.y-a.r<box.y-1||a.x+a.r>box.right+1||a.y+a.r>box.bottom+1)outside.push(a.id);
 for(let j=i+1;j<nodes.length;j++){const b=nodes[j];if(Math.hypot(a.x-b.x,a.y-b.y)+.2<a.r+b.r)overlap.push([a.id,b.id]);}}
const edges=[...host.querySelectorAll('[data-relation]')];
for(const edge of edges){const [from,to]=edge.dataset.relation.split('/').map(Number),length=edge.getTotalLength(),matrix=edge.getScreenCTM();
 for(let i=1;i<30;i++){const point=edge.getPointAtLength(length*i/30);const p=new DOMPoint(point.x,point.y).matrixTransform(matrix);
 for(const n of nodes)if(n.id!==from&&n.id!==to&&Math.hypot(n.x-p.x,n.y-p.y)<n.r-1)crossings.push([from,to,n.id]);}}
return {members:nodes.length,visible:nodes.filter(n=>n.x>=box.x&&n.x<=box.right&&n.y>=box.y&&n.y<=box.bottom).length,hit:nodes.filter(n=>n.hit).length,labels:nodes.filter(n=>n.label).length,drawn:edges.filter(e=>getComputedStyle(e).visibility!=='hidden'&&Number(getComputedStyle(e).opacity)>.01).length,relations:+host.dataset.relations,overlap,outside,crossings,tab_stops:host.querySelectorAll('[data-node][tabindex="0"]').length};
}"""


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();a.output.mkdir(parents=True,exist_ok=False);result={'mode':'SYNTHETIC','cases':[],'interactions':[],'performance':[]};errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        def page_for(count,renderer,viewport):
            f,b=fixture(count);context=browser.new_context(viewport={'width':viewport[0],'height':viewport[1]},has_touch=viewport[0]<600,reduced_motion='reduce')
            context.add_init_script('('+SETUP+')('+json.dumps(f)+')')
            context.route('**/api/session',lambda route:route.fulfill(json=b))
            context.route('**/api/operations',lambda route:route.abort())
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(a.url.rstrip('/')+f'/prototype/?renderer={renderer}')
            page.wait_for_function('(n)=>document.querySelectorAll("[data-node]").length===n&&document.querySelectorAll("[data-relation]").length===n-1',arg=count)
            return context,page
        try:
            for count in [3,11,20,50,100]:
                for renderer in ['svg','flow']:
                    for viewport in [(1440,900),(1920,1080),(390,844)]:
                        context,page=page_for(count,renderer,viewport)
                        page.mouse.move(0,0);page.wait_for_timeout(120)
                        stats=page.evaluate(GEOMETRY);record={'nodes':count,'renderer':renderer,'viewport':viewport,**stats};result['cases'].append(record)
                        assert stats['visible']==count and stats['hit']==count,record
                        assert not stats['overlap'] and not stats['outside'] and not stats['crossings'],record
                        assert stats['drawn']==count-1 and stats['relations']==count-1 and stats['tab_stops']==1,record
                        if count in [11,100]:page.screenshot(path=str(a.output/f'synthetic-{renderer}-{count}-{viewport[0]}.png'))
                        context.close()
            for count in [11,100]:
                for viewport in [(1440,900),(1920,1080),(390,844)]:
                    context,page=page_for(count,'svg',viewport);page.goto(a.url.rstrip('/')+'/')
                    page.wait_for_function('(n)=>document.querySelectorAll(".stage-node").length===n',arg=count)
                    page.mouse.move(0,0);page.wait_for_timeout(120)
                    page.screenshot(path=str(a.output/f'baseline-6ae0cfe-{count}-{viewport[0]}.png'));context.close()
            for renderer in ['svg','flow']:
                context,page=page_for(100,renderer,(1440,900))
                page.get_by_label('搜索节点').fill('#100');page.get_by_label('搜索节点').press('Enter')
                page.get_by_label('节点 100 详情').wait_for()
                assert page.locator('[data-node="100"]').get_attribute('aria-pressed')=='true'
                page.get_by_label('关闭节点详情').click();page.keyboard.press('Escape')
                assert page.locator('[data-node][aria-pressed="true"]').count()==0
                page.get_by_label('返回全景').click();page.locator('[data-node][tabindex="0"]').focus();page.keyboard.press('End')
                page.wait_for_function('()=>document.activeElement.dataset.node==="100"')
                page.get_by_label('节点状态筛选').select_option('Leader');assert page.locator('.is-filtered').count()==99
                page.get_by_label('节点状态筛选').select_option('all')
                before=page.locator('.zoom-label').inner_text();page.locator('.canvas-host').hover();page.mouse.wheel(0,50)
                assert page.locator('.zoom-label').inner_text()==before
                page.keyboard.down('Control');page.mouse.wheel(0,-100);page.keyboard.up('Control')
                page.wait_for_function('()=>document.querySelector(".zoom-label").textContent==="122%"')
                page.get_by_label('返回全景').click()
                # Selection, dialogs and drafts survive increasing snapshots. Offline identity is unknown, not mismatched.
                page.locator('[data-node="3"]').click();page.locator('[data-act=stop]').click()
                page.evaluate('()=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;f.snapshot.completed_at=new Date().toISOString();window.__send(f)}')
                assert page.get_by_role('dialog').is_visible();page.get_by_role('button',name='取消',exact=True).click()
                page.keyboard.press('Escape')
                page.evaluate('()=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;f.snapshot.nodes[2].reachable=false;f.snapshot.nodes[2].identity_ok=false;f.snapshot.nodes[2].status=null;window.__send(f)}')
                page.wait_for_function('()=>document.querySelector("[data-node=\\"3\\"]").dataset.availability==="offline"')
                # Switching A/B and compare must not create another subscription.
                for _ in range(6):
                    for label in ['SVG','React Flow','并排比较']:page.get_by_role('button',name=label,exact=True).click()
                assert page.evaluate('()=>window.__streams.size')==1
                assert page.evaluate('()=>window.__created')==1
                page.get_by_role('button',name='SVG' if renderer=='svg' else 'React Flow',exact=True).click()
                # A stale sample must remove relations and distinguish unknown state.
                page.evaluate('()=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;f.snapshot.completed_at=new Date(0).toISOString();window.__send(f)}')
                page.wait_for_function('()=>document.querySelectorAll("[data-relation]").length===0')
                assert page.locator('[data-availability=unknown]').count()==100
                result['interactions'].append({'renderer':renderer,'result':'PASS','single_sse':True,'selection_keyboard_filter_stale':True})
                context.close()
            for renderer in ['svg','flow']:
                # Genuine HTTP policy remains at the Go server; here verify the UI's transport hint.
                context,page=page_for(11,renderer,(1440,900));_,boot=fixture(11)
                context.route('**/api/session',lambda route:route.fulfill(json=boot,headers={'X-MyRaft-Read-Only':'1'}))
                page.reload();page.wait_for_function('()=>document.querySelectorAll("[data-node]").length===11')
                assert page.locator('[data-act=generate]').is_disabled();assert page.locator('[data-act=verify]').is_disabled()
                context.close()
                context,page=page_for(11,renderer,(1440,900));pending=[]
                context.route('**/api/operations',lambda route:pending.append(route))
                page.locator('[data-act=generate]').click();page.get_by_test_id('confirm').click()
                page.wait_for_function('()=>document.querySelector("[data-testid=confirm]").disabled')
                assert len(pending)==1
                page.evaluate('()=>{const f=structuredClone(window.__fixture);f.generation=2;f.snapshot.generation=2;f.session.id="session-B";f.snapshot.seq++;f.snapshot.completed_at=new Date().toISOString();window.__send(f)}')
                page.get_by_role('dialog').wait_for(state='hidden');pending[0].abort()
                page.wait_for_function('()=>!document.querySelector("[data-act=generate]").disabled')
                assert page.locator('.notice-error').count()==0,'old-scope error leaked into new session'
                assert len(pending)==1
                page.locator('[data-act=generate]').click();page.get_by_test_id('confirm').click()
                page.wait_for_function('()=>document.querySelector("[data-testid=confirm]").disabled');assert len(pending)==2;pending[1].abort()
                page.get_by_role('alert').wait_for();assert '结果未知' in page.get_by_role('alert').inner_text();assert len(pending)==2
                result['interactions'].append({'renderer':renderer,'result':'PASS','readonly_unknown_write_old_scope':True});context.close()
            for renderer in ['svg','flow']:
                context,page=page_for(100,renderer,(390,844))
                page.get_by_label('打开工作区导航').click();page.get_by_role('button',name='一致性证据',exact=True).click();page.get_by_label('关闭证据').click()
                session=context.new_cdp_session(page)
                box=page.locator('.canvas-host').bounding_box();x=box['x']+box['width']/2;y=box['y']+box['height']/2
                session.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x-30,'y':y,'id':1},{'x':x+30,'y':y,'id':2}]})
                for distance in [40,50,60]:session.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x-distance,'y':y,'id':1},{'x':x+distance,'y':y,'id':2}]})
                session.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                page.wait_for_function('()=>parseInt(document.querySelector(".zoom-label").textContent)>100')
                page.get_by_label('返回全景').click();page.get_by_label('搜索节点').fill('100');page.get_by_label('搜索节点').press('Enter')
                page.get_by_label('节点 100 详情').wait_for();page.screenshot(path=str(a.output/f'synthetic-{renderer}-mobile-focus.png'))
                page.get_by_label('关闭节点详情').click();page.keyboard.press('Escape');page.get_by_label('返回全景').click()
                page.get_by_role('button',name='并排比较',exact=True).click()
                page.wait_for_function('()=>document.querySelectorAll("[data-node]").length===200')
                page.screenshot(path=str(a.output/f'synthetic-{renderer}-mobile-compare.png'))
                result['interactions'].append({'renderer':renderer,'result':'PASS','mobile_navigation_pinch_focus_compare':True});context.close()
            context,page=page_for(11,'svg',(1440,900))
            context.route('**/FlowCanvas-*.js',lambda route:route.abort())
            page.get_by_role('button',name='React Flow',exact=True).click()
            page.get_by_role('button',name='重新加载页面').wait_for()
            assert page.locator('.topbar').is_visible()
            assert page.evaluate('()=>window.__streams.size')==1
            result['interactions'].append({'result':'PASS','renderer_chunk_failure_contained':True});context.close()
            # Same sequence and viewport, each renderer alone; not a production throughput benchmark.
            for renderer in ['svg','flow']:
                for trial in range(3):
                    context,page=page_for(100,renderer,(1440,900))
                    cdp=context.new_cdp_session(page);cdp.send('Performance.enable')
                    before={m['name']:m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                    stats=page.evaluate('''async()=>{const times=[];for(let i=0;i<120;i++){const f=structuredClone(window.__fixture);f.snapshot.seq++;f.snapshot.completed_at=new Date().toISOString();f.snapshot.nodes.forEach(n=>{n.status.commit_index++;n.status.last_log_index++;n.status.last_applied++});const start=performance.now();window.__send(f);await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));times.push(performance.now()-start);}return {times,long_tasks:window.__long,heap:performance.memory?.usedJSHeapSize??null,active_sse:window.__streams.size};}''')
                    values=sorted(stats.pop('times'));stats.update(renderer=renderer,trial=trial+1,samples=len(values),p50_ms=statistics.median(values),p95_ms=values[int(len(values)*.95)-1],maximum_ms=max(values))
                    after={m['name']:m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                    stats['task_cpu_ms']=(after['TaskDuration']-before['TaskDuration'])*1000
                    stats['script_cpu_ms']=(after['ScriptDuration']-before['ScriptDuration'])*1000
                    stats['js_heap_bytes']=after['JSHeapUsedSize']
                    cdp.send('HeapProfiler.collectGarbage');memory_before={m['name']:m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                    for _ in range(10):
                        for label in ['SVG','React Flow','并排比较']:page.get_by_role('button',name=label,exact=True).click()
                    page.get_by_role('button',name='SVG' if renderer=='svg' else 'React Flow',exact=True).click()
                    cdp.send('HeapProfiler.collectGarbage');memory_after={m['name']:m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                    stats['switch_lifecycle']={key:{'before':memory_before[key],'after':memory_after[key]} for key in ['Nodes','JSEventListeners','JSHeapUsedSize']}
                    assert page.evaluate('()=>window.__streams.size')==1
                    result['performance'].append(stats);context.close()
            assert not errors,errors
            result.update(result='PASS',page_errors=errors)
        except Exception as error:
            result.update(result='FAIL',error=f'{type(error).__name__}: {error}',page_errors=errors);raise
        finally:
            (a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));browser.close()
    print(json.dumps({'result':result['result'],'cases':len(result['cases']),'interactions':len(result['interactions']),'trials':len(result['performance'])}))


if __name__=='__main__':main()
