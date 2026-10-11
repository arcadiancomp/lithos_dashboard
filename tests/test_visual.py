import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
from decimal import Decimal
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lithos_pricing as pricing
spec = importlib.util.spec_from_file_location('signal_backend', ROOT / 'lithos_web.py')
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

class DashboardTests(unittest.TestCase):
    def test_json_demo_marked_and_numeric(self):
        c = web.Collector(None, 'DEMO', demo=True)
        x = c.collect_demo()
        self.assertTrue(x['demo'])
        self.assertEqual(x['pool']['blocks'],34)
        self.assertEqual(x['collateral']['queued'],61)
        self.assertTrue(x['samples'])
        self.assertEqual(web.json_ready({'x':__import__('decimal').Decimal('1.25')}), {'x':1.25})

    def test_market_pool_verified_and_spot_valued(self):
        pool = {'tokenY': pricing.LIT_MAINNET, 'tokenDecimals': 9,
                'reservesX': '200000000000', 'reservesY': '100000000000000',
                'syncHeight': 1000, 'utxoId': 'ff' * 32}
        quote = pricing.evaluate_pool(pool, Decimal('288'), 1001)
        self.assertTrue(quote['available'])
        self.assertEqual(quote['ergPerLitSpot'], Decimal('0.002'))
        self.assertEqual(quote['spotErgMonth'], Decimal('0.576'))
        self.assertFalse(pricing.evaluate_pool({**pool, 'tokenY': 'LITH'}, Decimal('1'), 1000)['available'])
        self.assertFalse(pricing.evaluate_pool({**pool, 'reservesX': '0'}, Decimal('1'), 1000)['available'])
        self.assertFalse(pricing.evaluate_pool(pool, Decimal('1'), 1050)['available'])

    def test_quoted_value_requires_genuine_simulation(self):
        from unittest.mock import patch
        pool = {'tokenY': pricing.LIT_MAINNET, 'tokenDecimals': 9,
                'reservesX': '200000000000', 'reservesY': '100000000000000',
                'syncHeight': 1000, 'utxoId': 'ff' * 32}
        quote = {'ergIn': False, 'isExecutable': True,
                 'amountIn': '288000000000', 'amountOut': '565000000', 'priceImpact': 0.01}
        with patch.object(pricing, 'quote_swap', return_value=quote), patch.object(pricing, 'read_erg_usd', return_value={'price': Decimal('0.33'), 'asOf':123, 'source':'CoinGecko'}):
            m = pricing.price_income(None, 'http://127.0.0.1:9000',
                    {'litMonth': Decimal('288'), 'baselineErgMonth': Decimal('1.83'), 'confirmedLit':Decimal('250')},
                    1000, pool)
        self.assertEqual(m['quotedErgMonth'], Decimal('0.565'))
        self.assertEqual(m['combinedTypicalUsdMonth'], Decimal('2.395') * Decimal('0.33'))
        self.assertEqual(m['spotErgMonth'], Decimal('0.576'))
        with patch.object(pricing, 'quote_swap', return_value={**quote, 'isExecutable': False}):
            no = pricing.price_income(None, 'http://127.0.0.1:9000', {'litMonth':288}, 1000, pool, include_usd=False)
        self.assertIsNone(no.get('quotedErgMonth'))
        self.assertNotIn('combinedTypicalUsdMonth', no)

    def test_author_attribution_and_lan_option(self):
        import install_visual
        page = (ROOT / 'lithos_web_assets' / 'index.html').read_text()
        self.assertGreaterEqual(page.count('Arcadian Computers, LLC'), 2)
        self.assertIn('MIT License', page)
        self.assertIn('"--web-listen"', install_visual.INSERT_ARGS)
        self.assertIn('"--listen", args.web_listen', install_visual.INSERT_HANDLER)
        script = (ROOT / 'lithos_web.py').read_text()
        self.assertIn("ipaddress.ip_address(args.listen)", script)
        self.assertNotIn('remote binding disabled', script)
        self.assertNotIn('Bind: localhost only', script)

    def test_numeric_income_patch_is_one_time_and_upgrade_safe(self):
        import install_visual
        sample = ("def render():\n" + install_visual.INCOME_ANCHOR
                + "    section(f\"DAILY HISTORY\")\n"
                + "    print(col(\"bond refunds excluded; LIT has no USD valuation.\", DIM))\n")
        patched = install_visual.add_lit_valuation(sample)
        self.assertIn('from lithos_pricing import price_income, numeric_lines', patched)
        self.assertIn('LIT market value is indicative.', patched)
        self.assertEqual(patched, install_visual.add_lit_valuation(patched))
        compile(patched, '<patched>', 'exec')

    def test_upgrade_v020_launcher_adds_listen_and_preserves_flags(self):
        import install_visual
        with tempfile.TemporaryDirectory() as d:
            temp = Path(d)
            target = temp / 'lithos_dashboard'
            # Reconstruct the v0.2.0 launcher that had --web and --web-port,
            # but no --web-listen. Regression for upgrades on ergollm.
            parser = '''#!/usr/bin/env python3
import argparse

def api_get(): pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:9000')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument(
        "--web", action="store_true")
    parser.add_argument(
        "--numeric", action="store_true")
    parser.add_argument(
        "--web-port", type=int, default=8787)
    parser.add_argument(
        "--web-interval", type=int, default=5)
    args = parser.parse_args()
    if args.web and args.numeric:
        parser.error('conflict')
    if args.web:
        from lithos_web import main as lithos_web_main
        return lithos_web_main([
            "--url", args.url,
            "--days", str(args.days),
            "--port", str(args.web_port),
            "--interval", str(args.web_interval),
        ])
    print('NUMERIC')
if __name__ == '__main__': main()
'''
            target.write_text(parser)
            install_visual.patch_target(target)
            content = target.read_text()
            self.assertEqual(content.count('"--web-listen"'), 1)
            self.assertEqual(content.count('"--listen", args.web_listen,'), 1)
            self.assertEqual(content.count('"--web", action='), 1)
            help_result = subprocess.run([sys.executable, str(target), '--help'],
                                         capture_output=True, text=True)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn('--web-listen', help_result.stdout)
            self.assertEqual((temp/'lithos_dashboard.before_lit_valuation').read_text(), parser)
            # Check the actual forwarded arguments without opening a port.
            (temp/'lithos_web.py').write_text('def main(args):\n    print("ARGS",repr(args))\n')
            call = subprocess.run([sys.executable, str(target), '--web', '--web-listen',
                                   '192.168.1.9'], capture_output=True, text=True)
            self.assertEqual(call.returncode, 0, call.stderr)
            self.assertIn("'--listen', '192.168.1.9'", call.stdout)
            self.assertEqual(install_visual.upgrade_web_launcher(content), content)

    def test_upgrade_v021_pricing_version_can_repair_without_overwriting_old_backup(self):
        import install_visual
        with tempfile.TemporaryDirectory() as d:
            temp = Path(d)
            target = temp / 'lithos_dashboard'
            # A user already ran the broken v0.2.1 installer. It placed pricing
            # but never upgraded the existing v0.2.0 --web option parser.
            sample = '''#!/usr/bin/env python3
import argparse, sys

def api_get(): pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:9000')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--web-port", type=int, default=8787)
    parser.add_argument(
        "--web-interval", type=int, default=5)
    args = parser.parse_args()
    if args.web:
        from lithos_web import main as lithos_web_main
        return lithos_web_main([
            "--port", str(args.web_port),
            "--interval", str(args.web_interval)])
    from lithos_pricing import price_income, numeric_lines
if __name__ == '__main__': main()
'''
            target.write_text(sample)
            (temp / 'lithos_dashboard.before_lit_valuation').write_text('EXISTING BACKUP')
            install_visual.patch_target(target)
            self.assertEqual((temp / 'lithos_dashboard.before_lit_valuation').read_text(), 'EXISTING BACKUP')
            self.assertEqual((temp / 'lithos_dashboard.before_web_listen').read_text(), sample)
            self.assertIn('"--web-listen"', target.read_text())

    def test_installer_does_not_destroy_original(self):
        with tempfile.TemporaryDirectory() as d:
            temp = Path(d)
            shutil.copy2(ROOT / 'lithos_web.py', temp / 'lithos_web.py')
            shutil.copytree(ROOT / 'lithos_web_assets', temp / 'lithos_web_assets')
            target = temp / 'lithos_dashboard'
            original = ('#!/usr/bin/env python3\n'
                'def api_get(): pass\n'
                'def main():\n'
                '    import argparse\n'
                '    parser = argparse.ArgumentParser()\n'
                '    args = parser.parse_args()\n'
                '    print("ORIGINAL")\n'
                'if __name__ == "__main__": main()\n')
            target.write_text(original)
            r = subprocess.run(['python3',str(ROOT/'install_visual.py'),'--target',str(target)],capture_output=True,text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((temp/'lithos_dashboard.before_visual').read_text(), original)
            self.assertIn('from lithos_web import main as lithos_web_main', target.read_text())
            again = subprocess.run(['python3',str(ROOT/'install_visual.py'),'--target',str(target)],capture_output=True,text=True)
            self.assertEqual(again.returncode,0,again.stderr)
            once = subprocess.run(['python3',str(target),'--numeric'],capture_output=True,text=True)
            self.assertEqual(once.stdout.strip(),'ORIGINAL')
            self.assertEqual(once.returncode,0,once.stderr)

if __name__=='__main__':
    unittest.main()
