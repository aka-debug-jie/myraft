"""Same-host cold first interaction and drag frames; synthetic API, real Go assets."""
import argparse,json,statistics,time
from pathlib import Path
from playwright.sync_api import sync_playwright
from prototype_ui_test import fixture,SETUP

parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False);result={'mode':'SYNTHETIC','runs':[]}
with sync_playwright() as p:
    browser=p.chromium.launch()
    try:
        for count in [11,100]:
            for renderer in ['svg','flow']:
                for trial in range(3):
                    frame,bootstrap=fixture(count);context=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='reduce')
                    context.add_init_script('('+SETUP+')('+json.dumps(frame)+')');context.route('**/api/session',lambda route:route.fulfill(json=bootstrap));page=context.new_page()
                    started=time.perf_counter();page.goto(args.url.rstrip('/')+f'/prototype/?renderer={renderer}')
                    page.wait_for_function('(n)=>document.querySelectorAll("[data-node]").length===n&&document.querySelectorAll("[data-relation]").length===n-1',arg=count)
                    ready=(time.perf_counter()-started)*1000
                    page.locator('[data-node="1"]').click();page.get_by_label('节点 1 详情').wait_for();interactive=(time.perf_counter()-started)*1000
                    page.get_by_label('关闭节点详情').click();page.keyboard.press('Escape');page.get_by_label('返回全景').click()
                    page.evaluate('()=>{window.__frames=[];window.__record=true;let last=performance.now();function tick(now){if(!window.__record)return;window.__frames.push(now-last);last=now;requestAnimationFrame(tick);}requestAnimationFrame(tick);}')
                    box=page.locator('.canvas-host').bounding_box();page.mouse.move(box['x']+box['width']*.46,box['y']+box['height']*.35);page.mouse.down()
                    page.mouse.move(box['x']+box['width']*.66,box['y']+box['height']*.48,steps=40);page.mouse.move(box['x']+box['width']*.46,box['y']+box['height']*.35,steps=40);page.mouse.up()
                    values=page.evaluate('()=>{window.__record=false;return window.__frames.slice(1)}');values.sort();assert values
                    metrics=page.evaluate('()=>({long_tasks:window.__long,resources:performance.getEntriesByType("resource").filter(e=>e.name.includes("/prototype/")).map(e=>({file:e.name.split("/").pop(),bytes:e.encodedBodySize})),heap:performance.memory?.usedJSHeapSize??null})')
                    metrics.update(nodes=count,renderer=renderer,trial=trial+1,ready_ms=ready,first_inspector_ms=interactive,drag_frames=len(values),drag_p50_ms=statistics.median(values),drag_p95_ms=values[int(len(values)*.95)-1])
                    result['runs'].append(metrics);context.close()
        result['result']='PASS'
    finally:browser.close();(args.output/'results.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'result':result['result'],'runs':len(result['runs'])}))
