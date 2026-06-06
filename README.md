# NSE / Upstox Data Pipeline

**Multi-source data pipeline for Indian financial market data**

Fetches historical data from **NSE India** (equities + index) and **Upstox** (equities + F&O options/futures), with incremental checkpoint tracking and provider-partitioned storage.

---

## Features

| Source | Data Types | Storage |
|---|---|---|
| **NSE India** | Equities (daily OHLCV), Nifty 500 Index | `data/nse/equities_{year}.parquet` + consolidated |
| **Upstox** | Equities (day/week/month candles) | `data/upstox/{symbol}.parquet` |
| **Upstox F&O** | OPTSTK, OPTIDX, FUTSTK, FUTIDX (candles) | `data/upstox_options/{tradingsymbol}.parquet` + contract manifest |

Key capabilities:
- **Incremental fetch** — checkpoint system avoids re-downloading existing data
- **Per-symbol tracking** — knows exactly what date ranges are stored
- **Contract manifest** — expiry-queryable catalog of all F&O contracts
- **Expiry-aware filtering** — fetch only the next N expiries per underlying
- **Parallel fetching** — ThreadPoolExecutor for concurrent downloads
- **Rate limiting** — exponential backoff for HTTP 429 responses

---

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Fetch NSE equity + index data
nse-relative fetch --provider nse

# Fetch Upstox equity data (monthly interval)
nse-relative fetch --provider upstox --interval month

# Fetch Nifty 50 F&O options (next 2 expiries, all strikes)
nse-relative fetch --provider upstox_options --index nifty50

# Fetch stock + index options + futures
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures
```

---

## CLI Reference

### `nse-relative fetch`

| Option | Description | Default |
|---|---|---|
| `--provider, -p` | `nse`, `upstox`, `upstox_options` | `nse` |
| `--index, -x` | NSE index constituent list | `nifty500` |
| `--symbols, -s` | Limit to specific symbols | all |
| `--start` / `--from` | Start date DD-MM-YYYY | env default |
| `--end` / `--to` | End date DD-MM-YYYY | env / today |
| `--interval, -i` | Candle interval (`day`, `week`, `month`) | provider default |
| `--force, -f` | Ignore checkpoint, re-fetch all | False |
| `--skip-index` | Skip index fetch (NSE only) | False |
| **UpstoxOptions only:** | | |
| `--instrument-types, -t` | `OPTSTK`, `OPTIDX` (comma-sep) | `OPTSTK` |
| `--include-futures` | Also fetch `FUTSTK` / `FUTIDX` | False |
| `--n-expiries` | Upcoming expiries per underlying (`0` = all) | `2` |

### List commands

```bash
nse-relative list-providers    # nse, upstox, upstox_options
nse-relative list-indices      # All 20+ NSE index constituent lists
nse-relative --version         # 0.3.0
```

---

## Data Storage Layout

```
data/
├── nse/
│   ├── equities_2025.parquet      # Yearly partitions
│   ├── equities_2026.parquet
│   ├── equities.parquet           # Consolidated (all years)
│   ├── indices.parquet            # Nifty 500 benchmark
│   └── _checkpoint.json           # Per-symbol fetch tracking
│
├── upstox/
│   ├── RELIANCE.parquet           # Per-symbol files
│   ├── TCS.parquet
│   └── _checkpoint.json
│
└── upstox_options/
    ├── NIFTY26JUN23600CE.parquet  # Per-contract files
    ├── NIFTY26JUN23600PE.parquet
    ├── _contracts.parquet         # Contract manifest (expiry-queryable)
    └── _checkpoint.json
```

### Contract metadata

Each F&O contract file includes metadata columns alongside OHLC+OI data:

```
date, open, high, low, close, vol, oi, symbol,
instrument_type, option_type, expiry, strike, lot_size, underlying_name
```

### Checkpoint system

Each provider has a `_checkpoint.json` tracking per-symbol date ranges. Before downloading, the provider checks if the range is already covered. Use `--force` to bypass.

---

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Default | Description |
|---|---|---|
| `NSE_FETCH_START` | `01-01-2021` | NSE fetch start date |
| `NSE_FETCH_END` | (today) | NSE fetch end date |
| `NSE_FETCH_CHUNK_DAYS` | `110` | API chunk size |
| `NSE_STORAGE_FORMAT` | `parquet` | `parquet` or `csv` |
| `NSE_RATE_MAX_WORKERS` | `5` | Parallel workers |
| `UPSTOX_INTERVAL` | `month` | Candle interval |
| `UPSTOX_MAX_WORKERS` | `10` | Parallel workers |
| `UPSTOX_FETCH_START` | `01-01-2000` | Upstox fetch start |
| `UPSTOX_OPTIONS_INTERVAL` | `day` | Options candle interval |
| `UPSTOX_OPTIONS_TYPES` | `OPTSTK` | F&O types to fetch |
| `UPSTOX_OPTIONS_N_EXPIRIES` | `2` | Expiries per underlying |
| `NSE_LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Architecture

```
src/nse_relative/
│
├── cli.py                          # CLI entry point (fetch + list commands)
│
├── config/
│   ├── settings.py                 # Dataclass-based configuration
│   └── logger.py                   # Logging setup
│
├── domain/
│   ├── models.py                   # OptionContract, enums, value objects
│   └── coverage.py                 # CoverageRange, CheckpointData
│
├── application/
│   └── fetch_service.py            # Fetch orchestration with DI
│
├── infrastructure/
│   ├── api/
│   │   ├── nse_client.py           # NSE HTTP client + response parsing
│   │   └── upstox_client.py        # Upstox HTTP client (shared equity+F&O)
│   ├── storage/
│   │   ├── repository.py           # Storage protocol
│   │   ├── file_repository.py      # Filesystem implementation (parquet/csv)
│   │   └── manifest.py             # Contract manifest CRUD
│   ├── checkpoint/
│   │   └── json_checkpoint.py      # Per-provider incremental fetch tracking
│   └── symbol_source/
│       ├── nse_index_csv.py         # NSE index constituent fetcher
│       └── upstox_instruments.py    # Upstox instrument master + discovery
│
├── pipeline/
│   ├── base.py                     # DataProvider abstract base
│   ├── nse_provider.py             # NSE fetch orchestration
│   ├── upstox_provider.py          # Upstox equity fetch
│   └── upstox_options_provider.py  # Upstox F&O fetch
│
└── shared/
    ├── rate_limiter.py             # Thread-safe exponential backoff
    ├── utils.py                    # Date chunking helpers
    └── exceptions.py               # Domain exception hierarchy
```

---

## Development

```bash
# Editable install
pip install -e ".[dev]"

# Run tests
pytest

# Lint + type-check
ruff check src/
mypy src/

# Format
ruff format src/
```

---

## License

MIT
