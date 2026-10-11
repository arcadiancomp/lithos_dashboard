#!/usr/bin/env python3
"""Conservative LIT/ERG/USD indicative valuation for Lithos miner dashboards.

No secrets, no transactions: GET /dex/pool and POST /dex/swap/check (a simulation)
and optional CoinGecko public ERG/USD price. Never treat a pool spot price as a
promised sale price. Unknown token ID, stale markets and non-executable quotes
remain unavailable, never zero-valued or fabricated.
"""
import json
import time
import urllib.request
from decimal import Decimal, InvalidOperation

LIT_MAINNET = 'c1980d829988229516430a47a5eca376060b6ce859616db0936e78ab25cb6de7'
NANO = Decimal('1000000000')
ERG_USD_URL = 'https://api.coingecko.com/api/v3/simple/price?ids=ergo&vs_currencies=usd&include_last_updated_at=true'
_cache = {}


def positive(value):
    try:
        x = Decimal(str(value))
        return x if x.is_finite() and x > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def read_erg_usd(timeout=4):
    """Only return a genuinely recent public ERG/USD price. No fallback guess."""
    key = 'erg_usd'
    cached = _cache.get(key)
    now = time.time()
    if cached and now - cached[0] < 300:
        return cached[1]
    try:
        req = urllib.request.Request(ERG_USD_URL, headers={'User-Agent': 'LithosDashboard/0.2', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(32769)
        if len(raw) > 32768:
            raise ValueError('market response too large')
        obj = json.loads(raw.decode('utf-8'))['ergo']
        price = positive(obj.get('usd'))
        updated = int(obj.get('last_updated_at', 0))
        if price is None or updated <= 0 or now - updated > 900 or updated > now + 120:
            raise ValueError('ERG/USD quote missing or stale')
        result = {'price': price, 'asOf': updated, 'source': 'CoinGecko (ERG/USD)'}
    except (Exception,):
        result = None
    # Back off from failed lookups for 60 seconds, rather than hammering the API.
    _cache[key] = (now - (240 if result is None else 0), result)
    return result


def quote_swap(base, amount_raw, timeout=5):
    """Simulate selling LIT for ERG; Lithos /dex/swap/check sends no transaction."""
    key = ('swap', base, str(amount_raw))
    cached = _cache.get(key)
    now = time.time()
    if cached and now - cached[0] < 30:
        return cached[1]
    url = base.rstrip('/') + '/dex/swap/check'
    request = urllib.request.Request(url, data=json.dumps({'amountIn': str(amount_raw), 'ergIn': False}).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('quote response too large')
    response = json.loads(raw.decode('utf-8'))
    _cache[key] = (now, response)
    return response


def evaluate_pool(pool, lit_month, chain_height=None):
    """Pure arithmetic; require the exact mainnet LIT and positive liquidity."""
    if not isinstance(pool, dict):
        return {'available': False, 'reason': 'LithosDex pool unavailable'}
    if not pool.get('tokenY'):
        return {'available': False, 'reason': 'LithosDex pool unavailable'}
    if str(pool.get('tokenY')).lower() != LIT_MAINNET:
        return {'available': False, 'reason': 'Pool token ID is not mainnet LIT'}
    decimals = pool.get('tokenDecimals')
    if decimals != 9:
        return {'available': False, 'reason': 'LIT decimals are unverified'}
    x_raw = positive(pool.get('reservesX'))
    y_raw = positive(pool.get('reservesY'))
    if not x_raw or not y_raw:
        return {'available': False, 'reason': 'Pool has no usable ERG/LIT reserves'}
    pool_height = int(pool.get('syncHeight') or 0)
    if pool_height <= 0 or (chain_height and abs(int(chain_height) - pool_height) > 20):
        return {'available': False, 'reason': 'LithosDex pool chain height is stale or unknown'}
    lit_reserve = y_raw / NANO
    erg_reserve = x_raw / NANO
    spot = erg_reserve / lit_reserve
    lit = positive(lit_month)
    result = {'available': True, 'source': 'LithosDex /dex/pool', 'poolHeight': pool_height,
        'poolBoxId': pool.get('utxoId'), 'litTokenId': LIT_MAINNET,
        'litReserve': lit_reserve, 'ergReserve': erg_reserve, 'ergPerLitSpot': spot,
        'litMonth': lit, 'spotErgMonth': (spot * lit if lit else None),
        'quotedErgMonth': None, 'quoteExecutable': False, 'priceImpact': None,
        'valuation': 'indicative spot; not realizable proceeds until a swap quote succeeds'}
    return result


def price_income(core, base, income, height=None, pool=None, include_usd=True, include_quote=True):
    """Return a market valuation dictionary; never modify original income totals.

    Quote is a simulated full monthly LIT sale so its price impact is included.
    Historical payouts are converted at current indicative spot only and kept separate.
    """
    lit = (income or {}).get('litMonth') if isinstance(income, dict) else None
    try:
        pool = pool if pool is not None else core.api_get(base, '/dex/pool', timeout=5)
        output = evaluate_pool(pool, lit, height)
    except Exception as exc:
        output = {'available': False, 'reason': f'LithosDex unavailable: {type(exc).__name__}'}
    if not output.get('available'):
        return output
    spot = output['ergPerLitSpot']
    confirmed = positive((income or {}).get('confirmedLit'))
    output['confirmedLitSpotErg'] = confirmed * spot if confirmed else None
    if include_quote and output['litMonth'] is not None:
        try:
            raw = int(output['litMonth'] * NANO)
            if raw > 0 and raw <= 2**63 - 1:
                q = quote_swap(base, raw)
                if q.get('ergIn') is False and q.get('isExecutable') is True and str(q.get('amountIn')) == str(raw):
                    amount_out = positive(q.get('amountOut'))
                    if amount_out:
                        output['quotedErgMonth'] = amount_out / NANO
                        output['quoteExecutable'] = True
                        output['priceImpact'] = q.get('priceImpact')
                        output['valuation'] = 'simulated LIT→ERG sale; reflects current pool curve/fees, not future prices or settlement'
        except Exception:
            pass
    if include_usd:
        usd = read_erg_usd()
        if usd is not None:
            output['ergUsd'] = usd['price']
            output['usdAsOf'] = usd['asOf']
            output['usdSource'] = usd['source']
            output['litUsdSpot'] = output['ergPerLitSpot'] * usd['price']
            # Only use the simulated sale return for the combined total when executable.
            if output['quoteExecutable']:
                output['litUsdMonthQuoted'] = output['quotedErgMonth'] * usd['price']
                erg_scenario = (income or {}).get('baselineErgMonth')
                if erg_scenario is not None:
                    output['combinedTypicalUsdMonth'] = (Decimal(str(erg_scenario)) + output['quotedErgMonth']) * usd['price']
    return output


def numeric_lines(market):
    """Text panel for the original numeric layout."""
    if not market.get('available'):
        return ['  LIT exchange value      unavailable (' + str(market.get('reason', 'unknown')) + ')',
                '  Existing LIT quantity estimates are preserved; no USD value assumed.']
    lines = ['  LIT/ERG pool spot        ' + f"{market['ergPerLitSpot']:.9f} ERG/LIT",
        '  Available liquidity     ' + f"{market['ergReserve']:,.3f} ERG / {market['litReserve']:,.1f} LIT",
        '  LIT / 30d spot value    ' + (f"~{market['spotErgMonth']:.6f} ERG" if market.get('spotErgMonth') is not None else 'insufficient data')]
    if market.get('confirmedLitSpotErg') is not None:
        lines.append('  Confirmed LIT at spot    ' + f"~{market['confirmedLitSpotErg']:.6f} ERG (not realized)")
    if market.get('quoteExecutable'):
        lines.append('  LIT / 30d sale quote    ' + f"~{market['quotedErgMonth']:.6f} ERG (fee/impact adjusted)")
    else:
        lines.append('  LIT sale quote          unavailable; spot is NOT guaranteed realizable')
    if market.get('ergUsd'):
        lines.append('  ERG/USD market          ' + f"${market['ergUsd']:.4f}")
        if market.get('litUsdMonthQuoted') is not None:
            lines.append('  LIT / 30d USD quote     ' + f"~${market['litUsdMonthQuoted']:.2f}")
        if market.get('combinedTypicalUsdMonth') is not None:
            lines.append('  ERG + LIT / 30d USD    ' + f"~${market['combinedTypicalUsdMonth']:.2f} (conditional)")
    else:
        lines.append('  USD conversion          unavailable (no fresh ERG/USD feed)')
    lines.append('  Indicative values only; pool execution, spreads, fees, liquidity and prices change.')
    return lines
