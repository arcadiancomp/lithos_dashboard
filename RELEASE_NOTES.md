# Lithos Dashboard v0.2.1

Authored by **Arcadian Computers, LLC** · **MIT License**

## Highlights

- Animated browser dashboard inspired by ErgoScan's dark cards, with live
  charts for super shares and hashrate, NISP, collateral, network economics,
  and mining reward estimates.
- Numeric-only browser mode and the complete original terminal dashboard
  available via `--numeric` (also still the default).
- Optional LAN bind with `--web-listen 192.168.1.9` or `0.0.0.0`.
- Conservative LIT/ERG valuation from the verified Ergo mainnet LithosDex
  liquidity pool, simulated sale proceeds after price impact, and fresh ERG/USD
  quotes when available. Unavailable data is never reported as zero value.
- Explicit separation of personal rewards from network-wide economics.
- Added Arcadian Computers, LLC authorship and MIT license links.
- Python standard library only. No third-party browser assets or trackers.

## Install

```sh
tar -xzf lithos_dashboard-0.2.1.tar.gz
cd lithos_dashboard-0.2.1
python3 install_visual.py --repo /srv/git/lithos_dashboard
lithos_dashboard --web --web-listen 192.168.1.9
```

The installer makes backups and preserves the existing NISP/adoption history.
Web port 8787 is unauthenticated; restrict it to your trusted LAN.

## Validation

Automated tests cover UI snapshot, pricing checks, LIT identity, installer
idempotence, and read-only simulated swap handling. Live LIT/ERG prices
remain estimates, not guaranteed proceeds.

- Fixed upgrade from v0.2.0: existing `--web` launchers now gain `--web-listen` without requiring a clean install; added regression tests.
