"""Regression tests for smoke-test process cleanup without real subprocesses."""
import json
import io
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_test import _cleanup_processes, _finalize_result, _stop_process
import smoke_test


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

    def test_cleanup_failure_changes_final_result_to_fail(self):
        failed = Mock()
        failed.poll.return_value = None
        failed.kill.side_effect = OSError("permanent kill failure")
        exited = Mock()
        exited.poll.return_value = None
        output = Mock()
        sock = Mock()
        processes = {1: failed, 2: exited}
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            result = {"result": "PASS"}
            with self.assertRaises(RuntimeError):
                _finalize_result(folder, result, processes, [output], [sock])
            saved = json.loads((folder / "result.json").read_text())
            self.assertEqual(saved["result"], "FAIL")
            self.assertIn("cleanup_error", saved)
            exited.kill.assert_called_once_with()
            output.close.assert_called_once_with()
            sock.close.assert_called_once_with()

    def test_scenario_publishes_pass_only_after_cleanup(self):
        for cleanup_error in (None, RuntimeError("injected cleanup failure")):
            with self.subTest(cleanup_error=cleanup_error), tempfile.TemporaryDirectory() as tmp:
                statuses = [
                    (1, "Leader", 1, 1), (2, "Follower", 1, 1), (3, "Follower", 1, 1),
                    (1, "Leader", 1, 1), (2, "Follower", 1, 1), (3, "Follower", 1, 1),
                    (2, "Leader", 2, 2), (3, "Follower", 2, 2),
                    (2, "Leader", 2, 2), (3, "Follower", 2, 2), (1, "Follower", 2, 2),
                    (1, "Follower", 2, 2), (1, "Candidate", 3, -1),
                ]

                def query(args, **kwargs):
                    node, role, term, leader = statuses.pop(0)
                    self.assertEqual(int(args[args.index("-id") + 1]), node)
                    return Mock(returncode=0, stdout=json.dumps(
                        dict(id=node, state=role, term=term, leader_id=leader)))

                process = Mock()
                process.poll.return_value = None
                output = io.StringIO()
                with patch.object(smoke_test, "ROOT", Path(tmp)), \
                     patch.object(smoke_test.subprocess, "Popen", return_value=process), \
                     patch.object(smoke_test.subprocess, "run", side_effect=query), \
                     patch.object(smoke_test.time, "sleep"), \
                     patch.object(smoke_test, "_cleanup_processes", side_effect=cleanup_error) as cleanup, \
                     patch("sys.stdout", output):
                    if cleanup_error:
                        with self.assertRaisesRegex(RuntimeError, "injected cleanup failure"):
                            smoke_test.scenario(3)
                    else:
                        smoke_test.scenario(3)
                result_path, = Path(tmp).glob(".test-output/*/result.json")
                result = json.loads(result_path.read_text())
                self.assertEqual(result["result"], "FAIL" if cleanup_error else "PASS")
                self.assertEqual("PASS restart" in output.getvalue(), cleanup_error is None)
                cleanup.assert_called_once()
                self.assertFalse(statuses)

    def test_scenario_records_failure_or_interruption(self):
        for error, expected in ((RuntimeError("startup failed"), "FAIL"),
                                (KeyboardInterrupt(), "INTERRUPTED")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                with patch.object(smoke_test, "ROOT", Path(tmp)), \
                     patch.object(smoke_test.socket, "socket", side_effect=error):
                    with self.assertRaises(type(error)):
                        smoke_test.scenario(3)
                result_path, = Path(tmp).glob(".test-output/*/result.json")
                result = json.loads(result_path.read_text())
                self.assertEqual(result["result"], expected)
                self.assertTrue(result["error"])


if __name__ == "__main__":
    unittest.main()
