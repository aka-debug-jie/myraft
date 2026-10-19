"""Regression tests for reports generated from their input evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('render_report.py')


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


class ReportInputTests(unittest.TestCase):
    def render(self, root, environment, rows, summary, validation):
        benchmark = root / 'benchmark-input'
        benchmark.mkdir()
        write_json(benchmark / 'environment.json', environment)
        write_json(benchmark / 'results.json', rows)
        write_json(benchmark / 'summary.json', summary)
        validation_path = root / 'validation.json'
        write_json(validation_path, validation)
        output = root / 'report.md'
        subprocess.run([sys.executable, str(SCRIPT), '--benchmark', str(benchmark),
                        '--validation', str(validation_path), '--output', str(output)],
                       check=True, capture_output=True, text=True)
        return output.read_text(encoding='utf-8'), benchmark

    def test_linux_two_rounds_counts_results_and_ignores_stale_summary(self):
        rows = [
            {'nodes': 3, 'scenario': 'election', 'result': 'PASS', 'elapsed_seconds': 1.0},
            {'nodes': 3, 'scenario': 'election', 'result': 'FAIL', 'elapsed_seconds': None},
            {'nodes': 3, 'scenario': 'catchup', 'result': 'PASS', 'elapsed_seconds': 2.0},
        ]
        env = {'platform': 'Ubuntu 24.04', 'python': '3.12.4',
               'arguments': {'nodes': [3], 'scenarios': ['election', 'catchup'], 'rounds': 2},
               'timings_ms': {'heartbeat': 75},
               'measurement': 'monotonic polling observation'}
        stale = [{'nodes': 100, 'scenario': 'election', 'attempts': 999, 'passed': 999,
                  'failed': 0, 'mean_seconds': 900.0}]
        with tempfile.TemporaryDirectory() as name:
            report, benchmark = self.render(Path(name), env, rows, stale, {'checks': {}})
        self.assertIn('Ubuntu 24.04', report)
        self.assertNotIn('Windows 11', report)
        self.assertNotIn('Go 1.26.3', report)
        self.assertIn('3 节点', report)
        self.assertIn('2 轮', report)
        self.assertIn('通过 2 轮', report)
        self.assertIn('失败 1 轮', report)
        self.assertIn('未执行 1 轮', report)
        self.assertIn('| 3 | 初次选举（外部观测） | 1/2 | 1.000', report)
        self.assertNotIn('| 100 |', report)
        self.assertIn('输入数据目录为 `benchmark-input`', report)
        self.assertNotIn(str(benchmark.parent), report)

    def test_missing_environment_and_validation_fields_are_reported(self):
        rows = [{'nodes': 5, 'scenario': 'failover', 'result': 'INTERRUPTED',
                 'elapsed_seconds': None}]
        with tempfile.TemporaryDirectory() as name:
            report, _ = self.render(Path(name), {}, rows,
                                    [{'nodes': 5, 'scenario': 'failover', 'attempts': 0,
                                      'passed': 0, 'failed': 0, 'mean_seconds': 123}],
                                    {})
        self.assertIn('平台：未记录', report)
        self.assertIn('Python：未记录', report)
        self.assertIn('Go：未记录', report)
        self.assertIn('计划轮数 未记录', report)
        self.assertIn('中断 1 轮', report)
        self.assertIn('| 未记录 | 未记录 |', report)
        self.assertIn('| 5 | 故障至新写入提交 | 0/1 | 未测得', report)


if __name__ == '__main__':
    unittest.main()
