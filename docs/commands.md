# 📋 NSE Data Pipeline — Command Reference

> **Full command reference for `nse-relative` CLI**

---

## 🔹 `fetch` — Data Fetching

```
nse-relative fetch [options]
```

### Common options

| Option | Alias | Values | Default | Description |
|---|---|---|---|---|
| `--provider` | `-p` | `nse`, `upstox`, `upstox_options` | `nse` | Data source |
| `--index` | `-x` | *see list-indices* | `nifty500` | NSE index for symbol sourcing |
| `--symbols` | `-s` | space-separated symbols | all | Limit to specific symbols |
| `--start` | `--from` | DD-MM-YYYY | env default | Fetch start date |
| `--end` | `--to` | DD-MM-YYYY | env / today | Fetch end date |
| `--interval` | `-i` | `day`, `week`, `month` | provider default | Candle interval |
| `--force` | `-f` | flag | `False` | Bypass checkpoint, re-fetch all |
| `--skip-index` | — | flag | `False` | Skip index data (NSE only) |

### F&O-specific options

| Option | Alias | Values | Default | Description |
|---|---|---|---|---|
| `--instrument-types` | `-t` | `OPTSTK,OPTIDX` (comma-sep) | `OPTSTK` | F&O contract types |
| `--include-futures` | — | flag | `False` | Also fetch futures (FUTSTK/FUTIDX) |
| `--n-expiries` | — | integer (0 = all) | `2` | Upcoming expiry cycles per underlying |

---

### 📈 NSE Equities

```bash
# Nifty 50 equities (default date range from .env)
nse-relative fetch --provider nse --index nifty50

# All ~750 stocks with custom range
nse-relative fetch --provider nse --index nifty_total_market \
  --start 01-01-2020 --end 31-12-2025

# Specific symbols
nse-relative fetch --provider nse --symbols RELIANCE TCS HDFCBANK

# Force re-fetch (ignore checkpoint)
nse-relative fetch --provider nse --force

# Equities only, no index data
nse-relative fetch --provider nse --skip-index
```

### 📈 Upstox Equities

```bash
# Default (Nifty 500, monthly candles)
nse-relative fetch --provider upstox

# Nifty 200, daily candles from 2020
nse-relative fetch --provider upstox --interval day \
  --index nifty200 --start 01-01-2020

# Full history, monthly
nse-relative fetch --provider upstox --interval month

# Specific tradingsymbols
nse-relative fetch --provider upstox --symbols RELIANCE TCS HDFCBANK
```

---

### 🎯 Options & Futures (most powerful feature)

#### Stock Options (OPTSTK) — e.g. Nifty 50

```bash
# 🔥 Fetch ALL Nifty 50 stock options
# NEXT 2 expiries per stock, ALL strikes, CE + PE, daily candles
nse-relative fetch --provider upstox_options --index nifty50
```

**How it works:**

```
Nifty 50 (50 stocks)
  │
  ├─ RELIANCE → OPTSTK contracts matched by ISIN
  │   ├─ Expiry 1 (e.g. Jun 26): strikes 1200–1500, CE+PE  → ~600 contracts
  │   └─ Expiry 2 (e.g. Jul 30): strikes 1200–1500, CE+PE  → ~600 contracts
  │
  ├─ TCS → OPTSTK contracts
  │   ├─ Expiry 1: strikes 3200–3800, CE+PE
  │   └─ Expiry 2: strikes 3200–3800, CE+PE
  │
  └─ ... (all 50 stocks)
```

Each contract file (e.g. `TCS26JUN3450CE.parquet`) contains:
`date, open, high, low, close, vol, oi, symbol, instrument_type, option_type, expiry, strike, lot_size, underlying_name`

**~4,000 contracts total** (50 stocks × 2 expiries × ~20 strikes × 2 types)

#### Index Options (OPTIDX) — All Indices

```bash
# 🔥 Fetch ALL index options (NIFTY, BANKNIFTY, FINNIFTY, etc.)
nse-relative fetch --provider upstox_options --instrument-types OPTIDX

# Combined: stock options + index options
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX"

# Add futures too
nse-relative fetch --provider upstox_options --index nifty50 \
  --instrument-types "OPTSTK,OPTIDX" --include-futures
```

Available index options (auto-discovered): `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, `NIFTY`, `NIFTYNXT50`, `SENSEX`, `SENSEX50`, and more.

#### Specific Tradingsymbols

```bash
# Fetch specific contracts by tradingsymbol
nse-relative fetch --provider upstox_options \
  --symbols NIFTY26JUN23600CE NIFTY26JUN23600PE RELIANCE26JUN1230CE
```

#### Expiry Filtering Control

```bash
# Next 3 expiries per underlying (instead of default 2)
nse-relative fetch --provider upstox_options --n-expiries 3

# ALL expiries (disable expiry filter)
# Fetches everything in the instrument master (recently expired + upcoming)
nse-relative fetch --provider upstox_options --n-expiries 0
```

> **Historical + Current**: When `--n-expiries 2`, only the next 2 upcoming expiries are fetched. Contracts that have already expired are skipped. Use `--n-expiries 0` to fetch ALL contracts in the instrument master (including recently expired ones). For truly historical data (years-old expired contracts), they won't be in the current instrument master CSV.

#### Custom Date Range

```bash
# Fetch options from a specific date range
nse-relative fetch --provider upstox_options \
  --start 01-01-2024 --end 01-06-2026
```

> ⚠️ The Upstox instrument master CSV contains recently listed contracts. Very old expired contracts may not be discoverable.

---

## 🔹 List Commands

```bash
# Show providers with stored instrument counts
nse-relative list-providers

# Show available NSE index constituent lists
nse-relative list-indices

# Show stored symbols for a provider with date coverage
nse-relative list-symbols --provider nse
nse-relative list-symbols --provider upstox

# Show stored F&O contracts
nse-relative list-symbols --provider upstox --asset-class derivative

# Show stored indices
nse-relative list-symbols --provider nse --asset-class index

# Show detailed instrument coverage from catalog
nse-relative list-instruments
```

---

## 🔹 Migration

```bash
# Migrate NSE data from old flat format to new structured layout
nse-relative migrate --provider nse

# Migrate Upstox data
nse-relative migrate --provider upstox
```

---

## 🔹 Utility

```bash
# Show version
nse-relative --version

# Show help
nse-relative --help
nse-relative fetch --help
```

---

## 🔹 Examples Cheatsheet

```bash
# ── Quick fetches ──────────────────────────────────────

# 1. Nifty 50 equities + index data
nse-relative fetch -p nse -x nifty50

# 2. Nifty 200 equities from Upstox (daily)
nse-relative fetch -p upstox -x nifty200 -i day

# 3. Nifty 50 stock options (next 2 expiries, all strikes)
nse-relative fetch -p upstox_options -x nifty50

# 4. All index options (NIFTY, BANKNIFTY, etc.)
nse-relative fetch -p upstox_options -t OPTIDX

# 5. Everything: stock options + index options + futures
nse-relative fetch -p upstox_options -x nifty50 \
  -t "OPTSTK,OPTIDX" --include-futures

# ── Advanced ───────────────────────────────────────────

# Nifty 50 options, next 3 expiries
nse-relative fetch -p upstox_options -x nifty50 --n-expiries 3

# All contracts (disable expiry filter)
nse-relative fetch -p upstox_options -x nifty50 --n-expiries 0

# Force re-fetch everything
nse-relative fetch -p nse --force
nse-relative fetch -p upstox --force
nse-relative fetch -p upstox_options --force

# Weekly options candles
nse-relative fetch -p upstox_options -x nifty50 -i week
```
