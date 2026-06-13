# 📋 NSE Data Pipeline — Complete Command Reference

> Full reference for every `nse-relative` command and option.
> Also available at: `nse-relative --help` / `nse-relative fetch --help`

---

## 🔹 Global Options

| Option | Description |
|---|---|
| `--version` | Print version number and exit |
| `--help` | Show help message and exit |

---

## 🔹 `fetch` — Fetch Market Data

```
nse-relative fetch [options]
```

### All Options

| Option | Alias | Type | Default | Description |
|---|---|---|---|---|
| `--provider` | `-p` | `nse` / `upstox` / `upstox_options` | `nse` | Data source |
| `--index` | `-x` | *one of 21 NSE indices* | `nifty500` | NSE index for symbol sourcing |
| `--underlying` | — | string | *(none)* | Single stock/index name for F&O (e.g. WIPRO, NIFTY, RELIANCE) |
| `--symbols` | `-s` | space-separated list | *(all)* | Restrict to specific symbols |
| `--start` / `--from` | — | `DD-MM-YYYY` | env default | Fetch start date |
| `--end` / `--to` | — | `DD-MM-YYYY` | env / today | Fetch end date |
| `--interval` | `-i` | `day` / `week` / `month` | provider default | Candle bar interval |
| `--instrument-types` | `-t` | comma-sep: `OPTSTK,OPTIDX` | `OPTSTK` | F&O contract types to fetch |
| `--include-futures` | — | flag | `False` | Also fetch FUTSTK/FUTIDX |
| `--n-expiries` | — | integer | `2` | Expiry cycles per underlying (`0`=all) |
| `--force` | `-f` | flag | `False` | Ignore checkpoint, re-fetch all |
| `--skip-index` | — | flag | `False` | Skip index fetch (NSE only) |

---

### 📈 Equities — NSE

Fetch daily OHLCV data from the NSE India public website, plus Nifty 500 index.

```bash
# Basic — Nifty 50 equities + Nifty 500 index
nse-relative fetch --provider nse --index nifty50

# All ~750 listed stocks
nse-relative fetch --provider nse --index nifty_total_market

# Custom date range (required for data before 2021)
nse-relative fetch --provider nse --index nifty50 \
  --start 01-01-2000 --end 01-06-2026

# Specific symbols only
nse-relative fetch --provider nse --symbols RELIANCE TCS HDFCBANK \
  --start 01-01-2010 --end 01-06-2026

# Equities only — skip index data
nse-relative fetch --provider nse --index nifty50 --skip-index

# Force re-fetch everything (bypass checkpoint)
nse-relative fetch --provider nse --force
```

**Available indices** (21 total):
`nifty50`, `nifty100`, `nifty200`, `nifty500`, `nifty_total_market`, `nifty_next_50`, `nifty_midcap_50`, `nifty_midcap_150`, `nifty_smallcap_50`, `nifty_smallcap_100`, `nifty_smallcap_250`, `nifty_microcap_250`, `nifty_large_midcap_250`, `nifty_mid_smallcap_400`, `nifty200_momentum_30`, `nifty_midcap150_momentum_50`, `nifty500_momentum_50`, `nifty500_multicap_50_25_25`, `nifty500_large_mid_small_equal`, `nifty_mid_smallcap400_momentum_quality_100`, `nifty_smallcap250_momentum_quality_100`

```bash
# See full list with URLs
nse-relative list-indices
```

---

### 📈 Equities — Upstox

Fetch candle data (day/week/month) for NSE equities via Upstox V2 API.
Symbols are ISIN-filtered against the chosen NSE index.

```bash
# Nifty 500 equities (default), monthly candles
nse-relative fetch --provider upstox

# Nifty 200, daily candles, full history
nse-relative fetch --provider upstox --interval day --index nifty200 \
  --start 01-01-2000

# Nifty 50, weekly candles, custom date range
nse-relative fetch --provider upstox --interval week --index nifty50 \
  --start 01-01-2010 --end 01-06-2026

# Specific symbols only
nse-relative fetch --provider upstox --symbols RELIANCE TCS HDFCBANK

# Force re-fetch
nse-relative fetch --provider upstox --force
```

---

### 🎯 Options & Futures — Upstox F&O

The most powerful feature. Discovers contracts from the Upstox instrument master, applies expiry filtering, and fetches daily OHLCV+OI candles.

#### How Discovery Works

