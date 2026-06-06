<div align="center">

# 📊 NSE / Upstox Data Pipeline

**Multi-source data pipeline for Indian financial market data — equities, options & futures**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-purple)](https://github.com/astral-sh/ruff)

</div>

---

## 🔥 What it does

Fetches historical market data from **two sources** and stores it in a clean, queryable format:

| Source | Equities | Options (OPTSTK) | Index Options (OPTIDX) | Futures | Index |
|---|---|---|---|---|---|
| **NSE India** (public API) | ✅ Daily OHLCV | ❌ | ❌ | ❌ | ✅ Nifty 500 |
| **Upstox** (V2 API) | ✅ Day/Week/Month | ✅ | ✅ | ✅ | ❌ |

Key features:
- **Incremental fetch** — checkpoint system skips already-downloaded date ranges
- **Per-symbol tracking** — knows exact date coverage for every instrument
- **Contract manifest** — expiry-queryable catalog of all F&O contracts
- **Expiry-aware filtering** — fetch only the next N expiries per underlying
- **Parallel fetching** — ThreadPoolExecutor for concurrent downloads
- **Rate limiting** — exponential backoff for HTTP 429 responses
- **Unified metadata catalog** — single registry of all downloaded instruments

---

## 🚀 Quick Start

### 1. Clone & setup

```bash
git clone <your-repo-url>
cd nse-data-repo

# Create virtual environment (Python 3.10+)
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
# source venv/bin/activate
```

### 2. Install

```bash
# Development install with all dependencies
pip install -e ".[dev]"

# Or from requirements.txt
pip install -r requirements.txt
```

### 3. Configure

Copy the environment template and adjust if needed:

```bash
cp .env.example .env
# Edit .env to set fetch dates or other options
```

The defaults work out of the box for fetching — no API keys required for NSE or Upstox data.

### 4. Fetch data

```bash
# Fetch NSE equity data + Nifty 500 index (Nifty 50 constituents)
nse-relative fetch --provider nse --index nifty50

# Fetch Upstox equity data (monthly candles, Nifty 200 universe)
nse-relative fetch --provider upstox --index nifty200 --interval month

# Fetch F&O options (stock options for Nifty 50, next 2 expiries)
nse-relative fetch --provider upstox_options --index nifty50

# Fetch index options + stock options + futures
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures

# Force re-fetch everything (bypass checkpoint)
nse-relative fetch --provider nse --force
```

### 5. Explore stored data

```bash
nse-relative list-providers         # Show providers + stored counts
nse-relative list-indices           # List all NSE index constituent lists
nse-relative list-symbols           # List stored equity symbols with coverage
nse-relative list-symbols --asset-class derivative   # List stored F&O contracts
```

---

## 📋 CLI Reference

### `nse-relative fetch`

| Option | Description | Default |
|---|---|---|
| `--provider, -p` | Data source: `nse`, `upstox`, `upstox_options` | `nse` |
| `--index, -x` | NSE index constituent list (e.g. `nifty50`, `nifty500`) | `nifty500` |
| `--symbols, -s` | Limit to specific symbols / tradingsymbols | all |
| `--start` / `--from` | Start date `DD-MM-YYYY` | env default |
| `--end` / `--to` | End date `DD-MM-YYYY` | env or today |
| `--interval, -i` | Candle interval: `day`, `week`, `month` | provider default |
| `--force, -f` | Ignore checkpoint, re-fetch all | `False` |
| `--skip-index` | Skip Nifty 500 index fetch (NSE only) | `False` |
| **F&O specific:** | | |
| `--instrument-types, -t` | Comma-separated: `OPTSTK`, `OPTIDX` | `OPTSTK` |
| `--include-futures` | Also fetch `FUTSTK` / `FUTIDX` | `False` |
| `--n-expiries` | Upcoming expiry cycles per underlying (`0` = all) | `2` |

#### Examples

```bash
# NSE — all ~750 stocks (nifty_total_market)
nse-relative fetch --provider nse --index nifty_total_market

# NSE — specific symbols
nse-relative fetch --provider nse --symbols RELIANCE TCS HDFCBANK

# Upstox — daily candles for Nifty 200 from 2020
nse-relative fetch --provider upstox --interval day --index nifty200 --start 01-01-2020

# Upstox — monthly candles, full history
nse-relative fetch --provider upstox --interval month --index nifty500

# F&O — index options only (all available indices)
nse-relative fetch --provider upstox_options --instrument-types OPTIDX

# F&O — next 3 expiries per underlying
nse-relative fetch --provider upstox_options --n-expiries 3

# F&O — specific tradingsymbols
nse-relative fetch --provider upstox_options \
  --symbols NIFTY26JUN23600CE NIFTY26JUN23600PE
```

### List commands

```bash
nse-relative list-providers        # Show providers + stored instrument counts
nse-relative list-asset-classes    # Show asset classes with data
nse-relative list-indices          # Show all 20+ NSE index constituent lists
nse-relative list-instruments      # Show detailed coverage from catalog
nse-relative list-symbols          # List stored symbols with date ranges
nse-relative list-symbols -a derivative   # List stored F&O contracts
nse-relative --version             # Show version
```

### Migration (from old flat format)

```bash
# Migrate NSE data from old flat-file format to new structured layout
nse-relative migrate --provider nse

# Migrate Upstox data
nse-relative migrate --provider upstox
```

---

## 📂 Data Storage Layout

The pipeline uses a **provider-partitioned, asset-class-aware** storage scheme:

```
data/
├── _catalog.parquet              # 🔄 Unified metadata registry (all providers)
│
├── nse/
│   ├── _checkpoint.json          # Per-symbol fetch tracking
│   ├── equities/
│   │   ├── RELIANCE.parquet      # One file per symbol
│   │   ├── TCS.parquet
│   │   └── ...
│   └── indices/
│       └── NIFTY 500.parquet     # Benchmark index data
│
└── upstox/
    ├── _checkpoint.json
    ├── equities/
    │   ├── RELIANCE.parquet
    │   ├── TCS.parquet
    │   └── ...
    └── derivatives/
        ├── _contracts.parquet    # 📋 Contract manifest (expiry-queryable)
        ├── NIFTY26JUN23600CE.parquet  # Per-contract files
        ├── NIFTY26JUN23600PE.parquet
        └── ...
```

### Contract manifest

The `_contracts.parquet` file acts as a queryable catalog — enables O(1) expiry-based lookups without scanning individual files:

```python
from nse_relative.infrastructure.repositories import DerivativeRepository
from nse_relative.config.settings import UPSTOX_STORAGE_DIR

repo = DerivativeRepository("upstox", UPSTOX_STORAGE_DIR)

# All NIFTY contracts
nifty_contracts = repo.query_manifest(underlying_name="NIFTY")

# All CE contracts expiring on a specific date
calls = repo.query_manifest(expiry="2026-06-09", option_type="CE")
```

### Checkpoint tracking

Each provider's `_checkpoint.json` tracks per-symbol coverage:

```json
{
  "version": 2,
  "last_updated": "2026-06-06T12:00:00",
  "asset_classes": {
    "equity": {
      "nifty50": {
        "RELIANCE": {
          "date_min": "2000-01-07",
          "date_max": "2026-06-05",
          "rows": 6134
        }
      }
    }
  }
}
```

---

## 🏗️ Architecture

The codebase follows a **clean architecture** pattern with four layers:

```
┌──────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER                        │
│                   cli.py — Thin CLI dispatch                  │
├──────────────────────────────────────────────────────────────┤
│                     APPLICATION LAYER                         │
│    FetchOrchestrator        InstrumentService                │
│    (coordinates fetching)   (queries coverage)               │
├──────────────────────────────────────────────────────────────┤
│                    INFRASTRUCTURE LAYER                       │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │  Providers    │  │ Repositories │  │  Persistence       │   │
│  │  NSEProvider  │  │  EquityRepo  │  │  CheckpointStore   │   │
│  │  UpstoxProv.  │  │  DerivRepo   │  │  MetadataCatalog   │   │
│  │               │  │  IndexRepo   │  │  Serializers       │   │
│  └──────────────┘  └──────────────┘  └───────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  API Layer                                            │    │
│  │  SymbolRegistry (NSE indices + Upstox instruments)    │    │
│  │  RateLimiter  (exponential backoff)                   │    │
│  └──────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│                       DOMAIN LAYER                            │
│  Instrument  Equity  DerivativeContract  Index               │
│  AssetClass  Interval  CoverageRange  Candle                 │
└──────────────────────────────────────────────────────────────┘
```

### Source tree

```
src/nse_relative/
│
├── presentation/
│   └── cli.py                       # 🆕 Thin CLI entry point
│
├── application/
│   └── services/
│       ├── fetch_orchestrator.py    # 🆕 Coordinates multi-source fetching
│       └── instrument_service.py    # 🆕 Query stored instruments/coverage
│
├── infrastructure/
│   ├── api/
│   │   ├── rate_limiter.py          # Thread-safe exponential backoff
│   │   └── symbol_registry.py       # 🆕 Live NSE index + Upstox instrument resolution
│   ├── persistence/
│   │   ├── checkpoint_store.py      # 🆕 Per-provider fetch tracking
│   │   ├── metadata_catalog.py      # 🆕 Unified Parquet-based registry
│   │   └── serializers.py           # 🆕 Parquet/CSV read/write helpers
│   ├── providers/
│   │   ├── base.py                  # 🆕 DataProvider ABC
│   │   ├── nse_provider.py          # 🆕 NSE API — equities + index
│   │   └── upstox_provider.py       # 🆕 Upstox API — equities + F&O (merged)
│   └── repositories/
│       ├── equity_repository.py     # 🆕 data/{provider}/equities/{sym}.parquet
│       ├── derivative_repository.py # 🆕 data/{provider}/derivatives/{sym}.parquet
│       └── index_repository.py      # 🆕 data/{provider}/indices/{sym}.parquet
│
├── domain/
│   ├── instruments.py               # 🆕 Instrument, Equity, DerivativeContract, Index
│   ├── data_types.py                # 🆕 AssetClass, Interval, CoverageRange, Candle
│   └── exceptions.py                # 🆕 PipelineError, FetchError, etc.
│
├── config/
│   ├── settings.py                  # Settings dataclass (from env vars)
│   └── logger.py                    # Logging setup
│
└── pipeline/                        # 🔄 Backward-compat re-exports of old API
    └── ...
```

### Data flow

```
NSE website API ──→ NSEProvider ──→ EquityRepository ──→ data/nse/equities/{sym}.parquet
                                    IndexRepository  ──→ data/nse/indices/{sym}.parquet

Upstox API ──→ UpstoxProvider ──→ EquityRepository ──→ data/upstox/equities/{sym}.parquet
                                  DerivativeRepository ──→ data/upstox/derivatives/{sym}.parquet
                                                        ─→ data/upstox/derivatives/_contracts.parquet
```

Each fetch operation:
1. Checks **CheckpointStore** — skips symbols whose date range is already covered
2. Fetches missing data from the API (with rate limiting)
3. Saves to the appropriate **Repository** (append + deduplicate)
4. Updates **CheckpointStore** with new date coverage
5. Registers in **MetadataCatalog** for unified querying

### Why this architecture?

| Principle | How it's applied |
|---|---|
| **Separation of Concerns** | Domain / Infrastructure / Application / Presentation layers |
| **Single Responsibility** | Each class has one job (fetch, store, query, orchestrate) |
| **Repository Pattern** | Consistent read/write/query interface for all asset types |
| **Dependency Injection** | Providers receive their symbol registry, catalog via constructor |
| **Domain Model** | `Instrument` hierarchy captures real-world structure |
| **Composition over Inheritance** | Providers compose repositories + checkpoint + catalog |

---

## ⚙️ Configuration

All settings are loaded from environment variables (with optional `.env` file). Copy `.env.example` → `.env` and adjust:

| Variable | Default | Description |
|---|---|---|
| **NSE** | | |
| `NSE_FETCH_START` | `01-01-2021` | Data fetch start date (DD-MM-YYYY) |
| `NSE_FETCH_END` | (today) | Data fetch end date |
| `NSE_FETCH_CHUNK_DAYS` | `110` | API chunk size (max 70 records/call) |
| `NSE_STORAGE_FORMAT` | `parquet` | Storage format (`parquet` or `csv`) |
| `NSE_RATE_MAX_WORKERS` | `5` | Parallel fetch workers |
| `NSE_LOG_LEVEL` | `INFO` | Logging verbosity |
| **Upstox (equities)** | | |
| `UPSTOX_INTERVAL` | `month` | Candle interval (`day`, `week`, `month`) |
| `UPSTOX_MAX_WORKERS` | `10` | Parallel workers |
| `UPSTOX_FETCH_START` | `01-01-2000` | Fetch start date |
| **Upstox (F&O)** | | |
| `UPSTOX_OPTIONS_INTERVAL` | `day` | Options candle interval |
| `UPSTOX_OPTIONS_MAX_WORKERS` | `5` | Parallel workers |
| `UPSTOX_OPTIONS_FETCH_START` | `01-01-2024` | Fetch start date |
| `UPSTOX_OPTIONS_TYPES` | `OPTSTK` | F&O types (`OPTSTK,OPTIDX`) |
| `UPSTOX_OPTIONS_N_EXPIRIES` | `2` | Expiry cycles per underlying (`0` = all) |
| `UPSTOX_OPTIONS_INDEX_NAMES` | (auto) | Restrict index options (e.g. `NIFTY,BANKNIFTY`) |

### Rate limiter settings

| Variable | Default | Description |
|---|---|---|
| `NSE_RATE_INITIAL_DELAY` | `0.5` | Initial delay (seconds) |
| `NSE_RATE_MAX_DELAY` | `30.0` | Maximum delay after backoff |
| `NSE_RATE_BACKOFF_FACTOR` | `2.0` | Multiplicative backoff factor |
| `NSE_FETCH_MAX_RETRIES` | `5` | Max retries per request |
| `NSE_FETCH_SLEEP` | `0.1` | Sleep between requests |

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

# See all CLI commands
nse-relative --help
nse-relative fetch --help
```

### Migrating from old format

If you have existing data from a previous version (flat files in `data/nse/` and `data/upstox/`), migrate to the new structured layout:

```bash
nse-relative migrate --provider nse
nse-relative migrate --provider upstox
```

This copies all existing data into the new `equities/`, `derivatives/`, and `indices/` subdirectories. Old files remain untouched.

---

## 📄 License

MIT — see [LICENSE](LICENSE).
