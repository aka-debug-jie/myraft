#!/usr/bin/env python3
"""Browser acceptance for pixel-budgeted topology groups and reported paths."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import dashboard_ui_test as base


VIEWPORTS = ((1440, 900), (1920, 1080), (1366, 768), (800, 600), (390, 844), (390, 667), (360, 640))
NODE_COUNTS = (3, 11, 20, 50, 100)
REPORT = base.OUTPUT / "group-ui-report.json"


class GroupBrowserAcceptance(base.DashboardBrowserTests):
    """Use only synthetic frames; no browser action reaches a real API endpoint."""

    def open_synthetic(self, width: int, height: int):
        context, page = self.new_page(width=width, height=height)
        api_requests = []

        def mock_api(route):
            request = route.request
            api_requests.append({"method": request.method, "path": request.url.split("?", 1)[0]})
            if request.method == "POST":
                route.fulfill(status=200, content_type="application/json", body='{"id":"SYNTHETIC-POST"}')
            elif request.method in {"GET", "HEAD"}:
                route.fulfill(status=200, content_type="application/json", body="{}")
            else:
                route.fulfill(status=204, body="")

        # The exact /api/session route installed by the shared helper has higher priority.
        page.route("**/api/**", mock_api)
        self.intercept_synthetic_api(page)
        page.goto(base.BASE_URL, wait_until="domcontentloaded", timeout=15000)
        self.wait_for_synthetic_stream(page)
        return context, page, api_requests

    def emit_fixture(self, page, count: int):
        frame = base.stage_fixture(count)
        frame["snapshot"]["seq"] = 2
        # Keep one member in the roster without inventing a reachability relation.
        frame["snapshot"]["nodes"][-1]["reachable"] = False
        frame["snapshot"]["nodes"][-1]["identity_ok"] = False
        page.evaluate("frame => window.__emitSyntheticFrame(frame)", frame)
        page.wait_for_function(
            "count => document.querySelectorAll('#stage-host .stage-node').length === count", arg=count
        )
        page.wait_for_function("() => document.querySelector('.stage-node[data-node=\\\"1\\\"]')?.classList.contains('center-slot')")

    def visible_group_snapshot(self, page):
        return page.evaluate("""() => {
          const host=document.querySelector('#stage-host'),r=host.getBoundingClientRect(),world=document.querySelector('.stage-world');
          const m=new DOMMatrixReadOnly(getComputedStyle(world).transform),scale=Math.hypot(m.a,m.b);
          const nodes=[...host.querySelectorAll('.stage-node')],visible=nodes.filter(n=>!n.hidden);
          const label=document.querySelector('.group-label'),texts=visible.map(n=>({id:Number(n.dataset.node),font:parseFloat(getComputedStyle(n.querySelector('.stage-id')).fontSize)*scale}));
          const nodeChecks=visible.map(n=>{const b=n.getBoundingClientRect(),x=b.left+b.width/2,y=b.top+b.height/2,e=document.elementFromPoint(x,y);return{id:Number(n.dataset.node),hit:!!e&&e.closest('.stage-node')===n,bounds:b.left>=r.left-.5&&b.top>=r.top-.5&&b.right<=r.right+.5&&b.bottom<=r.bottom+.5};});
          return {members:nodes.map(n=>Number(n.dataset.node)).sort((a,b)=>a-b),visible:visible.map(n=>Number(n.dataset.node)).sort((a,b)=>a-b),groupLabel:label.textContent,groupLabelVisible:!!label.getClientRects().length,nodeChecks,texts,scale};
        }""")

    def inspect_visible_paths(self, page, count: int):
        return page.evaluate("""count => {
          const host=document.querySelector('#stage-host'),nodes=[...host.querySelectorAll('.stage-node')],byId=new Map(nodes.map(n=>[Number(n.dataset.node),n]));
          const visible=new Set(nodes.filter(n=>!n.hidden).map(n=>Number(n.dataset.node))),unreachable=count;
          const paths=[...host.querySelectorAll('.stage-reported-edge')],visiblePaths=paths.filter(p=>getComputedStyle(p).display!=='none');
          const issues=[],samples=[];
          const center=n=>{const r=n.getBoundingClientRect();return{x:r.left+r.width/2,y:r.top+r.height/2,radius:Math.min(r.width,r.height)/2}};
          const dist=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
          const pointSegment=(p,a,b)=>{const dx=b.x-a.x,dy=b.y-a.y,l=dx*dx+dy*dy,t=l?Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/l)):0;return Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy)};
          function intersects(a,b,c,d){
            const cross=(p,q,r)=>(q.x-p.x)*(r.y-p.y)-(q.y-p.y)*(r.x-p.x);
            const on=(p,q,r)=>Math.min(p.x,q.x)-.15<=r.x&&r.x<=Math.max(p.x,q.x)+.15&&Math.min(p.y,q.y)-.15<=r.y&&r.y<=Math.max(p.y,q.y)+.15;
            const x1=cross(a,b,c),x2=cross(a,b,d),x3=cross(c,d,a),x4=cross(c,d,b);
            return ((x1>0&&x2<0)||(x1<0&&x2>0))&&((x3>0&&x4<0)||(x3<0&&x4>0)) || Math.abs(x1)<.15&&on(a,b,c)||Math.abs(x2)<.15&&on(a,b,d)||Math.abs(x3)<.15&&on(c,d,a)||Math.abs(x4)<.15&&on(c,d,b);
          }
          const matrix=host.querySelector('svg').getScreenCTM();
          const mapped=(el,s)=>{const p=el.getPointAtLength(s),q=new DOMPoint(p.x,p.y).matrixTransform(matrix);return{x:q.x,y:q.y}};
          const lineData=[];
          for(const path of paths){
            const from=Number(path.dataset.from),to=Number(path.dataset.to),shown=getComputedStyle(path).display!=='none',a=byId.get(from),b=byId.get(to);
            if(from===unreachable)issues.push(`unreachable #${from} has a relation path`);
            if(!a||!b)issues.push(`path ${from}->${to} has a missing member endpoint`);
            if(shown&&(!visible.has(from)||!visible.has(to)))issues.push(`visible path ${from}->${to} has an endpoint outside the visible group`);
            if(!shown&&visible.has(from)&&visible.has(to))issues.push(`path ${from}->${to} is hidden although both endpoints are visible`);
            if(!shown)continue;
            const ca=center(a),cb=center(b),clearance=dist(ca,cb)-ca.radius-cb.radius-1.8;
            if(clearance<6-.05)issues.push(`endpoint clearance ${from}->${to} is ${clearance.toFixed(2)}px, below 6px`);
            const length=path.getTotalLength(),step=4,points=[];
            for(let s=0;s<length;s+=step)points.push(mapped(path,s));points.push(mapped(path,length));
            const line={from,to,points};lineData.push(line);
            for(const n of nodes){
              const id=Number(n.dataset.node);if(id===from||id===to||n.hidden)continue;
              const c=center(n),radius=c.radius+.9;
              for(let i=1;i<points.length;i++)if(pointSegment(c,points[i-1],points[i])<radius-.1){issues.push(`path ${from}->${to} crosses non-endpoint node #${id}`);break;}
            }
            samples.push({from,to,length:Math.round(length*100)/100,endpointClearance:Math.round(clearance*100)/100,samples:points.length});
          }
          for(let i=0;i<lineData.length;i++)for(let j=i+1;j<lineData.length;j++){
            const a=lineData[i],b=lineData[j];
            if(a.to===b.to){const gap=dist(a.points.at(-1),b.points.at(-1))-1.8;if(gap<6-.05)issues.push(`center ports ${a.from}/${b.from} clear gap ${gap.toFixed(3)}px below 6px`);} 
            for(let x=1;x<a.points.length;x++){
              let hit=false;
              for(let y=1;y<b.points.length;y++)if(intersects(a.points[x-1],a.points[x],b.points[y-1],b.points[y])){hit=true;break;}
              if(hit){issues.push(`visible paths ${a.from}->${a.to} and ${b.from}->${b.to} cross`);break;}
            }
          }
          const expected=[...visible].filter(id=>id!==1&&id!==unreachable).length;
          if(visiblePaths.length!==expected)issues.push(`expected ${expected} valid visible relations, found ${visiblePaths.length}`);
          return {visiblePathCount:visiblePaths.length,totalPathElements:paths.length,issues,samples};
        }""", count)

    def screenshot(self, page, name: str):
        page.screenshot(path=str(base.OUTPUT / name), full_page=True)

    def test_group_matrix_and_rendered_geometry(self):
        cases = []
        failures = []

        def check(case, condition, message):
            if not condition:
                case["issues"].append(message)
                failures.append(f'{case["case"]}: {message}')

        for width, height in VIEWPORTS:
            for count in NODE_COUNTS:
                case_name = f"{count}-{width}x{height}"
                case = {"case": case_name, "viewport": {"width": width, "height": height}, "nodes": count,
                        "groups": [], "issues": [], "thumbnails": [], "search": None, "end_key": None,
                        "api_requests": []}
                cases.append(case)
                context, page, api_requests = self.open_synthetic(width, height)
                case["api_requests"] = api_requests
                try:
                    self.emit_fixture(page, count)
                    snapshot = self.visible_group_snapshot(page)
                    check(case, snapshot["members"] == list(range(1, count + 1)), "DOM does not contain the full member roster")
                    check(case, f"共 {count}" in snapshot["groupLabel"], "group label omits the total member count")
                    check(case, "组" in snapshot["groupLabel"], "group label does not identify the readable group")
                    seen = set()
                    visited = set()
                    group_limit = count + 1
                    for group_number in range(group_limit):
                        snapshot = self.visible_group_snapshot(page)
                        check(case, len(snapshot["visible"]) > 0, "a readable group contains no visible nodes")
                        check(case, snapshot["visible"] != [], "group has no visible members")
                        current_group = snapshot["groupLabel"]
                        if current_group in visited:
                            case["issues"].append(f"group traversal repeated {current_group!r}")
                            failures.append(f"{case_name}: group traversal repeated {current_group!r}")
                            break
                        visited.add(current_group)
                        seen.update(snapshot["visible"])
                        check(case, 1 in snapshot["visible"], f"group {current_group!r} does not retain the reachable center Leader")
                        for item in snapshot["nodeChecks"]:
                            check(case, item["hit"], f"node #{item['id']} center is covered in {current_group!r}")
                            check(case, item["bounds"], f"node #{item['id']} lies outside the stage host in {current_group!r}")
                        for item in snapshot["texts"]:
                            check(case, item["font"] >= 11, f"node #{item['id']} effective text is {item['font']:.2f}px in {current_group!r}")
                        geometry = self.inspect_visible_paths(page, count)
                        for issue in geometry["issues"]:
                            check(case, False, f"{current_group!r}: {issue}")
                        case["groups"].append({"label": current_group, "visible_ids": snapshot["visible"],
                                               "font_px": snapshot["texts"], "world_scale": snapshot["scale"],
                                               "paths": geometry["samples"], "path_issues": geometry["issues"]})
                        if group_number == 0:
                            self.screenshot(page, f"group-{case_name}.png")
                        next_group = page.get_by_role("button", name="下一组")
                        if not next_group.is_visible() or next_group.is_disabled():
                            break
                        old_label = current_group
                        next_group.click()
                        try:
                            page.wait_for_function("old => document.querySelector('.group-label')?.textContent !== old", arg=old_label, timeout=5000)
                        except Exception as error:
                            check(case, False, f"next-group did not advance: {error}")
                            break
                    check(case, seen == set(range(1, count + 1)), f"visible group union is {sorted(seen)}, expected 1..{count}")

                    overview = page.get_by_role("button", name="全部节点缩略视图")
                    case["thumbnail_button_visible"] = overview.is_visible()
                    if overview.is_visible():
                        overview.click()
                        thumb = self.visible_group_snapshot(page)
                        check(case, thumb["visible"] == list(range(1, count + 1)), "thumbnail does not show all members")
                        labels = page.locator(".stage-node:not(.center-slot) .stage-id").evaluate_all(
                            "es=>es.map(e=>getComputedStyle(e).display)"
                        )
                        check(case, all(value == "none" for value in labels), "thumbnail leaves small node labels visible")
                        case["thumbnails"].append({"visible_ids": thumb["visible"], "hidden_label_displays": labels})
                        self.screenshot(page, f"thumbnail-{case_name}.png")
                        back = page.get_by_role("button", name="全部节点缩略视图")
                        check(case, back.is_visible() and back.inner_text() == "可读分组", "thumbnail has no readable-group return control")
                        back.click()
                        restored = self.visible_group_snapshot(page)
                        check(case, "组" in restored["groupLabel"] and f"共 {count}" in restored["groupLabel"], "thumbnail did not return to a labeled readable group")
                        check(case, all(item["font"] >= 11 for item in restored["texts"]), "readable-group return kept sub-11px labels")
                    else:
                        case["thumbnails"].append({"skipped": "single readable group; thumbnail control is not exposed"})

                    if count == 100:
                        search = page.get_by_role("searchbox", name="搜索节点 ID")
                        search.fill("#100")
                        search.press("Enter")
                        target = page.locator('.stage-node[data-node="100"]')
                        try:
                            page.wait_for_function("() => {const n=document.querySelector('.stage-node[data-node=\\\"100\\\"]');return n&&!n.hidden}", timeout=5000)
                        except Exception as error:
                            check(case, False, f"search #100 did not reveal node 100: {error}")
                        found = self.visible_group_snapshot(page)
                        check(case, target.is_visible(), "search #100 target is not visible")
                        check(case, 100 in found["visible"], "search #100 did not select a visible group")
                        case["search"] = {"visible": target.is_visible(), "visible_ids": found["visible"]}
                        if target.is_visible():
                            self.screenshot(page, f"search-100-{width}x{height}.png")
                        page.locator("[data-act=close-detail]").click()
                        prev = page.get_by_role("button", name="上一组")
                        for _ in range(count + 1):
                            if not prev.is_visible() or prev.is_disabled():
                                break
                            prev.click()
                        first = page.locator('.stage-node[data-node="1"]')
                        first.focus()
                        page.keyboard.press("End")
                        try:
                            page.wait_for_function("() => {const n=document.querySelector('.stage-node[data-node=\\\"100\\\"]');return n&&!n.hidden}", timeout=5000)
                        except Exception as error:
                            check(case, False, f"End did not reveal node 100: {error}")
                        end_target = page.locator('.stage-node[data-node="100"]')
                        check(case, end_target.is_visible(), "End-key target node 100 is not visible")
                        case["end_key"] = {"visible": end_target.is_visible(), "active_node": page.evaluate("document.activeElement?.dataset.node")}
                        if end_target.is_visible():
                            self.screenshot(page, f"end-100-{width}x{height}.png")
                except Exception as error:
                    message = f"{type(error).__name__}: {error}"
                    case["issues"].append(message)
                    failures.append(f"{case_name}: {message}")
                finally:
                    context.close()

        REPORT.write_text(json.dumps({"url": base.BASE_URL, "viewports": VIEWPORTS, "node_counts": NODE_COUNTS,
                                      "cases": cases, "failures": failures}, ensure_ascii=False, indent=2))
        if failures:
            self.fail(f"{len(failures)} group UI acceptance failures; first: {failures[0]}")


def run() -> int:
    base.OUTPUT.mkdir(parents=True, exist_ok=True)
    suite = unittest.TestSuite([GroupBrowserAcceptance("test_group_matrix_and_rendered_geometry")])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    (base.OUTPUT / "group-ui-runner.json").write_text(json.dumps({
        "tests_run": result.testsRun,
        "failures": [{"test": str(test), "traceback": detail} for test, detail in result.failures],
        "errors": [{"test": str(test), "traceback": detail} for test, detail in result.errors],
    }, ensure_ascii=False, indent=2))
    return not result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(run())
