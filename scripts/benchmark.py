"""Real-process Raft experiments; Python standard library only, one cluster at a time."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import socket
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / ('raft-node.exe' if os.name == 'nt' else 'raft-node')
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


class Cluster:
    def __init__(self, count, folder, timeout):
        self.folder, self.timeout = folder, timeout
        self.processes, self.outputs = {}, []
        self.query_timeouts = 0
        self.folder.mkdir(parents=True)
        sockets = []
        try:
            for _ in range(count):
                s = socket.socket()
                s.bind(('127.0.0.1', 0))
                sockets.append(s)
            self.nodes = [{'id': i + 1, 'addr': f'127.0.0.1:{s.getsockname()[1]}'}
                          for i, s in enumerate(sockets)]
            self.config = folder / 'nodes.json'
            self.query_config = folder / 'query-nodes.json'
            self.config.write_text(json.dumps({'nodes': self.nodes}), encoding='utf-8')
        finally:
            for s in sockets:
                s.close()

    def run(self, *args, config=None, timeout=None):
        result = subprocess.run([str(EXE), '-config', str(config or self.config), *map(str, args)],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                timeout=timeout or self.timeout + 3, creationflags=FLAGS)
        if result.returncode:
            raise RuntimeError(f'CLI {args}: {result.stdout}\n{result.stderr}')
        return json.loads(result.stdout)

    def update_query(self):
        # This is only a client query list; the voters' original configuration never changes.
        self.query_config.write_text(json.dumps({'nodes': [n for n in self.nodes
                                                          if n['id'] in self.processes]}), encoding='utf-8')

    def start(self, node_id):
        out = (self.folder / f'process-{node_id}.log').open('ab')
        self.outputs.append(out)
        self.processes[node_id] = subprocess.Popen(
            [str(EXE), '-id', str(node_id), '-config', str(self.config),
             '-data-dir', str(self.folder / 'data'), '-log-dir', str(self.folder / 'logs'),
             '-election-min', '3s', '-election-jitter', '3s', '-heartbeat', '150ms', '-rpc-timeout', '1s'],
            cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, creationflags=FLAGS,
            env={**os.environ, 'GOMAXPROCS': '1'})
        self.update_query()

    def stop(self, node_id):
        p = self.processes[node_id]
        p.kill()
        p.wait(timeout=10)
        self.processes.pop(node_id)
        self.update_query()

    def statuses(self, target=0):
        for node_id, p in self.processes.items():
            if p.poll() is not None:
                raise RuntimeError(f'node {node_id} exited ({p.returncode}); see process log')
        begin = time.perf_counter()
        result = self.run('-status-all', '-target-index', target, '-timeout', '3s',
                          config=self.query_config, timeout=5)
        elapsed = time.perf_counter() - begin
        return result, elapsed

    def wait(self, *, logs=False, target=0, commands=None, checkpoint=None):
        deadline = time.perf_counter() + self.timeout
        stable, previous = 0, None
        last, query_seconds = [], 0.0
        while time.perf_counter() < deadline:
            try:
                last, query_seconds = self.statuses(target)
            except subprocess.TimeoutExpired:
                self.query_timeouts += 1
                stable, previous = 0, None
                continue
            if time.perf_counter() >= deadline:
                break
            good, leader = consistent(last, logs, target, commands, checkpoint)
            key = (leader['id'], leader['term'], last[0]['committed_hash']) if good else None
            stable = stable + 1 if good and key == previous else int(good)
            previous = key
            if stable >= 2:
                (self.folder / 'last-status.json').write_text(json.dumps(last, indent=2), encoding='utf-8')
                return leader, last, query_seconds
            time.sleep(0.1)
        raise TimeoutError(f'cluster did not converge: {last}')

    def generate(self, count, seed, timeout=None):
        seconds = timeout or self.timeout
        reply = self.run('-demo', count, '-seed', seed, '-timeout', f'{seconds}s',
                         config=self.query_config, timeout=seconds + 3)
        if not reply.get('accepted') or not reply.get('committed') or reply.get('commands') != count:
            raise AssertionError(f'commands not confirmed: {reply}')
        return reply

    def close(self):
        errors = []
        for node_id, p in list(self.processes.items()):
            try:
                if p.poll() is None:
                    p.kill()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=30)
            except Exception as exc:
                errors.append(f'{node_id}: {exc}')
        for out in self.outputs:
            out.close()
        self.processes.clear()
        if errors:
            raise RuntimeError('process cleanup failed: ' + '; '.join(errors))


def consistent(states, logs, target, commands, checkpoint=None):
    if not states or any(s.get('error') for s in states):
        return False, None
    leaders = [s for s in states if s['state'] == 'Leader']
    if len(leaders) != 1:
        return False, None
    leader = leaders[0]
    if any(s['term'] != leader['term'] or s['leader_id'] != leader['id'] for s in states):
        return False, None
    if logs:
        base = states[0]
        keys = ('last_log_index', 'commit_index', 'last_applied', 'log_hash',
                'committed_hash', 'committed_commands', 'applied_commands', 'x')
        for s in states:
            if s['last_log_index'] != s['commit_index'] or s['last_applied'] != s['commit_index']:
                return False, None
            if any(s[k] != base[k] for k in keys):
                return False, None
            if commands is not None and s['applied_commands'] != commands:
                return False, None
            if target and (not s['target_available'] or s['target_index'] != target or
                           s['target_hash'] != base['target_hash'] or s['target_x'] != base['target_x']):
                return False, None
    if checkpoint and any(not s.get('target_available') or s.get('target_index') != checkpoint['index'] or
                          s.get('target_hash') != checkpoint['hash'] or s.get('target_x') != checkpoint['x']
                          for s in states):
        return False, None
    return True, leader


def save_checkpoint(folder, state):
    checkpoint = {'index': state['target_index'], 'hash': state['target_hash'], 'x': state['target_x']}
    (folder / 'checkpoint.json').write_text(json.dumps(checkpoint, indent=2), encoding='utf-8')
    return checkpoint


def source_hashes():
    paths = [ROOT / 'go.mod', *ROOT.glob('*.go')]
    for directory in ('config', 'raft', 'rpc', 'scripts'):
        paths.extend(p for p in (ROOT / directory).iterdir() if p.suffix in ('.go', '.py', '.ps1'))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def build_current(output):
    global EXE
    def git(*args):
        try:
            r = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=10)
            return r.stdout.strip() if r.returncode == 0 else None
        except FileNotFoundError:
            return None
    version = subprocess.check_output(['go', 'version'], cwd=ROOT, text=True).strip()
    before = source_hashes()
    dirty = git('status', '--porcelain=v1', '--untracked-files=normal')
    EXE = output / ('raft-node.exe' if os.name == 'nt' else 'raft-node')
    subprocess.run(['go', 'build', '-o', str(EXE), '.'], cwd=ROOT, check=True)
    if source_hashes() != before:
        raise RuntimeError('source changed during build; rerun with a stable working tree')
    return {'go': version, 'git_commit': git('rev-parse', 'HEAD'),
            'git_dirty': None if dirty is None else bool(dirty),
            'source_sha256': before, 'binary_sha256': hashlib.sha256(EXE.read_bytes()).hexdigest(),
            'build_command': ['go', 'build', '-o', EXE.name, '.']}


def experiment(count, scenario, entries, seed, folder, timeout):
    c = Cluster(count, folder, timeout)
    row = {'nodes': count, 'scenario': scenario, 'requested_commands': entries, 'seed': seed,
           'result': 'FAIL', 'elapsed_seconds': None, 'error': None}
    begin = time.perf_counter()
    try:
        if scenario == 'divergence':
            c.run('-prepare-divergence', '-demo', entries, '-seed', seed,
                  '-data-dir', str(folder / 'data'))
        start_ids = range(1, count if scenario == 'catchup' else count + 1)
        begin = time.perf_counter()
        for node_id in start_ids:
            c.start(node_id)
        row['launch_seconds'] = time.perf_counter() - begin
        leader, _, _ = c.wait()
        row['initial_leader'] = leader['id']
        if scenario == 'election':
            row['elapsed_seconds'] = time.perf_counter() - begin
            row['local_election_ms'] = leader['election_ms']
            leader, states, query_seconds = c.wait(logs=True)
        elif scenario == 'failover':
            reply = c.generate(entries, seed)
            leader, initial, _ = c.wait(logs=True, target=reply['last_index'], commands=entries)
            checkpoint = save_checkpoint(c.folder, initial[0])
            rng = random.Random(seed)
            killed = [leader['id']]
            max_faults = (count - 1) // 2
            killed += rng.sample([i for i in c.processes if i != leader['id']], rng.randrange(max_faults))
            old_term = leader['term']
            begin = time.perf_counter()
            for node_id in killed:
                c.stop(node_id)
            row['kill_seconds'] = time.perf_counter() - begin
            replacement, _, _ = c.wait()
            row['leader_observed_seconds'] = time.perf_counter() - begin
            if replacement['term'] <= old_term:
                raise AssertionError('leader term did not advance')
            reply = c.generate(1, seed + 1)
            row['elapsed_seconds'] = time.perf_counter() - begin
            row['local_election_ms'] = replacement['election_ms']
            row['killed_ids'] = killed
            leader, states, query_seconds = c.wait(logs=True, target=checkpoint['index'],
                                                    commands=entries + 1, checkpoint=checkpoint)
            # Restart original disks and verify catch-up without changing membership.
            for node_id in killed:
                c.start(node_id)
            leader, states, query_seconds = c.wait(logs=True, target=checkpoint['index'],
                                                    commands=entries + 1, checkpoint=checkpoint)
            row['restarted_nodes_caught_up'] = True
        elif scenario == 'catchup':
            reply = c.generate(entries, seed)
            _, initial, _ = c.wait(logs=True, target=reply['last_index'], commands=entries)
            checkpoint = save_checkpoint(c.folder, initial[0])
            begin = time.perf_counter()
            c.start(count)
            leader, states, query_seconds = c.wait(logs=True, target=checkpoint['index'],
                                                    commands=entries, checkpoint=checkpoint)
            row['elapsed_seconds'] = time.perf_counter() - begin
            row['target_index'] = reply['last_index']
        else:
            leader, states, query_seconds = c.wait(logs=True, target=129)
            fixture = json.loads((folder / 'data' / 'fixture.json').read_text(encoding='utf-8'))
            if any(s['target_hash'] != fixture['common_hash'] or s['target_x'] != fixture['common_x'] for s in states):
                raise AssertionError('committed fixture prefix changed')
            # A final leader query gives a monotonic upper observation bound from its election.
            final = c.run('-id', leader['id'], '-status', '-timeout', '3s')
            if final['term'] != leader['term'] or final['state'] != 'Leader':
                raise AssertionError('leader changed during final timing query')
            row['elapsed_seconds'] = final['leader_age_ms'] / 1000
            row['startup_to_sync_seconds'] = time.perf_counter() - begin
            row['common_commit_index'] = 129
            # Uncommitted arithmetic tails may legitimately be discarded by Raft.
            if any(s['commit_index'] < 129 or s['applied_commands'] < 128 for s in states):
                raise AssertionError('committed fixture prefix was lost')
        if scenario in ('failover', 'catchup'):
            row.update(checkpoint_index=checkpoint['index'], checkpoint_hash=checkpoint['hash'],
                       checkpoint_x=checkpoint['x'], checkpoint_preserved=True)
        row.update(result='PASS', final_leader=leader['id'], final_term=leader['term'],
                   committed_commands=states[0]['committed_commands'],
                   commit_index=states[0]['commit_index'], x=states[0]['x'],
                   committed_hash=states[0]['committed_hash'], last_query_seconds=query_seconds)
    except KeyboardInterrupt:
        row['result'], row['error'] = 'INTERRUPTED', 'KeyboardInterrupt'
    except Exception as exc:
        row['error'] = f'{type(exc).__name__}: {exc}'
        row['failure_observed_seconds'] = time.perf_counter() - begin
    finally:
        try:
            c.close()
        except Exception as exc:
            row['result'], row['error'] = 'FAIL', f'{row.get("error")}; {exc}'
            row['cleanup_failed'] = True
        row['query_timeouts'] = c.query_timeouts
        (folder / 'result.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
    return row


def summarize(rows):
    groups = []
    for key in sorted({(r['nodes'], r['scenario']) for r in rows}):
        selected = [r for r in rows if (r['nodes'], r['scenario']) == key]
        values = [r['elapsed_seconds'] for r in selected if r['result'] == 'PASS']
        local = [r['local_election_ms'] for r in selected if r['result'] == 'PASS' and 'local_election_ms' in r]
        groups.append({'nodes': key[0], 'scenario': key[1], 'attempts': len(selected),
                       'passed': len(values), 'failed': sum(r['result'] == 'FAIL' for r in selected),
                       'interrupted': sum(r['result'] == 'INTERRUPTED' for r in selected),
                       'mean_seconds': statistics.mean(values) if values else None,
                       'median_seconds': statistics.median(values) if values else None,
                       'min_seconds': min(values) if values else None,
                       'max_seconds': max(values) if values else None,
                       'mean_local_election_ms': statistics.mean(local) if local else None})
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nodes', nargs='+', type=int, default=[10, 20, 50, 100])
    parser.add_argument('--entries', type=int, default=2101)
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--scenarios', nargs='+', choices=['election', 'failover', 'catchup', 'divergence'],
                        default=['election', 'failover', 'catchup', 'divergence'])
    parser.add_argument('--output', type=Path, default=ROOT / '.test-output' / f'benchmark-{time.time_ns()}')
    args = parser.parse_args()
    if min(args.nodes) < 3 or args.rounds < 1 or args.entries < 256 or not 1 <= args.timeout <= 600:
        parser.error('nodes >=3, rounds >=1, entries >=256, timeout 1..600 required')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = {'platform': platform.platform(), 'python': platform.python_version(),
                   'logical_cpus': os.cpu_count(), 'node_gomaxprocs': 1, 'timings_ms': {'election_min': 3000, 'election_jitter': 3000, 'heartbeat': 150, 'rpc_timeout': 1000}, 'arguments': vars(args).copy(),
                   'measurement': 'monotonic polling observation; per wait/generate timeout, not total scenario budget; two consistent snapshots 100 ms apart; includes polling overhead'}
    environment['arguments']['output'] = str(output)
    (output / 'environment.json').write_text(json.dumps(environment, indent=2), encoding='utf-8')
    try:
        environment.update(build_current(output))
    except BaseException as exc:
        (output / 'run-status.json').write_text(json.dumps({'status': 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'BUILD_FAILED', 'completed': 0}), encoding='utf-8')
        raise
    (output / 'environment.json').write_text(json.dumps(environment, indent=2), encoding='utf-8')
    rows = []
    cases = ((n, s, r) for n in args.nodes for s in args.scenarios for r in range(args.rounds))
    for count, scenario, iteration in cases:
        folder = output / f'{scenario}-{count}-r{iteration+1}'
        row = experiment(count, scenario, args.entries, args.seed + iteration, folder, args.timeout)
        row['round'] = iteration + 1
        rows.append(row)
        (output / 'results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
        (output / 'summary.json').write_text(json.dumps(summarize(rows), indent=2), encoding='utf-8')
        print(f"{scenario} n={count} round={iteration+1}: {row['result']} {row['elapsed_seconds']} {(row['error'] or '')[:250]}", flush=True)
        if row.get('cleanup_failed') or row['result'] == 'INTERRUPTED':
            break
    keys = sorted({k for row in rows for k in row})
    with (output / 'results.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    final_status = ('CLEANUP_FAILED' if any(r.get('cleanup_failed') for r in rows) else
                    'INTERRUPTED' if any(r['result'] == 'INTERRUPTED' for r in rows) else 'COMPLETE')
    (output / 'run-status.json').write_text(json.dumps({'status': final_status,
        'planned': len(args.nodes) * len(args.scenarios) * args.rounds, 'completed': len(rows),
        'passed': sum(r['result'] == 'PASS' for r in rows), 'failed': sum(r['result'] == 'FAIL' for r in rows),
        'interrupted': sum(r['result'] == 'INTERRUPTED' for r in rows)}, indent=2), encoding='utf-8')
    print(f'Results: {output}', flush=True)
    return 0 if all(r['result'] == 'PASS' for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
