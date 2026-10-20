"""Paired real-process latency/monitoring trials. Standard library; browsers need Playwright.

Builds all binaries from --source. Never combines platforms, retries uncertain writes,
or treats profiler runs as latency samples. Output directories must be new.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

import benchmark as bench
from arithmetic_reference import verify_files


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def summarize(attempts):
    measured = [s for s in attempts if not s['warmup']]
    good = [s['seconds'] for s in measured if s['committed'] and not s.get('error')]
    return {'percentile_population': 'successful_requests_only',
            'attempts': len(measured), 'successes': len(good), 'failures': len(measured)-len(good),
            'p50_seconds': statistics.median(good) if good else None,
            'p95_seconds': sorted(good)[math.ceil(len(good)*.95)-1] if good else None}


def process_resources(pid):
    if sys.platform.startswith('linux'):
        root = Path('/proc') / str(pid)
        fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
        return {'cpu_seconds': (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK'),
                'rss_bytes': int((root/'statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE'),
                'threads': int(fields[17]), 'handles': len(list((root/'fd').iterdir()))}
    if os.name == 'nt':
        import ctypes as c
        from ctypes import wintypes as w
        class Counters(c.Structure):
            _fields_ = [('cb', w.DWORD), ('faults', w.DWORD)] + [(n, c.c_size_t) for n in
                ['peak_ws', 'ws', 'peak_pool', 'pool', 'peak_nonpool', 'nonpool', 'pagefile', 'peak_pagefile']]
        kernel, psapi = c.WinDLL('kernel32', use_last_error=True), c.WinDLL('psapi', use_last_error=True)
        kernel.OpenProcess.restype = w.HANDLE
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)]*4
        kernel.GetProcessHandleCount.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
        psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.POINTER(Counters), w.DWORD]
        handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
        if not handle:
            raise OSError(c.get_last_error(), 'OpenProcess')
        try:
            times = [w.FILETIME() for _ in range(4)]
            counters = Counters(); counters.cb = c.sizeof(counters)
            handles = w.DWORD()
            if not kernel.GetProcessTimes(handle, *[c.byref(x) for x in times]) or not psapi.GetProcessMemoryInfo(handle, c.byref(counters), counters.cb) or not kernel.GetProcessHandleCount(handle, c.byref(handles)):
                raise OSError(c.get_last_error(), 'process resource read')
            ticks = sum((x.dwHighDateTime << 32) | x.dwLowDateTime for x in times[2:])
            return {'cpu_seconds': ticks/1e7, 'rss_bytes': counters.ws, 'threads': None, 'handles': handles.value}
        finally:
            kernel.CloseHandle(handle)
    raise OSError('resource sampling unavailable on this platform')


class Sampler:
    def __init__(self, processes):
        self.processes, self.rows, self.stop_event = processes, [], threading.Event()
        self.thread = threading.Thread(target=self.run)
    def run(self):
        start = time.perf_counter()
        while True:
            row = {'elapsed_seconds': time.perf_counter()-start, 'processes': {}}
            for name, proc in self.processes.items():
                try:
                    row['processes'][name] = process_resources(proc.pid)
                except (OSError, ValueError, IndexError) as exc:
                    row['processes'][name] = {'error': str(exc)}
            self.rows.append(row)
            if self.stop_event.wait(.25):
                break
    def start(self):
        self.thread.start()
    def stop(self):
        self.stop_event.set(); self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError('resource sampler did not stop')


def snapshot(url):
    with urllib.request.urlopen(url+'/api/snapshot', timeout=5) as r:
        return json.load(r)['snapshot']


def idle_rounds(url, nodes):
    # Node EventRange calls can accompany Summary calls. Settle event backlog first.
    old, stable = snapshot(url), 0
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        time.sleep(.2)
        new = snapshot(url)
        if new['seq'] == old['seq']:
            continue
        stable = stable+1 if new['monitor_rpcs']-old['monitor_rpcs'] == nodes*(new['seq']-old['seq']) else 0
        old = new
        if stable == 2:
            break
    if stable < 2:
        raise RuntimeError('collector did not settle for idle comparison')
    start = old
    while time.monotonic() < deadline:
        time.sleep(.2); new = snapshot(url)
        if new['seq'] >= start['seq']+5:
            return {'rounds': new['seq']-start['seq'], 'monitor_rpcs': new['monitor_rpcs']-start['monitor_rpcs'],
                    'expected_summary_rpcs': nodes*(new['seq']-start['seq'])}
    raise TimeoutError('five shared sampling rounds did not finish')


def trial(args, count, browsers, iteration, root, dashboard, probe, playwright):
    case = root/f'n{count}-b{browsers}-r{iteration}'
    cluster = bench.Cluster(count, case, 120, args.batch)
    controller = browser = sampler = output = None
    states = None
    row = {'nodes': count, 'browsers': browsers, 'round': iteration, 'batch': args.batch,
           'collector': not args.no_collector, 'result': 'FAIL', 'requested_samples': args.samples}
    try:
        for n in cluster.nodes:
            cluster.start(n['id'])
        cluster.wait(logs=True, commands=0)
        processes = {f'node-{i}': p for i, p in cluster.processes.items()}
        if not args.no_collector:
            output = (case/'controller.txt').open('wb')
            controller = subprocess.Popen([str(dashboard), '-listen', '127.0.0.1:0', '-config', str(cluster.config),
                '-data-root', str(case/'console'), '-node-bin', str(bench.EXE), '-source-dir', str(args.source),
                '-python', sys.executable], stdout=output, stderr=subprocess.STDOUT,
                env={**os.environ, 'GOMAXPROCS': '1'}, creationflags=bench.FLAGS)
            processes['controller'] = controller
            deadline = time.monotonic()+15
            while True:
                m = re.search(r'http://127.0.0.1:\d+', (case/'controller.txt').read_text(encoding='utf-8'))
                if m:
                    url = m[0]; break
                if controller.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('controller did not start')
                time.sleep(.05)
            if browsers:
                browser = playwright.chromium.launch(headless=True)
                for _ in range(browsers):
                    page = browser.new_page(viewport={'width': 1440, 'height': 900})
                    page.goto(url, wait_until='domcontentloaded')
                    page.wait_for_function("""n => {
                      const label = document.querySelector('#connection')?.textContent || '';
                      return label.includes('已连接') &&
                        document.querySelectorAll('#main [data-node]').length >= n;
                    }""", arg=count, timeout=15000)
            row['idle_sampling'] = idle_rounds(url, count)
            if row['idle_sampling']['monitor_rpcs'] != row['idle_sampling']['expected_summary_rpcs']:
                raise AssertionError('idle monitor RPC count differs from one shared collector')
        sampler = Sampler(processes); sampler.start()
        begin = time.perf_counter()
        result = bench.run_tool([str(probe), '-config', str(cluster.config), '-samples', str(args.samples),
                                '-warmup', str(args.warmup), '-entries', '64', '-seed', str(42+iteration),
                                '-output', str(case/'attempts.jsonl')], 120)
        row['probe_wall_seconds'] = time.perf_counter()-begin
        raw = json.loads(result); write(case/'latency.json', raw)
        sampler.stop(); write(case/'resources.json', sampler.rows); sampler = None
        row.update(summarize(raw['attempts']))
        committed = sum(64 for x in raw['attempts'] if x['committed'] and not x.get('error'))
        _, states, _ = cluster.wait(logs=True, commands=committed)
        if row['failures'] or row['attempts'] != args.samples:
            raise AssertionError('write failures/incomplete samples; uncertain writes were not retried')
        row['result'] = 'PASS'
    except KeyboardInterrupt:
        row.update(result='INTERRUPTED', error='KeyboardInterrupt')
    except Exception as exc:
        row['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        errors = []
        if (case/'attempts.jsonl').exists() and row['result'] != 'PASS':
            partial = []
            for line in (case/'attempts.jsonl').read_text(encoding='utf-8').splitlines():
                try:
                    partial.append(json.loads(line))
                except json.JSONDecodeError:
                    break
            row.update(summarize(partial))
            row['incomplete_attempt_journal'] = True
            row['inflight_outcome'] = 'unknown; not retried'
            write(case/'latency-partial.json', partial)
        for cleanup in ([sampler.stop] if sampler else []) + ([browser.close] if browser else []):
            try:
                cleanup()
            except Exception as exc:
                errors.append(str(exc))
        if sampler:
            write(case/'resources.json', sampler.rows)
        if controller:
            try:
                controller.terminate()
                try:
                    controller.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    controller.kill(); controller.wait(timeout=5)
            except Exception as exc:
                errors.append(str(exc))
        if output:
            output.close()
        try:
            cluster.close()
        except Exception as exc:
            errors.append(str(exc))
        if errors:
            row.update(result='FAIL', cleanup_errors=errors)
        if row['result'] == 'PASS':
            try:
                write(case/'arithmetic-reference.json', verify_files(case/'data', states))
            except Exception as exc:
                row.update(result='FAIL', error=f'independent reference: {exc}')
        write(case/'result.json', row)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--nodes', nargs='+', type=int, default=[11, 50, 100])
    p.add_argument('--browsers', nargs='+', type=int, default=[0])
    p.add_argument('--rounds', type=int, default=3)
    p.add_argument('--samples', type=int, default=200)
    p.add_argument('--warmup', type=int, default=20)
    p.add_argument('--batch', type=int, default=128)
    p.add_argument('--no-collector', action='store_true')
    args = p.parse_args()
    if min(args.nodes)<3 or max(args.nodes)>100 or min(args.browsers)<0 or max(args.browsers)>10 or args.rounds<1 or args.samples<1 or args.warmup<0:
        p.error('invalid bounded trial parameters')
    if args.no_collector and any(args.browsers):
        p.error('--no-collector requires zero browsers')
    args.source, args.output = args.source.resolve(), args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    bench.ROOT = args.source
    def inputs():
        paths = [*args.source.glob('*.go'), args.source/'go.mod']
        for name in ['raft', 'rpc', 'config', 'cmd/dashboard']:
            paths.extend(p for p in (args.source/name).rglob('*') if p.is_file() and
                         p.suffix in {'.go', '.html', '.css', '.js'})
        return {p.relative_to(args.source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(paths)}
    source_inputs = inputs()
    env = bench.build_current(args.output)
    ext = '.exe' if os.name == 'nt' else ''
    dashboard, probe = args.output/('console'+ext), args.output/('probe'+ext)
    probe_source = Path(__file__).with_name('perf_probe.go').resolve()
    bench.run_tool(['go','build','-o',str(dashboard),'./cmd/dashboard'],120)
    bench.run_tool(['go','build','-o',str(probe),str(probe_source)],120)
    if inputs() != source_inputs:
        raise RuntimeError('source changed during build')
    env.update(platform=platform.platform(), python=platform.python_version(), gomaxprocs=1,
               build_inputs_sha256=source_inputs,
               binaries_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [bench.EXE,dashboard,probe]},
               probe_source_sha256=hashlib.sha256(probe_source.read_bytes()).hexdigest(),
               runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               parameters=vars(args)|{'source':str(args.source),'output':str(args.output)},
               measurement='TCP connect + Generate until committed reply; discovery excluded; no retries',
               resource_scope='owned Raft nodes and controller, excluding browsers and transient probe')
    write(args.output/'environment.json',env)
    rows, pw = [], None
    try:
        if any(args.browsers):
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
        for count in args.nodes:
            for iteration in range(1,args.rounds+1):
                order = args.browsers if iteration%2 else list(reversed(args.browsers))
                for browsers in order:
                    row = trial(args,count,browsers,iteration,args.output,dashboard,probe,pw)
                    rows.append(row); write(args.output/'results.json',rows)
                    print(json.dumps(row),flush=True)
                    if row['result']=='INTERRUPTED' or row.get('cleanup_errors'):
                        raise SystemExit(130 if row['result']=='INTERRUPTED' else 1)
    finally:
        if pw:
            pw.stop()
        write(args.output/'run-status.json',{'completed':len(rows),'planned':len(args.nodes)*len(args.browsers)*args.rounds,
              'passed':sum(r['result']=='PASS' for r in rows), 'failed':sum(r['result']=='FAIL' for r in rows),
              'interrupted':sum(r['result']=='INTERRUPTED' for r in rows),
              'not_run':len(args.nodes)*len(args.browsers)*args.rounds-len(rows)})
    if any(r['result']!='PASS' for r in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
