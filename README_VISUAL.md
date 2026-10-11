# Lithos / Signal — visual dashboard (v0.2.1)

Optional, read-only browser interface for [Arcadian Computers' lithos_dashboard](https://github.com/arcadiancomp/lithos_dashboard), inspired by ErgoScan's dark card-based design.

**No Python packages, npm, CDN, web wallets, or secrets.** Backend and interface use the Python standard library, inline JavaScript, CSS, and native SVG charts. The existing `lithos_dashboard` numerical terminal layout and its original income estimates are retained in normal and `--numeric` modes, with a new LIT-market-valuation addendum. It does not replace earned ERG with speculative converted LIT.

## Install on ergollm

Copy the tarball to `ergollm`, then run (as root):

```sh
tar -xzf lithos_dashboard-0.2.1.tar.gz
cd lithos_dashboard-0.2.1
python3 install_visual.py --repo /srv/git/lithos_dashboard
```

This augments both `/usr/local/sbin/lithos_dashboard` and `/srv/git/lithos_dashboard/lithos_dashboard`. On a fresh installation each is backed up as `lithos_dashboard.before_visual`. Upgrading from v0.2.0 instead saves `lithos_dashboard.before_lit_valuation`. The installer is repeatable and does not replace existing backups. If upgrading an already-installed v0.2.0 or early v0.2.1, it also migrates the previous web option parser to add `--web-listen`; that repair is backed up as `lithos_dashboard.before_web_listen` when pricing was already installed. It places `lithos_web.py`, `lithos_pricing.py`, and `lithos_web_assets/index.html` beside each dashboard file. With `--repo`, it also installs the release notes, tests, installer script and updates the existing README and `.gitignore` for a complete source release. If you want to try only the installed executable first, omit `--repo`.

Launch the new view:

```sh
lithos_dashboard --web --web-listen 192.168.1.9
```

Sample every three seconds instead of five, on another local port:

```sh
lithos_dashboard --web --web-interval 3 --web-port 8788
```

**Keep your terminal numeric interface:**

```sh
lithos_dashboard --numeric
```

In fact, the plain `lithos_dashboard` command also continues to run the original terminal UI. The `--web` flag is opt-in until you have verified that the browser view works well on your network.

### Open from a different workstation on your LAN

For `ergollm` at `192.168.1.9`, launch on the server:

```sh
lithos_dashboard --web --web-listen 192.168.1.9
```

Then visit **http://192.168.1.9:8787/** from the other workstation.
The application also supports `--web-listen 0.0.0.0` to bind all network interfaces.
The default without this option is still `127.0.0.1` for safer localhost-only use.

**Security:** Web access has no authentication. Only expose TCP 8787 to
trusted hosts on the LAN; never port-forward it from the public Internet.
Lithos itself remains on `127.0.0.1:9000`.

For SSH forwarding instead, keep the default localhost bind and forward
local TCP 8787 to `127.0.0.1:8787` over PuTTY.

The browser view has its own **Visual / Numbers** toggle. The browser Numbers tab shows key measurements as a numeric table; `lithos_dashboard --numeric` retains the *complete original* detailed numeric console layout.

### What the graphs actually represent

- **Hashrate and shares/hour:** live samples gathered every 5 seconds (3–120 seconds configurable). The timeline starts collecting when the server starts; it **does not invent historical samples**.
- **NISP eligibility strip:** real recorded NISP observations from the original dashboard's height history. An unobserved height is never fabricated.
- **Daily Lithos genesis:** confirmed UTC daily buckets returned from the client's `/stats/mining/buckets` API.
- **Income model:** the existing dashboard's `calculate_monthly_income()` computation. It remains conditional and low-confidence with few payouts; figures are not promises of future revenue.
- **LIT market:** `/dex/pool` gives actual LIT/ERG reserves and indicative marginal spot. The optional **read-only simulated** `POST /dex/swap/check` prices a sale of the projected 30-day LIT amount, including pool trading fees and price impact. An executable simulation still is not a guaranteed execution at a future date.
- **LIT/USD:** if a fresh ERG/USD quote is available from the CoinGecko simple-price public endpoint, it is multiplied by the simulated LIT→ERG proceeds. No token value is borrowed from the unrelated Plasma-chain LITH. A missing/stale quote yields **unavailable**, never zero or a fake hardcoded USD number.
- **Collateral positions:** the protocol-wide `/collateral/market` active and queued box counts, **not this wallet's own lending positions**.
- **Miner indicators:** Stratum connection count, **not per-GPU telemetry**. The local Lithos API has no per-worker GPU breakdown.

A `--demo` flag on `lithos_web.py` produces **clearly marked fabricated preview data**, only for testing the look without connecting to Lithos. Never use demo output for actual mining decisions.

### Resource/security considerations

The browser talks only to the local `lithos_web.py` HTTP server. That server issues read-only GET requests to Lithos and, for prices, a **simulation-only** `POST /dex/swap/check` that signs/broadcasts no transaction. It optionally fetches the public CoinGecko ERG/USD rate (every five minutes when available). It does not expose either wallet credentials or API keys. All browser JavaScript and CSS are embedded locally.

The server refreshes lightweight mining stats at the sampling interval, historical buckets and payment history no more than once per minute, and collateral market values no more than once per 20 seconds. It does **not** perform the original dashboard's expensive 1,000-block network-adoption rescan, because doing that every 5 seconds could load your node. The numeric dashboard retains the adoption analyzer. This separation is intentional.

The browser service uses the same NISP state history file as the original dashboard (`~/.local/state/lithos_dashboard/nisp_history.json`). Avoid running the original numeric and web views concurrently from the same user account until a shared-state locking mechanism is added, as both may write that file.

### Back out

Stop the web server with Ctrl-C. Restore the installed numeric executable from its backup and remove the optional web module/assets if desired:

```sh
cp -a /usr/local/sbin/lithos_dashboard.before_visual /usr/local/sbin/lithos_dashboard
```

Likewise for your repository source if you used `--repo`:

```sh
cp -a /srv/git/lithos_dashboard/lithos_dashboard.before_visual /srv/git/lithos_dashboard/lithos_dashboard
```

The installer never changes Lithos itself, your mining configuration, node settings, GPU miners, or wallet.

### Independent verification on ergollm

Run the public, read-only pool inspection before trusting the market panel:

```sh
curl -fsS http://127.0.0.1:9000/dex/pool | \
 jq '{tokenY,tokenDecimals,reservesX,reservesY,syncHeight,utxoId}'
```

The pool must use the exact Ergo mainnet token ID `c1980d829988229516430a47a5eca376060b6ce859616db0936e78ab25cb6de7` and non-zero reserves. `reservesX` is nanoERG, `reservesY` is LIT at nine decimals. Quotes are only displayed if the API returns `isExecutable: true` for the full LIT amount. The USD rate must be fresh (updated in the past 15 minutes). No value is implied when any check fails.

Selling tokens is a separate action requiring wallet interaction; this dashboard never executes a swap. Liquidity can change materially and the quoted LIT/ERG amount excludes costs outside the pool (e.g. wallet/network fees).


## Authorship and license

**Author:** Arcadian Computers, LLC  
**License:** MIT — Copyright (c) 2026 Arcadian Computers, LLC.

The full license text is included in `LICENSE` and the GitHub repository.
The ErgoScan-inspired visual layout is an original implementation using local
CSS and SVG; no ErgoScan images, code, or other proprietary assets are bundled.

## Release preparation

Before publishing, install the archive on `ergollm` and verify the live 
`/dex/pool` response (including the exact Ergo mainnet LIT ID) and that the
numeric view still works. Run `python3 -m unittest discover -s tests -v`.
This is an upgrade of the dashboard only; the Lithos miner is not modified.
