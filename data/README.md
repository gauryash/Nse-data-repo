# Data directory

Data files are **not** tracked in git. Regenerate them with the CLI.

## Storage Layout

| Provider | Path | Command |
|---|---|---|
| NSE (equities) | `data/nse/equities_{year}.parquet` | `nse-relative fetch --provider nse` |
| NSE (consolidated) | `data/nse/equities.parquet` | automatically rebuilt |
| NSE (Nifty 500) | `data/nse/indices.parquet` | automatically fetched with equities |
| Upstox (per symbol) | `data/upstox/{symbol}.parquet` | `nse-relative fetch --provider upstox` |
| Upstox (symbol list) | `data/SymbolList.xlsx` | auto-generated from ISIN filtering |

## Format

Default: **Parquet with gzip compression**. Set `NSE_STORAGE_FORMAT=csv` for CSV output.

## Reference Data

- `NSE_1000.csv` — NSE company list with ISIN codes (tracked in git).
