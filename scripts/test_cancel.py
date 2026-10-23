"""Controller cancellation preserves evidence and only cleans owned subprocesses."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark


class CancellationTests(unittest.TestCase):
    def test_failed_tree_cleanup_and_fallback_remain_cleanup_failure(self):
        process = Mock(returncode=None)
        with patch.object(benchmark, 'check_cancelled', side_effect=[None, KeyboardInterrupt]), \
             patch.object(benchmark.subprocess, 'Popen', return_value=process), \
             patch.object(benchmark.os, 'killpg', side_effect=OSError('tree cleanup failed'), create=True), \
             patch.object(benchmark.subprocess, 'run', side_effect=OSError('tree cleanup failed')):
            process.wait.side_effect = subprocess.TimeoutExpired('owned child', 5)
            with self.assertRaises(benchmark.CleanupError):
                benchmark.run_tool(['fake-go'], 10)

    @unittest.skipUnless(sys.platform == 'linux', 'process group assertion uses Linux /proc')
    def test_cancel_build_tree_preserves_unrelated_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pidfile, marker = root / 'child.pid', root / 'cancel'
            child = 'import time; time.sleep(10)'
            parent = ('import pathlib,subprocess,sys,time; '
                      f'p=subprocess.Popen([sys.executable,"-c",{child!r}]); '
                      f'pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(10)')
            sentinel = subprocess.Popen([sys.executable, '-c', child])
            def cancel_when_started():
                deadline = time.monotonic() + 5
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                marker.touch()
            cancel = threading.Thread(target=cancel_when_started)
            cancel.start()
            try:
                with patch.object(benchmark, 'CANCEL_FILE', marker):
                    with self.assertRaises(KeyboardInterrupt):
                        benchmark.run_tool([sys.executable, '-c', parent], 5)
                self.assertIsNone(sentinel.poll())
                pid = int(pidfile.read_text())
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try:
                        dead = Path(f'/proc/{pid}/stat').read_text().split(') ')[1].startswith('Z')
                    except FileNotFoundError:
                        dead = True
                    if dead:
                        break
                    time.sleep(.01)
                self.assertTrue(dead, 'owned compiler child survived cancellation')
            finally:
                cancel.join(timeout=6)
                sentinel.kill()
                sentinel.wait(timeout=5)

    def test_tool_timeout_is_bounded(self):
        with patch.object(benchmark, 'CANCEL_FILE', None):
            with self.assertRaises(subprocess.TimeoutExpired):
                benchmark.run_tool([sys.executable, '-c', 'import time; time.sleep(10)'], .1)

    def test_cancel_during_build_records_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker, started = root / 'cancel', root / 'started'
            fake = root / 'fake_go.py'
            fake.write_text('import pathlib,sys,time\n'
                            'if sys.argv[1] == "version": print("go version fake")\n'
                            'else:\n'
                            f' pathlib.Path({str(started)!r}).touch()\n'
                            ' time.sleep(2)\n'
                            ' pathlib.Path(sys.argv[3]).write_bytes(b"fake")\n')
            original_popen = subprocess.Popen
            owned_builds = []
            def popen(command, *args, **kwargs):
                if command[0] == 'go':
                    command = [sys.executable, str(fake), *command[1:]]
                process = original_popen(command, *args, **kwargs)
                if len(command) > 2 and command[1] == str(fake) and command[2] == 'build':
                    owned_builds.append(process)
                return process
            def cancel_when_started():
                deadline = time.monotonic() + 5
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                if started.exists():
                    marker_request_ns.append(time.monotonic_ns())
                    marker.write_text('cancel')
                    marker_written_ns.append(time.monotonic_ns())
            cancel = threading.Thread(target=cancel_when_started)
            args = ['benchmark.py', '--nodes', '3', '--rounds', '1', '--output', str(root / 'run'),
                    '--cancel-file', str(marker)]
            sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])
            interrupted_ns = None
            sentinel_survived = False
            runner_returncodes = None
            marker_request_ns = []
            marker_written_ns = []
            cancel.start()
            try:
                with patch.object(sys, 'argv', args), patch.object(benchmark.subprocess, 'Popen', side_effect=popen), \
                     patch.object(benchmark, 'CANCEL_FILE', None):
                    try:
                        benchmark.main()
                    except KeyboardInterrupt:
                        interrupted_ns = time.monotonic_ns()
                    else:
                        self.fail('benchmark.main did not raise KeyboardInterrupt')
                runner_returncodes = [process.returncode for process in owned_builds]
                sentinel_survived = sentinel.poll() is None
            finally:
                cancel.join(timeout=6)
                for process in owned_builds:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                if sentinel.poll() is None:
                    sentinel.kill()
                sentinel.wait(timeout=5)
            self.assertFalse(cancel.is_alive(), 'cancel synchronizer did not finish')
            self.assertTrue(started.exists(), 'build process never reached its synchronized start')
            self.assertTrue(marker.exists(), 'cancel synchronizer did not write the marker')
            self.assertEqual(len(marker_written_ns), 1, 'cancel marker write did not complete')
            self.assertEqual(len(marker_request_ns), 1, 'cancel request was not recorded')
            self.assertIsNotNone(interrupted_ns, 'KeyboardInterrupt was not observed')
            response = interrupted_ns - marker_request_ns[0]
            self.assertGreaterEqual(response, 0)
            print(f'build cancel request start-to-interrupt response: {response / 1e9:.3f}s')
            self.assertEqual(len(owned_builds), 1)
            self.assertIsNotNone(runner_returncodes, 'runner process state was not recorded')
            self.assertIsNotNone(runner_returncodes[0], 'runner did not exit and reap the owned build process')
            self.assertTrue(sentinel_survived, 'cancellation affected an unrelated sentinel process')
            self.assertFalse((root / 'run' / benchmark.EXE.name).exists(), 'incomplete binary was left as a build result')
            self.assertEqual(json.loads((root / 'run/run-status.json').read_text())['status'], 'INTERRUPTED')

    def test_cancelled_cli_is_killed_and_waited(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'cancel'
            marker.write_text('cancel')
            cluster = object.__new__(benchmark.Cluster)
            cluster.config, cluster.timeout = Path(directory) / 'nodes.json', 3
            process = Mock()
            process.poll.return_value = None
            with patch.object(benchmark, 'CANCEL_FILE', marker), \
                 patch.object(benchmark.subprocess, 'Popen', return_value=process):
                with self.assertRaises(KeyboardInterrupt):
                    cluster.run('-status-all')
            process.kill.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=5)
            process.communicate.assert_not_called()

    def test_normal_cli_is_not_killed_after_poll_timeout(self):
        cluster = object.__new__(benchmark.Cluster)
        cluster.config, cluster.timeout = Path('nodes.json'), 3
        process = Mock(returncode=0)
        process.poll.return_value = 0
        process.communicate.side_effect = [subprocess.TimeoutExpired('cli', .2), ('{"ok": true}', '')]
        with patch.object(benchmark, 'CANCEL_FILE', None), \
             patch.object(benchmark.subprocess, 'Popen', return_value=process):
            self.assertEqual(cluster.run('-verify'), {'ok': True})
        process.kill.assert_not_called()
        process.wait.assert_called_once_with(timeout=5)

    def test_cancel_before_build_records_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'cancel'
            marker.write_text('cancel')
            output = Path(directory) / 'run'
            args = ['benchmark.py', '--nodes', '3', '--entries', '256', '--rounds', '1',
                    '--output', str(output), '--cancel-file', str(marker)]
            with patch.object(sys, 'argv', args), patch.object(benchmark, 'CANCEL_FILE', None), \
                 patch.object(benchmark, 'build_current') as build:
                with self.assertRaises(KeyboardInterrupt):
                    benchmark.main()
            build.assert_not_called()
            status = json.loads((output / 'run-status.json').read_text())
            self.assertEqual(status['status'], 'INTERRUPTED')
            self.assertEqual(status['completed'], 0)


if __name__ == '__main__':
    unittest.main()
