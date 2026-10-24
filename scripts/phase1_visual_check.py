"""Read-only real KPI checks and labelled synthetic exceptional-state screenshots."""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright
from prototype_ui_test import fixture,SETUP

parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--hundred-url',required=True);parser.add_argument('--output',required=True,type=Path)
a=parser.parse_args();a.output.mkdir(parents=True,exist_ok=False);result={'real':[],'synthetic':[]};errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch()
    try:
        for count,url in [(11,a.url),(100,a.hundred_url)]:
            for renderer in ['svg','flow']:
                page=browser.new_page(viewport={'width':1440,'height':900},reduced_motion='reduce');page.on('pageerror',lambda e:errors.append(str(e)))
                page.add_init_script('''(()=>{const Native=window.EventSource;window.__observations=[];window.EventSource=class extends Native{constructor(...args){super(...args);this.addEventListener('frame',e=>{const f=JSON.parse(e.data),prior=window.__observations.at(-1);if(!prior||f.snapshot.seq>prior.snapshot.seq){window.__observations.push(f);window.__observations=window.__observations.slice(-2);}});}}})();''')
                page.goto(url.rstrip('/')+f'/prototype/?renderer={renderer}')
                page.wait_for_function('(n)=>document.querySelectorAll("[data-node]").length===n&&document.querySelector("[data-kpi=rpc]").textContent!=="—"',arg=count)
                check=page.evaluate('''()=>{const [a,b]=window.__observations,leader=b.snapshot.nodes.find(n=>n.reachable&&n.identity_ok&&n.status?.state==='Leader').status;const values=Object.fromEntries([...document.querySelectorAll('[data-kpi]')].map(n=>[n.dataset.kpi,n.textContent]));return {values,expected:{leader:'#'+leader.id,term:String(leader.term),commit:String(leader.commit_index),applied:String(leader.last_applied),x:String(leader.x),rpc:((b.snapshot.monitor_rpcs-a.snapshot.monitor_rpcs)/((Date.parse(b.snapshot.completed_at)-Date.parse(a.snapshot.completed_at))/1000)).toFixed(1)},seq:b.snapshot.seq};}''')
                assert check['values']==check['expected'],check
                for width,height in [(1440,900),(1920,1080),(390,844)]:
                    page.set_viewport_size({'width':width,'height':height});page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                    assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(animations='disabled',path=str(a.output/f'real-{renderer}-{count}-{width}-dark.png'))
                page.set_viewport_size({'width':1440,'height':900});page.get_by_label('切换主题').click();page.wait_for_function('()=>document.documentElement.dataset.theme==="light"');page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');page.screenshot(animations='disabled',path=str(a.output/f'real-{renderer}-{count}-light.png'))
                page.get_by_label('切换投影模式').click();page.wait_for_function('()=>document.documentElement.dataset.present==="true"');page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');page.screenshot(animations='disabled',path=str(a.output/f'real-{renderer}-{count}-projection.png'))
                page.get_by_label('切换投影模式').click();page.get_by_label('切换主题').click();page.wait_for_function('()=>document.documentElement.dataset.theme==="dark"')
                page.get_by_label('搜索节点').fill(str(count));page.get_by_label('搜索节点').press('Enter');page.get_by_label(f'节点 {count} 详情').wait_for();page.screenshot(animations='disabled',path=str(a.output/f'real-{renderer}-{count}-inspector.png'))
                result['real'].append({'nodes':count,'renderer':renderer,'result':'PASS',**check});page.close()
        for scenario in ['empty','stale','multiple-leaders','identity','disconnected','loading']:
            frame,bootstrap=fixture(11);context=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='reduce')
            pending=[];gate={'hold':scenario=='loading'};context.add_init_script('('+SETUP+')('+json.dumps(frame)+')');context.route('**/api/session',lambda route:pending.append(route) if gate['hold'] else route.fulfill(json=bootstrap));context.route('**/api/operations',lambda route:route.abort());page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(a.url.rstrip('/')+'/prototype/?renderer=svg')
            if scenario=='loading':page.get_by_text('正在连接控制器',exact=True).wait_for()
            else:
                page.wait_for_function('()=>document.querySelectorAll("[data-node]").length===11')
                page.evaluate('''kind=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;if(kind==='empty'){f.session=null;f.snapshot.nodes=[]}if(kind==='stale')f.snapshot.completed_at=new Date(0).toISOString();if(kind==='multiple-leaders')f.snapshot.nodes[1].status.state='Leader';if(kind==='identity')f.snapshot.nodes[0].identity_ok=false;if(kind==='disconnected'){for(const s of window.__streams)s.onerror?.(new Event('error'));return;}window.__send(f);}''',scenario)
                expected={'empty':'无活跃会话','stale':'采样过期','multiple-leaders':'观察到多个本地 Leader','identity':'身份异常','disconnected':'连接中断'}[scenario]
                page.wait_for_function('(label)=>document.querySelector("[data-observation-state]").textContent===label',arg=expected)
            page.screenshot(animations='disabled',path=str(a.output/f'synthetic-{scenario}.png'));result['synthetic'].append({'scenario':scenario,'result':'PASS'})
            gate['hold']=False
            for route in pending:route.fulfill(json=bootstrap)
            if pending:page.wait_for_function('()=>window.__streams.size===1')
            context.unroute_all(behavior='wait')
            context.close()
        assert not errors,errors;result.update(result='PASS',page_errors=errors)
    finally:browser.close();(a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({'result':result['result'],'real_checks':len(result['real']),'synthetic_states':len(result['synthetic'])}))
