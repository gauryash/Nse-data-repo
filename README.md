<div align="center">

# 📈 NSE Relative Strength Analyzer

**Multi‑source data pipeline + Options & Equities + Relative Strength + Anchored VWAP + Telegram scanners**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-purple)](https://github.com/astral-sh/ruff)

</div>

---

## 🔥 Features

| Layer | What it does |
|---|---|
| **Data Pipeline** | Fetch historical data from **NSE website**, **Upstox API** (equities), or **Upstox F&O** (options & futures) |
| **Options & Futures** | Unified discovery for **stock options (OPTSTK)** and **index options (OPTIDX)**; expiry‑aware filtering (next N expiries per underlying); auto‑discovers all strikes + CE/PE |
| **Relative Strength** | `RS = (stock_return / nifty_return) - 1` with 50‑week lookback → ranked CSV |
| **Alpha Pipeline** | 12‑step signal processing: remove drift, normalise volatility, strip market bias, extract pure alpha |
| **Alpha Backtest** | Rolling monthly rebalance (long-only, top 10 %) powered by VectorBT for Sharpe, drawdown & more |
| **Anchored VWAP** | Scan Upstox symbols for stocks trading within 3 % of 10/20/30‑year anchored VWAP |
| **Telegram Scanners** | Run Chartink screeners, composite factor scoring, and Trendlyne sector reports → Telegram |

---

## 🚀 Quick Start

```bash
# Install
pip install -e ".[dev]"

# ── Equities ──────────────────────────────────────────────────

# 1. Fetch NSE equity + Nifty 500 index data
nse-relative fetch --provider nse

# 2. Compute Relative Strength and save ranked CSV
nse-relative rs

# 3. Fetch Upstox historical candles (monthly interval)
nse-relative fetch --provider upstox --interval month

# 4. Run Anchored VWAP proximity screener
nse-relative vwap

# ── Options & Futures ─────────────────────────────────────────

# 5. Fetch Nifty 50 stock options (next 2 expiries, all strikes)
nse-relative fetch --provider upstox_options --index nifty50

# 6. Fetch stock options + index options (NIFTY, BANKNIFTY, etc.)
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX"

# 7. Fetch next 3 expiries for everything (stocks + indices + futures)
nse-relative fetch --provider upstox_options --n-expiries 3 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures

# ── Scanners ─────────────────────────────────────────────────

# 8. Fire all Telegram scanners
nse-relative scan all
```

---

## 📋 Commands Reference

### `nse-relative fetch`

| Option | Description | Default |
|---|---|---|
| `--provider, -p` | `nse`, `upstox`, or `upstox_options` | `nse` |
| `--index, -x` | NSE index constituent list (see below) | `nifty500` |
| `--symbols, -s` | Limit to specific symbols / tradingsymbols | all |
| `--start` / `--from` | Start date DD-MM-YYYY | provider default (env or hardcoded) |
| `--end` / `--to` | End date DD-MM-YYYY | provider default (env or today) |
| `--interval, -i` | Candle interval: `day`, `week`, `month` | provider default |
| `--force, -f` | Ignore checkpoint, re-fetch all from scratch | `False` |
| `--skip-index` | Skip index data (NSE only) | `False` |
| **UpstoxOptions‑only:** | | |
| `--instrument-types, -t` | F&O types: `OPTSTK`, `OPTIDX` (comma‑separated) | `OPTSTK` |
| `--include-futures` | Also fetch `FUTSTK` / `FUTIDX` | `False` |
| `--n-expiries` | Upcoming expiry cycles per underlying (`0` = all) | `2` |

#### Examples — Equities

```bash
# NSE — Nifty 500 constituents (default date range from env)
nse-relative fetch --provider nse

# NSE — all ~750 stocks for a custom date range
nse-relative fetch --provider nse --index nifty_total_market --start 01-01-2025 --end 31-12-2025

# NSE — just 50 large-caps
nse-relative fetch --provider nse --index nifty50

# NSE — specific symbols only
nse-relative fetch --provider nse --symbols RELIANCE TCS HDFCBANK

# Upstox — daily candles for Nifty 200 from 2020 onwards
nse-relative fetch --provider upstox --interval day --index nifty200 --start 01-01-2020

# Upstox — monthly candles, full history (defaults: 2000-01-01 → today)
nse-relative fetch --provider upstox --interval month --index nifty500

# Force re-fetch (bypass checkpoint)
nse-relative fetch --provider upstox --force

# Equities only, no index data
nse-relative fetch --provider nse --skip-index
```

#### Examples — Options & Futures

```bash
# Stock options (OPTSTK) for Nifty 50 — next 2 expiries, all strikes
nse-relative fetch --provider upstox_options --index nifty50

# Index options (OPTIDX) for all available indices — next 2 weekly expiries
nse-relative fetch --provider upstox_options --instrument-types OPTIDX

# Both stock options + index options + stock futures
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures

# Specific tradingsymbols (e.g. NIFTY 23600 CE Jun 2026 expiry)
nse-relative fetch --provider upstox_options \
  --symbols NIFTY26JUN23600CE NIFTY26JUN23600PE

# Fetch the next 3 expiry cycles (instead of default 2)
nse-relative fetch --provider upstox_options --n-expiries 3

# Fetch ALL contracts (disable expiry filter)
nse-relative fetch --provider upstox_options --n-expiries 0

# Weekly candles for options
nse-relative fetch --provider upstox_options --interval week
```

#### Options – How expiry filtering works

Discovering contracts follows a two‑step pipeline:

```
discover_option_contracts()          filter_by_expiry()
     OPTSTK ── ISIN match ──┐
                            ├──→ All contracts ──→ Next N expiries per underlying
     OPTIDX ── auto‑discover ┘
```

**Per‑underlying grouping**, not a global expiry threshold:
- **NIFTY** (index, weekly) → next 2 weekly expiries (e.g. Jun 9, Jun 16)
- **RELIANCE** (stock, monthly) → next 2 monthly expiries (e.g. Jun 30, Jul 28)
- Each expiry includes **all strikes × (CE + PE)** for those dates

Index options are **auto‑discovered** from the Upstox instrument master CSV.
Currently available indices: `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, `NIFTY`,
`NIFTYNXT50`, `SENSEX`, `SENSEX50`, and more.

#### Checkpoint system

Each provider tracks what date ranges have already been fetched in
``data/{provider}/_checkpoint.json``.  Before downloading a symbol, the
provider checks whether the requested date range is already covered.  If it
is, the symbol is **skipped** — no HTTP request is made.

Use ``--force`` / ``-f`` to ignore the checkpoint and re-fetch everything
from scratch.  The checkpoint is automatically updated after every
successful fetch.

```bash
# First run — fetches everything (slow)
nse-relative fetch --provider upstox --interval month --index nifty200

# Second run — skips all symbols already covered (fast)
nse-relative fetch --provider upstox --interval month --index nifty200

# Re-fetch everything
nse-relative fetch --provider upstox --interval month --index nifty200 --force
```

### `nse-relative rs`

| Option | Description | Default |
|---|---|---|
| `--output, -o` | Output CSV path | `rs_weekly.csv` |
| `--lookback, -l` | Lookback weeks | `50` |

```bash
nse-relative rs                          # default output
nse-relative rs -o my_rankings.csv -l 25 # custom lookback
```

### `nse-relative vwap`

| Option | Description | Default |
|---|---|---|
| `--output, -o` | Output Excel path | `data/ScreenerList_VWAP_Proximity.xlsx` |
| `--threshold, -t` | Proximity threshold (decimal) | `0.03` (3 %) |

```bash
nse-relative vwap                          # default 3 % threshold
nse-relative vwap -t 0.05 -o tight.xlsx    # 5 % threshold
```

### `nse-relative alpha run`

Run the **12‑step signal-processing pipeline** on a single window.

| Option | Description | Default |
|---|---|---|
| `--index, -x` | NSE index universe | `nifty500` |
| `--lookback, -M` | Lookback periods | `252` (≈1 trading year) |
| `--estimation, -d` | Estimation periods | `20` (≈1 trading month) |
| `--eta` | Weighting scale | `1.0` |
| `--output, -o` | Output CSV path | `alpha_ranking.csv` |
| `--send` | Send results to Telegram | `False` |
| `--top` | Show top N stocks in console | `10` |

```bash
# Basic run (Nifty 50, defaults)
nse-relative alpha run --index nifty50

# Custom parameters
nse-relative alpha run --index nifty50 --lookback 504 --estimation 40 --eta 0.5

# Run and send to Telegram
nse-relative alpha run --index nifty50 --send

# Show top 20 stocks
nse-relative alpha run --index nifty50 --top 20
```

### `nse-relative alpha backtest`

**Rolling monthly backtest** — runs the 12‑step pipeline on every month-end,
rebalances an equal-weight long-only portfolio (top 10 %), and computes
performance metrics via **VectorBT**.

| Option | Description | Default |
|---|---|---|
| `--index, -x` | NSE index universe | `nifty500` |
| `--lookback, -M` | Lookback periods | `252` |
| `--estimation, -d` | Estimation periods | `20` |
| `--eta` | Weighting scale | `1.0` |
| `--top-pct` | Top percentile of stocks to keep | `0.10` (10 %) |
| `--min-stocks` | Minimum stocks per month | `5` |

```bash
# Basic backtest (Nifty 50, defaults)
nse-relative alpha backtest --index nifty50

# Custom selection
nse-relative alpha backtest --index nifty50 --top-pct 0.15 --min-stocks 10
```

Output files (all saved to `analysis/`):

| File | Description |
|---|---|
| `portfolio_weights.csv` | Daily weight matrix |
| `equity_curve.csv` | Portfolio NAV |
| `performance_metrics.csv` | VectorBT metrics (Sharpe, DD, etc.) |
| `backtest_summary.csv` | One row per rebalance event |
| `backtest_log.txt` | Human-readable run log |
| `rankings/*.csv` | Per-month alpha rankings |

Sample output:
```
  ==================================================
  PERFORMANCE METRICS  (VectorBT)
  ==================================================
    Total Return:           -5.23 %
    Annualized Return:     -2.14 %
    Annualized Vol:        18.45 %
    Sharpe Ratio:         -0.1160
    Max Drawdown:         -18.34 %
    Calmar Ratio:         -0.1142
    Sortino Ratio:        -0.1590
    Avg Daily Turnover:    0.0098
```

### `nse-relative alpha send`

Re-send previous ranking results to Telegram:

```bash
nse-relative alpha send -i alpha_ranking.csv
```

### `nse-relative scan`

```bash
nse-relative scan all                          # run every scanner
nse-relative scan chartink                     # only Chartink
nse-relative scan composite sector             # Composite + Sector only
```

### Utility commands

```bash
nse-relative list-providers    # nse, upstox, upstox_options
nse-relative list-analytics   # rs, vwap, alpha
nse-relative list-scanners    # chartink, composite, sector
nse-relative list-indices     # all 20+ NSE index constituent lists with URLs
nse-relative --version        # 0.2.0
```

### Available NSE indices (`nse-relative list-indices`)

| Index Name | Constituents | Description |
|---|---|---|
| `nifty50` | 50 | Nifty 50 large-caps |
| `nifty100` | 100 | Nifty 100 |
| `nifty200` | 200 | Nifty 200 |
| `nifty500` | 500 | Nifty 500 (default) |
| `nifty_total_market` | ~750 | All listed equities |
| `nifty_next_50` | 50 | Next 50 (51–100) |
| `nifty_midcap_50` | 50 | Mid-cap 50 |
| `nifty_midcap_150` | 150 | Mid-cap 150 |
| `nifty_smallcap_50` | 50 | Small-cap 50 |
| `nifty_smallcap_100` | 100 | Small-cap 100 |
| `nifty_smallcap_250` | 250 | Small-cap 250 |
| `nifty_microcap_250` | 250 | Micro-cap 250 |
| `nifty_large_midcap_250` | 250 | Large + Mid-cap 250 |
| `nifty_mid_smallcap_400` | 400 | Mid + Small-cap 400 |
| … plus momentum/quality factor indices | | |

---

## 🏗️ Architecture

```
src/nse_relative/
│
├── cli.py                          # Unified CLI entry point
│
├── config/
│   ├── settings.py                 # All env-var configuration
│   └── logger.py                   # Logging setup
│
├── pipeline/                       # ─── Data fetching layer ───
│   ├── base.py                     # DataProvider ABC
│   ├── nse_provider.py             # NSE website API (equities + index)
│   ├── upstox_provider.py          # Upstox API — equities (ISIN-filtered)
│   ├── upstox_options_provider.py  # Upstox API — F&O options & futures ✨
│   ├── storage.py                  # Provider-partitioned Parquet/CSV + contract manifest
│   ├── symbol_manager.py           # NSE index CSVs + Upstox ISIN pipeline + OptionContract domain model
│   ├── checkpoint.py               # Per-provider incremental fetch tracking
│   └── rate_limiter.py             # Thread-safe exponential backoff
│
├── analytics/                      # ─── Traditional analytics ───
│   ├── base.py                     # BaseAnalyzer ABC
│   ├── relative_strength.py        # RS = (stock_ret / nifty_ret) - 1
│   ├── anchored_vwap.py            # Anchored VWAP proximity screener
│   └── utils.py                    # resample_weekly, date_chunks, etc.
│
├── alphaextraction/                # ─── Alpha pipeline (12-step) ───
│   ├── signal_pipeline.py          # Phase 1-3: preprocessing → alpha → weights
│   ├── backtest.py                 # Rolling monthly backtest + VectorBT metrics
│   └── reporting.py                # Console / CSV / Telegram output formatting
│
└── scanners/                       # ─── Telegram screeners ───
    ├── base.py                     # BaseScanner ABC
    ├── chartink_scanner.py         # Chartink.com screeners
    ├── composite_scorer.py         # screener.in multi-factor decile ranking
    ├── sector_scanner.py           # Trendlyne sector / index reports
    ├── telegram_notifier.py        # Telegram send + DataFrame formatting
    └── queries.py                  # Chartink scan clauses
```

### Data flow

```
NSE API ──→ NSEProvider ──────→ data/nse/*.parquet ──→ RelativeStrength ──→ rs_weekly.csv
                                                           │
                                                           ├── AlphaPipeline ──→ alpha_ranking.csv
                                                           │
                                                           └── AlphaBacktest ──→ analysis/* (VectorBT)

Upstox API ──→ UpstoxProvider ──→ data/upstox/*.parquet
                                           │
                                           └──→ AnchoredVWAP ──→ VWAP_Proximity.xlsx

Upstox API ──→ UpstoxOptionsProvider ──→ data/upstox_options/{tradingsymbol}.parquet
                                           │
                                           ├── _contracts.parquet   (contract manifest)
                                           ├── _checkpoint.json     (incremental fetch tracking)
                                           └── [expiry‑aware filtering → analytics]

Chartink / Screener.in / Trendlyne ──→ Scanner ──→ Telegram
```

---

## 📂 Data Storage

| Provider | Path | Contents | Format |
|---|---|---|---|
| **NSE** | `data/nse/equities_{year}.parquet` | Yearly partitions | Parquet (gzip) |
| **NSE** | `data/nse/equities.parquet` | Consolidated all years | Parquet (gzip) |
| **NSE** | `data/nse/indices.parquet` | Nifty 500 index | Parquet (gzip) |
| **Upstox** | `data/upstox/{symbol}.parquet` | One file per equity symbol | Parquet (gzip) |
| **Upstox Options** | `data/upstox_options/{tradingsymbol}.parquet` | Per‑contract OHLC+OI candle data | Parquet (gzip) |
| **Upstox Options** | `data/upstox_options/_contracts.parquet` | Contract manifest (expiry‑queryable catalog) | Parquet (gzip) |
| **Upstox Options** | `data/upstox_options/_checkpoint.json` | Per‑contract fetch tracking | JSON |
| **Upstox** | `data/SymbolList_{index}.xlsx` | ISIN-filtered symbol list | Excel |

> 💡 Set `NSE_STORAGE_FORMAT=csv` to write CSV instead — easier to inspect in a spreadsheet.

#### Option contract data structure

Each contract file (e.g. `NIFTY26JUN23600CE.parquet`) contains:

```
date, open, high, low, close, vol, oi, symbol,
instrument_type, option_type, expiry, strike, lot_size, underlying_name
```

| Column | Example | Description |
|---|---|---|
| `date` | `2026-05-12` | Trading date (IST) |
| `open/ high/ low/ close` | `526.7` | OHLC prices (in INR) |
| `vol` | `2,340` | Traded quantity (contracts) |
| `oi` | `1,365` | Open Interest |
| `symbol` | `NIFTY26JUN23600CE` | Tradingsymbol |
| `instrument_type` | `OPTIDX` | OPTSTK / OPTIDX / FUTSTK / FUTIDX |
| `option_type` | `CE` | CE / PE / FF (futures) |
| `expiry` | `2026-06-09` | Contract expiry |
| `strike` | `23600.0` | Strike price |
| `lot_size` | `65` | Lot multiplier |
| `underlying_name` | `NIFTY` | Company or index name |

---

## ⚙️ Configuration

Copy `.env.example` → `.env` and fill in:

### Required for scanners (Telegram)

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from [@BotFather](https://t.me/botfather) |
| `CHAT_ID_ALERT` | Target chat / group ID |
| `CHAT_ID_BOT` | Your private chat ID |

### Optional overrides (all prefixed with `NSE_`)

| Variable | Default | Description |
|---|---|---|
| `NSE_DEFAULT_INDEX` | `nifty500` | Default NSE index for symbol sourcing |
| `NSE_FETCH_START` | `01-01-2021` | Fetch start (DD-MM-YYYY) |
| `NSE_FETCH_END` | `23-05-2026` | Fetch end (DD-MM-YYYY) |
| `NSE_FETCH_CHUNK_DAYS` | `110` | Chunk size for NSE API (max 70 records/call) |
| `NSE_RS_LOOKBACK` | `50` | RS lookback weeks |
| `NSE_ALPHA_LOOKBACK` | `252` | Alpha pipeline lookback periods (M) |
| `NSE_ALPHA_ESTIMATION` | `20` | Alpha pipeline estimation periods (d) |
| `NSE_ALPHA_ETA` | `1.0` | Alpha pipeline weighting scale (η) |
| `NSE_STORAGE_FORMAT` | `parquet` | `parquet` or `csv` |
| `NSE_RATE_MAX_WORKERS` | `5` | Parallel fetch workers |
| `NSE_LOG_LEVEL` | `INFO` | Logging verbosity |
| `UPSTOX_INTERVAL` | `month` | Candle interval (`day`, `week`, `month`) |
| `UPSTOX_MAX_WORKERS` | `10` | Upstox parallel workers |
| `UPSTOX_FETCH_START` | `01-01-2000` | Upstox fetch start date (DD-MM-YYYY) |
| `UPSTOX_OPTIONS_INTERVAL` | `day` | Options candle interval |
| `UPSTOX_OPTIONS_MAX_WORKERS` | `5` | Options parallel workers |
| `UPSTOX_OPTIONS_FETCH_START` | `01-01-2024` | Options fetch start date |
| `UPSTOX_OPTIONS_TYPES` | `OPTSTK` | F&O types: `OPTSTK,OPTIDX` |
| `UPSTOX_OPTIONS_N_EXPIRIES` | `2` | Upcoming expiry cycles per underlying (`0` = all) |
| `UPSTOX_OPTIONS_INDEX_NAMES` | *(auto)* | Restrict index options (e.g. `NIFTY,BANKNIFTY`) |

---

## 🔧 Development

```bash
# Editable install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint + type-check
ruff check src/
mypy src/

# Format
ruff format src/

# Makefile shortcuts
make fetch-nse       # nse-relative fetch --provider nse
make fetch-upstox    # nse-relative fetch --provider upstox
make rs              # nse-relative rs
make vwap            # nse-relative vwap
make scan            # nse-relative scan all
make clean           # remove generated data
```

---

## 📐 Alpha Pipeline — 12-Step Formula

For a **detailed, step-by-step explanation** of every formula (with notation,
intuition, implementation, assumptions, and references), see:

> **[`docs/alpha_pipeline.md`](docs/alpha_pipeline.md)**

### Quick summary

| Phase | Step | Formula | What it does |
|-------|------|---------|-------------|
| **1. Preprocessing** | 1 | $X = R - \bar{R}$ | Remove each stock's drift |
| | 2 | $\sigma^2 = \frac{1}{M}\sum X^2$ | Estimate volatility |
| | 3 | $Y = X / \sigma$ | Z-score normalise |
| | 4 | Truncate to $M-1$ | Drop most recent period |
| **2. Cross-sectional** | 5 | $\Lambda = Y - \bar{Y}$ | Strip market-wide bias |
| | 6 | Trim to $d$ periods | Align estimation window |
| **3. Alpha extraction** | 7 | $E = \frac{1}{d}\sum R_{\text{last }d}$ | Expected return |
| | 8 | $E_n = E / \sigma$ | Risk-adjust (Sharpe-like) |
| | 9 | $\varepsilon = \text{residual}(E_n \sim \bar{\Lambda})$ | **Pure alpha** via OLS |
| | 10 | $w_{\text{raw}} = \eta \cdot \varepsilon / \sigma$ | Inverse-vol weighting |
| | 11 | $w = w_{\text{raw}} / \sum|w_{\text{raw}}|$ | Budget constraint |
| | 12 | $CS = \sum w \cdot S$ | Combined signal scalar |

---

## 🧩 Options Pipeline — Design

### Domain model

```
OptionContract (dataclass)
├── instrument_key: str         # NSE_FO|{exchange_token}
├── tradingsymbol: str          # e.g. NIFTY26JUN23600CE
├── underlying_name: str        # Company name or index name
├── underlying_type: str        # "STOCK" or "INDEX"
├── instrument_type: str        # OPTSTK / OPTIDX / FUTSTK / FUTIDX
├── option_type: str            # CE / PE / FF
├── expiry: date
├── strike: float | None
├── lot_size: int
└── tick_size: float
```

### Discovery strategies

| Type | Discovery method | Filtering |
|---|---|---|
| **OPTSTK** (stock options) | Match `name` column against NSE equity ISIN‑derived names | Only contracts whose underlying is in the target NSE index |
| **OPTIDX** (index options) | Auto‑discovered from Upstox instrument master CSV `OPTIDX` section | All available indices, or restrict via `UPSTOX_OPTIONS_INDEX_NAMES` |
| **FUTSTK / FUTIDX** | Same as OPTSTK / OPTIDX | Only when `--include-futures` is passed |

### Expiry filtering

```
contracts_df → groupby("name") → sort("expiry") → keep first N expiry dates
                                                      ↓
                                              All strikes × CE/PE for those dates
```

- **Per‑underlying** expiry grouping (not a global cutoff) — correct for mixed weekly/monthly cycles
- NIFTY (weekly) → next 2 weekly expiries
- Stocks (monthly) → next 2 monthly expiries

### Contract manifest

All fetched contracts are catalogued in `_contracts.parquet` — enables O(1) queries:

```python
from nse_relative.pipeline import storage as store

# All contracts for NIFTY
store.query_contracts("upstox_options", underlying_name="NIFTY")

# All CE contracts expiring on a specific date
store.query_contracts("upstox_options", expiry="2026-06-09", option_type="CE")
```

---

## 📐 RS Formula

```
stock_return  = close_today / close_50_weeks_ago
nifty_return  = nifty_today / nifty_50_weeks_ago
RS            = (stock_return / nifty_return) - 1
```

- **RS > 0** → stock outperformed Nifty 500 over the lookback period.
- Data is resampled to **weekly (Friday)** before computation.

---

## 🙏 Disclaimer

This tool fetches data from **NSE India**, **Upstox**, **Chartink**, **Screener.in**, and **Trendlyne**.  
Respect each platform's terms of service and rate limits.  
The author is **not responsible** for any misuse, financial losses, or API violations.

---

## 📜 License

MIT — see [LICENSE](LICENSE).
