#!/usr/bin/env python3
"""Synthetic geometry and observation-contract tests, not consensus evidence."""
import argparse
import json
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / 'cmd/dashboard/static'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    topology = 'data:text/javascript,' + quote((ROOT/'topology.js').read_text())
    source = (ROOT/'stage.js').read_text().replace("'./topology.js'", repr(topology))
    stage = 'data:text/javascript,' + quote(source)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
        page.set_content('<div id="host" style="width:1440px;height:1000px"></div>')
        result = page.evaluate('''async ({topology,stage}) => {
          const {geometry,route}=await import(topology),{Stage}=await import(stage);
          const failures=[],check=(ok,message)=>{if(!ok)failures.push(message)};
          const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS(svg.namespaceURI,'path');svg.append(path);document.body.append(svg);
          let routes=0;
          function inspect(g,from,to){
            const d=route(g,from,to);check(Boolean(d),`missing route ${from}->${to}`);if(!d)return;
            path.setAttribute('d',d);const length=path.getTotalLength();routes++;
            const sampled=[];for(let at=0;at<=length;at+=6){const p=path.getPointAtLength(at);sampled.push([p.x,p.y]);}
            for(const[id,c]of g.positions){if(id===from||id===to)continue;
              for(const p of sampled){if(Math.hypot(p[0]-c[0],p[1]-c[1])<g.radii.get(id)+1){failures.push(`route ${from}->${to} crosses ${id} n=${g.positions.size}`);break;}}
            }
            for(const[id,at]of [[from,0],[to,length]]){const p=path.getPointAtLength(at),c=g.positions.get(id);check(Math.abs(Math.hypot(p.x-c[0],p.y-c[1])-g.radii.get(id))<.2,`endpoint ${id}`);}
          }
          for(const n of [0,3,11,15,16,20,50,100]){
            const ids=Array.from({length:n},(_,i)=>i*3+7);
            for(const leader of ids){const g=geometry(ids,ids,leader,n>50?2800:1920,n>50?1800:1200);for(const id of ids)if(id!==leader)inspect(g,id,leader);}
          }
          for(const n of [11,20,100]){
            const ids=Array.from({length:n},(_,i)=>i+1),g=geometry(ids,ids,1,n>50?2800:1920,n>50?1800:1200);
            for(const id of ids.slice(0,12))if(id!==n)inspect(g,id,n);
          }
          svg.remove();const host=document.querySelector('#host'),s=new Stage(host),ids=Array.from({length:11},(_,i)=>i+1);
          const frame=(leader,seq,term=1,instance='a')=>({members:ids,scope:'one',fresh:true,snapshotSeq:seq,nodes:ids.map(id=>({id,reachable:true,identity_ok:true,status:{state:id===leader?'Leader':'Follower',term,leader_id:leader,instance_id:instance+id}}))});
          s.update(frame(1,1));check(s.centerId===null,'one snapshot centered leader');check(s.geom.center===1,'initial display did not seed a center');s.update(frame(1,1));check(s.centerId===null,'same seq counted twice');
          s.update(frame(1,2));check(s.centerId===1,'two observations did not center');const initial=new Map(s.positions);
          s.update(frame(7,3,2));check(s.centerId===1,'new leader moved prematurely');s.update(frame(7,4,2));check(s.centerId===7,'new leader not centered');
          check(ids.every(id=>id===1||id===7||JSON.stringify(initial.get(id))===JSON.stringify(s.positions.get(id))),'unrelated node moved');
          check(JSON.stringify(s.geom.slots.get(1))===JSON.stringify(s.positions.get(1)),'old leader did not return to its ID slot');
          s.update(frame(3,5,3,'first'));s.update(frame(3,6,3,'second'));check(s.centerId===7,'different instances counted together');
          s.update(frame(3,7,3,'second'));check(s.centerId===3,'same new instance never centered');
          const multi=frame(4,8,4);multi.nodes[5].status.state='Leader';s.update(multi);s.update({...multi,snapshotSeq:9});check(s.centerId===3,'multiple leaders changed center');
          s.update({...frame(4,10,4),fresh:false});check(s.edges.size===0,'stale edges retained');
          const wrong=frame(4,11,4);wrong.nodes[3].identity_ok=false;s.update(wrong);check(s.edges.size===0,'wrong leader identity drawn');
          const mismatch=frame(4,12,4);mismatch.nodes[0].status.term=3;s.update(mismatch);check(!s.edges.has(1),'cross-term relationship drawn');
          s.update(frame(4,13,4));const cached=s.edges.get(1).getAttribute('d');let mutations=0;
          const observer=new MutationObserver(list=>{mutations+=list.filter(x=>x.attributeName==='d').length});observer.observe(s.svg,{subtree:true,attributes:true});
          const samples=[];for(let i=0;i<200;i++){const t=performance.now();s.update({...frame(4,13,4),selected:i%11+1});samples.push(performance.now()-t);}
          await Promise.resolve();observer.disconnect();check(mutations===0,'ordinary selection/update rerouted paths');check(s.edges.get(1).getAttribute('d')===cached,'cached route changed');
          s.update(frame(9,20,6));const absent=frame(9,21,6);delete absent.nodes[8].status.instance_id;s.update(absent);s.update(frame(9,22,6));check(s.centerId===4,'missing instance did not reset confirmation');s.update(frame(9,23,6));check(s.centerId===9,'recovered instance did not confirm');
          const denseIds=Array.from({length:100},(_,i)=>i+1),dense={scope:'dense',members:denseIds,fresh:true,snapshotSeq:1,nodes:denseIds.map(id=>({id,reachable:true,identity_ok:true,status:{state:id===1?'Leader':'Follower',term:1,leader_id:1,instance_id:'dense-'+id}}))};
          host.style.width='390px';host.style.height='473px';s.update(dense);s.update({...dense,snapshotSeq:2});s.fit();s.focus(1);const rect=s.nodes.get(1).getBoundingClientRect(),bounds=host.getBoundingClientRect();check(Math.abs(rect.x+rect.width/2-bounds.x-195)<1&&Math.abs(rect.y+rect.height/2-bounds.y-236.5)<1,'readable focus not centered');
          s.showAllRelations=false;s.selected=1;s.hovered=2;
          s.update({...dense,snapshotSeq:3,selected:1});check(s.showAllRelations,'leader selection left an empty filter active');
          s.hovered=3;s.update({...frame(2,1),scope:'two'});check(s.hovered===null,'scope retained hovered relation');check(s.centerId===null,'scope retained center');check(s.eventsSeen.size===0,'scope retained events');s.destroy();check(!host.children.length,'destroy leaked DOM');
          samples.sort((a,b)=>a-b);return {routes,failures,stable_update_samples:samples.length,stable_update_p95_ms:samples[Math.floor(samples.length*.95)]};
        }''', {'topology':topology,'stage':stage})
        browser.close()
    (args.output/'topology-contract.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    if result['failures']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
