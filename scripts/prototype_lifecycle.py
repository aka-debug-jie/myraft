"""Warm both renderers before measuring repeated switch cleanup (synthetic only)."""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright
from prototype_ui_test import fixture,SETUP

parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False);result={'mode':'SYNTHETIC','runs':[]}
with sync_playwright() as p:
    browser=p.chromium.launch()
    try:
        for renderer in ['svg','flow']:
            frame,bootstrap=fixture(100);context=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='reduce')
            context.add_init_script('('+SETUP+')('+json.dumps(frame)+')');context.route('**/api/session',lambda route:route.fulfill(json=bootstrap));page=context.new_page()
            page.goto(args.url.rstrip('/')+f'/prototype/?renderer={renderer}');cdp=context.new_cdp_session(page);cdp.send('Performance.enable')
            def settle():
                page.evaluate('()=>{const f=structuredClone(window.__fixture);f.snapshot.seq++;f.snapshot.completed_at=new Date().toISOString();window.__send(f)}')
                page.wait_for_function('()=>document.querySelectorAll("[data-node]").length===100&&document.querySelectorAll("[data-relation]").length===99')
                page.evaluate('async()=>{await new Promise(r=>requestAnimationFrame(r));await new Promise(r=>requestAnimationFrame(r));await new Promise(r=>requestIdleCallback(r,{timeout:1000}));}')
            def cycle():
                for label in ['SVG','React Flow','并排比较']:
                    page.get_by_role('button',name=label,exact=True).click()
                    page.wait_for_function('(n)=>document.querySelectorAll("[data-node]").length===n',arg=200 if label=='并排比较' else 100)
                page.get_by_role('button',name='SVG' if renderer=='svg' else 'React Flow',exact=True).click();settle()
            for _ in range(2):cycle()
            samples=[];record={'renderer':renderer,'warmup_cycles':2,'measured_cycles':8,'samples':samples};result['runs'].append(record)
            for batch in range(9):
                if batch:cycle()
                cdp.send('HeapProfiler.collectGarbage');metrics={m['name']:m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
                samples.append({'batch':batch,**{key:metrics[key] for key in ['Nodes','JSEventListeners','JSHeapUsedSize']},'sse':page.evaluate('()=>window.__streams.size')})
            assert all(row['sse']==1 for row in samples)
            context.close()
        result['result']='PASS'
    except Exception as error:
        result['result']='FAIL';result['error']=str(error);result['debug']=page.evaluate('()=>({nodes:document.querySelectorAll("[data-node]").length,edges:document.querySelectorAll("[data-relation]").length,text:document.body.innerText,frame:window.__fixture,streams:window.__streams.size})');page.screenshot(path=str(args.output/'failure.png'));raise
    finally:
        browser.close();(args.output/'results.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
