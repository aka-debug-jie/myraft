"""Regression tests for experiment cleanup, without starting any node processes."""
import subprocess
import contextlib
import io
import json
import tempfile
from unittest import mock
import benchmark
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark import Cluster, consistent, summarize


class FakeProcess:
    def __init__(self, *, kill_error=False, wait_success=False, wait_failure=False, wait_hook=None):
        self.kill_calls = self.wait_calls = 0
        self.exited = False
        self.kill_error = kill_error
        self.wait_success = wait_success
        self.wait_failure = wait_failure
        self.wait_hook = wait_hook

    def kill(self):
        self.kill_calls += 1
        if self.kill_error:
            raise OSError('injected kill failure')

    def poll(self):
        return 0 if self.exited else None

    def wait(self, timeout):
        self.wait_calls += 1
        if self.wait_hook:
            self.wait_hook()
        if self.wait_success:
            self.exited = True
            return 0
        if self.wait_failure:
            raise subprocess.TimeoutExpired('owned node', timeout)
        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired('owned node', timeout)
        self.exited = True
        return 0


class BenchmarkTests(unittest.TestCase):
    def _states(self):
        leader = dict(id=1, state='Leader', term=2, leader_id=1, election_ms=150,
                      target_index=4, target_hash='checkpoint', target_x=9, target_available=True)
        follower = dict(leader, id=2, state='Follower')
        other = dict(leader, id=3, state='Follower')
        return [leader, follower, other]

    def test_failed_failover_retains_planned_and_executed_stops(self):
        states = self._states()
        class FakeCluster:
            def __init__(self, count, folder, timeout, batch_size):
                self.folder, self.timeout = folder, timeout
                self.folder.mkdir(parents=True)
                self.processes = {1: object(), 2: object(), 3: object()}
                self.query_timeouts, self.wait_calls = 0, 0
            def wait(self, **kwargs):
                self.wait_calls += 1
                if self.wait_calls == 1:
                    return states[0], states, 0.01
                if self.wait_calls == 2:
                    return states[0], states, 0.01
                raise RuntimeError('replacement never observed')
            def generate(self, count, seed):
                return {'accepted': True, 'committed': True, 'commands': count, 'last_index': 4}
            def start(self, node_id):
                pass
            def stop(self, node_id):
                self.processes.pop(node_id)
            def close(self):
                self.processes.clear()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(benchmark, 'Cluster', FakeCluster):
            row = benchmark.experiment(3, 'failover', 256, 7, Path(directory) / 'trial', 5)
        self.assertEqual(row['result'], 'FAIL')
        self.assertEqual(row.get('killed_ids'), [1], row)
        self.assertEqual(row['failure_plan'], [{'id': 1, 'role': 'Leader', 'term': 2}])
        self.assertEqual(row['stop_records'][0]['remaining_nodes'], 2)
        self.assertEqual(row['stop_records'][0]['quorum'], 2)
        self.assertTrue(row['stop_records'][0]['majority_available'])

    def test_catchup_rejects_existing_node_disk_before_start(self):
        states = self._states()
        class FakeCluster:
            started_ids = []
            def __init__(self, count, folder, timeout, batch_size):
                self.folder, self.timeout = folder, timeout
                self.processes, self.query_timeouts = {1: object(), 2: object()}, 0
            def wait(self, **kwargs):
                return states[0], states, 0.01
            def generate(self, count, seed):
                return {'accepted': True, 'committed': True, 'commands': count, 'last_index': 4}
            def start(self, node_id):
                self.started_ids.append(node_id)
            def close(self):
                self.processes.clear()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(benchmark, 'Cluster', FakeCluster):
            folder = Path(directory) / 'trial'
            (folder / 'data').mkdir(parents=True)
            (folder / 'data' / 'node-3-state.json').write_text('{}')
            row = benchmark.experiment(3, 'catchup', 256, 7, folder, 5)
        self.assertEqual(row['result'], 'FAIL')
        self.assertIn('not empty', row['error'])
        self.assertEqual(FakeCluster.started_ids, [1, 2])

    def test_failed_stop_keeps_handle_for_final_cleanup(self):
        node = FakeProcess()
        c = Cluster.__new__(Cluster)
        c.processes = {7: node}
        c.outputs = []
        with self.assertRaises(subprocess.TimeoutExpired):
            c.stop(7)
        self.assertIs(c.processes[7], node)
        c.close()
        self.assertTrue(node.exited)
        self.assertEqual(node.kill_calls, 2)
        self.assertEqual(node.wait_calls, 2)
        self.assertEqual(c.processes, {})

    def test_close_kills_every_owned_process_before_first_wait(self):
        processes = {node_id: FakeProcess() for node_id in (1, 2, 3)}
        nodes = tuple(processes.values())
        observed_kills = []
        processes[1].wait_hook = lambda: observed_kills.append(
            tuple(process.kill_calls for process in nodes)
        )
        c = Cluster.__new__(Cluster)
        c.processes = processes
        c.outputs = []

        c.close()

        self.assertTrue(observed_kills)
        self.assertEqual(observed_kills[0], (1, 1, 1))

    def test_close_still_waits_all_handles_after_kill_failure(self):
        processes = {
            1: FakeProcess(kill_error=True, wait_failure=True),
            2: FakeProcess(wait_success=True),
        }
        first, second = processes.values()
        c = Cluster.__new__(Cluster)
        c.processes = processes
        c.outputs = []

        with self.assertRaisesRegex(RuntimeError, 'process cleanup failed'):
            c.close()

        self.assertGreater(first.wait_calls, 0)
        self.assertGreater(second.kill_calls, 0)
        self.assertGreater(second.wait_calls, 0)
        self.assertIs(c.processes[1], first)
        self.assertNotIn(2, c.processes)

    def test_failed_trials_do_not_enter_timing_mean(self):
        rows = [{'nodes': 10, 'scenario': 'election', 'result': 'PASS', 'elapsed_seconds': 2},
                {'nodes': 10, 'scenario': 'election', 'result': 'FAIL', 'elapsed_seconds': 100}]
        result = summarize(rows)[0]
        self.assertEqual((result['attempts'], result['passed'], result['failed']), (2, 1, 1))
        self.assertEqual(result['mean_seconds'], 2)

    def test_equal_x_does_not_hide_log_difference(self):
        a = dict(id=1, state='Leader', term=1, leader_id=1, last_log_index=2, commit_index=2,
                 last_applied=2, log_hash='A', committed_hash='A', committed_commands=1,
                 applied_commands=1, x=0)
        b = dict(a, id=2, state='Follower', log_hash='B', committed_hash='B')
        self.assertFalse(consistent([a, b], logs=True, target=0, commands=1)[0])


    def test_equal_final_state_cannot_replace_saved_history(self):
        checkpoint = dict(index=2, hash='original-prefix', x=7)
        a = dict(id=1, state='Leader', term=3, leader_id=1, last_log_index=9,
                 commit_index=9, last_applied=9, log_hash='same-final',
                 committed_hash='same-final', committed_commands=7, applied_commands=7,
                 x=20, target_available=True, target_index=2,
                 target_hash='replaced-prefix', target_x=7)
        b = dict(a, id=2, state='Follower')
        self.assertTrue(consistent([a, b], True, 2, 7)[0])
        self.assertFalse(consistent([a, b], True, 2, 7, checkpoint=checkpoint)[0])
        a['target_hash'] = b['target_hash'] = checkpoint['hash']
        self.assertTrue(consistent([a, b], True, 2, 7, checkpoint=checkpoint)[0])
        b['target_x'] = 8
        self.assertFalse(consistent([a, b], True, 2, 7, checkpoint=checkpoint)[0])


    def test_last_round_interrupt_or_cleanup_failure_is_not_complete(self):
        for outcome, extra, expected in [('INTERRUPTED', {}, 'INTERRUPTED'),
                                          ('FAIL', {'cleanup_failed': True}, 'CLEANUP_FAILED')]:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'run'
                row = dict(nodes=3, scenario='election', result=outcome,
                           elapsed_seconds=None, error='injected', **extra)
                argv = ['benchmark.py', '--nodes', '3', '--rounds', '1',
                        '--scenarios', 'election', '--output', str(output)]
                with mock.patch.object(sys, 'argv', argv), mock.patch.object(benchmark, 'build_current', return_value={}), \
                     mock.patch.object(benchmark, 'experiment', return_value=row), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(benchmark.main(), 1)
                status = json.loads((output / 'run-status.json').read_text())
                self.assertEqual(status['status'], expected)


    def test_batch_sizes_are_not_pooled(self):
        rows = [dict(nodes=11, scenario='replication', batch_size=b, result='PASS', elapsed_seconds=v)
                for b, v in [(64, 1.0), (64, 3.0), (128, 8.0), (256, 4.0)]]
        stats = summarize(rows)
        self.assertEqual([s['batch_size'] for s in stats], [64, 128, 256])
        self.assertEqual([s['mean_seconds'] for s in stats], [2.0, 8.0, 4.0])

    def test_summary_all_applied_uses_only_successful_rows_with_measurements(self):
        rows = [dict(nodes=3, scenario='replication', result='PASS', elapsed_seconds=1,
                     all_applied_seconds=3),
                dict(nodes=3, scenario='replication', result='PASS', elapsed_seconds=2,
                     all_applied_seconds=5),
                dict(nodes=3, scenario='replication', result='PASS', elapsed_seconds=4),
                dict(nodes=3, scenario='replication', result='FAIL', elapsed_seconds=6,
                     all_applied_seconds=100)]
        result = summarize(rows)[0]
        self.assertEqual((result['mean_all_applied_seconds'], result['median_all_applied_seconds'],
                          result['min_all_applied_seconds'], result['max_all_applied_seconds']),
                         (4, 4, 3, 5))

    def test_batch_order_rotates_and_reverses_by_round(self):
        batches = [64, 128, 256]
        self.assertEqual(benchmark.batch_order_for_round(batches, 0), [64, 128, 256])
        self.assertEqual(benchmark.batch_order_for_round(batches, 1), [64, 256, 128])
        self.assertEqual(benchmark.batch_order_for_round(batches, 2), [256, 64, 128])

    def test_main_runs_rounds_before_batches_and_records_batch_order(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            calls = []
            def fake_experiment(count, scenario, entries, seed, folder, timeout, batch, round_number):
                calls.append((batch, seed, round_number, folder.name))
                return dict(nodes=count, scenario=scenario, batch_size=batch, round=round_number,
                            result='PASS', elapsed_seconds=1, error=None)
            argv = ['benchmark.py', '--nodes', '3', '--rounds', '3', '--entries', '256',
                    '--seed', '40', '--scenarios', 'election', '--batch-sizes', '64', '128', '256',
                    '--output', str(output)]
            with mock.patch.object(sys, 'argv', argv), mock.patch.object(benchmark, 'build_current', return_value={}), \
                 mock.patch.object(benchmark, 'experiment', side_effect=fake_experiment), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(benchmark.main(), 0)
            self.assertEqual(calls, [
                (64, 40, 1, 'election-3-b64-r1'), (128, 40, 1, 'election-3-b128-r1'), (256, 40, 1, 'election-3-b256-r1'),
                (64, 41, 2, 'election-3-b64-r2'), (256, 41, 2, 'election-3-b256-r2'), (128, 41, 2, 'election-3-b128-r2'),
                (256, 42, 3, 'election-3-b256-r3'), (64, 42, 3, 'election-3-b64-r3'), (128, 42, 3, 'election-3-b128-r3'),
            ])
            environment = json.loads((output / 'environment.json').read_text())
            self.assertEqual(environment['batch_execution_order'], [
                {'round': 1, 'batch_sizes': [64, 128, 256]},
                {'round': 2, 'batch_sizes': [64, 256, 128]},
                {'round': 3, 'batch_sizes': [256, 64, 128]},
            ])

    def test_summary_separates_election_and_startup_sync_timings(self):
        rows = [dict(nodes=3, scenario='catchup', result='PASS', elapsed_seconds=4,
                     local_election_ms=120, startup_to_sync_seconds=8),
                dict(nodes=3, scenario='catchup', result='PASS', elapsed_seconds=6,
                     local_election_ms=180, startup_to_sync_seconds=10)]
        result = summarize(rows)[0]
        self.assertEqual((result['median_local_election_ms'], result['min_local_election_ms'],
                          result['max_local_election_ms']), (150, 120, 180))
        self.assertEqual((result['median_startup_to_sync_seconds'], result['min_startup_to_sync_seconds'],
                          result['max_startup_to_sync_seconds']), (9, 8, 10))


if __name__ == '__main__':
    unittest.main()