```
1. Download Upstox instrument master CSV (~200K rows)
   └── Filter to exchange="NSE_FO"

2. STOCK OPTIONS (OPTSTK):
   └── Match NSE index ISINs → find company names
       └── Filter OPTSTK contracts by those names

3. INDEX OPTIONS (OPTIDX):
   └── Auto-discovered from instrument master
       └── All available indices included

4. EXPIRY FILTERING (per underlying):
   └── Group contracts by underlying stock/index
       └── Sort by expiry → keep next N unique dates
           └── ALL strikes × (CE + PE) kept
```

#### Stock Options — Nifty 50

```bash
# Nifty 50 stock options — next 2 expiries, all strikes, daily
nse-relative fetch --provider upstox_options --index nifty50

# Custom date range
nse-relative fetch --provider upstox_options --index nifty50 \
  --start 01-01-2024 --end 01-06-2026

# Next 5 expiries per stock
nse-relative fetch --provider upstox_options --index nifty50 \
  --n-expiries 5

# All expiries (disable expiry filter)
nse-relative fetch --provider upstox_options --index nifty50 \
  --n-expiries 0

# Weekly candle interval
nse-relative fetch --provider upstox_options --index nifty50 \
  --interval week
```

#### Single Stock Options (`--underlying`)

Fetch options for just **one** underlying stock instead of a whole index.
Uses the Nifty 500 index as the default symbol universe, then filters
down to the matching stock by extracting the short name from the
tradingsymbol (e.g. `WIPRO26JUN160CE` → `WIPRO`).

```bash
# All options for WIPRO (default: next 2 expiries)
nse-relative fetch --provider upstox_options --underlying WIPRO

# With date range
nse-relative fetch --provider upstox_options --underlying WIPRO \
  --start 01-01-2024 --end 06-06-2026

# Next 5 expiries for WIPRO
nse-relative fetch --provider upstox_options --underlying WIPRO \
  --n-expiries 5

# All expiries (0 = disable filter)
nse-relative fetch --provider upstox_options --underlying WIPRO \
  --n-expiries 0

# Index options for a single index (NIFTY, BANKNIFTY, etc.)
nse-relative fetch --provider upstox_options --underlying NIFTY \
  --instrument-types OPTIDX
```

#### Index Options

```bash
# All index options (NIFTY, BANKNIFTY, FINNIFTY, SENSEX, etc.)
nse-relative fetch --provider upstox_options --instrument-types OPTIDX

# Index options with custom date range
nse-relative fetch --provider upstox_options --instrument-types OPTIDX \
  --start 01-01-2024 --end 01-06-2026

# Index options, next 3 expiries
nse-relative fetch --provider upstox_options --instrument-types OPTIDX \
  --n-expiries 3
```

#### Combinations

```bash
# Stock options + Index options
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX"

# Stock options + Index options + Futures
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures

# All asset classes, custom range, next 3 expiries
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures \
  --start 01-01-2024 --end 01-06-2026 --n-expiries 3
```

#### Futures Only

```bash
# Stock futures + index futures
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "FUTSTK,FUTIDX"
```

#### Specific Contract Tradingsymbols

```bash
nse-relative fetch --provider upstox_options \
  --symbols NIFTY26JUN23600CE NIFTY26JUN23600PE RELIANCE26JUN1230CE
```

#### Force Re-fetch

```bash
nse-relative fetch --provider upstox_options --force
nse-relative fetch --provider upstox_options --index nifty50 --force
```

---

## 🔹 `list-providers` — Show Providers

```bash
nse-relative list-providers
```

Output:
```
Available providers:
  - nse
  - upstox
  - upstox_options
```

---

## 🔹 `list-indices` — Show NSE Indices

List all 21 NSE index constituent lists with their approximate sizes.

```bash
nse-relative list-indices
```

Sample output:
```
Available NSE index constituent lists:
  - nifty50
  - nifty100
  - nifty200
  - nifty500
  - nifty_total_market
  ...
```

> Note: Some indices fetch live from NSE servers — first call may be slow.

---

## 🔹 Examples Cheatsheet

