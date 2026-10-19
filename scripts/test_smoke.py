"""Regression tests for smoke-test process cleanup without real subprocesses."""
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_test import _cleanup_processes, _stop_process


class SmokeCleanupTests(unittest.TestCase):
    def test_kill_failure_keeps_process_registered(self):
        process = Mock()
        process.kill.side_effect = OSError("kill failed")
        processes = {1: process}
        with self.assertRaises(OSError):
            _stop_process(processes, 1)
        self.assertIs(processes[1], process)

    def test_wait_timeout_keeps_process_registered(self):
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired("node", 5)
        processes = {1: process}
        with self.assertRaises(subprocess.TimeoutExpired):
            _stop_process(processes, 1)
        self.assertIs(processes[1], process)

    def test_cleanup_continues_after_one_process_fails(self):
        failed = Mock()
        failed.poll.return_value = None
        failed.kill.side_effect = OSError("permanent kill failure")
        exited = Mock()
        exited.poll.return_value = None
        processes = {1: failed, 2: exited}
        with self.assertRaises(RuntimeError):
            _cleanup_processes(processes)
        failed.kill.assert_called_once_with()
        failed.wait.assert_called_once_with(timeout=5)
        exited.kill.assert_called_once_with()
        exited.wait.assert_called_once_with(timeout=5)


if __name__ == "__main__":
    unittest.main()
