#!/usr/bin/env python3
"""Synthetic browser regressions for stage, task, and navigation interactions."""

from __future__ import annotations

import json
import sys
import unittest

import dashboard_ui_test as base


class InteractionRegressionTests(base.DashboardBrowserTests):
    """Browser-only checks; all API endpoints are intercepted with synthetic data."""

    def open_app(self, *, width: int = 1440, height: int = 900, control_enabled: bool = True):
        context, page = self.new_page(width=width, height=height)

        def mock_unmatched_api(route):
            request = route.request
            if request.method == "POST":
                route.fulfill(status=200, content_type="application/json", body='{"id":"SYNTHETIC-POST"}')
            elif request.method in {"GET", "HEAD"}:
                route.fulfill(status=200, content_type="application/json", body='{}')
            else:
                route.fulfill(status=204, body="")

        # This lower-priority fallback closes every API path; the exact bootstrap
        # mock installed below handles /api/session first.
        page.route("**/api/**", mock_unmatched_api)
        self.intercept_synthetic_api(page, control_enabled=control_enabled)
        page.goto(base.BASE_URL, wait_until="domcontentloaded", timeout=15000)
        self.wait_for_synthetic_stream(page)
        return context, page

    def emit_stage(self, page, count: int, *, leader_id: int = 1, operations=None):
        frame = base.stage_fixture(count, leader_id=leader_id)
        frame["snapshot"]["seq"] = 2
        if operations is not None:
            frame["operations"] = operations
        page.evaluate("frame => window.__emitSyntheticFrame(frame)", frame)
        page.wait_for_function(
            "count => document.querySelectorAll('#stage-host .stage-node').length === count", arg=count
        )

    def save_shot(self, page, name: str):
        page.screenshot(path=str(base.OUTPUT / f"{name}.png"), full_page=True)

    def test_task_tray_and_zoom_return_center_remain_clickable(self):
        context, page = self.open_app()
        try:
            self.emit_stage(page, 100, operations=[{"id": "synthetic-task", "kind": "generate", "state": "running"}])
            tray = page.locator("#task-tray")
            self.assertTrue(tray.is_visible(), "the active task summary should remain visible")
            page.get_by_role("button", name="放大").click()
            orientation=page.get_by_role("button",name="返回全景")
            self.assertTrue(orientation.evaluate("n=>{const r=n.getBoundingClientRect();return n.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}"))
            orientation.click()
            center = page.locator(".stage-node.center-slot").first
            hit = center.evaluate("n => {const r=n.getBoundingClientRect(),e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!e&&e.closest('.stage-node')===n}")
            self.assertTrue(hit, "the full-view center node is covered after returning from zoom")
            self.save_shot(page, "task-tray-zoom-center")
        finally:
            context.close()

    def test_zoom_control_edge_and_left_drag_do_not_open_navigation(self):
        context, page = self.open_app(width=390, height=844)
        try:
            self.emit_stage(page, 11)
            zoom = page.get_by_role("button", name="放大")
            box = zoom.bounding_box()
            self.assertIsNotNone(box)
            page.mouse.click(box["x"] + 1, box["y"] + box["height"] / 2)
            sidebar = page.locator("#sidebar")
            self.assertFalse(sidebar.evaluate("e=>e.classList.contains('open')"), "zoom control edge opened navigation")
            host = page.locator("#stage-host").bounding_box()
            page.mouse.move(host["x"] + 5, host["y"] + host["height"] * .55)
            page.mouse.down()
            page.mouse.move(host["x"] + 50, host["y"] + host["height"] * .55, steps=5)
            page.mouse.up()
            self.assertFalse(sidebar.evaluate("e=>e.classList.contains('open')"), "left-edge canvas drag opened navigation")
            self.save_shot(page, "mobile-left-edge-interaction")
        finally:
            context.close()

    def test_details_and_task_tray_do_not_cover_selected_node_at_11_or_100(self):
        context, page = self.open_app()
        try:
            for count, node_id in ((11, 4), (100, 55)):
                self.emit_stage(page, count, operations=[{"id": f"synthetic-{count}", "kind": "generate", "state": "running"}])
                target = page.locator(f'.stage-node[data-node="{node_id}"]')
                if not target.is_visible():
                    page.locator('#search').fill(str(node_id));page.locator('#search').press('Enter')
                else:target.click()
                self.assertTrue(page.locator("#node-detail").is_visible())
                result = page.evaluate("""id => {
                  const n=document.querySelector(`.stage-node[data-node="${id}"]`),d=document.querySelector('#node-detail'),t=document.querySelector('#task-tray');
                  const r=n.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
                  const a=d.getBoundingClientRect(),b=t.getBoundingClientRect();
                  return {hit:!!hit&&hit.closest('.stage-node')===n,overlap:!t.hidden&&a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top};
                }""", node_id)
                self.assertTrue(result["hit"], f"detail panel covers node #{node_id} in {count}-node layout")
                self.assertFalse(result["overlap"], f"detail and task tray overlap in {count}-node layout")
                page.locator("[data-act=close-detail]").click()
            self.save_shot(page, "detail-task-tray-nodes")
        finally:
            context.close()

    def test_canvas_blank_and_escape_clear_selection_after_detail_close(self):
        context, page = self.open_app()
        try:
            self.emit_stage(page, 11)
            page.locator('.stage-node[data-node="4"]').click()
            page.locator("[data-act=close-detail]").click()
            point = page.evaluate("""() => {
              const h=document.querySelector('#stage-host'),r=h.getBoundingClientRect();
              for(let y=r.top+12;y<r.bottom-12;y+=17)for(let x=r.left+12;x<r.right-12;x+=17){
                const e=document.elementFromPoint(x,y);
                if(e&&h.contains(e)&&e.closest('.stage-world')&&!e.closest('.stage-node,.stage-control,.stage-orientation,.stage-topbar,.stage-legend,.lesson-dock'))return{x,y};
              }
              return null;
            }""")
            self.assertIsNotNone(point, "could not find an uncovered canvas point")
            page.mouse.click(point["x"], point["y"])
            self.assertEqual(page.locator(".stage-node.selected").count(), 0, "blank canvas click left a selected node")
            page.locator('.stage-node[data-node="5"]').click()
            page.locator("[data-act=close-detail]").click()
            page.keyboard.press("Escape")
            self.assertEqual(page.locator(".stage-node.selected").count(), 0, "Escape left a selected node")
        finally:
            context.close()

    def test_unreachable_identity_mismatch_is_not_reported_as_identity_error(self):
        context, page = self.open_app()
        try:
            self.emit_stage(page, 3)
            frame = base.stage_fixture(3)
            frame["snapshot"]["seq"] = 3
            frame["snapshot"]["nodes"][1]["reachable"] = False
            frame["snapshot"]["nodes"][1]["identity_ok"] = False
            page.evaluate("frame=>window.__emitSyntheticFrame(frame)", frame)
            node = page.locator('.stage-node[data-node="2"]')
            self.assertFalse(node.evaluate("e=>e.classList.contains('identity-error')"))
            frame["snapshot"]["seq"] = 4
            frame["snapshot"]["nodes"][1]["reachable"] = True
            page.evaluate("frame=>window.__emitSyntheticFrame(frame)", frame)
            self.assertTrue(node.evaluate("e=>e.classList.contains('identity-error')"))
        finally:
            context.close()

    def test_readonly_badge_is_text_not_a_numeric_status(self):
        context, page = self.open_app(control_enabled=False)
        try:
            badge = page.locator(".lesson-index")
            self.assertTrue(badge.is_visible())
            self.assertIn("只读", badge.inner_text())
            self.assertFalse(any(char.isdigit() for char in badge.inner_text()), "read-only badge contains a numeric status")
        finally:
            context.close()

    def test_unknown_leader_and_fresh_candidate_have_distinct_status(self):
        context, page = self.open_app()
        try:
            self.emit_stage(page, 3)
            frame = base.stage_fixture(3)
            frame["snapshot"]["seq"] = 3
            for node in frame["snapshot"]["nodes"]:
                node["status"]["state"] = "Unknown"
                node["status"]["leader_id"] = None
            page.evaluate("frame=>window.__emitSyntheticFrame(frame)", frame)
            status = page.locator(".stage-observation")
            expect_unknown = status.inner_text()
            self.assertIn("尚未观察到 Leader", expect_unknown)
            frame["snapshot"]["seq"] = 4
            frame["snapshot"]["nodes"][0]["status"]["state"] = "Candidate"
            page.evaluate("frame=>window.__emitSyntheticFrame(frame)", frame)
            self.assertIn("竞选中", page.locator('.stage-node[data-node="1"] .stage-role').inner_text())
            self.assertNotEqual(expect_unknown, status.inner_text())
        finally:
            context.close()

    def test_stage_uses_one_or_fewer_tab_stops_and_arrows_move_between_nodes(self):
        context, page = self.open_app()
        try:
            self.emit_stage(page, 11)
            stops = page.locator(".stage-node").evaluate_all("ns=>ns.filter(n=>n.tabIndex>=0).length")
            self.assertLessEqual(stops, 1, "more than one node participates in sequential Tab navigation")
            self.assertGreaterEqual(stops, 1, "no node is keyboard reachable")
            page.locator('.stage-node[data-node="1"]').focus()
            page.keyboard.press("ArrowRight")
            focused = page.evaluate("document.activeElement?.dataset.node")
            self.assertNotEqual(focused, "1", "ArrowRight did not move keyboard focus to another node")
            self.assertTrue(page.locator(".stage-node").evaluate_all("ns=>ns.some(n=>n===document.activeElement)"))
        finally:
            context.close()

    def test_wheel_requires_control_modifier_to_zoom(self):
        context, page = self.open_app()
        try:
            self.emit_stage(page, 11)
            node = page.locator('.stage-node[data-node="1"]')
            before = node.bounding_box()
            host = page.locator("#stage-host").bounding_box()
            page.mouse.move(host["x"] + host["width"] / 2, host["y"] + host["height"] / 2)
            page.mouse.wheel(0, -400)
            page.wait_for_timeout(80)
            after_plain = node.bounding_box()
            self.assertAlmostEqual(before["width"], after_plain["width"], delta=0.5, msg="wheel without Control changed zoom")
            page.keyboard.down("Control")
            page.mouse.wheel(0, -400)
            page.keyboard.up("Control")
            page.wait_for_function("before=>document.querySelector('.stage-node[data-node=\"1\"]').getBoundingClientRect().width>before+1",arg=after_plain['width'])
            after_ctrl = node.bounding_box()
            self.assertGreater(after_ctrl["width"], after_plain["width"] + 1, "Control+wheel did not zoom")
        finally:
            context.close()

    def test_submit_verify_and_search_entries_are_visible_without_navigation(self):
        context, page = self.open_app()
        try:
            submit = page.get_by_role("button", name="提交命令").first
            verify = page.get_by_role("button", name="校验当前").first
            search = page.get_by_role("searchbox", name="搜索节点 ID")
            self.assertTrue(submit.is_visible(), "submit entry is hidden behind navigation")
            self.assertTrue(verify.is_visible(), "verification entry is hidden behind navigation")
            self.assertTrue(search.is_visible(), "node search is hidden behind navigation")
            self.assertFalse(page.locator("#sidebar").evaluate("e=>e.classList.contains('open')"))
            self.save_shot(page, "direct-submit-verify-search")
        finally:
            context.close()

    def test_group_switch_clears_previous_relation_filter(self):
        context,page=self.open_app(width=390,height=667)
        try:
            self.emit_stage(page,100)
            page.locator('.stage-node[data-node="2"]').click()
            page.locator('[data-act=close-detail]').click()
            page.get_by_role('button',name='聚焦选中节点关系').click()
            self.assertEqual(page.locator('.stage-reported-edge:visible').count(),1)
            page.get_by_role('button',name='下一组').click()
            self.assertGreater(page.locator('.stage-reported-edge:visible').count(),1)
            self.assertEqual(page.locator('.stage-node.selected').count(),0)
            self.assertFalse(page.locator('.stage-relation-note').is_visible())
        finally:context.close()

    def test_fault_workspace_inspector_occupies_its_own_region(self):
        context,page=self.open_app()
        try:
            self.emit_stage(page,11)
            self.navigate(page,'faults')
            page.locator('.stage-node[data-node="4"]').click()
            detail=page.locator('#node-detail');self.assertTrue(detail.is_visible())
            self.assertTrue(detail.evaluate("d=>{const a=d.getBoundingClientRect(),b=document.querySelector('#stage-host').getBoundingClientRect();return a.left>=b.right||a.top>=b.bottom||a.bottom<=b.top}"))
            page.screenshot(path=str(base.OUTPUT/'fault-inspector.png'),full_page=True)
        finally:context.close()


def run() -> int:
    base.OUTPUT.mkdir(parents=True, exist_ok=True)
    names = [name for name in InteractionRegressionTests.__dict__ if name.startswith("test_")]
    suite = unittest.TestSuite(InteractionRegressionTests(name) for name in names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "tests_run": result.testsRun,
        "failures": [{"test": str(test), "traceback": detail} for test, detail in result.failures],
        "errors": [{"test": str(test), "traceback": detail} for test, detail in result.errors],
        "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
    }
    (base.OUTPUT / "interaction-ui-results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return not result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(run())