```bash
# ═══════════════════════════════════════════════════════════
# QUICK STARTERS
# ═══════════════════════════════════════════════════════════

# 1. Nifty 50 equities + index data
nse-relative fetch -p nse -x nifty50

# 2. Nifty 200 equities from Upstox (daily)
nse-relative fetch -p upstox -x nifty200 -i day

# 3. Nifty 50 stock options (next 2 expiries, all strikes)
nse-relative fetch -p upstox_options -x nifty50

# 4. All index options (NIFTY, BANKNIFTY, etc.)
nse-relative fetch -p upstox_options -t OPTIDX

# 5. Everything: stock opts + index opts + futures
nse-relative fetch -p upstox_options -x nifty50 \
  -t "OPTSTK,OPTIDX" --include-futures

# ═══════════════════════════════════════════════════════════
# DATE RANGE EXAMPLES
# ═══════════════════════════════════════════════════════════

# NSE equities — full history from 2000
nse-relative fetch -p nse -x nifty50 --start 01-01-2000 --end 01-06-2026

# Upstox equities — last 5 years
nse-relative fetch -p upstox -x nifty200 -i month \
  --start 01-01-2021 --end 01-06-2026

# Options — since listing
nse-relative fetch -p upstox_options -x nifty50 \
  --start 01-01-2024 --end 01-06-2026

# Options — just current year
nse-relative fetch -p upstox_options -t OPTIDX \
  --start 01-01-2026 --end 01-06-2026

# ═══════════════════════════════════════════════════════════
# EXPIRY CONTROL
# ═══════════════════════════════════════════════════════════

# Next 2 expiries (default)
nse-relative fetch -p upstox_options -x nifty50

# Next 5 expiries
nse-relative fetch -p upstox_options -x nifty50 --n-expiries 5

# ALL expiries (disable filter)
nse-relative fetch -p upstox_options -x nifty50 --n-expiries 0

# ═══════════════════════════════════════════════════════════
# FORCE RE-FETCH
# ═══════════════════════════════════════════════════════════

nse-relative fetch -p nse --force
nse-relative fetch -p upstox --force
nse-relative fetch -p upstox_options --force

# ═══════════════════════════════════════════════════════════
# SINGLE STOCK F&O (--underlying)
# ═══════════════════════════════════════════════════════════

# WIPRO — next 2 expiries (default)
nse-relative fetch -p upstox_options --underlying WIPRO

# WIPRO — last 5 expiries
nse-relative fetch -p upstox_options --underlying WIPRO --n-expiries 5

# WIPRO — full date range
nse-relative fetch -p upstox_options --underlying WIPRO \
  --start 01-01-2024 --end 06-06-2026

# RELIANCE — all expiries (disable expiry filter)
nse-relative fetch -p upstox_options --underlying RELIANCE --n-expiries 0

# NIFTY index options (single index)
nse-relative fetch -p upstox_options --underlying NIFTY -t OPTIDX

# ═══════════════════════════════════════════════════════════
# SPECIFIC SYMBOLS
# ═══════════════════════════════════════════════════════════

# NSE equities
nse-relative fetch -p nse -s RELIANCE TCS HDFCBANK

# Upstox equities
nse-relative fetch -p upstox -s RELIANCE TCS HDFCBANK

# F&O contracts by tradingsymbol
nse-relative fetch -p upstox_options \
  -s NIFTY26JUN23600CE NIFTY26JUN23600PE

# ═══════════════════════════════════════════════════════════
# INTERVAL CONTROL (Upstox only)
# ═══════════════════════════════════════════════════════════

nse-relative fetch -p upstox -i day
nse-relative fetch -p upstox -i week
nse-relative fetch -p upstox -i month
nse-relative fetch -p upstox_options -i day
```

---

## ⚠️ Troubleshooting

### `nse-relative: command not found`

The venv isn't activated or the package isn't installed:

```bash
# Activate venv (Windows)
venv\Scripts\activate

# Install
pip install -e .
```

### `ModuleNotFoundError: No module named 'nse_data_pipeline.presentation'`

Stale entry point executable. Reinstall:

```bash
pip uninstall nse-relative -y
pip install -e .
```

Or use the module directly:

```bash
python -m nse_data_pipeline fetch --provider upstox --index nifty50
```

### Unicode/encoding errors on Windows

If you see `UnicodeEncodeError: 'charmap' codec can't encode character`,
set your console to UTF-8:

```bash
chcp 65001
```

---

## 📖 See Also

- **README.md** — Overview, setup, architecture, data storage
- **`requirements.txt`** — Runtime dependencies
- **`requirements-dev.txt`** — Dev dependencies
- **`.env.example`** — All configurable environment variables
- **`pyproject.toml`** — Project metadata and dependencies
