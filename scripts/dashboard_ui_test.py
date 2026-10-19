#!/usr/bin/env python3
"""Read-only browser checks for the MyRaft console.

The live-console test performs GET requests only and stores screenshots under
--output. Other tests explicitly use synthetic intercepted API fixtures; they
exercise browser rendering and do not represent Raft or protocol evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="base URL of an already-running console")
    parser.add_argument("--output", required=True, type=Path, help="directory for browser screenshots")
    return parser.parse_args()


ARGS = parse_args()
BASE_URL = ARGS.url.rstrip("/")
OUTPUT = ARGS.output.resolve()


def utc_stamp(age_seconds: int = 0) -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z")


def session_fixture(with_session: bool = True) -> dict:
    session = None
    if with_session:
        session = {
            "id": "SYNTHETIC-SESSION",
            "name": "合成浏览器状态",
            "managed": False,
            "config": {
                "cluster_id": "SYNTHETIC-CLUSTER",
                "nodes": [{"id": node_id} for node_id in (1, 2, 3)],
            },
        }
    return {
        "controller_id": "SYNTHETIC-CONTROLLER",
        "mode": "REAL",
        "csrf_token": "SYNTHETIC-ONLY",
        "session": session,
        "sessions": [session] if session else [],
        "generation": 1,
        "control_allowed": False,
        "control_enabled": False,
        "poll_ms": 1000,
    }


def frame_fixture(*, with_session: bool = True, age_seconds: int = 0) -> dict:
    return {
        "controller_id": "SYNTHETIC-CONTROLLER",
        "mode": "REAL",
        "session": session_fixture(with_session)["session"],
        "generation": 1,
        "snapshot": {
            "session_id": "SYNTHETIC-SESSION" if with_session else "",
            "generation": 1,
            "seq": 1,
            "completed_at": utc_stamp(age_seconds),
            "nodes": [],
        },
        "events": [],
        "event_seq": 0,
        "gap": False,
        "stream_dropped": 0,
        "operations": [],
        "control_enabled": False,
        "busy": False,
    }


class DashboardBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        cls.playwright = sync_playwright().start()
        cls.browser: Browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()

    def new_page(self, *, width: int = 1365, height: int = 900) -> tuple[BrowserContext, Page]:
        context = self.browser.new_context(viewport={"width": width, "height": height})
        return context, context.new_page()

    def intercept_synthetic_api(self, page: Page, *, with_session: bool = True, age_seconds: int = 0,
                                connection_error: bool = False) -> None:
        """Install stable synthetic bootstrap and EventSource responses for UI only."""

        def route_session(route: Route) -> None:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(session_fixture(with_session), ensure_ascii=False))

        frame = json.dumps(frame_fixture(with_session=with_session, age_seconds=age_seconds), ensure_ascii=False)
        page.add_init_script(script=f"""(() => {{
          const frame = {json.dumps(frame)};
          const fail = {json.dumps(connection_error)};
          window.EventSource = class SyntheticEventSource {{
            constructor() {{
              this.handlers = new Map();
              this.closed = false;
              queueMicrotask(() => {{
                if (this.closed) return;
                if (fail) {{ this.onerror?.(new Event('error')); return; }}
                for (const handler of this.handlers.get('frame') || []) handler({{data: frame}});
              }});
            }}
            addEventListener(name, handler) {{
              const handlers = this.handlers.get(name) || [];
              handlers.push(handler);
              this.handlers.set(name, handlers);
            }}
            close() {{ this.closed = true; }}
          }};
        }})();""")
        page.route("**/api/session", route_session)

    def test_live_console_read_only_tabs_and_screenshots(self) -> None:
        """Capture the supplied live target; only GET traffic is allowed."""
        context, page = self.new_page()
        methods: list[str] = []
        page.on("request", lambda request: methods.append(request.method))
        try:
            response = page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.assertIsNotNone(response, "live URL returned no document response")
            self.assertLess(response.status, 400, f"live URL returned HTTP {response.status}")
            page.locator("#main").wait_for(state="visible", timeout=8000)
            page.screenshot(path=str(OUTPUT / "live-console-desktop.png"), full_page=True)

            tabs = page.locator("#nav button[data-page]")
            self.assertEqual(tabs.count(), 6, "expected the six public console tabs")
            for index in range(tabs.count()):
                page.locator("#nav button[data-page]").nth(index).click()
                self.assertTrue(page.locator("#main h1").is_visible(), "tab did not render a heading")

            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(OUTPUT / "live-console-mobile.png"), full_page=True)
            self.assertTrue(all(method == "GET" for method in methods),
                            f"live-console browser issued non-GET requests: {methods}")
        finally:
            context.close()

    def test_synthetic_loading_fixture(self) -> None:
        """Capture the shipped initial loading markup with app bootstrap intercepted."""
        context, page = self.new_page()
        try:
            page.route("**/app.js", lambda route: route.abort())
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            loading = page.get_by_role("status").filter(has_text="正在读取本地集群状态")
            loading.wait_for(state="visible", timeout=3000)
            page.screenshot(path=str(OUTPUT / "synthetic-loading-fixture.png"), full_page=True)
        finally:
            context.close()

    def test_synthetic_empty_connection_error_and_stale_fixtures(self) -> None:
        """Check empty, disconnected, and stale labels using intercepted fixtures."""
        for name, options, expected in (
            ("empty", {"with_session": False}, "无活跃会话"),
            ("connection-error", {"connection_error": True}, "连接中断"),
            ("stale", {"with_session": True, "age_seconds": 60}, "样本过期"),
        ):
            with self.subTest(fixture=name):
                context, page = self.new_page()
                try:
                    self.intercept_synthetic_api(page, **options)
                    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
                    page.get_by_text(expected, exact=False).first.wait_for(state="visible", timeout=5000)
                    page.screenshot(path=str(OUTPUT / f"synthetic-{name}-fixture.png"), full_page=True)
                finally:
                    context.close()

    def test_synthetic_100_node_topology_renderer(self) -> None:
        """Feed 100 explicitly synthetic nodes to the public pure topology renderer."""
        context, page = self.new_page()
        try:
            # Keep the pure renderer fixture isolated from app stream updates.
            page.route("**/app.js", lambda route: route.abort())
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            rendered = page.evaluate("""async () => {
              const {topology} = await import('./charts.js');
              const nodes = Array.from({length: 100}, (_, i) => ({
                id: i + 1, reachable: false, status: null,
              }));
              document.querySelector('#main').innerHTML = topology(nodes, 1, 200);
              return {
                count: document.querySelectorAll('.topology-view [data-node]').length,
                listRole: document.querySelector('.node-grid')?.getAttribute('role'),
                label: document.querySelector('.topology-view')?.textContent.includes('逻辑关系，非实测链路'),
              };
            }""")
            self.assertEqual(rendered["count"], 100)
            self.assertEqual(rendered["listRole"], "list")
            self.assertTrue(rendered["label"])
            page.screenshot(path=str(OUTPUT / "synthetic-100-node-renderer-fixture.png"), full_page=True)
        finally:
            context.close()

    def test_mobile_menu_keyboard_focus_theme_and_projection(self) -> None:
        """Exercise mobile navigation and presentation controls without API writes."""
        context, page = self.new_page(width=390, height=844)
        methods: list[str] = []
        page.on("request", lambda request: methods.append(request.method))
        try:
            self.intercept_synthetic_api(page)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            menu = page.locator('[data-act="menu"]')
            menu.focus()
            page.keyboard.press("Enter")
            self.assertEqual(menu.get_attribute("aria-expanded"), "true")
            self.assertEqual(page.locator("#sidebar").get_attribute("inert"), None)
            page.keyboard.press("Escape")
            self.assertEqual(menu.get_attribute("aria-expanded"), "false")
            self.assertIsNotNone(page.locator("#sidebar").get_attribute("inert"))

            page.keyboard.press("Tab")
            focused_outline = page.evaluate("() => getComputedStyle(document.activeElement).outlineStyle")
            self.assertEqual(focused_outline, "solid", "keyboard focus indicator is not visible")

            page.locator('[data-act="theme"]').click()
            self.assertIn(page.locator("html").get_attribute("data-theme"), ("dark", "light"))
            page.locator('[data-act="present"]').click()
            self.assertIn("present", page.locator("body").get_attribute("class"))
            self.assertTrue(all(method == "GET" for method in methods),
                            f"synthetic interaction issued non-GET requests: {methods}")
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
