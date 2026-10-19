"""Real local console acceptance, screenshots, shared collection and modest latency trials.
Requires optional Playwright Chromium and prebuilt Go binaries. Owns only its new
controller/session directory; controller shutdown cleans its retained child handles.
"""
from pathlib import Path
import json,subprocess,time,re,os,statistics,hashlib,zipfile,io
from playwright.sync_api import sync_playwright, expect
import argparse,sys
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dashboard', type=Path, required=True)
parser.add_argument('--node', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args=parser.parse_args()
repo=Path(__file__).resolve().parents[1];root=args.output.resolve();root.mkdir(parents=True,exist_ok=False);output=(root/'controller.txt').open('wb')
env=os.environ.copy()
process=subprocess.Popen([str(args.dashboard.resolve()),'-listen','127.0.0.1:0','-data-root',str(root/'sessions'),'-node-bin',str(args.node.resolve()),'-source-dir',str(repo),'-python',sys.executable,'-allow-control'],stdout=output,stderr=subprocess.STDOUT,env=env)
summary={'mode':'REAL','root':root.name,'measurements':[]}
try:
 url=None
 for _ in range(100):
  m=re.search(r'http://127.0.0.1:\d+',(root/'controller.txt').read_text())
  if m:url=m[0];break
  time.sleep(.05)
 assert url
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1050},reduced_motion='reduce');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  api=p.request.new_context(base_url=url)
  def frame():return api.get('/api/snapshot').json()
  def until(test,timeout=45):
   end=time.monotonic()+timeout
   while time.monotonic()<end:
    f=frame()
    if test(f):return f
    time.sleep(.1)
   raise AssertionError('timeout: '+json.dumps(frame(),ensure_ascii=False)[:3000])
  def operate(kind,**kw):
   b=api.get('/api/session').json();f=frame()
   r=api.post('/api/operations',headers={'Origin':url,'X-CSRF-Token':b['csrf_token']},data={'kind':kind,'controller_id':f['controller_id'],'session_id':f['session']['id'] if f['session'] else '', 'generation':f['generation'],**kw})
   assert r.ok, r.text()
   return r.json()
  def completed(op,timeout=60):
   f=until(lambda f:any(o['id']==op['id'] and o.get('ended_at') for o in f['operations']),timeout)
   return next(o for o in f['operations'] if o['id']==op['id'])
  page.goto(url);page.locator('[data-page=settings]').click();page.locator('[data-act=enable-control]').click();page.locator('#confirm').click()
  expect(page.locator('#create-form button')).to_be_enabled();page.locator('#create-form button').click()
  until(lambda f: len(f['snapshot']['nodes'] or [])==11 and sum(n.get('status',{}).get('state')=='Leader' for n in f['snapshot']['nodes'] if n.get('status'))==1 and not f['busy'])
  page.locator('[data-page=overview]').click();page.locator('[data-act=generate]').click();page.locator('#confirm').dblclick()
  f=until(lambda f:any(o['kind']=='generate' and o.get('committed') for o in f['operations']))
  assert len([o for o in f['operations'] if o['kind']=='generate'])==1
  target=f['target'];until(lambda f:all(n.get('status') and n['status']['last_applied']>=target for n in f['snapshot']['nodes']))
  assert completed(operate('checkpoint'))['state']=='succeeded';saved=frame()['checkpoint']
  leader=next(n['id'] for n in frame()['snapshot']['nodes'] if n.get('status',{}).get('state')=='Leader')
  page.locator(f'[data-node="{leader}"]').first.click();page.locator('[data-act=stop]').click();assert page.locator('#action-dialog').is_visible()
  # Cancel confirmation must perform no stop.
  page.locator('#action-dialog button[value=cancel]').click();assert all(n['reachable'] for n in frame()['snapshot']['nodes'])
  page.locator('[data-act=stop]').click();page.locator('#confirm').click()
  until(lambda f:any(n.get('status') and n['status']['state']=='Leader' and n['id']!=leader for n in f['snapshot']['nodes']) and not f['busy'])
  assert completed(operate('generate',count=3,seed=42))['committed']
  assert completed(operate('restart',node_id=leader))['state']=='succeeded'
  until(lambda f:all(n.get('status') and n['status']['applied_commands']==2104 for n in f['snapshot']['nodes']))
  assert completed(operate('verify_history'))['state']=='succeeded'
  assert completed(operate('verify'))['state']=='succeeded';assert frame()['checkpoint']==saved
  # Actual browser counts all share the same collector; counters include node protocol RPCs.
  # Wait for event backlog from verification/recovery to be collected before idle measurements.
  previous=frame()['snapshot'];stable=0
  for _ in range(15):
   current=until(lambda f:f['snapshot']['seq']>previous['seq'])['snapshot']
   stable=stable+1 if current['monitor_rpcs']-previous['monitor_rpcs']==11*(current['seq']-previous['seq']) else 0
   previous=current
   if stable>=2:break
  assert stable>=2, 'event collector did not settle'
  pages=[page]
  for count in [1,5,10]:
   while len(pages)<count:
    tab=browser.new_page();tab.goto(url);pages.append(tab)
   start=frame()['snapshot'];end=until(lambda f:f['snapshot']['seq']>=start['seq']+5)['snapshot']
   before=sum(n['status']['rpc_requests'] for n in start['nodes']);after=sum(n['status']['rpc_requests'] for n in end['nodes'])
   m={'browsers':count,'rounds':end['seq']-start['seq'],'monitor_rpcs':end['monitor_rpcs']-start['monitor_rpcs'],'node_total_rpcs':after-before}
   assert m['monitor_rpcs']==11*m['rounds'],m
   summary['measurements'].append(m)
  # Same shared collector on for both groups; varies only browser count/rendering.
  latencies=[]
  for count in [10,0,10,0]:
   if count==0:
    for tab in pages:tab.close()
    pages=[]
   else:
    while len(pages)<count:
     tab=browser.new_page();tab.goto(url);pages.append(tab)
   for trial in range(3):
    begin=time.perf_counter();op=completed(operate('generate',count=256,seed=42+trial));elapsed=time.perf_counter()-begin
    assert op['committed'];latencies.append({'browsers':count,'entries':256,'external_seconds':elapsed})
  summary['latency_trials']=latencies
  page=browser.new_page(viewport={'width':1440,'height':1050},reduced_motion='reduce');page.on('pageerror',lambda e:errors.append(str(e)));page.goto(url)
  # Independent real experiment, then an interrupted run.
  op=completed(operate('experiment',nodes=[3],scenarios=['replication'],count=2101,rounds=1,seed=42,batch=128),120)
  assert op['state']=='succeeded',op
  interrupted=operate('experiment',nodes=[10],scenarios=['election'],count=256,rounds=3,seed=42,batch=128)
  until(lambda f:any(o['id']==interrupted['id'] and o.get('result',{}).get('phase')=='running' for o in f['operations']),120)
  operate('cancel_experiment',operation_id=interrupted['id'])
  canceled=completed(interrupted,30);assert canceled['state']=='canceled',canceled
  summary['experiment']={'result':op['result'],'interrupted':canceled['result']}
  assert completed(operate('verify_history'))['state']=='succeeded'
  assert completed(operate('verify'))['state']=='succeeded'
  exported=completed(operate('export'));assert exported['state']=='succeeded'
  data=api.get('/api/exports/'+exported['id']).body();assert hashlib.sha256(data).hexdigest()==exported['result']['sha256']
  (root/'evidence.zip').write_bytes(data)
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   assert z.testzip() is None
   assert any(x.endswith('results.json') for x in z.namelist())
   assert any(x.endswith('run-status.json') for x in z.namelist())
  for tab in ['overview','logs','faults','experiments','evidence','settings']:
   page.locator('[data-page='+tab+']').click()
   if tab=='logs':page.locator('#logs-form button').click();expect(page.locator('[data-entry]').first).to_be_visible()
   page.screenshot(path=str(root/(tab+'.png')),full_page=True)
  page.locator('[data-page=overview]').click();page.locator('[data-act=theme]').first.click();page.screenshot(path=str(root/'dark.png'),full_page=True)
  page.locator('[data-act=theme]').first.click();page.locator('[data-act=present]').first.click();page.screenshot(path=str(root/'projection.png'),full_page=True);page.locator('[data-act=present]').first.click()
  page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(root/'mobile.png'),full_page=True)
  assert not errors,errors
  summary.update({'result':'PASS','original_checkpoint':saved,'final_checkpoint':frame()['checkpoint'],'page_errors':errors})
  (root/'results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps({'result':'PASS','root':str(root),'measurements':summary['measurements'],'latency_trials':latencies},ensure_ascii=False),flush=True)
  browser.close();api.dispose()
finally:
 process.terminate()
 try:process.wait(timeout=25)
 except subprocess.TimeoutExpired:process.kill();process.wait();raise RuntimeError('controller cleanup exceeded bound; inspect child ownership')
 output.close()
