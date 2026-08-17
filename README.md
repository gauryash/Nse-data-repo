# NSE Data Pipeline

Multi-source pipeline for Indian financial market data -- equities, options, and futures.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-purple)](https://github.com/astral-sh/ruff)

---

## Overview

Fetches historical market data from two sources and stores it in Parquet format for analysis. The pipeline is organized around a clean class hierarchy with dependency injection, making it extensible to new data sources.

| Source | Equities | Stock Options | Index Options | Futures | Index |
|--------|----------|---------------|---------------|---------|-------|
| **NSE India** (website API) | Daily OHLCV | -- | -- | -- | Nifty 500 |
| **Upstox** (V2 API) | Day/Week/Month | All strikes x expiries | NIFTY, BANKNIFTY, etc. | FUTSTK/FUTIDX | -- |

### Capabilities

- **NSE equity data** -- 20+ index constituent lists (Nifty 50, 500, etc.)
- **Upstox equity data** -- ISIN-filtered against any NSE index
- **Options chain** -- Full strike/expiry discovery for stock and index options
- **Expiry-aware filtering** -- Per-underlying, keeps next N expiries with all strikes
- **Incremental fetch** -- Per-symbol checkpoint avoids re-downloads
- **Contract manifest** -- Parquet catalog enables expiry-based queries
- **Parallel downloads** -- ThreadPoolExecutor with rate limiting
- **Live market monitor** -- One Upstox V3 WebSocket (LTPC) behind a
  FastAPI + Next.js dashboard: NIFTY 50/100/200 · F&O / indices /
  commodity option chains with live % change, reference-counted
  subscriptions and a 5000-key budget

---

## Architecture

The codebase follows a layered architecture with dependency injection.  A
**live-market layer** (Upstox Market Data Feed V3 WebSocket) sits beside
the historical pipeline, sharing the same instrument master and domain
models:

```
                          Historical                       Live monitor
                                                             │
 CLI (cli.py)                                        FastAPI (live/app.py)
   │                                                        │
 PipelineOrchestrator                              LiveMarketHub  ── one Upstox V3
   │                                                     │         WS connection (ltpc)
   +-- ProviderFactory (registry)                       ├── watch_chain / unwatch
   |     +-- NSEProvider                                │    (reference-counted)
   |     +-- UpstoxProvider                             ├── quote store + % change
   |     +-- UpstoxOptionsProvider                      └── 5000-key LTPC budget
   |                                                        │
   +-- Infrastructure Layer                                ├── WebSocket /ws  ── web/ (Next.js)
         +-- APIClients       (NseClient, UpstoxClient)    └── REST /api (catalog + status)
         +-- Storage           (StorageRepository protocol,
         |                      FileStorageRepository,
         |                      ProviderLayout, FormatHandler,
         |                      ContractManifest)
         +-- Checkpoint        (JsonCheckpoint)
         +-- Symbol Sources    (NseIndexConstituents,
                                InstrumentMaster (JSON BOD),
                                OptionDiscoverer,
                                UpstoxLiveCatalog)
```

Data flow:

```
                     Upstox API                  NSE Website
                         |                           |
              +----------+----------+                |
              |                     |                |
         UpstoxProvider     UpstoxOptionsProvider    NSEProvider
         (equities)          (F&O)                   (equities+index)
              |                     |                |
              +----------+----------+----------------+
                         |
                  FileStorageRepository
                  data/{provider}/{...}
```

### Class hierarchy

```
DataProvider (ABC)
  +-- NSEProvider               equities + index via NSE India public API
  +-- UpstoxProvider            equities via Upstox V2 API
  +-- UpstoxOptionsProvider     F&O options + futures via Upstox V2 API

InstrumentMaster                downloads / caches Upstox instrument master JSON
  +-- SymbolExporter            saves/loads ISIN-filtered equity symbol lists
  +-- OptionDiscoverer          discovers F&O contracts (stock + index)
  +-- ExpiryFilter              per-underlying expiry filtering

UpstoxLiveCatalog               live option-chain indexes (indices / NSE F&O stocks /
                                commodities incl. MCX), token -> instrument key map
universe (module)               static NIFTY 50/100/200 lists, F&O intersection

LiveMarketHub                   single V3 WS connection, refcounted subscriptions,
                                quote store, reconnect + resubscribe, LTPC budget
live/app.py + routes + ws       FastAPI: REST catalog + /ws browser protocol

FileStorageRepository           delegates to:
  +-- ProviderLayout            filesystem path generation
  +-- FormatHandler             Parquet / CSV serialisation
  +-- FnoSymbolParser           tradingsymbol parsing

StorageRepository (Protocol)    interface for alternative backends (S3, etc.)
ContractManifest                CRUD for _contracts.parquet index
JsonCheckpoint                  per-symbol fetch tracking
```

---

## Quick Start

### Installation

```bash
git clone <repo-url>
cd nse-data-repo

python -m venv venv
# Linux / macOS
source venv/bin/activate
# Git Bash on Windows
source venv/Scripts/activate
# Windows CMD / PowerShell
# venv\Scripts\activate

pip install -e ".[dev]"
```

### First fetch

```bash
# Fetch Nifty 50 equities from NSE
nse-data-pipeline fetch --provider nse --index nifty50

# Fetch Upstox equity data (Nifty 200, monthly candles)
nse-data-pipeline fetch --provider upstox --index nifty200 --interval month

# Stock options for Nifty 50 constituents (default: 2 expiries)
nse-data-pipeline fetch --provider upstox_options --index nifty50

# Index options only (NIFTY, BANKNIFTY, FINNIFTY, etc.)
nse-data-pipeline fetch --provider upstox_options --instrument-types OPTIDX
```

---

## CLI Reference

### `fetch` -- Fetch market data

```
nse-data-pipeline fetch [options]
```

| Flag | Alias | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--provider` | `-p` | `nse`, `upstox`, `upstox_options` | `nse` | Data source |
| `--index` | `-x` | string | `nifty500` | NSE index for symbol sourcing |
| `--underlying` | | string | -- | Single stock/index for F&O (e.g. WIPRO, NIFTY) |
| `--underlyings` | | string[] | -- | Multiple underlyings for OPTSTK/FUTSTK F&O (OPTIDX/FUTIDX are preserved; takes precedence over `--underlying`) |
| `--symbols` | `-s` | string[] | -- | Specific symbols to fetch |
| `--start` / `--from` | | DD-MM-YYYY | env default | Fetch start date |
| `--end` / `--to` | | DD-MM-YYYY | env / today | Fetch end date |
| `--interval` | `-i` | `day`, `week`, `month` | provider default | Candle interval (Upstox) |
| `--instrument-types` | `-t` | string | env default | F&O types (`OPTSTK,OPTIDX`) |
| `--include-futures` | | flag | false | Include futures |
| `--n-expiries` | | int | env default (2) | Expiry cycles per underlying (0 = all) |
| `--force` | `-f` | flag | false | Re-fetch from scratch |
| `--skip-index` | | flag | false | Skip index data (NSE only) |

### Other commands

- `nse-data-pipeline list-providers` -- Show available data sources
- `nse-data-pipeline list-indices` -- Show available NSE index constituent lists
- `nse-data-pipeline live [--host HOST] [--port PORT]` -- Start the **live market monitor** (FastAPI + WebSocket backend for the `web/` dashboard)
- `nse-data-pipeline --version` -- Show version

### Live market monitor

```
nse-data-pipeline live --host 127.0.0.1 --port 8000
```

Starts a FastAPI server that owns a single Upstox Market Data Feed V3
WebSocket connection (mode `ltpc`) and exposes:

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Liveness probe |
| `GET /api/status` | Feed state: connected, `subscribed / limit` keys, active chains |
| `GET /api/universes` | NIFTY 50/100/200 static lists with live F&O eligibility counts |
| `GET /api/underlyings/{indices\|stocks\|commodities}` | Underlyings with option chains |
| `GET /api/expiries/{symbol}` | Upcoming expiry dates for an underlying |
| `GET /api/chain/{symbol}?expiry=YYYY-MM-DD` | Strike-sorted CE/PE contract list |
| `WS /ws` | Browser protocol: `watch` / `unwatch` / `ping`, batched `ticks` |

Requires `UPSTOX_ANALYTICS_TOKEN` (server only, 1-year validity) for live
prices; the catalog REST endpoints work without it. The frontend lives in
`web/` (Next.js + shadcn): `cd web && pnpm install && pnpm dev` with
`NEXT_PUBLIC_API_BASE` pointing at the backend.

### Provider comparison

| Feature | NSE | Upstox | UpstoxOptions |
|---------|-----|--------|---------------|
| Equities | Daily OHLCV | Day/Week/Month | -- |
| Index data | Nifty 500 | -- | -- |
| Stock options | -- | -- | OPTSTK, all strikes x expiries |
| Index options | -- | -- | OPTIDX (NIFTY, BANKNIFTY, etc.) |
| Futures | -- | -- | FUTSTK, FUTIDX |
| API type | Public website | Public REST (no key) | Public REST (no key) |
| Historical range | ~20 years | ~25 years | Depends on contract |
| Symbol source | NSE index CSVs | ISIN filter from NSE index | Instrument master discovery |

---

## Options and Futures -- Deep Dive

### Contract discovery

```
1. Upstox instrument master JSON BOD (complete.json.gz, ~123K rows) is
   downloaded and cached (data/instruments/, TTL 12h, stale fallback).
   The JSON schema is normalized to the legacy CSV-style columns
   (OPTSTK/OPTIDX/FUTSTK/FUTIDX, CE/PE, date expiry, ISIN number).

2. For STOCK OPTIONS (OPTSTK):
   Nifty 50 ISINs are matched against Upstox NSE_EQ instruments
   Company names extracted -> used to filter OPTSTK contracts

3. For INDEX OPTIONS (OPTIDX):
   Auto-discovered from the instrument master's OPTIDX section
   All available indices included (or restricted via config)

4. Expiry filtering (per underlying, not global):
   Contracts grouped by underlying stock/index
   Sorted by expiry date -> keep only next N unique dates
   ALL strikes x (CE + PE) kept for those dates
```

### Per-contract schema

Each file (e.g. `RELIANCE26JUN1230CE.parquet`) contains:

| Column | Example | Description |
|--------|---------|-------------|
| `date` | 2026-05-12 | Trading date (IST) |
| `open/high/low/close` | 52.30 | OHLC prices |
| `vol` | 2,340 | Traded quantity (contracts) |
| `oi` | 1,365 | Open interest |
| `symbol` | RELIANCE26JUN1230CE | Tradingsymbol |
| `instrument_type` | OPTSTK | OPTSTK / OPTIDX / FUTSTK / FUTIDX |
| `option_type` | CE | CE / PE / FF |
| `expiry` | 2026-06-26 | Contract expiry date |
| `strike` | 1230.0 | Strike price |
| `lot_size` | 100 | Lot multiplier |
| `underlying_name` | RELIANCE | Company or index name |

### Expiry filter behaviour

Per-underlying grouping, not a global expiry cutoff:

```
NIFTY (index, weekly expiry):
  Expiry 1: Jun 09 (all strikes x CE/PE)
  Expiry 2: Jun 16 (all strikes x CE/PE)

RELIANCE (stock, monthly expiry):
  Expiry 1: Jun 26 (all strikes x CE/PE)
  Expiry 2: Jul 30 (all strikes x CE/PE)
```

| `--n-expiries` | Behaviour |
|----------------|-----------|
| 2 (default) | Next 2 upcoming expiries per underlying |
| 0 | Disables filter -- fetches ALL discoverable contracts |
| 5 | Next 5 expiries per underlying |

### Examples

```bash
# Stock options only (Nifty 50 constituents, 2 expiries)
nse-data-pipeline fetch --provider upstox_options --index nifty50

# Index options only
nse-data-pipeline fetch --provider upstox_options --instrument-types OPTIDX

# Combined: stock + index options + futures
nse-data-pipeline fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures

# Disable expiry filter (get everything available)
nse-data-pipeline fetch --provider upstox_options --index nifty50 \
  --n-expiries 0

# Single stock options
nse-data-pipeline fetch --provider upstox_options --underlying RELIANCE

# Specific contract tradingsymbols
nse-data-pipeline fetch --provider upstox_options \
  --symbols NIFTY26JUN23600CE NIFTY26JUN23600PE
```

### Recipe: 10 stocks + NIFTY/BANKNIFTY, 3 expiries, 1-month history

Restrict index options in `.env` first (auto-discovered otherwise):

```env
UPSTOX_OPTIONS_INDEX_NAMES=NIFTY,BANKNIFTY
```

Clear the options checkpoint so the 1-month pull is clean:

```bash
rm -f data/upstox_options/_checkpoint.json
```

Single command for 10 Nifty 50 stock options + NIFTY & BANKNIFTY index
options, 3 upcoming expiries, last 30 days:

> `--underlyings` filters **OPTSTK/FUTSTK** rows only. Index options
> (OPTIDX/FUTIDX) are preserved as-is, governed by `--instrument-types`
> and `UPSTOX_OPTIONS_INDEX_NAMES`.

```bash
nse-data-pipeline fetch \
  --provider upstox_options \
  --instrument-types "OPTSTK,OPTIDX" \
  --underlyings RELIANCE TCS HDFCBANK INFY ICICIBANK SBIN BHARTIARTL LT ITC AXISBANK \
  --n-expiries 3 \
  --interval day \
  --start 25-05-2026 \
  --end 24-06-2026
```

---

## Data Storage Layout

```
data/
  nse/
    _checkpoint.json             per-symbol fetch tracking
    equities_{year}.parquet      yearly partitions
    equities.parquet             consolidated all years
    indices.parquet              Nifty 500 benchmark

  upstox/
    _checkpoint.json
    {SYMBOL}.parquet             per-equity files (RELIANCE.parquet, ...)

  upstox_options/
    _checkpoint.json
    _contracts.parquet           contract manifest (expiry-queryable)
    NIFTY/
      260609/                    expiry 2026-06-09
        NIFTY26060923600CE.parquet
      260630/                    expiry 2026-06-30
        NIFTY26JUN23600CE.parquet
    WIPRO/
      260630/
        WIPRO26JUN160CE.parquet
      260731/
        ...
    RELIANCE/
      ...
```

### Querying the contract manifest

```python
from nse_data_pipeline.infrastructure.storage.file_repository import (
    FileStorageRepository,
)
from nse_data_pipeline.infrastructure.storage.manifest import ContractManifest

storage = FileStorageRepository()
manifest = ContractManifest(storage, "upstox_options")

# All NIFTY contracts
nifty = manifest.query(underlying_name="NIFTY")

# All CE contracts for a specific expiry
calls = manifest.query(expiry="2026-06-09", option_type="CE")
```

---

## Codebase Structure

```
src/nse_data_pipeline/
  cli.py                           CLI entry point (argparse + dispatch)
  __init__.py                      Package metadata (version 0.3.0)
  __main__.py                      python -m nse_data_pipeline entry

  config/
    settings.py                    All env-var configuration
    logger.py                      Logging setup

  domain/
    models.py                      Domain models: OptionContract, enums, value objects
    live_models.py                 LiveQuote, ChainDefinition, LiveOptionContract
    coverage.py                    CoverageRange, CheckpointData

  application/
    fetch_service.py               PipelineOrchestrator + ProviderFactory
    live_market_hub.py             LiveMarketHub (live V3 feed manager)

  infrastructure/
    api/
      nse_client.py                NSE India HTTP client
      upstox_client.py             Upstox V2 historical-candle client
    checkpoint/
      json_checkpoint.py           Per-provider incremental fetch tracking
    storage/
      repository.py                StorageRepository protocol
      file_repository.py           Filesystem implementation
      layout.py                    ProviderLayout (path generation)
      format_handler.py            Parquet/CSV serialisation
      symbol_parser.py             F&O tradingsymbol parsing
      manifest.py                  ContractManifest CRUD
    symbol_source/
      nse_index_csv.py             NSE index constituent fetcher (NseIndexConstituents,
                                   IndexCsvCatalog)
      upstox_instruments.py        InstrumentMaster (JSON BOD + normalizer),
                                   SymbolExporter, OptionDiscoverer, ExpiryFilter
      upstox_live_catalog.py       UpstoxLiveCatalog (live chain indexes)
      universe.py                  Static NIFTY 50/100/200 lists + F&O intersection
  pipeline/
    base.py                        DataProvider ABC
    nse_provider.py                NSE equity + index fetching
    upstox_provider.py             Upstox equity fetching
    upstox_options_provider.py     F&O options + futures fetching

  application/
    live_market_hub.py             LiveMarketHub (V3 WS, refcounted subscriptions,
                                   quote store, reconnect, budget)

  live/
    app.py                         FastAPI app factory + broadcast loop
    routes.py                      REST catalog endpoints
    websocket.py                   /ws browser protocol + ConnectionManager

  shared/
    rate_limiter.py                Exponential backoff rate limiter
    exceptions.py                  Domain exception hierarchy
    utils.py                       Date helpers
```

Frontend (`web/`, Next.js + shadcn): `src/lib/market-store.ts` (WS client +
quote store), `src/hooks/use-market-feed.ts`, `src/components/market/`
(universe-picker, chain-workspace, option-chain-panel, chain/movers tables,
connection-status).

---

## Configuration

Copy `.env.example` -> `.env` and adjust as needed. All defaults work out of the box -- no API keys required.

| Variable | Default | Description |
|----------|---------|-------------|
| **NSE** | | |
| `NSE_DEFAULT_INDEX` | `nifty500` | Default NSE index |
| `NSE_FETCH_START` | `01-01-2021` | Fetch start (DD-MM-YYYY) |
| `NSE_FETCH_CHUNK_DAYS` | `110` | API chunk size |
| `NSE_STORAGE_FORMAT` | `parquet` | `parquet` or `csv` |
| `NSE_RATE_MAX_WORKERS` | `5` | Parallel workers |
| `NSE_LOG_LEVEL` | `INFO` | Logging verbosity |
| **Upstox (equities)** | | |
| `UPSTOX_INTERVAL` | `month` | Candle interval |
| `UPSTOX_MAX_WORKERS` | `10` | Parallel workers |
| `UPSTOX_FETCH_START` | `01-01-2000` | Fetch start |
| `UPSTOX_INSTRUMENTS_URL` | `complete.json.gz` | Instrument master (JSON BOD; CSV is deprecated) |
| `UPSTOX_INSTRUMENTS_CACHE_TTL_HOURS` | `12` | Instrument master cache TTL |
| **Upstox (F&O)** | | |
| `UPSTOX_OPTIONS_INTERVAL` | `day` | Options interval |
| `UPSTOX_OPTIONS_FETCH_START` | `01-01-2024` | Fetch start |
| `UPSTOX_OPTIONS_TYPES` | `OPTSTK` | F&O types to fetch |
| `UPSTOX_OPTIONS_N_EXPIRIES` | `2` | Expiry cycles per underlying |
| `UPSTOX_OPTIONS_INDEX_NAMES` | (auto) | Restrict index options |
| **Upstox (live monitor)** | | |
| `UPSTOX_ANALYTICS_TOKEN` | (empty) | Analytics token for Market Data Feed V3 (server only, 1-year validity) |
| `UPSTOX_LIVE_MAX_KEYS` | `5000` | LTPC subscription budget per connection |

Rate limiter: `NSE_RATE_INITIAL_DELAY=0.5`, `NSE_RATE_MAX_DELAY=30.0`, `NSE_RATE_BACKOFF_FACTOR=2.0`, `NSE_FETCH_MAX_RETRIES=5`

---

## Development

```bash
# Editable install with dev dependencies
pip install -e ".[dev]"

# Tests
pytest

# Lint
ruff check src/
ruff format src/

# Type check
mypy src/

# CLI help
nse-data-pipeline --help
nse-data-pipeline fetch --help
```

### Troubleshooting

**Entry point fails after code changes:**
```bash
pip uninstall nse-data-pipeline -y
pip install -e .
```

**Fallback -- run module directly:**
```bash
python -m nse_data_pipeline fetch --provider upstox --index nifty50
```

---

## License

MIT
