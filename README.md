<div align="center">

# 📈 NSE / Upstox Data Pipeline

**Multi-source pipeline for Indian financial market data — Equities, Options & Futures**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-purple)](https://github.com/astral-sh/ruff)

</div>

---

## 🔥 Overview

Fetches historical market data from **two sources** and stores it in Parquet format for analysis.

| Source | Equities | Stock Options (OPTSTK) | Index Options (OPTIDX) | Futures | Index |
|---|---|---|---|---|---|
| **NSE India** (website API) | ✅ Daily OHLCV | ❌ | ❌ | ❌ | ✅ Nifty 500 |
| **Upstox** (V2 API) | ✅ Day/Week/Month | ✅ All strikes × expiries | ✅ NIFTY, BANKNIFTY, etc. | ✅ FUTSTK/FUTIDX | ❌ |

Key capabilities:
- **NSE Equity data** — 20+ index constituent lists (Nifty 50, 500, etc.)
- **Upstox Equity data** — ISIN-filtered against any NSE index
- **Options chain** — Full strike/expiry discovery for stock + index options
- **Expiry-aware filtering** — Per-underlying, keeps next N expiries (all strikes)
- **Incremental fetch** — Per-symbol checkpoint avoids re-downloads
- **Contract manifest** — `_contracts.parquet` enables expiry-based queries
- **Parallel downloads** — ThreadPoolExecutor with rate limiting

> 📖 **Detailed command reference**: [docs/commands.md](docs/commands.md)

---

## 🚀 Setup

### Prerequisites
- Python 3.10+
- Git

### Installation

```bash
# Clone
git clone <your-repo-url>
cd nse-data-repo

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
# source venv/bin/activate

# Install
pip install -e ".[dev]"
```

### Configuration (optional)

```bash
cp .env.example .env
```

All defaults work out of the box — no API keys required. The `.env` file lets you override fetch date ranges, intervals, and logging level.

---

## 📊 Quick Start

```bash
# ── Equities ──────────────────────────────────────────

# Fetch Nifty 50 equities + Nifty 500 index
nse-relative fetch --provider nse --index nifty50

# Fetch Upstox equity data (Nifty 200, monthly candles)
nse-relative fetch --provider upstox --index nifty200 --interval month

# ── Options & Futures ─────────────────────────────────

# Stock options for Nifty 50 (next 2 expiries, all strikes, daily)
nse-relative fetch --provider upstox_options --index nifty50

# Index options (NIFTY, BANKNIFTY, FINNIFTY, etc.)
nse-relative fetch --provider upstox_options --instrument-types OPTIDX

# Everything: stock options + index options + futures
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures
```

---

## 🎯 Options & Futures — Deep Dive

This is the most powerful feature. Here's exactly how it works.

### How contract discovery works

```
1. Upstox instrument master CSV (~200K rows) is downloaded
   └── Filtered to exchange="NSE_FO"

2. For STOCK OPTIONS (OPTSTK):
   └── Nifty 50 ISINs are matched against Upstox NSE_EQ instruments
       └── Company names extracted → used to filter OPTSTK contracts

3. For INDEX OPTIONS (OPTIDX):
   └── Auto-discovered from the instrument master's OPTIDX section
       └── All available indices included (or restricted via config)

4. Expiry filtering (per underlying, not global):
   └── Contracts grouped by underlying stock/index
       └── Sorted by expiry date → keep only next N unique dates
           └── ALL strikes × (CE + PE) kept for those dates
```

### What you get per contract

Each file (e.g. `RELIANCE26JUN1230CE.parquet`) contains:

| Column | Example | Description |
|---|---|---|
| `date` | `2026-05-12` | Trading date (IST) |
| `open/high/low/close` | `52.30` | OHLC prices |
| `vol` | `2,340` | Traded quantity (contracts) |
| `oi` | `1,365` | Open Interest |
| `symbol` | `RELIANCE26JUN1230CE` | Tradingsymbol |
| `instrument_type` | `OPTSTK` | OPTSTK / OPTIDX / FUTSTK / FUTIDX |
| `option_type` | `CE` | CE / PE / FF |
| `expiry` | `2026-06-26` | Contract expiry date |
| `strike` | `1230.0` | Strike price |
| `lot_size` | `100` | Lot multiplier |
| `underlying_name` | `RELIANCE` | Company or index name |

### Expiry filter — how it works

```
Per-underlying grouping (not a global expiry cutoff):

NIFTY (index, weekly expiry):
  ├── Expiry 1: Jun 09 (all strikes × CE/PE)
  └── Expiry 2: Jun 16 (all strikes × CE/PE)

RELIANCE (stock, monthly expiry):
  ├── Expiry 1: Jun 26 (all strikes × CE/PE)
  └── Expiry 2: Jul 30 (all strikes × CE/PE)
```

### Historical vs current data

| Option | Behavior | Use case |
|---|---|---|
| `--n-expiries 2` (default) | Fetches only **next 2 upcoming** expiries per underlying | Current trading, active contracts |
| `--n-expiries 0` | Disables filter — fetches **ALL** discoverable contracts | Full historical archive (includes recently expired) |
| `--n-expiries 5` | Keeps next 5 expiries per underlying | Wider coverage |

> ⚠️ The Upstox instrument master CSV only contains **currently listed + recently expired** contracts. Very old expired contracts may not be discoverable. For deep historical options data, use `--n-expiries 0` to get everything available.

### Available index options

Auto-discovered indices (check list by running the fetcher):
`BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, `NIFTY`, `NIFTYNXT50`, `SENSEX`, `SENSEX50`, and more.

### Examples

```bash
# Stock options for Nifty 50 constituents (default: 2 expiries)
nse-relative fetch --provider upstox_options --index nifty50

# Index options ONLY
nse-relative fetch --provider upstox_options --instrument-types OPTIDX

# Combined: stock + index options + futures
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures

# All expiries (disable expiry filter)
nse-relative fetch --provider upstox_options --index nifty50 \
  --n-expiries 0

# Next 3 expiries per underlying
nse-relative fetch --provider upstox_options --index nifty50 \
  --n-expiries 3

# Specific contract tradingsymbols
nse-relative fetch --provider upstox_options \
  --symbols NIFTY26JUN23600CE NIFTY26JUN23600PE

# Weekly candle interval
nse-relative fetch --provider upstox_options --index nifty50 \
  --interval week
```

---

## 📂 Data Storage

```
data/
│
├── nse/
│   ├── _checkpoint.json          # Per-symbol fetch tracking
│   ├── equities_{year}.parquet   # Yearly partitions
│   ├── equities.parquet          # Consolidated all years
│   └── indices.parquet           # Nifty 500 benchmark
│
└── upstox/
    ├── _checkpoint.json
    ├── {SYMBOL}.parquet          # Per-equity files (RELIANCE.parquet, etc.)
    │
    └── upstox_options/           # F&O data
        ├── _checkpoint.json
        ├── _contracts.parquet    # 📋 Contract manifest (expiry-queryable)
        ├── NIFTY/
        │   ├── 260609/           # Expiry 2026-06-09 (weekly)
        │   │   ├── NIFTY26060923600CE.parquet
        │   │   └── ...
        │   └── 260630/           # Expiry 2026-06-30 (monthly)
        │       ├── NIFTY26JUN23600CE.parquet
        │       └── ...
        ├── WIPRO/
        │   ├── 260630/
        │   │   ├── WIPRO26JUN160CE.parquet
        │   │   └── ...
        │   └── 260731/
        │       └── ...
        ├── RELIANCE/
        │   └── ...
        └── (legacy flat files from previous runs)
```

### Querying the contract manifest

```python
from nse_relative.infrastructure.storage.manifest import ContractManifest
from nse_relative.infrastructure.storage.file_repository import FileStorageRepository

storage = FileStorageRepository()
manifest = ContractManifest(storage, "upstox_options")

# All NIFTY contracts
nifty = manifest.query(underlying_name="NIFTY")

# All CE contracts for a specific expiry
calls = manifest.query(expiry="2026-06-09", option_type="CE")
```

---

## 🏗️ Codebase Structure

```
src/nse_relative/
│
├── cli.py                          # CLI entry point (argparse + dispatch)
├── __init__.py                     # Package metadata
├── __main__.py                     # `python -m nse_relative` entry
│
├── config/
│   ├── settings.py                 # All env-var configuration
│   └── logger.py                   # Logging setup
│
├── domain/
│   ├── models.py                   # Domain models: OptionContract, enums, value objects
│   └── coverage.py                 # CoverageRange, CheckpointData
│
├── application/
│   └── fetch_service.py            # Fetch orchestration + dependency wiring
│
├── infrastructure/
│   ├── api/
│   │   ├── nse_client.py           # NSE HTTP client + response parsing
│   │   └── upstox_client.py        # Upstox HTTP client (shared by equity + F&O)
│   ├── checkpoint/
│   │   └── json_checkpoint.py      # Per-provider incremental fetch tracking
│   ├── storage/
│   │   ├── repository.py           # Storage protocol/interface
│   │   ├── file_repository.py      # Filesystem implementation (Parquet/CSV)
│   │   └── manifest.py             # Contract manifest CRUD
│   └── symbol_source/
│       ├── nse_index_csv.py        # NSE index constituent fetcher
│       └── upstox_instruments.py   # Upstox instrument master + option discovery
│
├── pipeline/
│   ├── base.py                     # DataProvider abstract base
│   ├── nse_provider.py            # NSE equity + index fetching
│   ├── upstox_provider.py         # Upstox equity fetching
│   └── upstox_options_provider.py # 🎯 F&O options + futures fetching
│
└── shared/
    ├── rate_limiter.py             # Exponential backoff rate limiter
    ├── exceptions.py               # Domain exception hierarchy
    └── utils.py                    # Date helpers
```

### Data flow

```
                    ┌──────────────────┐
                    │     Upstox API    │
                    │  V2 Historical    │
                    └────────┬─────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
    ┌─────────────────┐          ┌────────────────────┐
    │  UpstoxProvider  │          │UpstoxOptionsProvider│
    │  (equities)      │          │  (options/futures)  │
    │                  │          │                     │
    │  ISIN-filtered   │          │  instrument master  │
    │  symbol list     │          │  → discover contracts│
    │  from NSE index  │          │  → filter by expiry │
    └────────┬─────────┘          │  → all strikes × CE/PE
             │                    └──────────┬──────────┘
             ▼                               ▼
    ┌─────────────────┐          ┌────────────────────┐
    │  FileStorageRepo │          │  FileStorageRepo    │
    │  data/upstox/    │          │  data/upstox/       │
    │  {sym}.parquet   │          │  upstox_options/    │
    └─────────────────┘          └────────────────────┘

    ┌──────────────────┐
    │    NSE Website   │
    │  Public API      │
    └────────┬─────────┘
             │
             ▼
    ┌─────────────────┐
    │  NSEProvider     │
    │  (equities+index)│
    └────────┬─────────┘
             ▼
    ┌─────────────────┐
    │  FileStorageRepo │
    │  data/nse/       │
    │  equities.parquet│
    │  indices.parquet │
    └─────────────────┘
```

---

## ⚙️ Configuration

Copy `.env.example` → `.env` and adjust as needed:

| Variable | Default | Description |
|---|---|---|
| **NSE** | | |
| `NSE_DEFAULT_INDEX` | `nifty500` | Default NSE index |
| `NSE_FETCH_START` | `01-01-2021` | Fetch start (DD-MM-YYYY) |
| `NSE_FETCH_END` | (today) | Fetch end date |
| `NSE_FETCH_CHUNK_DAYS` | `110` | API chunk size |
| `NSE_STORAGE_FORMAT` | `parquet` | `parquet` or `csv` |
| `NSE_RATE_MAX_WORKERS` | `5` | Parallel workers |
| `NSE_LOG_LEVEL` | `INFO` | Logging verbosity |
| **Upstox (equities)** | | |
| `UPSTOX_INTERVAL` | `month` | Candle interval |
| `UPSTOX_MAX_WORKERS` | `10` | Parallel workers |
| `UPSTOX_FETCH_START` | `01-01-2000` | Fetch start date |
| **Upstox (F&O)** | | |
| `UPSTOX_OPTIONS_INTERVAL` | `day` | Options interval |
| `UPSTOX_OPTIONS_FETCH_START` | `01-01-2024` | Fetch start |
| `UPSTOX_OPTIONS_TYPES` | `OPTSTK` | F&O types to fetch |
| `UPSTOX_OPTIONS_N_EXPIRIES` | `2` | Expiry cycles per underlying |
| `UPSTOX_OPTIONS_INDEX_NAMES` | (auto) | Restrict index options |

**Rate limiter:** `NSE_RATE_INITIAL_DELAY=0.5`, `NSE_RATE_MAX_DELAY=30.0`, `NSE_RATE_BACKOFF_FACTOR=2.0`, `NSE_FETCH_MAX_RETRIES=5`

---

## 🔧 Troubleshooting

### `ModuleNotFoundError: No module named 'nse_relative.presentation'`

The entry point script is stale. Reinstall the package:

```bash
pip uninstall nse-relative -y
pip install -e .
```

### Entry point still fails after reinstall

Use the module directly as a fallback — this always picks up the latest code:

```bash
python -m nse_relative fetch --provider upstox --index nifty50
```

### Unicode/encoding errors on Windows

The pipeline uses plain ASCII in log messages (`->` instead of `→`, `..` instead of `…`).
If you still see encoding errors, set your console to UTF-8:

```bash
chcp 65001
```

---

## 🔧 Development

```bash
# Editable install
pip install -e ".[dev]"

# Tests
pytest

# Lint
ruff check src/
ruff format src/

# Type-check
mypy src/

# See commands
nse-relative --help
nse-relative fetch --help
```

---

## 📖 Further Reading

- **[docs/commands.md](docs/commands.md)** — Full command reference with examples
- **`requirements.txt`** — Runtime dependencies (install with `pip install -r requirements.txt`)
- **`requirements-dev.txt`** — Dev dependencies (includes linting, testing)
- **`.env.example`** — All configurable environment variables
- **`pyproject.toml`** — Project metadata and dependencies

---

## 📄 License

MIT
