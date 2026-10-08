# Lithos Dashboard

A lightweight terminal dashboard for monitoring a
[Lithos Protocol](https://github.com/Lithos-Protocol/Lithos-Client)
miner, sequencer, and decentralized Ergo mining pool participant.

Designed and tested on Linux with Lithos Client v1.0.2.

## Features

- Live Lithos difficulty commitment status
- Commitment activation and lock countdowns
- Accepted/rejected super-share monitoring
- NISP health and remaining coverage
- Pool and network economic statistics
- Lithos block counts
- Initial holding value
- Candidate top-up revenue
- Revenue boost over the Ergo block subsidy
- Priority-bid revenue
- ErgoDEX and LithosDEX executor revenue
- Local realized payout tracking
- Local direct DEX executor income
- Daily historical revenue table
- ANSI color-coded terminal display
- No third-party Python dependencies

## Requirements

- Python 3
- Lithos Client HTTP API
- ANSI-compatible terminal

The dashboard uses only Python's standard library.

## Installation

Clone the repository:

```bash
git clone https://github.com/arcadiancomp/lithos_dashboard.git
cd lithos_dashboard
```

Install globally:

```bash
install -m 755 lithos_dashboard /usr/local/sbin/lithos_dashboard
```

## Usage

Run with defaults:

```bash
lithos_dashboard
```

The default Lithos API endpoint is:

```text
http://127.0.0.1:9000
```

The dashboard refreshes every 15 seconds and displays seven days of history.

Faster refresh:

```bash
lithos_dashboard --interval 5
```

Longer history:

```bash
lithos_dashboard --days 14
```

Render once:

```bash
lithos_dashboard --once
```

Remote API:

```bash
lithos_dashboard --url http://192.168.1.10:9000
```

Disable ANSI colors:

```bash
lithos_dashboard --no-color
```

## Economics

The dashboard deliberately distinguishes **network/pool economics** from
**local miner income**.

Important figures include:

- `Initial holding` — ERG initially placed into Lithos holding boxes.
- `Candidate top-ups` — additional ERG captured by block candidate sources.
- `Top-up boost` — candidate revenue relative to initial holding value.
- `Holding inflow / block` — initial holding plus candidate top-ups per Lithos block.
- `DEX revenue into pool` — DEX execution proceeds captured inside Lithos candidates.
- `Local direct DEX net` — Executor revenue earned directly by this client.
- `Local realized payout` — confirmed payout rewards attributed to the local miner.

Network and pool totals are not necessarily income belonging solely to the
local miner.

## Lithos sequencing

Lithos allows miners to build economically optimized block candidates rather
than merely supplying hashpower to a centralized pool.

Candidate revenue may include:

- ErgoDEX execution
- LithosDEX execution
- storage-rent collection
- collateral priority bids
- rollup transactions
- emission and collateral queue operations
- future arbitrage and other candidate-capital sources

Lithos Dashboard makes these economics visible in real time.

## Security

The dashboard performs read-only HTTP GET requests against the Lithos API.

It does not require a wallet password, Ergo node API key, Lithos API key,
seed phrase, or private key.

Keeping the Lithos HTTP API bound to `127.0.0.1` is recommended for local
installations.

## License

MIT

## Author

Arcadian Computers, LLC
