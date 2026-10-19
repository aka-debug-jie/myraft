"""Regression tests for experiment cleanup, without starting any node processes."""
import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark import Cluster, consistent, summarize


class FakeProcess:
    def __init__(self):
        self.kill_calls = self.wait_calls = 0
        self.exited = False

    def kill(self):
        self.kill_calls += 1

    def poll(self):
        return 0 if self.exited else None

    def wait(self, timeout):
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired('owned node', timeout)
        self.exited = True
        return 0


class BenchmarkTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
