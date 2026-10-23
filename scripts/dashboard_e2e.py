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
if os.name == 'nt':
 parser.error('This browser harness uses POSIX graceful shutdown; use the documented native Windows console acceptance steps.')
repo=Path(__file__).resolve().parents[1];root=args.output.resolve();root.mkdir(parents=True,exist_ok=False);output=(root/'controller.txt').open('wb')
env=os.environ.copy()
process=subprocess.Popen([str(args.dashboard.resolve()),'-listen','127.0.0.1:0','-data-root',str(root/'sessions'),'-node-bin',str(args.node.resolve()),'-source-dir',str(repo),'-python',sys.executable,'-allow-control'],stdout=output,stderr=subprocess.STDOUT,env=env)
summary={'mode':'REAL','root':root.name,'measurements':[],'dashboard_sha256':hashlib.sha256(args.dashboard.read_bytes()).hexdigest(),'node_sha256':hashlib.sha256(args.node.read_bytes()).hexdigest()}
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
  def operation_ids(kind):
   return {o['id'] for o in frame()['operations'] if o['kind']==kind}
  def wait_latest(kind,previous_ids,timeout=60):
   f=until(lambda f:any(o['kind']==kind and o['id'] not in previous_ids and o.get('ended_at') for o in f['operations']),timeout)
   return next(o for o in reversed(f['operations']) if o['kind']==kind and o['id'] not in previous_ids)
  def open_nav(tab):
   if not tab.locator('#sidebar').evaluate("e => e.classList.contains('open') || e.classList.contains('pinned')"):
    tab.locator('#nav-trigger').click()
  def navigate(tab,name):
   open_nav(tab);tab.locator(f'#nav button[data-page="{name}"]').click()
  def side_action(tab,name):
   open_nav(tab);tab.locator(f'#nav-actions [data-act="{name}"]').click()
  def close_menu(tab):
   if tab.locator('#sidebar').evaluate("e => e.classList.contains('open')"):
    tab.keyboard.press('Escape')
  page.goto(url);navigate(page,'settings');page.locator('#main [data-act=enable-control]').click();page.locator('#confirm').click()
  expect(page.locator('#create-form button')).to_be_enabled();page.locator('#create-form button').click()
  until(lambda f: len(f['snapshot']['nodes'] or [])==11 and sum(n.get('status',{}).get('state')=='Leader' for n in f['snapshot']['nodes'] if n.get('status'))==1 and not f['busy'])
  navigate(page,'overview');side_action(page,'generate');page.locator('#confirm').dblclick()
  f=until(lambda f:any(o['kind']=='generate' and o.get('committed') for o in f['operations']))
  assert len([o for o in f['operations'] if o['kind']=='generate'])==1
  target=f['target'];until(lambda f:all(n.get('status') and n['status']['last_applied']>=target for n in f['snapshot']['nodes']))
  navigate(page,'evidence');before=operation_ids('verify');side_action(page,'verify')
  assert wait_latest('verify',before)['state']=='succeeded'
  before=operation_ids('checkpoint');page.locator('#main [data-act=checkpoint]').click()
  assert wait_latest('checkpoint',before)['state']=='succeeded';saved=frame()['checkpoint']
  navigate(page,'overview')
  leader=next(n['id'] for n in frame()['snapshot']['nodes'] if n.get('status',{}).get('state')=='Leader')
  page.locator(f'#stage-host .stage-node[data-node="{leader}"]').click();page.locator('#node-detail [data-act=stop]').click();assert page.locator('#action-dialog').is_visible()
  # Cancel confirmation must perform no stop.
  page.locator('#action-dialog button[value=cancel]').click();assert all(n['reachable'] for n in frame()['snapshot']['nodes'])
  page.locator('#node-detail [data-act=stop]').click();page.locator('#confirm').click()
  until(lambda f:any(n.get('status') and n['status']['state']=='Leader' and n['id']!=leader for n in f['snapshot']['nodes']) and not f['busy'])
  before=operation_ids('generate');navigate(page,'overview');side_action(page,'generate')
  page.locator('#action-dialog input[name=count]').fill('3');page.locator('#action-dialog input[name=seed]').fill('42');page.locator('#confirm').click()
  assert wait_latest('generate',before)['committed']
  navigate(page,'overview');page.locator(f'#stage-host .stage-node[data-node="{leader}"]').click()
  before=operation_ids('restart');page.locator('#node-detail [data-act=restart]').click()
  assert wait_latest('restart',before)['state']=='succeeded'
  until(lambda f:all(n.get('status') and n['status']['applied_commands']==2104 for n in f['snapshot']['nodes']))
  navigate(page,'evidence');before=operation_ids('verify_history');page.locator('#main [data-act=verify-history]').click()
  assert wait_latest('verify_history',before)['state']=='succeeded'
  before=operation_ids('verify');side_action(page,'verify')
  assert wait_latest('verify',before)['state']=='succeeded';assert frame()['checkpoint']==saved
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
  # Independent real experiment, then an interrupted run, both submitted from the actual form.
  navigate(page,'experiments')
  form=page.locator('#experiment-form');form.locator('[name=nodes]:checked').uncheck();form.locator('[name=nodes][value="3"]').check();form.locator('[name=scenarios][value="replication"]').check();form.locator('details summary').click()
  form.locator('[name=entries]').fill('2101');form.locator('[name=rounds]').fill('1');form.locator('[name=seed]').fill('42');form.locator('[name=batch]').fill('128')
  # Live updates preserve the form node, values and caret instead of rebuilding it.
  page.evaluate("window.__experimentForm=document.querySelector('#experiment-form')")
  before_seq=frame()['snapshot']['seq'];until(lambda f:f['snapshot']['seq']>before_seq)
  assert page.evaluate("window.__experimentForm===document.querySelector('#experiment-form')")
  assert form.locator('[name=nodes]:checked').evaluate_all("es=>es.map(e=>e.value)")==['3']
  assert form.locator('[name=scenarios]:checked').evaluate_all("es=>es.map(e=>e.value)")==['replication']
  assert form.locator('[name=entries]').input_value()=='2101' and form.locator('[name=rounds]').input_value()=='1'
  assert form.locator('[name=seed]').input_value()=='42' and form.locator('[name=batch]').input_value()=='128'
  before=operation_ids('experiment');form.locator('button[type=submit]').click()
  op=wait_latest('experiment',before,120)
  assert op['state']=='succeeded',op
  form=page.locator('#experiment-form');form.locator('[name=nodes]:checked').uncheck();form.locator('[name=nodes][value="10"]').check();form.locator('[name=scenarios]:checked').uncheck();form.locator('[name=scenarios][value="election"]').check()
  form.locator('[name=entries]').fill('256');form.locator('[name=rounds]').fill('3');form.locator('[name=seed]').fill('42');form.locator('[name=batch]').fill('128')
  before=operation_ids('experiment');form.locator('button[type=submit]').click()
  running=until(lambda f:any(o['kind']=='experiment' and o['id'] not in before and o.get('result',{}).get('phase')=='running' for o in f['operations']),120)
  interrupted=next(o for o in running['operations'] if o['kind']=='experiment' and o['id'] not in before)
  with page.expect_response(lambda response: response.url.endswith('/api/operations') and response.request.post_data_json.get('kind')=='cancel_experiment') as cancel_response:
   page.locator('#main [data-act=cancel-experiment]').click()
  assert cancel_response.value.ok and cancel_response.value.json()['id']==interrupted['id']
  canceled=completed(interrupted,30);assert canceled['state']=='canceled',canceled
  summary['experiment']={'result':op['result'],'interrupted':canceled['result']}
  navigate(page,'evidence');before=operation_ids('verify_history');page.locator('#main [data-act=verify-history]').click()
  assert wait_latest('verify_history',before)['state']=='succeeded'
  before=operation_ids('verify');side_action(page,'verify')
  assert wait_latest('verify',before)['state']=='succeeded'
  before=operation_ids('export');page.locator('#main [data-act=export]').click()
  exported=wait_latest('export',before);assert exported['state']=='succeeded'
  data=api.get('/api/exports/'+exported['id']).body();assert hashlib.sha256(data).hexdigest()==exported['result']['sha256']
  (root/'evidence.zip').write_bytes(data)
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   assert z.testzip() is None
   assert any(x.endswith('results.json') for x in z.namelist())
   assert any(x.endswith('run-status.json') for x in z.namelist())
  for tab in ['overview','logs','faults','experiments','evidence','settings']:
   navigate(page,tab)
   if tab=='logs':page.locator('#main #logs-form button').click();expect(page.locator('[data-entry]').first).to_be_visible()
   close_menu(page)
   page.screenshot(path=str(root/(tab+'.png')),full_page=True)
  navigate(page,'overview');open_nav(page)
  if page.locator('html').get_attribute('data-theme')!='dark':page.locator('#sidebar [data-act=theme]').click()
  close_menu(page);page.screenshot(path=str(root/'dark.png'),full_page=True)
  open_nav(page);page.locator('#sidebar [data-act=theme]').click();page.locator('#sidebar [data-act=present]').click();close_menu(page)
  page.screenshot(path=str(root/'projection.png'),full_page=True);open_nav(page);page.locator('#sidebar [data-act=present]').click();close_menu(page)
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
