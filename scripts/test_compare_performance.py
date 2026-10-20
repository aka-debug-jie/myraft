import copy
import unittest
from compare_performance import compare, render


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.env = {'platform':'test-platform', 'go':'test-go', 'gomaxprocs':1, 'measurement':'test',
                    'parameters':{'samples':200,'warmup':20,'batch':128,'no_collector':False,'rounds':3}}
        self.row = {'nodes':11,'browsers':0,'batch':128,'collector':True,'result':'PASS',
                    'attempts':200,'successes':200,'failures':0,'p50_seconds':.1,'p95_seconds':.2}

    def test_failure_interruption_and_missing_group_are_not_pass(self):
        rows = compare((self.env,[self.row, self.row|{'result':'FAIL'}, self.row|{'result':'INTERRUPTED'}]),
                       (self.env,[]))
        a, b = rows[0]['baseline'], rows[0]['candidate']
        self.assertEqual((a['passed_rounds'], a['failed_rounds'], a['interrupted_rounds']), (1,1,1))
        self.assertEqual(b['passed_rounds'], 0)
        self.assertIsNone(b['p95_seconds'])
        self.assertIn('未记录', render(rows)[0])

    def test_environment_and_missing_metadata_reject_comparison(self):
        for key in ('platform','go','measurement'):
            env = copy.deepcopy(self.env); env[key] = 'different'
            with self.assertRaises(ValueError): compare((self.env,[]),(env,[]))
            del env[key]
            with self.assertRaises(ValueError): compare((self.env,[]),(env,[]))

    def test_median_of_rounds_not_pooled_or_zero(self):
        trials = [self.row|{'p95_seconds':n} for n in [.2,.8,.4]]
        rows = compare((self.env,trials),(self.env,trials))
        self.assertEqual(rows[0]['baseline']['p95_seconds'], .4)
        self.assertEqual(rows[0]['baseline']['p95_range_seconds'], [.2,.8])
        self.assertEqual(rows[0]['baseline']['successful_requests'],600)


if __name__ == '__main__':
    unittest.main()
