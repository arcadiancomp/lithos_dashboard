#!/usr/bin/env python3
"""Read-only live web frontend for arcadiancomp/lithos_dashboard (stdlib only).

Designed to run *beside* the existing lithos_dashboard program. All metrics
come from the local Lithos API and the core dashboard calculations; no external
fonts, scripts, CDN resources, wallets, or credentials are needed.
"""
import argparse
import ipaddress
import importlib.machinery
import importlib.util
import json
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import signal
import sys
import threading
import time
from urllib.parse import urlsplit
import lithos_pricing

VERSION = '0.2.1'
HERE = Path(__file__).resolve().parent
DEFAULT_CORE = HERE / 'lithos_dashboard'
STATIC_HTML = HERE / 'lithos_web_assets' / 'index.html'


def load_core(path=DEFAULT_CORE):
    loader = importlib.machinery.SourceFileLoader('lithos_dashboard_core', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def json_ready(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [json_ready(v) for v in value]
    return value


class Collector:
    def __init__(self, core, url, days=7, interval=5, demo=False):
        self.core = core
        self.url = core.normalize_base_url(url) if core else url
        self.days = max(1, min(int(days), 30))
        self.interval = max(3, int(interval))
        self.demo = demo
        self.history = deque(maxlen=360)
        self.lock = threading.Lock()
        self.snapshot = {'status': 'starting', 'version': VERSION, 'samples': []}
        self.stop = threading.Event()
        self.cached = {}
        self.stale_sources = set()
        self.thread = None

    def get(self, name, path, ttl, params=None, optional=False):
        cache = self.cached.get(name)
        if cache and time.monotonic() - cache[0] < ttl:
            return cache[1]
        try:
            doc = self.core.api_get(self.url, path, params=params, timeout=5)
            self.cached[name] = (time.monotonic(), doc)
            return doc
        except Exception:
            if cache:
                self.stale_sources.add(name)
                return cache[1]
            if optional:
                return {}
            raise

    def run(self):
        self.thread = threading.Thread(target=self.loop, name='lithos-sampler', daemon=True)
        self.thread.start()

    def loop(self):
        while not self.stop.is_set():
            begun = time.monotonic()
            try:
                result = self.collect_demo() if self.demo else self.collect()
                with self.lock:
                    self.snapshot = result
            except Exception as exc:
                with self.lock:
                    previous = dict(self.snapshot)
                    previous['status'] = 'stale' if previous.get('status') != 'starting' else 'error'
                    previous['error'] = f'{type(exc).__name__}: {str(exc)[:220]}'
                    self.snapshot = previous
            self.stop.wait(max(0.1, self.interval - (time.monotonic() - begun)))

    def read(self):
        with self.lock:
            return self.snapshot

    def collect(self):
        self.stale_sources = set()
        m = self.core
        commitment = self.get('commitment', '/mining/commitment', self.interval)
        workers = self.get('workers', '/stats/mining/workers', self.interval)
        stats = self.get('stats', '/stats', self.interval, optional=True)
        totals_doc = self.get('totals', '/stats/mining/totals', self.interval)
        market = self.get('market', '/collateral/market', 20, optional=True)
        bucket_doc = self.get('buckets', '/stats/mining/buckets', 60, params=self.bucket_params(), optional=True)
        ledger = self.get('ledger', '/stats/mining/payments', 60, params={'limit': 500}, optional=True)
        totals = totals_doc.get('totals') or {}

        # Shared core owns the precise NISP height accounting and payout model.
        nisp_history = m.update_nisp_history(m.default_nisp_state_file(), workers, stats_doc=stats)
        observed = m.integer(nisp_history.get('observedHeights'))
        missed = m.integer(nisp_history.get('lapseHeights'))
        avail = 100.0 * max(0, observed - missed) / observed if observed else None
        nisp = workers.get('nisp') or {}
        counted = m.integer(nisp.get('superSharesInWindow'))
        need = max(1, m.integer(nisp.get('required'), 10))
        in_force = commitment.get('inForce') or {}
        height = m.integer(commitment.get('height'))
        from_ms = m.integer(totals_doc.get('fromTimestamp'))
        observed_ms = m.integer(totals_doc.get('observedAt'))
        span_days = max(0, (observed_ms - from_ms) / 86400000) if from_ms and observed_ms else 0
        income = m.calculate_monthly_income(totals, ledger, span_days)
        econ = m.economics(totals)
        pool_quote = self.get('dex_pool', '/dex/pool', 30, optional=True)
        # A cached failed pool read must never be mislabeled as a fresh quote.
        market = (lithos_pricing.price_income(m, self.url, income, height=height, pool=pool_quote)
                  if 'dex_pool' not in self.stale_sources else
                  {'available': False, 'reason': 'DEX pool response is stale'})
        local = (stats.get('local') or {}).get('stratum') or {}
        job = local.get('activeJob') or {}
        hashrate = m.dec(workers.get('sessionHashesPerSecond')) / Decimal('1000000')
        now = int(time.time() * 1000)
        sample = {
            'ts': now,
            'height': height,
            'hashrateMH': float(hashrate),
            'sharesHour': float(m.dec(workers.get('superSharesPerHour'))),
            'nispCount': counted,
            'nispHeld': bool(nisp.get('held')),
            'accepted': m.integer(workers.get('acceptedShares')),
            'lithosBlocks': m.integer(totals.get('lithos.blocks')),
        }
        with self.lock:
            if 'workers' not in self.stale_sources and (not self.history or sample['ts'] > self.history[-1]['ts']):
                self.history.append(sample)
            samples = list(self.history)

        height_states = nisp_history.get('heightStates') or {}
        recent_heights = sorted(((m.integer(k), bool(v)) for k, v in height_states.items()), key=lambda x: x[0])[-120:]
        alerts = []
        if not bool(nisp.get('held')):
            alerts.append({'level': 'warning', 'text': 'NISP is below the qualification threshold'})
        elif m.integer(nisp.get('blocksRemaining')) <= 10:
            alerts.append({'level': 'warning', 'text': 'NISP coverage is running low'})
        source = m.integer(totals_doc.get('sourceHeight'))
        target = m.integer(totals_doc.get('targetHeight'))
        if source and target and target - source > 3:
            alerts.append({'level': 'warning', 'text': f'Statistics collector is {target-source} blocks behind'})
        if m.integer(workers.get('rejectedShares')):
            alerts.append({'level': 'warning', 'text': 'Mining shares have been rejected'})
        recent_blocks = stats.get('mining', {}).get('blocks', []) if isinstance(stats.get('mining'), dict) else []
        recent_blocks = recent_blocks if isinstance(recent_blocks, list) else []
        last_block = max((m.integer(x.get('height')) for x in recent_blocks if isinstance(x, dict)), default=0)
        if last_block and height - last_block > 500:
            alerts.append({'level': 'warning', 'text': f'No recognized Lithos genesis block in {height-last_block:,} Ergo blocks'})

        buckets = []
        for b in bucket_doc.get('buckets') or []:
            t = b.get('totals') or {}
            buckets.append({
                'date': m.ms_date(b.get('start')),
                'chain': m.num(t, 'chain.blocks'),
                'lithos': m.num(t, 'lithos.blocks'),
                'topup': float(m.erg(t, 'rollup.topUp.valueNanoErg')),
                'payout': float(m.erg(t, 'network.payout.rewardNanoErg')),
                'genesis': float(m.erg(t, 'holding.genesisNanoErg')),
            })

        critical_stale = sorted(self.stale_sources.intersection({'commitment', 'workers', 'totals'}))
        if self.stale_sources:
            alerts.append({'level': 'warning', 'text': 'Cached telemetry: ' + ', '.join(sorted(self.stale_sources))})
        return json_ready({
            'status': 'stale' if critical_stale else 'ready',
            'error': ('Cached API response(s): ' + ', '.join(critical_stale)) if critical_stale else None,
            'version': VERSION, 'observedAt': now,
            'backend': {'api': self.url, 'sourceHeight': source, 'targetHeight': target},
            'mining': {
                'height': height, 'state': commitment.get('state', '?'),
                'commitment': in_force.get('diff') or commitment.get('configDiff', '—'),
                'configuredDifficulty': commitment.get('configDiff', '—'),
                'changeHeight': m.integer(commitment.get('replaceableFromHeight')),
                'connections': m.integer(local.get('connectedConnections')),
                'jobMode': job.get('mode') or 'unknown',
                'jobHeight': m.integer(job.get('height')),
                'accepted': sample['accepted'],
                'rejected': m.integer(workers.get('rejectedShares')),
                'superShares': m.integer(workers.get('superShares')),
                'sharesHour': sample['sharesHour'],
                'hashrateMH': sample['hashrateMH'],
            },
            'nisp': {
                'held': bool(nisp.get('held')),
                'count': counted, 'required': need,
                'coverage': nisp.get('blocksRemaining'),
                'throughHeight': nisp.get('validThroughHeight'),
                'availability': avail,
                'observations': observed,
                'lapses': m.integer(nisp_history.get('lapseEvents')),
                'lapseHeights': missed,
                'longestLapse': m.integer(nisp_history.get('longestLapseHeights')),
                'heightSeries': [[h, 1 if held else 0] for h, held in recent_heights],
            },
            'pool': {
                'blocks': econ['lithos_blocks'],
                'initial': float(econ['genesis']),
                'topup': float(econ['topup']),
                'boost': float(econ['boost']),
                'poolDEX': float(econ['pool_dex']),
                'priority': float(econ['priority']),
                'networkPayout': float(econ['payout_reward']),
                'localPayout': float(econ['local_payout']),
                'directDEX': float(econ['local_dex_net']),
                'lastRecognizedBlock': last_block,
            },
            'collateral': {
                'active': market.get('activeSetSize'),
                'capacity': market.get('activeSetMax'),
                'queued': market.get('queueLength'),
                'syncHeight': market.get('syncHeight'),
            },
            'income': income,
            'market': market,
            'buckets': buckets,
            'samples': samples,
            'alerts': alerts,
        })

    def bucket_params(self):
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=self.days - 1)
        end = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)
        return {'from': int(start.timestamp() * 1000), 'until': int(end.timestamp() * 1000), 'interval': 'day'}

    def collect_demo(self):
        """Clearly marked offline visual preview, never passed off as live data."""
        t = int(time.time() * 1000)
        i = len(self.history)
        sample = {
            'ts': t, 'height': 1891922 + i, 'hashrateMH': 168 + 5 * __import__('math').sin(i / 6),
            'sharesHour': 6.3 + 0.7 * __import__('math').sin(i / 9),
            'nispCount': max(6, 11 + int(3 * __import__('math').sin(i / 8))),
            'nispHeld': True, 'accepted': 143 + i // 5, 'lithosBlocks': 34,
        }
        with self.lock:
            self.history.append(sample)
            samples = list(self.history)
        return {
            'status': 'ready', 'demo': True, 'version': VERSION, 'observedAt': t,
            'backend': {'api': 'DEMO — NO LIVE API', 'sourceHeight': 1891922, 'targetHeight': 1891922},
            'mining': {'height': sample['height'], 'state': 'active', 'commitment': '9.0M', 'configuredDifficulty': '10.6M',
                       'changeHeight': 1892071, 'connections': 4, 'jobMode': 'augmented', 'jobHeight': sample['height']+1,
                       'accepted': sample['accepted'], 'rejected': 0, 'superShares': sample['accepted'],
                       'sharesHour': sample['sharesHour'], 'hashrateMH': sample['hashrateMH']},
            'nisp': {'held': True, 'count': sample['nispCount'], 'required': 10, 'coverage': 12, 'throughHeight': sample['height']+12,
                     'availability': 79.8, 'observations': 1381, 'lapses': 28, 'lapseHeights': 279, 'longestLapse': 44,
                     'heightSeries': [[n, int((n % 29) > 6)] for n in range(1891802,1891922)]},
            'collateral': {'active': 100, 'capacity': 100, 'queued': 61, 'syncHeight': sample['height']},
            'pool': {'blocks': 34, 'initial': 100.326, 'topup': 47.846, 'boost': 47.7,
                     'poolDEX': 0.039, 'priority': 1.7, 'networkPayout': 141.282,
                     'localPayout': 2.154589, 'directDEX': 0.104, 'lastRecognizedBlock': 1891144},
            'market': {'available': False, 'reason': 'Demo mode: no verified live market quotes'},
            'income': {'baselineErgMonth': 1.83, 'allClaimsErgMonth':12.56,'litMonth':288,
                       'confirmedErg': 2.154589,'confirmedLit':249.477212,'pendingErg':0,'confirmedCount':8,
                       'confidence':'LOW','claimsPerMonth':46.6,'paidSample':8,'valuedClaims':0},
            'buckets': [
                {'date': f'2026-10-{d:02d}', 'chain': h, 'lithos': n, 'topup': top,
                 'payout': pay, 'genesis': gen}
                for d,h,n,top,pay,gen in [
                    (5,105,0,0,0,0),(6,744,3,10.955,0,8.852),(7,677,14,9.421,17.89,41.31),
                    (8,739,9,20.179,52.649,26.557),(9,717,8,7.291,46.736,23.606),
                    (10,684,0,0,24.008,0)]],
            'samples': samples, 'alerts': [{'level':'warning','text':'No recognized Lithos blocks in 778 Ergo blocks'}]
        }


