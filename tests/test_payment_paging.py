"""Regression tests for complete, bounded, lossless Lithos payment pagination."""
import os
import runpy
import unittest
from unittest.mock import patch


class PaymentPagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cls.ns = runpy.run_path(os.path.join(root, 'lithos_dashboard'))
        cls.api_global = cls.ns['fetch_payment_ledger'].__globals__

    def setUp(self):
        # Store on the instance; module functions assigned to a class bind 'self'.
        self.fetch = self.ns['fetch_payment_ledger']
        self.calc = self.ns['calculate_monthly_income']

    @staticmethod
    def rows(count):
        return [dict(outputId=f'out-{i}', transactionId=f'tx-{i}',
                     rewardNanoErg='100000000', surplusNanoErg='0', rewardLit='1000000000')
                for i in range(count)]

    def fake_api(self, data, calls, growing=False, hard_bytes=False, duplicate=False, shrink=False):
        def fetch(base, path, params=None, timeout=4, **kw):
            self.assertEqual(base, 'http://localhost:9000')
            self.assertEqual(path, '/stats/mining/payments')
            self.assertEqual(params['sort'], 'paid')
            self.assertEqual(params['order'], 'asc')
            off, lim = params['offset'], params['limit']
            calls.append((off, lim))
            if hard_bytes and lim > 137:
                raise ValueError('API response exceeds 2097152 bytes (/stats/mining/payments)')
            total = len(data) + (10 if growing and off else 0)
            if shrink and off:
                total = 1
            rows = data[off:off+lim]
            if duplicate and off:
                rows = [data[0]] + rows[1:]
            return {'status':'ready', 'offset':off, 'total':total, 'sort':'paid', 'order':'asc',
                    'payments':rows, 'claims':[{'phase':'holding','rollupNft':'open1'}],
                    'bounties':[{'transactionId':'bounty-1'}],
                    'source':{'height':12345}}
        return fetch

    def test_three_pages_without_claim_or_bounty_duplication(self):
        data, calls = self.rows(1003), []
        with patch.dict(self.api_global, {'api_get':self.fake_api(data,calls)}):
            ledger = self.fetch('http://localhost:9000')
        self.assertEqual(calls, [(0,500),(500,500),(1000,3)])
        self.assertEqual(ledger['total'], 1003)
        self.assertEqual(len(ledger['payments']), 1003)
        self.assertEqual(len(ledger['claims']), 1)
        self.assertEqual(len(ledger['bounties']), 1)
        self.assertEqual(ledger['payments'][-1]['outputId'], 'out-1002')
        self.assertEqual(ledger['offset'], 0)

    def test_income_uses_all_payments_over_500(self):
        data, calls = self.rows(1003), []
        with patch.dict(self.api_global, {'api_get':self.fake_api(data,calls)}):
            ledger = self.fetch('http://localhost:9000')
        model=self.calc({'rollup.submission.localCount':'1003','local.payout.outputs':'1003',
                         'local.payout.rewardNanoErg':'100300000000',
                         'local.payout.surplusNanoErg':'0',
                         'local.payout.rewardLit':'1003000000000'},ledger,30)
        self.assertNotIn('error', model)
        self.assertEqual(model['paidSample'],1003)
        self.assertEqual(str(model['baselineErgMonth']), '100.3')
        self.assertEqual(str(model['litMonth']), '1003')

    def test_automatically_reduces_page_size_if_response_exceeds_guard(self):
        calls=[]
        data=self.rows(303)
        with patch.dict(self.api_global, {'api_get':self.fake_api(data,calls,hard_bytes=True)}):
            ledger=self.fetch('http://localhost:9000')
        self.assertEqual(len(ledger['payments']),303)
        self.assertTrue(any(lim > 137 for _,lim in calls))
        self.assertTrue(any(lim <= 137 for _,lim in calls))

    def test_new_payouts_during_scan_do_not_shift_older_pages(self):
        data, calls=self.rows(520),[]
        with patch.dict(self.api_global, {'api_get':self.fake_api(data,calls,growing=True)}):
            ledger=self.fetch('http://localhost:9000')
        self.assertEqual(ledger['total'],520)
        self.assertEqual(len(ledger['payments']),520)

    def test_duplicate_outputs_are_rejected(self):
        data, calls=self.rows(501),[]
        with patch.dict(self.api_global, {'api_get':self.fake_api(data,calls,duplicate=True)}):
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                self.fetch('http://localhost:9000')

    def test_shrinking_total_is_rejected_not_silently_truncated(self):
        data, calls=self.rows(501),[]
        with patch.dict(self.api_global, {'api_get':self.fake_api(data,calls,shrink=True)}):
            with self.assertRaisesRegex(ValueError,'shrank'):
                self.fetch('http://localhost:9000')

    def test_empty_ledger(self):
        calls=[]
        with patch.dict(self.api_global, {'api_get':self.fake_api([],calls)}):
            ledger=self.fetch('http://localhost:9000')
        self.assertEqual(ledger['total'],0)
        self.assertEqual(ledger['payments'],[])
        self.assertEqual(calls,[(0,500)])

    def test_incomplete_page_not_accepted(self):
        data=self.rows(502)
        def broken(base,path,params=None,**kw):
            offset,limit=params['offset'],params['limit']
            return dict(status='ready',total=len(data),offset=offset,
                        payments=data[offset:offset+limit-1], claims=[], bounties=[])
        with patch.dict(self.api_global, {'api_get':broken}):
            with self.assertRaisesRegex(ValueError,'Incomplete'):
                self.fetch('http://localhost:9000')

    def test_not_ready_ledger_not_interpreted_as_empty(self):
        def not_ready(*args,**kw):
            return {'status':'catching-up','total':650,'payments':[], 'claims':[]}
        with patch.dict(self.api_global, {'api_get':not_ready}):
            ledger=self.fetch('http://localhost:9000')
        self.assertEqual(ledger['status'],'catching-up')

    def test_browser_collector_reuses_shared_pager(self):
        # The embedded browser collector must not regress to a one-page request.
        with open(os.path.join(os.path.dirname(__file__),'..','lithos_dashboard')) as f:
            code=f.read()
        self.assertIn('self.core.fetch_payment_ledger(self.url, timeout=10)',code)
        self.assertNotIn("params={'limit': 500}, optional=True",code)


if __name__ == '__main__':
    unittest.main()
