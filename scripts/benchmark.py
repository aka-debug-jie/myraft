"""Real-process Raft experiments; Python standard library only, one cluster at a time."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import signal
import socket
import statistics
import subprocess
import time
import uuid

from arithmetic_reference import verify_files

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / ('raft-node.exe' if os.name == 'nt' else 'raft-node')
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
CANCEL_FILE = None


def check_cancelled():
    if CANCEL_FILE is not None and CANCEL_FILE.exists():
        raise KeyboardInterrupt('controller cancellation requested')


class CleanupError(RuntimeError):
    pass


def run_tool(command, timeout):
    """Bound build tools, including their owned compiler children, on cancel/timeout."""
    check_cancelled()
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', creationflags=FLAGS,
                               start_new_session=os.name != 'nt')
    deadline = time.monotonic() + timeout
    try:
        while True:
            check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        # Do not poll/reap before killpg: the live child handle anchors this process group.
        try:
            if process.returncode is None:
                if os.name == 'nt':
                    taskkill = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe')
                    subprocess.run([taskkill, '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, timeout=5, check=True, creationflags=FLAGS)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
        except (OSError, subprocess.SubprocessError) as cleanup:
            # Retain an explicit cleanup failure even if the original event was cancellation.
            detail = str(cleanup)
            if process.returncode is None:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except (OSError, subprocess.SubprocessError) as fallback:
                    detail += f'; direct-child fallback failed: {fallback}'
            raise CleanupError(f'owned build-tool cleanup failed: {detail}') from cleanup
        finally:
            process.stdout.close()
            process.stderr.close()
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
    return stdout.strip()


class Cluster:
    def __init__(self, count, folder, timeout, batch_size=128):
        self.batch_size = batch_size
        self.folder, self.timeout = folder, timeout
        self.cluster_id = uuid.uuid4().hex
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
            self.config.write_text(json.dumps({'cluster_id': self.cluster_id, 'nodes': self.nodes}), encoding='utf-8')
        finally:
            for s in sockets:
                s.close()

    def run(self, *args, config=None, timeout=None):
        command = [str(EXE), '-config', str(config or self.config), *map(str, args)]
        budget = timeout or self.timeout + 3
        deadline = time.perf_counter() + budget
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8', creationflags=FLAGS)
        try:
            while True:
                check_cancelled()
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, budget)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        if process.returncode:
            raise RuntimeError(f'CLI {args}: {stdout}\n{stderr}')
        return json.loads(stdout)

    def update_query(self):
        # This is only a client query list; the voters' original configuration never changes.
        self.query_config.write_text(json.dumps({'cluster_id': self.cluster_id, 'nodes': [n for n in self.nodes
                                                                                           if n['id'] in self.processes]}), encoding='utf-8')

    def start(self, node_id):
        out = (self.folder / f'process-{node_id}.log').open('ab')
        self.outputs.append(out)
        self.processes[node_id] = subprocess.Popen(
            [str(EXE), '-id', str(node_id), '-config', str(self.config),
             '-data-dir', str(self.folder / 'data'), '-log-dir', str(self.folder / 'logs'),
             '-election-min', '3s', '-election-jitter', '3s', '-heartbeat', '150ms', '-rpc-timeout', '1s', '-batch-size', str(self.batch_size)],
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
            check_cancelled()
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
        processes = list(self.processes.items())
        for node_id, p in processes:
            try:
                if p.poll() is None:
                    p.kill()
            except Exception as exc:
                errors.append(f'{node_id}: {exc}')
        for node_id, p in processes:
            try:
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        p.kill()
                    except Exception as exc:
                        errors.append(f'{node_id}: {exc}')
                    p.wait(timeout=30)
                self.processes.pop(node_id, None)
            except Exception as exc:
                errors.append(f'{node_id}: {exc}')
        for out in self.outputs:
            out.close()
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
            return run_tool(['git', *args], 10)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None
    version = run_tool(['go', 'version'], 10)
    before = source_hashes()
    dirty = git('status', '--porcelain=v1', '--untracked-files=normal')
    EXE = output / ('raft-node.exe' if os.name == 'nt' else 'raft-node')
    run_tool(['go', 'build', '-o', str(EXE), '.'], 120)
    if source_hashes() != before:
        raise RuntimeError('source changed during build; rerun with a stable working tree')
    return {'go': version, 'git_commit': git('rev-parse', 'HEAD'),
            'git_dirty': None if dirty is None else bool(dirty),
            'source_sha256': before, 'binary_sha256': hashlib.sha256(EXE.read_bytes()).hexdigest(),
            'build_command': ['go', 'build', '-o', EXE.name, '.']}


def experiment(count, scenario, entries, seed, folder, timeout, batch_size=128, round_number=1):
    c = Cluster(count, folder, timeout, batch_size)
    row = {'nodes': count, 'scenario': scenario, 'requested_commands': entries, 'seed': seed,
           'result': 'FAIL', 'elapsed_seconds': None, 'error': None, 'batch_size': batch_size, 'round': round_number}
    begin = time.perf_counter()
    origin, events = begin, []
    def observe(event, **details):
        events.append({'event': event, 'offset_seconds': time.perf_counter() - origin, **details})
    try:
        check_cancelled()
        if scenario == 'divergence':
            c.run('-prepare-divergence', '-demo', entries, '-seed', seed,
                  '-data-dir', str(folder / 'data'))
        start_ids = range(1, count if scenario == 'catchup' else count + 1)
        begin = origin = time.perf_counter()
        for node_id in start_ids:
            c.start(node_id)
        observe('processes_started')
        row['launch_seconds'] = time.perf_counter() - begin
        leader, _, _ = c.wait()
        observe('leader_observed')
        row['initial_leader'] = leader['id']
        row['initial_local_election_ms'] = leader['election_ms']
        row['initial_election_observed_seconds'] = time.perf_counter() - begin
        if scenario == 'election':
            row['elapsed_seconds'] = time.perf_counter() - begin
            row['local_election_ms'] = leader['election_ms']
            row['election_observed_seconds'] = row['elapsed_seconds']
            leader, states, query_seconds = c.wait(logs=True)
        elif scenario == 'replication':
            begin = time.perf_counter()
            reply = c.generate(entries, seed)
            observe('commands_committed')
            row['elapsed_seconds'] = time.perf_counter() - begin
            leader, states, query_seconds = c.wait(logs=True, target=reply['last_index'], commands=entries)
            row['all_applied_seconds'] = time.perf_counter() - begin
        elif scenario == 'failover':
            reply = c.generate(entries, seed)
            observe('commands_committed')
            leader, initial, _ = c.wait(logs=True, target=reply['last_index'], commands=entries)
            checkpoint = save_checkpoint(c.folder, initial[0])
            role_by_id = {state['id']: {'role': state['state'], 'term': state['term']} for state in initial}
            rng = random.Random(seed)
            killed = [leader['id']]
            max_faults = (count - 1) // 2
            killed += rng.sample([i for i in c.processes if i != leader['id']], rng.randrange(max_faults))
            row['failure_plan'] = [{'id': node_id, **role_by_id[node_id]} for node_id in killed]
            row['killed_ids'] = list(killed)
            row['stop_records'] = []
            old_term = leader['term']
            begin = time.perf_counter()
            observe('fault_started')
            for node_id in killed:
                record = {'id': node_id, **role_by_id[node_id],
                          'start_offset_seconds': time.perf_counter() - origin,
                          'started_at_utc': datetime.now(timezone.utc).isoformat()}
                row['stop_records'].append(record)
                observe('stop_started', id=node_id, role=record['role'], term=record['term'])
                try:
                    c.stop(node_id)
                finally:
                    record.update(end_offset_seconds=time.perf_counter() - origin,
                                  ended_at_utc=datetime.now(timezone.utc).isoformat(),
                                  remaining_nodes=len(c.processes),
                                  quorum=count // 2 + 1,
                                  majority_available=(len(c.processes) >= count // 2 + 1))
                    observe('stop_finished', id=node_id, role=record['role'], term=record['term'],
                            remaining_nodes=record['remaining_nodes'], quorum=record['quorum'],
                            majority_available=record['majority_available'])
            row['kill_seconds'] = time.perf_counter() - begin
            replacement, _, _ = c.wait()
            observe('replacement_observed')
            row['leader_observed_seconds'] = time.perf_counter() - begin
            row['election_observed_seconds'] = row['leader_observed_seconds']
            row['fault_local_election_ms'] = replacement['election_ms']
            if replacement['term'] <= old_term:
                raise AssertionError('leader term did not advance')
            reply = c.generate(1, seed + 1)
            observe('replacement_write_committed')
            row['elapsed_seconds'] = time.perf_counter() - begin
            row['service_restored_seconds'] = row['elapsed_seconds']
            row['local_election_ms'] = replacement['election_ms']
            leader, states, query_seconds = c.wait(logs=True, target=checkpoint['index'],
                                                    commands=entries + 1, checkpoint=checkpoint)
            # Restart original disks and verify catch-up without changing membership.
            for node_id in killed:
                c.start(node_id)
            observe('nodes_restarted')
            leader, states, query_seconds = c.wait(logs=True, target=checkpoint['index'],
                                                    commands=entries + 1, checkpoint=checkpoint)
            row['restarted_nodes_caught_up'] = True
        elif scenario == 'catchup':
            reply = c.generate(entries, seed)
            observe('commands_committed')
            _, initial, _ = c.wait(logs=True, target=reply['last_index'], commands=entries)
            checkpoint = save_checkpoint(c.folder, initial[0])
            begin = time.perf_counter()
            data_dir = folder / 'data'
            node_state = data_dir / f'node-{count}-state.json'
            node_wal = data_dir / f'node-{count}-log.wal'
            if node_state.exists() or node_wal.exists():
                raise RuntimeError(f'catch-up node {count} is not empty: {node_state if node_state.exists() else node_wal}')
            row.update(catchup_before_index=0,
                       catchup_before_hash=hashlib.sha256(b'').hexdigest(), catchup_before_x=0)
            row['catchup_start_offset_seconds'] = time.perf_counter() - origin
            row['catchup_started_at_utc'] = datetime.now(timezone.utc).isoformat()
            c.start(count)
            observe('empty_node_started')
            leader, states, query_seconds = c.wait(logs=True, target=checkpoint['index'],
                                                    commands=entries, checkpoint=checkpoint)
            row['elapsed_seconds'] = time.perf_counter() - begin
            row['target_index'] = reply['last_index']
            row['catchup_end_offset_seconds'] = time.perf_counter() - origin
            row['catchup_ended_at_utc'] = datetime.now(timezone.utc).isoformat()
            caught_up = next(s for s in states if s['id'] == count)
            row['caught_up_entries'] = caught_up['last_log_index']
            row['catchup_after_index'] = caught_up['last_log_index']
            row['catchup_after_hash'] = caught_up['log_hash']
            row['catchup_after_x'] = caught_up['x']
            row['catchup_after_committed_hash'] = caught_up['committed_hash']
            row['catchup_history_checkpoint_preserved'] = all(
                s.get('target_available') and s.get('target_index') == checkpoint['index'] and
                s.get('target_hash') == checkpoint['hash'] and s.get('target_x') == checkpoint['x']
                for s in states)
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
        observe('converged')
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
        if row['result'] == 'PASS':
            try:
                reference = verify_files(folder / 'data', states)
                (folder / 'arithmetic-reference.json').write_text(json.dumps(reference, indent=2), encoding='utf-8')
                row['independent_reference'] = 'PASS'
            except Exception as exc:
                row['result'], row['error'] = 'FAIL', f'independent reference: {exc}'
        row['query_timeouts'] = c.query_timeouts
        (folder / 'events.json').write_text(json.dumps(events, indent=2), encoding='utf-8')
        (folder / 'result.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
    return row


def batch_order_for_round(batch_sizes, round_index):
    offset = round_index % len(batch_sizes)
    ordered = list(batch_sizes[offset:]) + list(batch_sizes[:offset])
    return list(reversed(ordered)) if round_index % 2 else ordered


def summarize(rows):
    groups = []
    for key in sorted({(r['nodes'], r['scenario'], r.get('batch_size', 128)) for r in rows}):
        selected = [r for r in rows if (r['nodes'], r['scenario'], r.get('batch_size', 128)) == key]
        values = [r['elapsed_seconds'] for r in selected if r['result'] == 'PASS']
        local = [r['local_election_ms'] for r in selected if r['result'] == 'PASS' and 'local_election_ms' in r]
        startup_sync = [r['startup_to_sync_seconds'] for r in selected
                        if r['result'] == 'PASS' and 'startup_to_sync_seconds' in r]
        groups.append({'nodes': key[0], 'scenario': key[1], 'attempts': len(selected),
                       'passed': len(values), 'failed': sum(r['result'] == 'FAIL' for r in selected),
                       'interrupted': sum(r['result'] == 'INTERRUPTED' for r in selected),
                       'mean_seconds': statistics.mean(values) if values else None,
                       'median_seconds': statistics.median(values) if values else None,
                       'min_seconds': min(values) if values else None,
                       'max_seconds': max(values) if values else None,
                       'mean_local_election_ms': statistics.mean(local) if local else None,
                       'median_local_election_ms': statistics.median(local) if local else None,
                       'min_local_election_ms': min(local) if local else None,
                       'max_local_election_ms': max(local) if local else None,
                       'mean_startup_to_sync_seconds': statistics.mean(startup_sync) if startup_sync else None,
                       'median_startup_to_sync_seconds': statistics.median(startup_sync) if startup_sync else None,
                       'min_startup_to_sync_seconds': min(startup_sync) if startup_sync else None,
                       'max_startup_to_sync_seconds': max(startup_sync) if startup_sync else None})
        for metric in ('election_observed_seconds', 'initial_election_observed_seconds', 'initial_local_election_ms', 'service_restored_seconds', 'all_applied_seconds'):
            measured = [r[metric] for r in selected if r['result'] == 'PASS' and metric in r]
            for name, aggregate in [('mean', statistics.mean), ('median', statistics.median), ('min', min), ('max', max)]:
                groups[-1][name + '_' + metric] = aggregate(measured) if measured else None
        if any('batch_size' in r for r in rows):
            groups[-1]['batch_size'] = key[2]
    return groups


def main():
    global CANCEL_FILE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nodes', nargs='+', type=int, default=[10, 20, 50, 100])
    parser.add_argument('--batch-sizes', nargs='+', type=int, default=[128])
    parser.add_argument('--entries', type=int, default=2101)
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--scenarios', nargs='+', choices=['election', 'failover', 'catchup', 'divergence', 'replication'],
                        default=['election', 'failover', 'catchup', 'divergence'])
    parser.add_argument('--output', type=Path, default=ROOT / '.test-output' / f'benchmark-{time.time_ns()}')
    parser.add_argument('--cancel-file', type=Path, help='controller-owned cancellation marker; preserves partial results and cleans owned processes')
    args = parser.parse_args()
    CANCEL_FILE = args.cancel_file
    if min(args.nodes) < 3 or args.rounds < 1 or args.entries < 256 or not 1 <= args.timeout <= 600:
        parser.error('nodes >=3, rounds >=1, entries >=256, timeout 1..600 required')
    if any(not 1 <= b <= 4096 for b in args.batch_sizes) or len(set(args.batch_sizes)) != len(args.batch_sizes):
        parser.error('batch sizes must be unique integers in 1..4096')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = {'platform': platform.platform(), 'python': platform.python_version(),
                   'logical_cpus': os.cpu_count(), 'node_gomaxprocs': 1, 'timings_ms': {'election_min': 3000, 'election_jitter': 3000, 'heartbeat': 150, 'rpc_timeout': 1000}, 'arguments': vars(args).copy(),
                   'measurement': 'monotonic polling observation; per wait/generate timeout, not total scenario budget; two consistent snapshots 100 ms apart; includes polling overhead'}
    environment['batch_execution_order'] = [
        {'round': iteration + 1, 'batch_sizes': batch_order_for_round(args.batch_sizes, iteration)}
        for iteration in range(args.rounds)
    ]
    environment['arguments']['output'] = str(output)
    environment['arguments']['cancel_file'] = str(CANCEL_FILE) if CANCEL_FILE is not None else None
    (output / 'environment.json').write_text(json.dumps(environment, indent=2), encoding='utf-8')
    try:
        check_cancelled()
        environment.update(build_current(output))
    except BaseException as exc:
        status = 'CLEANUP_FAILED' if isinstance(exc, CleanupError) else 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'BUILD_FAILED'
        (output / 'run-status.json').write_text(json.dumps({'status': status, 'completed': 0, 'error': str(exc)}), encoding='utf-8')
        raise
    (output / 'environment.json').write_text(json.dumps(environment, indent=2), encoding='utf-8')
    rows = []
    cases = ((n, s, b, r) for n in args.nodes for s in args.scenarios for r in range(args.rounds)
             for b in batch_order_for_round(args.batch_sizes, r))
    for count, scenario, batch, iteration in cases:
        batch_part = f'-b{batch}' if len(args.batch_sizes) > 1 else ''
        folder = output / f'{scenario}-{count}{batch_part}-r{iteration+1}'
        row = experiment(count, scenario, args.entries, args.seed + iteration, folder, args.timeout, batch, iteration+1)
        row['round'] = iteration + 1
        rows.append(row)
        (output / 'results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
        (output / 'summary.json').write_text(json.dumps(summarize(rows), indent=2), encoding='utf-8')
        print(f"{scenario} n={count} batch={batch} round={iteration+1}: {row['result']} {row['elapsed_seconds']} {(row['error'] or '')[:250]}", flush=True)
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
        'planned': len(args.nodes) * len(args.scenarios) * len(args.batch_sizes) * args.rounds, 'completed': len(rows),
        'passed': sum(r['result'] == 'PASS' for r in rows), 'failed': sum(r['result'] == 'FAIL' for r in rows),
        'interrupted': sum(r['result'] == 'INTERRUPTED' for r in rows)}, indent=2), encoding='utf-8')
    print(f'Results: {output}', flush=True)
    return 0 if all(r['result'] == 'PASS' for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
