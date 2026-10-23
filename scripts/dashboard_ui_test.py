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
    parser.add_argument("--synthetic-only", action="store_true", help="skip the live-console GET-only smoke test")
    return parser.parse_args()


ARGS = parse_args()
BASE_URL = ARGS.url.rstrip("/")
OUTPUT = ARGS.output.resolve()
SYNTHETIC_ONLY = ARGS.synthetic_only


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


def stage_fixture(node_count: int, *, leader_id: int = 1, term: int = 1) -> dict:
    """Return clearly synthetic Stage input; it is never Raft evidence."""
    fixture = frame_fixture()
    fixture["session"]["config"]["nodes"] = [{"id": node_id} for node_id in range(1, node_count + 1)]
    fixture["snapshot"]["nodes"] = [{
        "id": node_id,
        "reachable": True,
        "identity_ok": True,
        "status": {
            "state": "Leader" if node_id == leader_id else "Follower",
            "term": term,
            "leader_id": leader_id,
            "instance_id": f"SYNTHETIC-NODE-{node_id}",
            "last_log_index": 1,
            "commit_index": 1,
            "last_applied": 1,
        },
    } for node_id in range(1, node_count + 1)]
    return fixture


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

    def setUp(self) -> None:
        self.browser_diagnostics: list[str] = []

    def tearDown(self) -> None:
        result = self._outcome.result
        if result and any(test is self for test, _ in result.failures + result.errors):
            for item in self.browser_diagnostics:
                print(f"BROWSER DIAGNOSTIC: {item}", file=sys.stderr)

    def new_page(self, *, width: int = 1365, height: int = 900, touch: bool = False) -> tuple[BrowserContext, Page]:
        context = self.browser.new_context(viewport={"width": width, "height": height}, has_touch=touch)
        page = context.new_page()
        page.on("pageerror", lambda error: self.browser_diagnostics.append(f"pageerror: {error}"))
        page.on("console", lambda message: self.browser_diagnostics.append(f"console error: {message.text}")
                 if message.type == "error" else None)
        return context, page

    def navigate(self, page: Page, name: str) -> None:
        """Open hidden navigation when needed, navigate, then expect it closed."""
        sidebar = page.locator("#sidebar")
        if not sidebar.evaluate("element => element.classList.contains('open') || element.classList.contains('pinned')"):
            page.locator("#nav-trigger").click()
            page.wait_for_function("() => document.querySelector('#nav-trigger')?.getAttribute('aria-expanded') === 'true'")
        page.locator(f'#nav button[data-page="{name}"]').click()
        self.assertFalse(sidebar.evaluate("element => element.classList.contains('open')"),
                         "navigation selection did not close the drawer")

    def open_sidebar(self, page: Page) -> None:
        if not page.locator("#sidebar").evaluate(
            "element => element.classList.contains('open') || element.classList.contains('pinned')"
        ):
            page.locator("#nav-trigger").click()
            page.wait_for_function("() => document.querySelector('#nav-trigger')?.getAttribute('aria-expanded') === 'true'")

    def wait_for_synthetic_stream(self, page: Page) -> None:
        page.wait_for_function("() => (window.__syntheticSources || []).length > 0")

    def intercept_synthetic_api(self, page: Page, *, with_session: bool = True, age_seconds: int = 0,
                                connection_error: bool = False, control_enabled: bool = False,
                                hold_logs: bool = False, hold_operations: bool = False,
                                bootstrap_handler=None) -> None:
        """Install stable synthetic bootstrap and EventSource responses for UI only."""

        fixture = frame_fixture(with_session=with_session, age_seconds=age_seconds)
        fixture["control_enabled"] = control_enabled
        frame = json.dumps(fixture, ensure_ascii=False)
        bootstrap = session_fixture(with_session)
        bootstrap["control_allowed"] = control_enabled
        page.add_init_script(script=f"""(() => {{
          const frame = {json.dumps(frame)};
          window.__lastSyntheticFrame = frame;
          window.__emitSyntheticFrame = (next) => {{
            window.__lastSyntheticFrame = next;
            for (const source of window.__syntheticSources || []) {{
              if (!source.closed) for (const handler of source.handlers.get('frame') || []) handler({{data: JSON.stringify(next)}});
            }}
          }};
          window.__emitSyntheticRawFrame = (raw) => {{
            for (const source of window.__syntheticSources || []) {{
              if (!source.closed) for (const handler of source.handlers.get('frame') || []) handler({{data: raw}});
            }}
          }};
          const fail = {json.dumps(connection_error)};
          window.__syntheticLogReadCount = 0;
          if ({json.dumps(hold_logs)}) {{
            const originalFetch = window.fetch.bind(window);
            window.__syntheticLogResolvers = [];
            window.__resolveSyntheticLogs = (status=200) => {{
              const resolvers = window.__syntheticLogResolvers.splice(0);
              for (const resolve of resolvers) {{
                const body = status === 200 ? {{session_id:'SYNTHETIC-SESSION', generation:1, range:{{entries:[]}}}} : {{error:'synthetic log error'}};
                resolve(new Response(JSON.stringify(body), {{status, headers:{{'Content-Type':'application/json'}}}}));
              }}
            }};
          window.fetch = (input, init) => String(input).includes('/api/nodes/') && String(input).includes('/logs?')
            ? (window.__syntheticLogReadCount++, new Promise(resolve => window.__syntheticLogResolvers.push(resolve)))
              : originalFetch(input, init);
          }}
          if ({json.dumps(hold_operations)}) {{
            const originalFetch = window.fetch.bind(window);
            window.__syntheticOperationPosts = [];
            window.__syntheticOperationResolvers = [];
            window.__resolveSyntheticOperation = (result='success') => {{
              const resolve = window.__syntheticOperationResolvers.shift();
              if (!resolve) throw new Error('no synthetic operation is pending');
              if (result === 'network-error') resolve.reject(new TypeError('synthetic network failure'));
              else resolve.resolve(new Response(JSON.stringify({{id:'SYNTHETIC-OP',state:'accepted'}}), {{status:200,headers:{{'Content-Type':'application/json'}}}}));
            }};
            window.fetch = (input, init) => String(input).includes('/api/operations') && init?.method === 'POST'
              ? (window.__syntheticOperationPosts.push(JSON.parse(init.body)), new Promise((resolve,reject) => window.__syntheticOperationResolvers.push({{resolve,reject}})))
              : originalFetch(input, init);
          }}
          window.EventSource = class SyntheticEventSource {{
            constructor() {{
              this.handlers = new Map();
              this.closed = false;
              (window.__syntheticSources ||= []).push(this);
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
        if bootstrap_handler is None:
            page.route("**/api/session", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(bootstrap, ensure_ascii=False)))
        else:
            page.route("**/api/session", bootstrap_handler)

    def test_create_submit_is_immediately_busy_and_ignores_double_click(self) -> None:
        """A delayed synthetic operations response must not allow a second create POST."""
        context, page = self.new_page()
        try:
            self.intercept_synthetic_api(page, control_enabled=True, hold_operations=True)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            self.navigate(page, "settings")
            button = page.locator("#create-form button")
            page.evaluate("() => { const b=document.querySelector('#create-form button'); b.click(); b.click(); }")
            page.wait_for_function("() => (window.__syntheticOperationPosts || []).length === 1")
            self.assertTrue(button.is_disabled(), "create remained enabled while its POST was pending")
            self.assertEqual(page.evaluate("() => window.__syntheticOperationPosts.length"), 1,
                             "double-click submitted more than one create POST")
            page.evaluate("() => window.__resolveSyntheticOperation()")
        finally:
            context.close()

    def test_settings_draft_stays_but_create_disables_after_control_revoked(self) -> None:
        """A control-disabled synthetic frame must disable create after blur and retain the draft."""
        context, page = self.new_page()
        try:
            self.intercept_synthetic_api(page, control_enabled=True)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            self.navigate(page, "settings")
            name = page.locator('#create-form [name="name"]')
            name.fill("draft-after-revocation")
            revoked = frame_fixture()
            revoked["control_enabled"] = False
            revoked["snapshot"]["seq"] = 2
            page.evaluate("frame => window.__emitSyntheticFrame(frame)", revoked)
            page.evaluate("() => document.activeElement.blur()")
            button = page.locator("#create-form button")
            self.assertTrue(button.is_disabled(), "create stayed enabled after control was revoked")
            self.assertEqual(name.input_value(), "draft-after-revocation", "revocation discarded the form draft")
        finally:
            context.close()

    def test_generate_confirmation_rejects_changed_generation(self) -> None:
        """A confirmation captured for an old generation must not send a write POST."""
        context, page = self.new_page()
        try:
            self.intercept_synthetic_api(page, control_enabled=True, hold_operations=True)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            page.evaluate("() => document.querySelector('#nav-actions [data-act=generate]').click()")
            page.locator("#action-dialog").wait_for(state="visible")
            changed = frame_fixture()
            changed["generation"] = 2
            changed["control_enabled"] = True
            changed["snapshot"]["generation"] = 2
            changed["snapshot"]["seq"] = 2
            page.evaluate("frame => window.__emitSyntheticFrame(frame)", changed)
            page.locator("#action-dialog").wait_for(state="hidden")
            page.get_by_role("status").filter(has_text="会话已变化").wait_for(state="visible", timeout=3000)
            self.assertEqual(page.evaluate("() => window.__syntheticOperationPosts.length"), 0,
                             "stale confirmation issued an operations POST")
        finally:
            context.close()

    def test_older_bootstrap_response_cannot_replace_current_scope_or_control(self) -> None:
        """Out-of-order synthetic bootstrap reads must preserve the newest session and permission."""
        context, page = self.new_page()
        held_bootstraps: list[Route] = []
        bootstrap_count = 0
        initial = session_fixture()
        current = session_fixture()
        current["control_allowed"] = False
        current["sessions"] = [{**current["session"], "id": "CURRENT-BOOTSTRAP", "name": "当前引导会话"}]
        stale = session_fixture()
        stale["control_allowed"] = True
        stale["sessions"] = [{**stale["session"], "id": "STALE-BOOTSTRAP", "name": "过期引导会话"}]

        def bootstrap(route: Route) -> None:
            nonlocal bootstrap_count
            bootstrap_count += 1
            if bootstrap_count == 1:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(initial))
            else:
                held_bootstraps.append(route)

        try:
            self.intercept_synthetic_api(page, bootstrap_handler=bootstrap)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            generation_two = frame_fixture()
            generation_two["generation"] = 2
            generation_two["snapshot"]["generation"] = 2
            generation_two["snapshot"]["seq"] = 2
            with page.expect_request("**/api/session"):
                page.evaluate("frame => window.__emitSyntheticFrame(frame)", generation_two)
            self.assertEqual(len(held_bootstraps), 2, "expected two deferred bootstrap reads")
            held_bootstraps[1].fulfill(status=200, content_type="application/json", body=json.dumps(current))
            held_bootstraps[0].fulfill(status=200, content_type="application/json", body=json.dumps(stale))
            self.navigate(page, "settings")
            page.locator('[data-session="CURRENT-BOOTSTRAP"]').wait_for(state="visible")
            self.assertEqual(page.locator('[data-session="STALE-BOOTSTRAP"]').count(), 0,
                             "older bootstrap replaced the current session list")
            self.assertTrue(page.locator('[data-act="enable-control"]').is_disabled(),
                            "older bootstrap restored control permission")
        finally:
            context.close()

    def test_cancel_stop_confirmation_sends_no_post(self) -> None:
        """Canceling a synthetic stop confirmation must issue zero POST requests."""
        context, page = self.new_page()
        posts: list[str] = []
        try:
            self.intercept_synthetic_api(page, control_enabled=True)
            page.on("request", lambda request: posts.append(request.method)
                    if request.url.endswith("/api/operations") else None)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            frame = frame_fixture()
            frame["control_enabled"] = True
            frame["snapshot"]["nodes"] = [{"id": 1, "reachable": True, "owned": True,
                "status": {"state": "Leader", "term": 1, "leader_id": 1}}]
            page.evaluate("frame => window.__emitSyntheticFrame(frame)", frame)
            page.locator('#stage-host .stage-node[data-node="1"]').click()
            page.evaluate("() => document.querySelector('#node-detail [data-act=stop]').click()")
            page.locator("#action-dialog").wait_for(state="visible")
            page.locator('#dialog-form button[value="cancel"]').click()
            page.wait_for_function("() => !document.querySelector('#action-dialog')")
            self.assertEqual(posts, [], "canceling stop confirmation sent an operations POST")
        finally:
            context.close()

    def test_unknown_post_is_not_automatically_retried(self) -> None:
        """A synthetic network error after POST must not trigger an automatic retry."""
        context, page = self.new_page()
        try:
            self.intercept_synthetic_api(page, control_enabled=True, hold_operations=True)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            page.evaluate("() => document.querySelector('#nav-actions [data-act=generate]').click()")
            page.evaluate("() => document.querySelector('#dialog-form #confirm').click()")
            page.wait_for_function("() => (window.__syntheticOperationPosts || []).length === 1")
            page.evaluate("() => window.__resolveSyntheticOperation('network-error')")
            page.locator("#action-dialog .field-error").filter(has_text="synthetic network failure").wait_for(state="visible")
            self.assertTrue(page.locator("#confirm").is_disabled(), "unknown outcome left the same confirmation ready to resend")
            self.assertEqual(page.evaluate("() => window.__syntheticOperationPosts.length"), 1,
                             "unknown POST result was automatically retried")
        finally:
            context.close()

    def test_old_controller_post_reply_is_not_shown_in_new_controller(self) -> None:
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page,control_enabled=True,hold_operations=True)
            page.goto(BASE_URL);self.wait_for_synthetic_stream(page);self.navigate(page,"settings")
            page.locator('#create-form button').click()
            page.wait_for_function('window.__syntheticOperationPosts.length===1')
            current=session_fixture();current['controller_id']='NEW-CONTROLLER';current['control_allowed']=True
            page.route('**/api/session',lambda r:r.fulfill(status=200,content_type='application/json',body=json.dumps(current)))
            new=frame_fixture();new['controller_id']='NEW-CONTROLLER';new['control_enabled']=True
            page.evaluate('f=>window.__emitSyntheticFrame(f)',new)
            page.evaluate('window.__resolveSyntheticOperation()')
            page.wait_for_function("() => document.querySelector('#create-form button').disabled===false")
            self.assertNotIn('SYNTHETIC-OP',page.locator('#task-body').inner_text())
        finally:context.close()

    def test_bootstrap_retries_after_controller_changes(self) -> None:
        context,page=self.new_page();failures=[]
        try:
            self.intercept_synthetic_api(page,control_enabled=True)
            page.goto(BASE_URL);self.wait_for_synthetic_stream(page);self.navigate(page,'settings')
            current=session_fixture();current['controller_id']='RECOVERED-CONTROLLER';current['control_allowed']=True
            def recover(route):
                if not failures:
                    failures.append('first bootstrap failed');route.fulfill(status=503,body='temporary bootstrap failure')
                else:route.fulfill(status=200,content_type='application/json',body=json.dumps(current))
            page.route('**/api/session',recover)
            new=frame_fixture();new['controller_id']='RECOVERED-CONTROLLER';new['control_enabled']=True
            page.evaluate('f=>window.__emitSyntheticFrame(f)',new)
            page.wait_for_function("() => document.querySelector('#create-form button').disabled===false",timeout=10000)
            self.assertEqual(failures,['first bootstrap failed'])
        finally:context.close()

    def test_workflow_requires_identity_and_fresh_verification(self) -> None:
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page);page.goto(BASE_URL);self.wait_for_synthetic_stream(page)
            f=stage_fixture(3)
            f['snapshot']['nodes'][1]['identity_ok']=False
            f['current_verification']={'state':'stale'};f['history_verification']={'state':'stale'}
            f['checkpoint']={'index':1,'hash':'synthetic','x':0}
            page.evaluate('f=>window.__emitSyntheticFrame(f)',f)
            page.locator('.demo-trigger').click()
            states=page.locator('.workflow-step').evaluate_all("es=>es.map(e=>e.classList.contains('complete'))")
            self.assertFalse(states[0],'wrong identity marked cluster ready')
            self.assertFalse(states[2],'stale verification marked current check complete')
            self.assertFalse(states[5],'stale history marked history check complete')
        finally:context.close()

    def test_old_checkpoint_does_not_skip_new_write_verification(self) -> None:
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page,control_enabled=True)
            page.goto(BASE_URL);self.wait_for_synthetic_stream(page)
            f=stage_fixture(3);f['control_enabled']=True
            f['checkpoint']={'index':50,'hash':'SYNTHETIC','x':0}
            f['operations']=[{'id':'new-write','kind':'generate','state':'succeeded','committed':True,'result':{'last_index':100}}]
            f['current_verification']={'state':'stale'}
            for n in f['snapshot']['nodes']:n['status']['last_applied']=50
            page.evaluate('f=>window.__emitSyntheticFrame(f)',f)
            self.assertIn('应用与完整校验',page.locator('#lesson-dock').inner_text())
            self.assertEqual(page.locator('#lesson-dock [data-page=faults]').count(),0)
            page.locator('.stage-node[data-node="2"]').click()
            page.locator('[data-act=close-detail]').click()
            self.assertTrue(page.locator('.stage-node[data-node="2"]').evaluate("n=>n.classList.contains('selected')"))
        finally:context.close()

    def test_stage_controls_do_not_cover_nodes_and_readonly_is_explicit(self) -> None:
        context,page=self.new_page(width=1100,height=650)
        try:
            self.intercept_synthetic_api(page)
            page.goto(BASE_URL);self.wait_for_synthetic_stream(page)
            f=stage_fixture(11)
            page.evaluate('f=>window.__emitSyntheticFrame(f)',f)
            f['snapshot']['seq']=2;page.evaluate('f=>window.__emitSyntheticFrame(f)',f)
            page.wait_for_function("() => document.querySelector('.center-slot') !== null")
            self.assertIn('当前入口仅供查看',page.locator('#lesson-dock').inner_text())
            covers=page.locator('.stage-node').evaluate_all("nodes=>nodes.filter(n=>{const r=n.getBoundingClientRect();return !n.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}).map(n=>n.dataset.node)")
            self.assertEqual(covers,[])
            heights=page.locator('.stage-control:visible').evaluate_all('ns=>ns.map(n=>n.getBoundingClientRect().height)')
            self.assertTrue(all(h<=48 for h in heights))
            page.locator('.stage-node[data-node="2"]').click()
            self.assertIn('当前入口仅供查看',page.locator('#node-detail').inner_text())
            self.assertNotIn('可在会话设置启用控制',page.locator('#node-detail').inner_text())
        finally:context.close()

    def test_readonly_transport_disables_posts_but_allows_log_reads(self) -> None:
        context,page=self.new_page()
        try:
            def readonly(route):
                route.fulfill(status=200,content_type='application/json',headers={'X-MyRaft-Read-Only':'1'},body=json.dumps(session_fixture()|{'control_allowed':True,'control_enabled':True}))
            self.intercept_synthetic_api(page,control_enabled=True,bootstrap_handler=readonly)
            page.goto(BASE_URL);self.wait_for_synthetic_stream(page)
            f=stage_fixture(3);f['control_enabled']=True;page.evaluate('f=>window.__emitSyntheticFrame(f)',f)
            self.assertEqual(page.locator('#mode').inner_text(),'只读')
            self.assertIn('当前入口仅供查看',page.locator('#lesson-dock').inner_text())
            self.open_sidebar(page)
            self.assertTrue(page.locator('#nav-actions [data-act=verify]').is_disabled())
            self.assertIn('只允许查看',page.locator('#nav-actions [data-act=verify]').get_attribute('title'))
            self.navigate(page,'logs')
            self.assertTrue(page.locator('#logs-form button').is_enabled())
        finally:context.close()

    def test_live_update_preserves_input_focus_and_browser_navigation(self) -> None:
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page,control_enabled=True)
            page.goto(BASE_URL);self.wait_for_synthetic_stream(page);self.navigate(page,'settings')
            name=page.locator('#create-form [name=name]');name.fill('focused-classroom-draft')
            page.evaluate("window.__draftInput=document.activeElement;window.__draftInput.setSelectionRange(2,8)")
            page.evaluate("window.__emitSyntheticFrame({...window.__lastSyntheticFrame,snapshot:{...window.__lastSyntheticFrame.snapshot,seq:9}})")
            self.assertEqual(page.evaluate("({same:document.activeElement===window.__draftInput,start:document.activeElement.selectionStart,end:document.activeElement.selectionEnd})"),{'same':True,'start':2,'end':8})
            self.navigate(page,'logs');page.go_back()
            page.wait_for_function("document.body.dataset.page==='settings'")
            self.assertEqual(name.input_value(),'focused-classroom-draft')
            page.reload();self.wait_for_synthetic_stream(page)
            self.assertEqual(page.locator('body').get_attribute('data-page'),'settings')
        finally:context.close()

    def test_raw_receipt_is_rendered_only_on_explicit_expansion(self) -> None:
        context,page=self.new_page()
        try:
            self.intercept_synthetic_api(page);page.goto(BASE_URL);self.wait_for_synthetic_stream(page)
            frame=frame_fixture();frame['operations']=[{'id':'RAW-RECEIPT','kind':'experiment','state':'succeeded','result':{'marker':'EVIDENCE-ONLY-ON-DEMAND'}}]
            page.evaluate('f=>window.__emitSyntheticFrame(f)',frame)
            self.assertNotIn('EVIDENCE-ONLY-ON-DEMAND',page.locator('#task-body').text_content())
            page.locator('#task-summary').click();page.locator('#task-body details summary').click()
            page.locator('#task-body pre').filter(has_text='EVIDENCE-ONLY-ON-DEMAND').wait_for(state='visible')
        finally:context.close()

    def test_live_console_read_only_tabs_and_screenshots(self) -> None:
        """Capture the supplied live target; only GET traffic is allowed."""
        if SYNTHETIC_ONLY:
            self.skipTest("--synthetic-only: no live console target was supplied")
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
            page.wait_for_function("() => document.querySelectorAll('#nav button[data-page]').length === 6")
            self.assertEqual(tabs.count(), 6, "expected the six public console tabs")
            for name in ("overview", "logs", "faults", "experiments", "evidence", "settings"):
                self.navigate(page, name)
                self.assertEqual(page.locator("#main h1").count(), 1, "tab did not render a heading")
                if name == "overview":
                    self.assertLessEqual(page.locator("#main h1").bounding_box()["width"], 1, "overview heading should remain screen-reader only")

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
                    if name in ("connection-error", "stale"):
                        page.locator("#stage-alert").wait_for(state="visible", timeout=3000)
                    if name == "empty":
                        page.locator('#stage-alert button[data-page="settings"]').wait_for(state="visible")
                    page.screenshot(path=str(OUTPUT / f"synthetic-{name}-fixture.png"), full_page=True)
                finally:
                    context.close()

    def test_synthetic_stage_layout_counts_and_leader_stability(self) -> None:
        """Exercise the Stage DOM renderer with synthetic 11, 50, and 100 node fixtures."""
        context, page = self.new_page()
        try:
            self.intercept_synthetic_api(page)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            for count in (11, 50, 100):
                frame = stage_fixture(count)
                page.evaluate("frame => window.__emitSyntheticFrame(frame)", frame)
                nodes = page.locator("#stage-host .stage-node")
                page.wait_for_function(
                    "count => document.querySelectorAll('#stage-host .stage-node').length === count", arg=count
                )
                self.assertEqual(nodes.count(), count, f"synthetic Stage rendered the wrong number of nodes ({count})")
                self.assertTrue(page.locator("#stage-host .stage-node.leader").count() == 1)
                self.assertEqual(page.locator("#stage-host .stage-node.follower").count(), count - 1)
                if count == 11:
                    self.assertEqual(page.locator("#stage-host .stage-node.selected").count(), 0,
                                     "overview selected a node before user interaction")
                    nodes.nth(0).click()
                    page.locator("#node-detail .detail-close").wait_for(state="visible")
                    self.assertEqual(page.locator("#stage-host .stage-node.selected").count(), 1)
                    page.locator("#node-detail .detail-close").click()
                    page.locator("#node-detail").wait_for(state="hidden")
                if count == 50:
                    page.screenshot(path=str(OUTPUT / "synthetic-50-node-stage-fixture.png"), full_page=True)
                if count == 100:
                    boxes = [node.bounding_box() for node in nodes.all()]
                    self.assertTrue(all(box is not None for box in boxes), "synthetic 100-node Stage has hidden nodes")
                    for index, left in enumerate(boxes):
                        for right in boxes[index + 1:]:
                            self.assertTrue(left["x"] + left["width"] <= right["x"] or
                                            right["x"] + right["width"] <= left["x"] or
                                            left["y"] + left["height"] <= right["y"] or
                                            right["y"] + right["height"] <= left["y"],
                                            "synthetic 100-node Stage contains overlapping buttons")
                    page.screenshot(path=str(OUTPUT / "synthetic-100-node-stage-fixture.png"), full_page=True)
                if count == 11:
                    before = nodes.nth(0).bounding_box()
                    switched = stage_fixture(11, leader_id=2, term=2)
                    page.evaluate("frame => window.__emitSyntheticFrame(frame)", switched)
                    page.wait_for_function("() => document.querySelector('#stage-host .stage-node[data-node=\"2\"]')?.classList.contains('leader')")
                    after = page.locator('#stage-host .stage-node[data-node="1"]').bounding_box()
                    self.assertAlmostEqual(before["x"], after["x"], delta=0.5)
                    self.assertAlmostEqual(before["y"], after["y"], delta=0.5)
                    page.screenshot(path=str(OUTPUT / "synthetic-11-node-leader-switch-fixture.png"), full_page=True)
        finally:
            context.close()

    def test_stage_event_budget_fit_and_update_cost(self) -> None:
        """Synthetic rendering cost only; no claim about protocol or network timing."""
        context, page = self.new_page()
        try:
            page.route("**/app.js", lambda route: route.abort())
            page.goto(BASE_URL, wait_until="domcontentloaded")
            result = page.evaluate("""async () => {
              const {Stage}=await import('./stage.js');
              document.querySelector('#main').innerHTML='<div id="fit-test" style="width:360px;height:473px"></div>';
              const host=document.querySelector('#fit-test'), stage=new Stage(host);
              const members=Array.from({length:100},(_,i)=>({id:i+1}));
              const nodes=members.map(n=>({...n,reachable:true,identity_ok:true,status:{state:n.id===1?'Leader':'Follower',term:1,leader_id:1}}));
              const frame={members,nodes,fresh:true,scope:'synthetic',events:[]};
              stage.update(frame);stage.fit();
              const h=host.getBoundingClientRect();
              const fits=[...host.querySelectorAll('.stage-node')].every(n=>{const b=n.getBoundingClientRect();return b.left>=h.left-1&&b.right<=h.right+1&&b.top>=h.top-1&&b.bottom<=h.bottom+1});
              const event=seq=>({seq,source:'node',node_id:1,name:'log_committed',node_event:{seq}});
              stage.update({...frame,events:[event(1)]});const initial=stage.activeAnimations.size;
              stage.update({...frame,events:[event(1)]});const duplicate=stage.activeAnimations.size;
              const finished=[...stage.activeAnimations].map(a=>a.finished);
              document.dispatchEvent(new Event('visibilitychange'));
              await Promise.allSettled(finished);await Promise.resolve();
              stage.update({...frame,events:[event(1),event(2)]});const replay=stage.activeAnimations.size;
              const durations=[];
              for(let i=0;i<25;i++){const start=performance.now();stage.update(frame);durations.push(performance.now()-start)}
              stage.destroy();
              return {fits,initial,duplicate,replay,durations,remaining:host.children.length};
            }""")
            self.assertTrue(result["fits"], "fit clipped the 100-node mobile viewport")
            self.assertEqual(result["initial"], 1)
            self.assertEqual(result["duplicate"], 1)
            self.assertEqual(result["replay"], 0, "visibility recovery replayed old events")
            self.assertEqual(result["remaining"], 0)
            durations = sorted(result["durations"][5:])
            self.assertLess(durations[18], 50, "100-node update repeatedly exceeded 50ms")
            (OUTPUT / "synthetic-render-cost.json").write_text(json.dumps(result, indent=2))
        finally:
            context.close()

    def test_mobile_menu_keyboard_focus_theme_and_projection(self) -> None:
        """Exercise mobile navigation and presentation controls without API writes."""
        context, page = self.new_page(width=390, height=844, touch=True)
        methods: list[str] = []
        page.on("request", lambda request: methods.append(request.method))
        try:
            self.intercept_synthetic_api(page)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            menu = page.locator("#nav-trigger")
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

            menu.focus()
            page.keyboard.press("Enter")
            page.locator('#nav button[data-page="logs"]').focus()
            page.keyboard.press("Enter")
            self.assertFalse(page.locator("#sidebar").evaluate("element => element.classList.contains('open')"),
                             "keyboard navigation did not close the drawer")
            self.navigate(page, "overview")

            self.open_sidebar(page)
            page.locator("#nav-pin").click()
            self.assertEqual(page.locator("#nav-pin").get_attribute("aria-pressed"), "true")
            self.assertTrue(page.locator("#sidebar").evaluate("element => element.classList.contains('pinned')"))
            self.assertIsNone(page.locator("#sidebar").get_attribute("inert"),
                              "a pinned drawer must remain interactive")
            page.keyboard.press("Escape")
            self.assertFalse(page.locator("#sidebar").evaluate("element => element.classList.contains('open')"))
            self.assertFalse(page.locator("#sidebar").evaluate("element => element.classList.contains('pinned')"))
            self.assertEqual(page.locator("#nav-pin").get_attribute("aria-pressed"), "false")
            page.touchscreen.tap(20, 20)
            self.assertTrue(page.locator("#sidebar").evaluate("element => element.classList.contains('open')"),
                            "touch tap did not open navigation")
            initial_theme = page.locator('html').get_attribute('data-theme')
            page.locator('[data-act="theme"]').click()
            self.assertNotEqual(page.locator('html').get_attribute('data-theme'), initial_theme)
            self.assertIn(page.locator("html").get_attribute("data-theme"), ("dark", "light"))
            self.open_sidebar(page)
            page.locator('[data-act="present"]').click()
            self.assertIn("present", page.locator("body").get_attribute("class"))
            page.keyboard.press("Escape")
            self.open_sidebar(page)
            page.locator('[data-act="present"]').click()
            self.assertNotIn("present", page.locator("body").get_attribute("class") or "")
            page.emulate_media(reduced_motion="reduce")
            duration = page.locator("#stage-host .stage-node").first.evaluate("e => getComputedStyle(e).transitionDuration")
            self.assertIn(duration, ("0s", "0s, 0s"), "reduced-motion preference did not remove node transitions")
            self.assertTrue(all(method == "GET" for method in methods),
                            f"synthetic interaction issued non-GET requests: {methods}")
        finally:
            context.close()

    def test_log_request_in_flight_then_session_generation_switch(self) -> None:
        """A stale synthetic LogRange response must not leave the read button disabled."""
        context, page = self.new_page()
        try:
            self.intercept_synthetic_api(page, hold_logs=True)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            self.navigate(page, "logs")
            self.assertEqual(page.evaluate("() => window.__syntheticLogReadCount"), 0,
                             "opening logs issued an automatic history read")
            page.get_by_role("button", name="读取实际日志").click()
            self.assertEqual(page.locator("#logs-form button").inner_text(), "读取中…")
            page.wait_for_function("() => window.__syntheticLogResolvers.length === 2")
            switched = frame_fixture()
            switched["session"]["id"] = "SYNTHETIC-SESSION-2"
            switched["session"]["name"] = "切换后的合成会话"
            switched["generation"] = 2
            switched["snapshot"]["session_id"] = "SYNTHETIC-SESSION-2"
            switched["snapshot"]["generation"] = 2
            page.evaluate("frame => window.__emitSyntheticFrame(frame)", switched)
            self.assertTrue(page.locator("#logs-form button").is_enabled())
            self.assertEqual(page.locator("#main [role=alert]").count(), 0)
            page.evaluate("() => window.__resolveSyntheticLogs()")
            page.wait_for_timeout(50)
            self.assertTrue(page.locator("#logs-form button").is_enabled())
            self.assertEqual(page.locator("#main [role=alert]").count(), 0)

            page.get_by_role("button", name="读取实际日志").click()
            page.wait_for_function("() => window.__syntheticLogResolvers.length === 2")
            page.evaluate("() => window.__resolveSyntheticLogs(503)")
            page.get_by_role("alert").filter(has_text="synthetic log error").wait_for(state="visible")
            switched["session"]["id"] = "SYNTHETIC-SESSION-3"
            switched["session"]["name"] = "第三个合成会话"
            switched["generation"] = 3
            switched["snapshot"]["session_id"] = "SYNTHETIC-SESSION-3"
            switched["snapshot"]["generation"] = 3
            page.evaluate("frame => window.__emitSyntheticFrame(frame)", switched)
            self.assertEqual(page.locator("#main [role=alert]").count(), 0)
        finally:
            context.close()

    def test_log_selection_invalidates_in_flight_query(self) -> None:
        """Changing selected nodes invalidates an in-flight log result without rereading."""
        context, page = self.new_page()
        try:
            self.intercept_synthetic_api(page, hold_logs=True)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            self.navigate(page, "logs")
            page.get_by_role("button", name="读取实际日志").click()
            page.wait_for_function("() => window.__syntheticLogResolvers.length === 2")
            page.locator('[data-log-node="2"]').uncheck()
            self.assertTrue(page.locator("#logs-form button").is_enabled(),
                            "changing node selection left the old query loading")
            self.assertEqual(page.evaluate("() => window.__syntheticLogReadCount"), 2,
                             "changing node selection must not start another read")
            page.evaluate("() => window.__resolveSyntheticLogs(503)")
            page.wait_for_timeout(50)
            self.assertEqual(page.locator("#main [role=alert]").count(), 0,
                             "an invalidated query error was rendered")
            self.assertEqual(page.evaluate("() => window.__syntheticLogReadCount"), 2)
        finally:
            context.close()

    def test_create_and_experiment_form_drafts_survive_blur_and_sse(self) -> None:
        """Synthetic typing, blur, and SSE renders preserve both form drafts."""
        context, page = self.new_page()
        try:
            self.intercept_synthetic_api(page, control_enabled=True)
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            self.navigate(page, "settings")
            page.locator('#create-form [name="name"]').fill("draft-session")
            page.locator('#create-form [name="nodes"]').fill("17")
            page.locator('#create-form details summary').click()
            page.locator('#create-form [name="batch"]').fill("256")
            page.evaluate("() => document.activeElement.blur()")
            page.evaluate("() => window.__emitSyntheticFrame({ ...window.__lastSyntheticFrame, snapshot: { ...window.__lastSyntheticFrame.snapshot, seq: 2 } })")
            self.assertEqual(page.locator('#create-form [name="name"]').input_value(), "draft-session")
            self.assertEqual(page.locator('#create-form [name="nodes"]').input_value(), "17")
            self.assertEqual(page.locator('#create-form [name="batch"]').input_value(), "256")

            self.navigate(page, "experiments")
            page.locator('#experiment-form [name="entries"]').fill("4096")
            page.locator('#experiment-form [name="rounds"]').fill("3")
            page.locator('#experiment-form details summary').click()
            page.locator('#experiment-form [name="seed"]').fill("77")
            page.locator('#experiment-form [name="batch"]').fill("512")
            page.locator('#experiment-form [name="nodes"][value="3"]').check()
            page.locator('#experiment-form [name="nodes"][value="11"]').check()
            page.locator('#experiment-form [name="scenarios"][value="election"]').check()
            page.locator('#experiment-form [name="scenarios"][value="replication"]').check()
            page.evaluate("() => document.activeElement.blur()")
            frame = frame_fixture()
            frame["snapshot"]["seq"] = 3
            page.evaluate("frame => window.__emitSyntheticFrame(frame)", frame)
            self.assertEqual(page.locator('#experiment-form [name="entries"]').input_value(), "4096")
            self.assertEqual(page.locator('#experiment-form [name="rounds"]').input_value(), "3")
            self.assertEqual(page.locator('#experiment-form [name="seed"]').input_value(), "77")
            self.assertEqual(page.locator('#experiment-form [name="batch"]').input_value(), "512")
            self.assertEqual(page.locator('#experiment-form [name="nodes"]:checked').evaluate_all("es => es.map(e=>e.value)"), ["3", "11"])
            self.assertEqual(page.locator('#experiment-form [name="scenarios"]:checked').evaluate_all("es => es.map(e=>e.value)"), ["election", "replication"])
        finally:
            context.close()

    def test_experiment_chart_separates_requested_workloads(self) -> None:
        """Rows with distinct requested command counts have separate chart groups."""
        context, page = self.new_page()
        try:
            page.route("**/app.js", lambda route: route.abort())
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            result = page.evaluate("""async () => {
              const {experimentChart} = await import('./charts.js');
              const base = {platform:'linux', source_sha256:'abc', nodes:3, scenario:'replication', batch_size:128, result:'PASS'};
              document.querySelector('#main').innerHTML = experimentChart([
                {...base, requested_commands:256, elapsed_seconds:1},
                {...base, requested_commands:100000, elapsed_seconds:20},
              ]);
              return {groups:document.querySelectorAll('.experiment-chart article').length, text:document.querySelector('#main').textContent};
            }""")
            self.assertEqual(result["groups"], 2)
            self.assertIn("256 条命令", result["text"])
            self.assertIn("100,000 条命令", result["text"])
        finally:
            context.close()

    def test_unsafe_integer_api_and_sse_values_remain_exact(self) -> None:
        """Raw JSON fixtures preserve unsafe integers in API responses and displayed SSE data."""
        context, page = self.new_page()
        try:
            self.intercept_synthetic_api(page)
            raw_api = '{"x":9007199254740993}'
            self.assertIn('"x":9007199254740993', raw_api)
            page.route("**/api/raw-integer-fixture", lambda route: route.fulfill(
                status=200, content_type="application/json", body=raw_api))
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            self.wait_for_synthetic_stream(page)
            api_data = page.evaluate("async () => (await import('./api.js')).request('/api/raw-integer-fixture')")

            frame = frame_fixture()
            frame["snapshot"]["nodes"] = [{
                "id": 1, "reachable": True, "identity_ok": True,
                "status": {"state": "Follower", "term": 1, "last_log_index": 1,
                           "commit_index": 1, "last_applied": 1, "x": 9007199254740993,
                           "dropped_events": 0},
            }]
            raw_frame = json.dumps(frame, separators=(",", ":"))
            self.assertIn('"x":9007199254740993', raw_frame)
            page.evaluate("raw => window.__emitSyntheticRawFrame(raw)", raw_frame)
            node = page.locator('#stage-host .stage-node[data-node="1"]')
            node.wait_for(state="visible")
            page.wait_for_function(
                "() => document.querySelector('#stage-host .stage-node[data-node=\"1\"]')?.classList.contains('follower')"
            )
            node.click()
            page.locator("#node-detail").wait_for(state="visible")
            displayed = page.locator("#main").inner_text()
            self.assertEqual(
                {"api": api_data["x"], "ui": "9007199254740993" in displayed,
                 "rounded_ui": "9007199254740992" in displayed},
                {"api": "9007199254740993", "ui": True, "rounded_ui": False},
            )
            page.locator("#node-detail .detail-close").click()
            page.locator("#node-detail").wait_for(state="hidden")
            page.screenshot(path=str(OUTPUT / "synthetic-large-integer-display.png"), full_page=True)
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
