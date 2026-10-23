"""Synthetic copy/semantics checks using the existing Python Playwright dependency."""
import argparse,json
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
static=a.source/'cmd/dashboard/static'
charts='data:text/javascript,'+quote((static/'charts.js').read_text())
views='data:text/javascript,'+quote((static/'views.js').read_text().replace("'./charts.js'",repr(charts)))
JS='()=>{\n  const {views,charts}=window.ui;\n  const now=new Date().toISOString();\n  const members=[1,2,3,4].map(id=>({id}));\n  const snapshots=[\n    {id:1,reachable:true,identity_ok:true,status:{state:\'Leader\',term:7,leader_id:1}},\n    {id:2,reachable:true,identity_ok:true,status:{state:\'Follower\',term:7,leader_id:1}},\n    {id:3,reachable:true,identity_ok:true,status:{state:\'Follower\',term:7,leader_id:1}},\n    {id:4,reachable:true,identity_ok:true,status:{state:\'Follower\',term:6,leader_id:1}},\n  ];\n  const s={connected:true,selected:1,bootstrap:{poll_ms:1000,read_only_transport:true,control_allowed:false},frame:{snapshot:{completed_at:now,nodes:snapshots},session:{config:{nodes:members}},operations:[]}};\n  const checks=[];\n  const check=(name,condition,detail=\'\')=>checks.push({name,passed:Boolean(condition),detail});\n  const dock=views.lessonDock(s);\n  check(\'read-only lesson badge says 只读\',dock.includes(\'>只读</button>\')&&!/>0[1-6]<\\/button>/.test(dock),dock);\n  const exp=views.experiments(s);\n  const sizes=[...exp.matchAll(/name="nodes" value="(\\d+)"/g)].map(x=>Number(x[1]));\n  check(\'performance sizes are ordered 3,10,11,20,50,100\',JSON.stringify(sizes)===JSON.stringify([3,10,11,20,50,100]),JSON.stringify(sizes));\n  const detail=views.nodeDetail(s);\n  check(\'node detail uses Chinese label 节点 1\',detail.includes(\'节点 1\')&&!detail.includes(\'Node 1\'),detail.match(/<h2>.*?<\\/h2>/)?.[0]||\'\');\n  check(\'leader detail counts only valid same-term follower reports and says not ACK\',detail.includes(\'2 个\')&&detail.includes(\'Follower\')&&detail.includes(\'不是 ACK\'),detail);\n  const op={id:\'op-1\',kind:\'generate\',state:\'failed\',error:\'leadership changed; outcome not confirmed\',result:{phase:\'finished\'}};\n  const receipt=views.receipt(op);\n  check(\'receipt explains known backend error in Chinese and keeps raw error in details\',receipt.includes(\'提交结果未确认\')&&receipt.includes(\'leadership changed; outcome not confirmed\')&&receipt.includes(\'<details\'),receipt);\n  const chart=charts.experimentChart([{platform:\'linux\',source_sha256:\'abc\',nodes:3,scenario:\'election\',batch_size:1,requested_commands:10,round:1,result:\'PASS\',elapsed_seconds:1}]);\n  check(\'chart scenario is Chinese while result label is Chinese\',chart.includes(\'首次选举\')&&chart.includes(\'通过\'),chart);\n  return checks;\n}'
with sync_playwright() as pw:
 browser=pw.chromium.launch();page=browser.new_page()
 page.evaluate('async ([views,charts])=>{window.ui={views:await import(views),charts:await import(charts)}}',[views,charts])
 results=page.evaluate(JS)
 browser.close()
(a.output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps([{'name':r['name'],'passed':r['passed']} for r in results],ensure_ascii=False,indent=2))
assert all(r['passed'] for r in results)
