# NSE Data Pipeline

**Multi-source pipeline for Indian financial market data -- Equities, Options & Futures**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-purple)](https://github.com/astral-sh/ruff)

---

## Overview

Fetches historical market data from **two sources** and stores it in Parquet
format for analysis.  The pipeline is organized around a clean class hierarchy
with dependency injection, making it extensible to new data sources.

| Source | Equities | Stock Options | Index Options | Futures | Index |
|--------|----------|---------------|---------------|---------|-------|
| **NSE India** (website API) | Daily OHLCV | -- | -- | -- | Nifty 500 |
| **Upstox** (V2 API) | Day/Week/Month | All strikes x expiries | NIFTY, BANKNIFTY, etc. | FUTSTK/FUTIDX | -- |

### Capabilities

- **NSE Equity data** -- 20+ index constituent lists (Nifty 50, 500, etc.)
- **Upstox Equity data** -- ISIN-filtered against any NSE index
- **Options chain** -- Full strike/expiry discovery for stock + index options
- **Expiry-aware filtering** -- Per-underlying, keeps next N expiries (all strikes)
- **Incremental fetch** -- Per-symbol checkpoint avoids re-downloads
- **Contract manifest** -- `_contracts.parquet` enables expiry-based queries
- **Parallel downloads** -- ThreadPoolExecutor with rate limiting

---

## Architecture

The codebase follows a layered architecture with dependency injection:

```
CLI (cli.py)
  |
  v
PipelineOrchestrator
  |
  +-- ProviderFactory (registry)
  |     +-- NSEProvider
  |     +-- UpstoxProvider
  |     +-- UpstoxOptionsProvider
  |
  +-- Infrastructure Layer
        +-- APIClients       (NseClient, UpstoxClient)
        +-- Storage           (StorageRepository protocol,
        |                      FileStorageRepository,
        |                      ProviderLayout, FormatHandler,
        |                      ContractManifest)
        +-- Checkpoint        (JsonCheckpoint)
        +-- Symbol Sources    (NseIndexConstituents,
                               InstrumentMaster, OptionDiscoverer)
```

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

InstrumentMaster                downloads / caches Upstox instrument master CSV
  +-- SymbolExporter            saves/loads ISIN-filtered equity symbol lists
  +-- OptionDiscoverer          discovers F&O contracts (stock + index)
  +-- ExpiryFilter              per-underlying expiry filtering

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
source venv/bin/activate    # or venv\Scripts\activate on Windows

pip install -e ".[dev]"
```

### Your first fetch

```bash
# Fetch Nifty 50 equities from NSE
nse-relative fetch --provider nse --index nifty50

# Fetch Upstox equity data (Nifty 200, monthly candles)
nse-relative fetch --provider upstox --index nifty200 --interval month

# Stock options for Nifty 50 constituents (default: 2 expiries)
nse-relative fetch --provider upstox_options --index nifty50

# Index options only (NIFTY, BANKNIFTY, FINNIFTY, etc.)
nse-relative fetch --provider upstox_options --instrument-types OPTIDX
```

See the full reference below or `nse-relative fetch --help` for all options.

---

## CLI Reference

### `nse-relative fetch`

| Flag | Alias | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--provider` | `-p` | `nse`, `upstox`, `upstox_options` | `nse` | Data source |
| `--index` | `-x` | string | `nifty500` | NSE index for symbol sourcing |
| `--underlying` | | string | -- | Single stock/index for F&O (e.g. WIPRO, NIFTY) |
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

- `nse-relative list-providers` -- Show available data sources
- `nse-relative list-indices` -- Show available NSE index constituent lists
- `nse-relative --version` -- Show version

---

## Options & Futures -- Deep Dive

### Contract discovery

```
1. Upstox instrument master CSV (~200K rows) is downloaded
   Filtered to exchange="NSE_FO"

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

### Expiry filter -- behaviour

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
nse-relative fetch --provider upstox_options --index nifty50

# Index options only
nse-relative fetch --provider upstox_options --instrument-types OPTIDX

# Combined: stock + index options + futures
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures

# Disable expiry filter (get everything available)
nse-relative fetch --provider upstox_options --index nifty50 \
  --n-expiries 0

# Next 3 expiries per underlying
nse-relative fetch --provider upstox_options --index nifty50 \
  --n-expiries 3

# Specific contract tradingsymbols
nse-relative fetch --provider upstox_options \
  --symbols NIFTY26JUN23600CE NIFTY26JUN23600PE

# Weekly candles
nse-relative fetch --provider upstox_options --index nifty50 \
  --interval week
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
      _contracts.parquet         contract manifest (expiry-queryable)
      NIFTY/
        260609/                  expiry 2026-06-09
          NIFTY26060923600CE.parquet
        260630/                  expiry 2026-06-30
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
    coverage.py                    CoverageRange, CheckpointData

  application/
    fetch_service.py               PipelineOrchestrator + ProviderFactory

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
      upstox_instruments.py        InstrumentMaster, SymbolExporter,
                                   OptionDiscoverer, ExpiryFilter
  pipeline/
    base.py                        DataProvider ABC
    nse_provider.py                NSE equity + index fetching
    upstox_provider.py             Upstox equity fetching
    upstox_options_provider.py     F&O options + futures fetching

  shared/
    rate_limiter.py                Exponential backoff rate limiter
    exceptions.py                  Domain exception hierarchy
    utils.py                       Date helpers
```

---

## Configuration

Copy `.env.example` -> `.env` and adjust as needed. All defaults work
out of the box -- no API keys required.

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
| **Upstox (F&O)** | | |
| `UPSTOX_OPTIONS_INTERVAL` | `day` | Options interval |
| `UPSTOX_OPTIONS_FETCH_START` | `01-01-2024` | Fetch start |
| `UPSTOX_OPTIONS_TYPES` | `OPTSTK` | F&O types to fetch |
| `UPSTOX_OPTIONS_N_EXPIRIES` | `2` | Expiry cycles per underlying |
| `UPSTOX_OPTIONS_INDEX_NAMES` | (auto) | Restrict index options |

Rate limiter: `NSE_RATE_INITIAL_DELAY=0.5`, `NSE_RATE_MAX_DELAY=30.0`,
`NSE_RATE_BACKOFF_FACTOR=2.0`, `NSE_FETCH_MAX_RETRIES=5`

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
nse-relative --help
nse-relative fetch --help
```

### Troubleshooting

**Entry point fails after code changes:**
```bash
pip uninstall nse-relative -y
pip install -e .
```

**Fallback -- run module directly:**
```bash
python -m nse_data_pipeline fetch --provider upstox --index nifty50
```

---

## License

MIT