class Handler(BaseHTTPRequestHandler):
    collector = None

    def do_GET(self):
        target = urlsplit(self.path).path
        if target == '/api/snapshot':
            return self.respond(json.dumps(self.collector.read(), separators=(',', ':'), ensure_ascii=True).encode(),
                                'application/json; charset=utf-8')
        if target in ('/', '/index.html'):
            return self.respond(STATIC_HTML.read_bytes(), 'text/html; charset=utf-8')
        self.send_error(404, 'Not Found')

    def respond(self, payload, mimetype):
        self.send_response(200)
        self.send_header('Content-Type', mimetype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        if self.path != '/api/snapshot':
            super().log_message(format, *args)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Lithos visual dashboard — read-only browser UI')
    ap.add_argument('--url', default='http://127.0.0.1:9000', help='Lithos API URL')
    ap.add_argument('--listen', default='127.0.0.1', help='Bind address (localhost by default)')
    ap.add_argument('--port', type=int, default=8787)
    ap.add_argument('--interval', type=int, default=5, help='API sample interval in seconds (min 3)')
    ap.add_argument('--days', type=int, default=7, help='Historical UTC daily buckets')
    ap.add_argument('--demo', action='store_true', help='Offline presentation preview; never use actual mining data')
    args = ap.parse_args(argv)
    if not 1 <= args.port <= 65535:
        ap.error('port must be in 1..65535')
    if args.listen != 'localhost':
        try:
            ipaddress.ip_address(args.listen)
        except ValueError:
            ap.error('--listen must be a valid IP address or localhost')
    core = None if args.demo else load_core()
    collector = Collector(core, args.url, args.days, args.interval, args.demo)
    Handler.collector = collector
    server = ThreadingHTTPServer((args.listen, args.port), Handler)
    collector.run()
    print(f'LITHOS / SIGNAL v{VERSION} — http://{args.listen}:{args.port}/')
    if args.demo:
        print('DEMO MODE — generated sample data, not connected to a miner')
    exposure = ('loopback' if args.listen in ('127.0.0.1', '::1', 'localhost')
                else 'all interfaces' if args.listen in ('0.0.0.0', '::')
                else 'LAN interface')
    print(f'Bind: {args.listen} ({exposure}) | Browser API: read-only | Ctrl-C to stop')
    if exposure != 'loopback':
        print('SECURITY: No web authentication; limit TCP access to trusted LAN hosts.')
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        collector.stop.set()
        server.server_close()

if __name__ == '__main__':
    main()
