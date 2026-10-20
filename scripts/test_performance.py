import os
import unittest

from performance import process_resources, summarize


class PerformanceTests(unittest.TestCase):
    def test_percentiles_exclude_warmup_and_expose_failure(self):
        rows = [{'seconds': n, 'warmup': False, 'committed': True} for n in range(1, 201)]
        rows += [{'seconds': 9999, 'warmup': True, 'committed': True},
                 {'seconds': 9999, 'warmup': False, 'committed': False, 'error': 'outcome unknown'}]
        got = summarize(rows)
        self.assertEqual(got['attempts'], 201)
        self.assertEqual(got['failures'], 1)
        self.assertEqual(got['p50_seconds'], 100.5)
        self.assertEqual(got['p95_seconds'], 190)
        self.assertEqual(got['percentile_population'], 'successful_requests_only')

    def test_no_success_does_not_invent_latency(self):
        got = summarize([{'seconds': 1, 'warmup': False, 'committed': False}])
        self.assertIsNone(got['p95_seconds'])
        self.assertIsNone(got['p50_seconds'])
        self.assertEqual(got['successes'], 0)

    @unittest.skipUnless(os.name == 'nt' or os.path.isdir('/proc'), 'OS sampling not available')
    def test_own_process_resources(self):
        result = process_resources(os.getpid())
        self.assertGreater(result['rss_bytes'], 0)
        self.assertGreaterEqual(result['cpu_seconds'], 0)
        self.assertGreater(result['handles'], 0)


if __name__ == '__main__':
    unittest.main()
