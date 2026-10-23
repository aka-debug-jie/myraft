#!/usr/bin/env python3
"""Small browser acceptance test for experiment performance charts."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from playwright.sync_api import sync_playwright
import os


ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    os.chdir(ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    failures = []

    def check(label, condition, detail=""):
        if not condition:
            failures.append(f"FAIL: {label}{': ' + detail if detail else ''}")
        else:
            print(f"PASS: {label}")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"http://127.0.0.1:{server.server_port}/cmd/dashboard/static/index.html")
            result = page.evaluate("""async () => {
              const {experimentChart} = await import('./charts.js');
              const base = {platform:'linux', source_sha256:'abc123', nodes:3, scenario:'write', batch_size:10, requested_commands:100};
              const html = (rows) => experimentChart(rows.map((row) => ({...base, ...row})));
              const single = html([{round:1,result:'PASS',elapsed_seconds:2.5}]);
              const mixed = html([
                {round:1,result:'PASS',elapsed_seconds:2},
                {round:2,result:'PASS',elapsed_seconds:4},
                {round:3,result:'PASS',elapsed_seconds:-7},
                {round:4,result:'PASS',elapsed_seconds:''},
                {round:5,result:'FAIL',elapsed_seconds:999},
                {round:6,result:'INTERRUPTED',elapsed_seconds:888},
                {round:7,result:'PASS',elapsed_seconds:8},
              ]);
              const grouped = experimentChart([
                {...base, round:1, result:'PASS', elapsed_seconds:1},
                {...base, platform:'<img src=x onerror=alert(1)>', round:1, result:'PASS', elapsed_seconds:1},
              ]);
              document.body.innerHTML = `<main id="single">${single}</main><main id="mixed">${mixed}</main><main id="grouped">${grouped}</main>`;
              const singleRoot = document.querySelector('#single');
              const mixedRoot = document.querySelector('#mixed');
              return {
                singleSVGs: singleRoot.querySelectorAll('svg').length,
                singleText: singleRoot.innerText,
                mixedSVGs: mixedRoot.querySelectorAll('svg').length,
                mixedText: mixedRoot.innerText,
                mixedMarkup: mixedRoot.innerHTML,
                groupedCount: document.querySelectorAll('#grouped .perf-group').length,
                injectedImages: document.querySelectorAll('#grouped img').length,
              };
            }""")
            check("single PASS is summarized without redundant charts", result["singleSVGs"] == 0, f"found {result['singleSVGs']} SVG charts")
            check("multiple PASS values use one clear chart", result["mixedSVGs"] == 1, f"found {result['mixedSVGs']} SVG charts")
            for label, expected in [
                ("sample count", "n=3"),
                ("mean", "均值 4.667 s"),
                ("median", "中位数 4.000 s"),
                ("range", "范围 2.000–8.000 s"),
                ("failure count", "FAIL 1"),
                ("interruption count", "INTERRUPTED 1"),
            ]:
                check(f"{label} is explicit", expected in result["mixedText"], repr(result["mixedText"]))
            check("invalid elapsed values are absent from the chart", "-7" not in result["mixedMarkup"] and "999" not in result["mixedMarkup"] and "888" not in result["mixedMarkup"])
            check("timeline leaves missing rounds disconnected", result["mixedMarkup"].count('class="perf-line-segment"') == 1)
            check("SVG has an accessible label and seconds unit", 'aria-label="PASS 逐轮耗时，单位秒"' in result["mixedMarkup"])
            check("grouping fields still separate distinct platform runs", result["groupedCount"] == 2)
            check("untrusted group labels are escaped", result["injectedImages"] == 0)

            page.add_style_tag(url="/cmd/dashboard/static/charts.css")
            page.evaluate("""() => { document.body.innerHTML = `<main style="width:100%;max-width:100%;overflow:hidden">${document.querySelector('#mixed')?.innerHTML ?? ''}</main>`; }""")
            page.set_viewport_size({"width": 375, "height": 812})
            dimensions = page.evaluate("""() => ({
              viewport: document.documentElement.clientWidth,
              body: document.body.scrollWidth,
              root: document.querySelector('main').scrollWidth,
              rootClient: document.querySelector('main').clientWidth,
              chartScroll: document.querySelector('.perf-chart-scroll').clientWidth,
              chartContent: document.querySelector('.perf-timeline').clientWidth,
            })""")
            check("chart remains within a mobile viewport with readable scroll width", dimensions["body"] <= dimensions["viewport"] and dimensions["chartScroll"] <= dimensions["rootClient"] and dimensions["chartContent"] >= 520, str(dimensions))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    for failure in failures:
        print(failure)
    if failures:
        raise SystemExit(f"{len(failures)} chart acceptance assertion(s) failed")


if __name__ == "__main__":
    main()
