import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path.cwd()/'scripts'))
from prototype_ui_test import fixture,SETUP
out=Path(sys.argv[1]);result={'mode':'SYNTHETIC','method':'in-page DOM clicks and two RAF per state change, CDP GC per 50 cycles; removes per-click driver allocations','runs':[]}
with sync_playwright() as p:
 b=p.chromium.launch()
 try:
  for renderer in ['svg','flow']:
   f,boot=fixture(11);ctx=b.new_context(viewport={'width':390,'height':844},reduced_motion='no-preference');ctx.add_init_script('('+SETUP+')('+json.dumps(f)+')')
   ctx.route('**/api/session',lambda route:route.fulfill(json=boot));page=ctx.new_page();page.goto('http://127.0.0.1:18151/prototype/?renderer='+renderer);page.locator('[data-node="3"]').click();page.get_by_label('查看节点详情').wait_for();cdp=ctx.new_cdp_session(page);cdp.send('Performance.enable');samples=[]
   for batch in range(11):
    if batch:
     page.evaluate('''async()=>{const tick=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));for(let i=0;i<50;i++){const f=structuredClone(window.__fixture);f.snapshot.seq++;f.snapshot.completed_at=new Date().toISOString();window.__send(f);await tick();document.querySelector('[aria-label="查看节点详情"]').click();await tick();document.querySelector('.mobile-detail-header button').click();await tick();}}''')
    cdp.send('HeapProfiler.collectGarbage');m={x['name']:x['value'] for x in cdp.send('Performance.getMetrics')['metrics']};samples.append({'cycles':batch*50,**{k:m[k] for k in ['Nodes','JSEventListeners','JSHeapUsedSize']}})
   result['runs'].append({'renderer':renderer,'samples':samples,'sse':page.evaluate('()=>window.__streams.size')});ctx.close()
  assert all(r['sse']==1 and all(s['Nodes']==r['samples'][1]['Nodes'] and s['JSEventListeners']==r['samples'][1]['JSEventListeners'] for s in r['samples'][2:]) for r in result['runs']), result
  result['result']='PASS'
 finally:b.close();out.write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
