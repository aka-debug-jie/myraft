#!/usr/bin/env python3
"""Focused synthetic browser checks for Stage canvas behavior."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]



def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();OUT=args.output
    OUT.mkdir(parents=True, exist_ok=True)
    from urllib.parse import quote
    topology_url="data:text/javascript;charset=utf-8,"+quote((ROOT/"cmd/dashboard/static/topology.js").read_text())
    stage_source=(ROOT/"cmd/dashboard/static/stage.js").read_text().replace("'./topology.js'",repr(topology_url))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True)
        page.set_content('<div id="host" style="position:relative;width:390px;height:473px"></div>')
        page.add_script_tag(url="data:text/javascript;charset=utf-8," + __import__("urllib.parse").parse.quote(stage_source), type="module")
        result = page.evaluate("""async () => {
          const {Stage}=await import(document.querySelector('script[type=module]').src);
          const host=document.querySelector('#host'), stage=new Stage(host);
          const members=Array.from({length:100},(_,i)=>({id:i+1}));
          const nodes=members.map(n=>({id:n.id,reachable:true,identity_ok:true,status:{state:n.id===1?'Leader':'Follower',term:1,leader_id:1,instance_id:'instance-'+n.id}}));
          const frame={members,nodes,fresh:true,scope:'first',selected:50,events:[],snapshotSeq:1};
          stage.update(frame);stage.update({...frame,snapshotSeq:2});
          const bounds=host.getBoundingClientRect();
          const complete=()=>[...host.querySelectorAll('.stage-node')].filter(n=>{const r=n.getBoundingClientRect();return r.left>=bounds.left-1&&r.right<=bounds.right+1&&r.top>=bounds.top-1&&r.bottom<=bounds.bottom+1}).length;
          const initial={scale:stage.scale,visible:complete(),edges:host.querySelectorAll('.stage-reported-edge').length};
          const positions=JSON.stringify([...stage.nodes].map(([id,node])=>[id,node.style.left,node.style.top]));
          stage.scale=.75;stage.tx=-25;stage.ty=-17;stage.applyTransform();
          stage.update({...frame,snapshotSeq:3,nodes:nodes.map(n=>({...n,status:{...n.status,term:2}}))});
          const kept={scale:stage.scale,tx:stage.tx,ty:stage.ty};
          stage.update({...frame,scope:'second'});stage.update({...frame,scope:'second',snapshotSeq:2});
          const scopeFit={scale:stage.scale,visible:complete()};
          host.querySelector('.stage-control[aria-label="聚焦选中节点关系"]').click();
          const allEdges=[...host.querySelectorAll('.stage-reported-edge')].filter(e=>e.style.display!=='none').length;
          stage.showAllRelations=true;stage.update({...frame,scope:'second',snapshotSeq:2});
          const clickCount={value:0};host.addEventListener('click',e=>{if(e.target.closest('.stage-node'))clickCount.value++});
          const first=host.querySelector('.stage-node');
          first.click();const ordinaryClick=clickCount.value;
          for(const n of host.querySelectorAll('.stage-node'))n.setPointerCapture=()=>{};
          first.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:41,clientX:100,clientY:100}));
          first.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:41,clientX:109,clientY:100}));
          first.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:41,clientX:109,clientY:100}));
          first.click();const afterDragClick=clickCount.value;
          stage.scale=stage.minimumScale()+.01;
          const pair=[host.querySelector('.stage-node[data-node="1"]'),host.querySelector('.stage-node[data-node="2"]')];
          pair.forEach((node,i)=>node.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:50+i,clientX:100+i*100,clientY:100})));
          pair[1].dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:51,clientX:101,clientY:100}));
          const pinchMinimum={scale:stage.scale,minimum:stage.minimumScale()};
          pair.forEach((node,i)=>node.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:50+i,clientX:100+i,clientY:100})));
          stage.tx=-10000;stage.ty=-10000;stage.applyTransform();stage.focus(50);
          const focused=host.querySelector('.stage-node[data-node="50"]').getBoundingClientRect();
          host.focus();const beforeArrow=stage.tx;host.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));const arrowMoved=stage.tx<beforeArrow;
          const result={initial,positionsStable:positions===JSON.stringify([...stage.nodes].map(([id,node])=>[id,node.style.left,node.style.top])),kept,scopeFit,allEdges,filteredEdges:host.querySelectorAll('.stage-reported-edge').length,ordinaryClick,afterDragClick,pinchMinimum,focusedVisible:focused.left>=bounds.left-1&&focused.right<=bounds.right+1&&focused.top>=bounds.top-1&&focused.bottom<=bounds.bottom+1,arrowMoved};
          pageForShot();window.__stageTest=stage;return result;
          function pageForShot(){document.body.dataset.stageChecked='true'}
        }""")
        page.screenshot(path=str(OUT / "stage-after-390x844.png"), full_page=True)
        page.evaluate("window.__stageTest.destroy()")
        assert page.locator("#host > *").count()==0, "stage destroy left elements behind"
        (OUT / "stage-ui-test.json").write_text(json.dumps(result, indent=2))
        browser.close()
    failures = []
    if result["initial"]["visible"] != 100: failures.append("initial auto-fit clipped nodes")
    if result["initial"]["edges"] != 99 or result["filteredEdges"] != 99: failures.append("dense edge filter mismatch")
    if result["allEdges"] != 1: failures.append("all-relations toggle mismatch")
    if result["kept"] != {"scale": .75, "tx": -25, "ty": -17}: failures.append("routine update moved viewport")
    if result["scopeFit"]["visible"] != 100: failures.append("scope change did not fit")
    if not result["positionsStable"]: failures.append("routine update changed node layout")
    if result["ordinaryClick"] != 1 or result["afterDragClick"] != 1: failures.append("node click/drag suppression mismatch")
    if result["pinchMinimum"]["scale"] < result["pinchMinimum"]["minimum"]: failures.append("pinch crossed zoom minimum")
    if not result["focusedVisible"]: failures.append("focused node remained outside viewport")
    if not result["arrowMoved"]: failures.append("canvas arrow key did not pan")
    print(json.dumps({"result": result, "failures": failures}, indent=2))
    if failures: raise SystemExit(1)


if __name__ == "__main__":
    main()
