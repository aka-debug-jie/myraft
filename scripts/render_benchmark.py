"""Synthetic Stage render costs in Chromium, not Raft latency measurements."""
import argparse,json
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
static=a.source/'cmd/dashboard/static';topology='data:text/javascript,'+quote((static/'topology.js').read_text());stage='data:text/javascript,'+quote((static/'stage.js').read_text().replace("'./topology.js'",repr(topology)))
with sync_playwright() as pw:
 browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':900},reduced_motion='reduce')
 page.set_content('<div id="host" style="width:1440px;height:900px"></div>');page.add_style_tag(content=(static/'style.css').read_text())
 result=page.evaluate('''async url=>{
 const {Stage}=await import(url),runs=[];
 for(const count of [3,11,20,50,100])for(let trial=0;trial<3;trial++){
 const s=new Stage(document.querySelector('#host')),members=Array.from({length:count},(_,i)=>i+1);
 const frame=(leader,seq,term=1)=>({members,scope:'bench',fresh:true,snapshotSeq:seq,nodes:members.map(id=>({id,reachable:true,identity_ok:true,status:{state:id===leader?'Leader':'Follower',leader_id:leader,term,instance_id:'n'+id}}))});
 const run=f=>{const t=performance.now();s.update(f);return performance.now()-t};
 const initial=run(frame(1,1)),confirm=run(frame(1,2)),cost=[];
 for(let i=0;i<120;i++)cost.push(run({...frame(1,2),selected:i%count+1}));
 cost.sort((a,b)=>a-b);const change=run(frame(count,3,2)),settled=run(frame(count,4,2));
 runs.push({nodes:count,trial,first_ms:initial,confirmation_ms:confirm,stable_median_ms:cost[60],stable_p95_ms:cost[114],leader_change_first_ms:change,leader_change_confirm_ms:settled,paths:s.edges.size});s.destroy();
 }
 return {mode:'SYNTHETIC',browser:navigator.userAgent,viewport:[1440,900],samples_per_trial:120,runs};
}''',stage);browser.close()
(a.output/'render.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
