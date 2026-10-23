"""SVG geometry audit in Chromium. Synthetic data; no protocol claims."""
import argparse,json
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--observe',action='store_true',help='record a baseline without asserting corrected geometry');p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
url='data:text/javascript,'+quote((a.source/'cmd/dashboard/static/topology.js').read_text())
with sync_playwright() as pw:
 browser=pw.chromium.launch();page=browser.new_page()
 result=page.evaluate('''async url=>{
 const {geometry,route}=await import(url),results=[];
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');document.body.append(svg);
 const cross=(a,b,c,d)=>{const rx=b.x-a.x,ry=b.y-a.y,sx=d.x-c.x,sy=d.y-c.y,den=rx*sy-ry*sx;if(Math.abs(den)<1e-7)return false;const t=((c.x-a.x)*sy-(c.y-a.y)*sx)/den,u=((c.x-a.x)*ry-(c.y-a.y)*rx)/den;return t>1e-5&&t<1-1e-5&&u>1e-5&&u<1-1e-5;};
 for(const [w,h]of [[1440,900],[1920,1080],[390,844]])for(const n of [3,11,20,50,100]){
  const ids=Array.from({length:n},(_,i)=>i+1),g=geometry(ids,ids,Math.ceil(n/2),w,h),paths=[],t=performance.now();let nodeCrossings=0;
  for(const id of ids){if(id===g.center)continue;const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',route(g,id,g.center));svg.append(p);const length=p.getTotalLength(),points=[];
   for(let at=0;at<length;at+=4)points.push(p.getPointAtLength(at));points.push(p.getPointAtLength(length));
   for(const [other,c]of g.positions){if(other===id||other===g.center)continue;if(points.some(q=>Math.hypot(q.x-c[0],q.y-c[1])<g.radii.get(other)+1))nodeCrossings++;}
   paths.push({id,points});p.remove();
  }
  let endpointMin=Infinity,crossings=0,overlaps=0;
  for(let i=0;i<paths.length;i++)for(let j=i+1;j<paths.length;j++){
   const a=paths[i].points,b=paths[j].points;endpointMin=Math.min(endpointMin,Math.hypot(a.at(-1).x-b.at(-1).x,a.at(-1).y-b.at(-1).y));let hits=0,shared=0;
   for(let k=1;k<a.length;k++)for(let l=1;l<b.length;l++){
    const a0=a[k-1],a1=a[k],b0=b[l-1],b1=b[l];
    if(Math.max(a0.x,a1.x)<Math.min(b0.x,b1.x)||Math.max(b0.x,b1.x)<Math.min(a0.x,a1.x)||Math.max(a0.y,a1.y)<Math.min(b0.y,b1.y)||Math.max(b0.y,b1.y)<Math.min(a0.y,a1.y))continue;
    if(cross(a0,a1,b0,b1))hits++;
    if(Math.abs(a0.y-a1.y)<.001&&Math.abs(b0.y-b1.y)<.001&&Math.abs(a0.y-b0.y)<.001)shared+=Math.max(0,Math.min(Math.max(a0.x,a1.x),Math.max(b0.x,b1.x))-Math.max(Math.min(a0.x,a1.x),Math.min(b0.x,b1.x)));
   }crossings+=hits;if(shared>1)overlaps++;
  }
  results.push({nodes:n,viewport:[w,h],paths:paths.length,node_crossings:nodeCrossings,edge_crossings:crossings,overlapping_pairs:overlaps,min_endpoint_spacing: endpointMin,measurement_ms:performance.now()-t});
 }
 return {mode:'SYNTHETIC',method:'4px SVG samples; strict interior segment crossings, collinear horizontal overlaps >1px; endpoints in world pixels',results};
}''',url);browser.close()
(a.output/'geometry.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if not a.observe:
    for row in result['results']:
        assert row['node_crossings']==row['edge_crossings']==row['overlapping_pairs']==0,row
        assert row['paths']==row['nodes']-1 and row['min_endpoint_spacing']>=2.5,row

