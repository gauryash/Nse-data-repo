"""
Provider-partitioned data storage.

Each provider writes to ``data/{provider}/``.
Supports Parquet (gzip compressed) and CSV for testing.

Storage paths:
  NSE:    data/nse/equities_{year}.parquet(.csv)
          data/nse/equities.parquet(.csv)       (consolidated)
          data/nse/indices.parquet(.csv)
  Upstox: data/upstox/{symbol}.parquet(.csv)
"""

import os
import glob
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from nse_relative.config.settings import (
    NSE_STORAGE_DIR,
    UPSTOX_STORAGE_DIR,
    UPSTOX_OPTIONS_STORAGE_DIR,
    FETCH_STORAGE_FORMAT,
)

# ---------------------------------------------------------------------------
# Extension helpers
# ---------------------------------------------------------------------------

_FORMAT_EXT = {"parquet": ".parquet", "csv": ".csv"}


def _ext(fmt: str = FETCH_STORAGE_FORMAT) -> str:
    return _FORMAT_EXT.get(fmt, ".parquet")


def _read_func(fmt: str = FETCH_STORAGE_FORMAT):
    if fmt == "csv":
        return lambda p: pd.read_csv(p, parse_dates=["Date"] if "Date" in pd.read_csv(p, nrows=0).columns else False)
    # Use fastparquet (works with pandas 2.x; pyarrow requires pandas 3.x)
    return lambda p: pd.read_parquet(p, engine="fastparquet")


def _write_func(fmt: str = FETCH_STORAGE_FORMAT):
    if fmt == "csv":
        return lambda df, p: df.to_csv(p, index=False)
    # Use fastparquet (works with pandas 2.x; pyarrow requires pandas 3.x)
    return lambda df, p: df.to_parquet(p, index=False, compression="gzip", engine="fastparquet")


# ---------------------------------------------------------------------------
# Base path resolver
# ---------------------------------------------------------------------------

def _base_dir(provider: str) -> Path:
    if provider == "nse":
        return NSE_STORAGE_DIR
    if provider == "upstox":
        return UPSTOX_STORAGE_DIR
    if provider == "upstox_options":
        return UPSTOX_OPTIONS_STORAGE_DIR
    raise ValueError(f"Unknown provider: {provider}")


# ---------------------------------------------------------------------------
# Public helpers (provider-agnostic)
# ---------------------------------------------------------------------------

def equities_path(provider: str, year: Optional[int] = None) -> Path:
    """Path to an equities file for *provider*."""
    base = _base_dir(provider)
    ext = _ext()
    if year is not None:
        return base / f"equities_{year}{ext}"
    return base / f"equities{ext}"


def indices_path(provider: str) -> Path:
    """Path to the index data file for *provider*."""
    base = _base_dir(provider)
    return base / f"indices{_ext()}"


def symbol_path(provider: str, symbol: str) -> Path:
    """Path to an individual symbol file (used by Upstox)."""
    base = _base_dir(provider)
    return base / f"{symbol}{_ext()}"


# ---------------------------------------------------------------------------
# Equity readers / writers
# ---------------------------------------------------------------------------

def save_equities(df: pd.DataFrame, provider: str) -> None:
    """Save/append equity data partitioned by year."""
    df = df.copy()
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")

    df["Year"] = pd.to_datetime(df["Date"]).dt.year
    for year, group in df.groupby("Year"):
        path = equities_path(provider, int(year))
        if path.exists():
            existing = _read_func()(path)
            group = pd.concat([existing, group], ignore_index=True)
            group = group.drop_duplicates(
                subset=["Symbol", "Date"], keep="last"
            ).sort_values("Date")
        # Drop Year column before saving
        group.drop(columns=["Year"], inplace=True)
        _write_func()(group, path)

    # Rebuild consolidated
    rebuild_consolidated(provider)


def rebuild_consolidated(provider: str) -> None:
    """Merge all yearly equity parquets into a single file."""
    base = _base_dir(provider)
    ext = _ext()
    files = sorted(glob.glob(os.path.join(base, f"equities_*{ext}")))
    if not files:
        return
    dfs = [_read_func()(f) for f in files]
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Symbol", "Date"]).sort_values("Date")
    path = equities_path(provider)
    _write_func()(combined, path)


def load_equities(provider: str) -> pd.DataFrame:
    """Load the consolidated equities file for *provider*.

    Automatically rebuilds the consolidated file if it is stale
    (i.e. if yearly partition files exist outside the consolidated
    date range).
    """
    path = equities_path(provider)
    if not path.exists():
        return pd.DataFrame()

    df = _read_func()(path)
    if "Date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["Date"]):
        df["Date"] = pd.to_datetime(df["Date"])

    # Check if consolidated is stale (yearly files outside range)
    base = _base_dir(provider)
    ext = _ext()
    yearly_files = sorted(glob.glob(os.path.join(base, f"equities_*{ext}")))
    if len(yearly_files) > 1:  # at least one yearly file besides consolidated
        # Get min/max dates from yearly files
        try:
            first = _read_func()(yearly_files[0])
            last = _read_func()(yearly_files[-1])
            if "Date" in first.columns:
                first_dates = pd.to_datetime(first["Date"])
                yearly_min = first_dates.min()
            else:
                yearly_min = None
            if "Date" in last.columns:
                last_dates = pd.to_datetime(last["Date"])
                yearly_max = last_dates.max()
            else:
                yearly_max = None

            cons_min = df["Date"].min() if "Date" in df.columns else None
            cons_max = df["Date"].max() if "Date" in df.columns else None

            needs_rebuild = (
                (yearly_min is not None and cons_min is not None and yearly_min < cons_min)
                or (yearly_max is not None and cons_max is not None and yearly_max > cons_max)
            )
            if needs_rebuild:
                from nse_relative.config.logger import get_logger
                logger = get_logger(__name__)
                logger.info(
                    "Consolidated file stale (yearly range %s..%s vs cons %s..%s). Rebuilding...",
                    yearly_min.date() if yearly_min else "?",
                    yearly_max.date() if yearly_max else "?",
                    cons_min.date() if cons_min is not None else "?",
                    cons_max.date() if cons_max is not None else "?",
                )
                rebuild_consolidated(provider)
                df = _read_func()(path)
                if "Date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["Date"]):
                    df["Date"] = pd.to_datetime(df["Date"])
        except Exception as exc:
            # If anything goes wrong, just use the existing consolidated
            import warnings
            warnings.warn(f"Consolidated staleness check failed: {exc}")

    return df


def load_equities_yearly(provider: str) -> pd.DataFrame:
    """Load all yearly partitions and return a single DataFrame."""
    ext = _ext()
    files = sorted(glob.glob(os.path.join(_base_dir(provider), f"equities_*{ext}")))
    if not files:
        return pd.DataFrame()
    dfs = [_read_func()(f) for f in files]
    return pd.concat(dfs, ignore_index=True)


# ---------------------------------------------------------------------------
# Index readers / writers
# ---------------------------------------------------------------------------

def save_index(df: pd.DataFrame, provider: str) -> None:
    """Save index data."""
    path = indices_path(provider)
    _write_func()(df, path)


def load_index(provider: str) -> pd.DataFrame:
    """Load index data."""
    path = indices_path(provider)
    if not path.exists():
        return pd.DataFrame()
    df = _read_func()(path)
    if "Date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["Date"]):
        df["Date"] = pd.to_datetime(df["Date"])
    return df


# ---------------------------------------------------------------------------
# Individual symbol readers / writers (used by Upstox)
# ---------------------------------------------------------------------------

def save_symbol(df: pd.DataFrame, provider: str) -> None:
    """Save data for a single symbol (first row's symbol used as filename)."""
    if df.empty:
        return
    sym = df.iloc[0]["symbol"]
    path = symbol_path(provider, sym)
    _write_func()(df, path)


def load_symbol(provider: str, symbol: str) -> pd.DataFrame:
    """Load data for a single symbol."""
    path = symbol_path(provider, symbol)
    if not path.exists():
        return pd.DataFrame()
    return _read_func()(path)


def list_symbols(provider: str) -> list[str]:
    """List all symbols with stored data for *provider*."""
    base = _base_dir(provider)
    ext = _ext()
    files = glob.glob(os.path.join(base, f"*{ext}"))
    # Exclude meta files (equities*, indices*, etc.)
    names = []
    for f in files:
        stem = Path(f).stem
        if stem.startswith("equities") or stem.startswith("indices"):
            continue
        names.append(stem)
    return sorted(names)


# ---------------------------------------------------------------------------
# Options readers / writers (used by UpstoxOptions provider)
# ---------------------------------------------------------------------------

OPTIONS_META_COLUMNS = [
    "instrument_type", "option_type", "expiry", "strike",
    "lot_size", "underlying_name",
]


def options_path(provider: str, symbol: str) -> Path:
    """Path to an individual option contract file."""
    base = _base_dir(provider)
    return base / f"{symbol}{_ext()}"


def save_option(df: pd.DataFrame, provider: str) -> None:
    """Save data for a single option contract (first row's symbol used as filename).

    The DataFrame is expected to contain:
      - Candle columns: date, open, high, low, close, vol, oi
      - Symbol column: symbol (tradingsymbol)
      - Metadata columns: instrument_type, option_type, expiry, strike,
        lot_size, underlying_name (all optional but useful)
    """
    if df.empty:
        return
    sym = df.iloc[0]["symbol"]
    path = options_path(provider, sym)
    _write_func()(df, path)


def load_option(provider: str, symbol: str) -> pd.DataFrame:
    """Load data for a single option contract."""
    path = options_path(provider, symbol)
    if not path.exists():
        return pd.DataFrame()
    return _read_func()(path)


def list_option_symbols(provider: str) -> list[str]:
    """List all option contract tradingsymbols with stored data."""
    base = _base_dir(provider)
    ext = _ext()
    files = glob.glob(os.path.join(base, f"*{ext}"))
    names = []
    for f in files:
        stem = Path(f).stem
        if stem.startswith("equities") or stem.startswith("indices"):
            continue
        names.append(stem)
    return sorted(names)


def build_options_checkpoint_entry(row: pd.Series) -> dict:
    """Build a metadata dict for an option contract from a CSV row.

    Returns a dict suitable for storing in the checkpoint as symbol metadata.
    """
    return {
        "instrument_type": row.get("instrument_type", ""),
        "option_type": row.get("option_type", ""),
        "expiry": str(row.get("expiry", "")),
        "strike": float(row["strike"]) if pd.notna(row.get("strike")) else None,
        "lot_size": int(row["lot_size"]) if pd.notna(row.get("lot_size")) else None,
        "underlying_name": row.get("name", ""),
    }


# ---------------------------------------------------------------------------
# Contract manifest  –  expiry-queryable catalog of all fetched contracts
# ---------------------------------------------------------------------------

CONTRACT_MANIFEST_FILE = "_contracts.parquet"

# Columns stored in the manifest (must match OptionContract dataclass fields)
MANIFEST_COLUMNS = [
    "instrument_key", "tradingsymbol", "underlying_name", "underlying_type",
    "instrument_type", "option_type", "expiry", "strike", "lot_size", "tick_size",
]


def manifest_path(provider: str) -> Path:
    """Path to the contract manifest file for *provider*."""
    return _base_dir(provider) / CONTRACT_MANIFEST_FILE


def _parquet_engine() -> str:
    """Return 'pyarrow' if available, else 'fastparquet' (used for manifest)."""
    try:
        import pyarrow  # noqa: F401
        return "pyarrow"
    except ImportError:
        return "fastparquet"


def save_contract_manifest(provider: str, contracts_df: pd.DataFrame) -> None:
    """Append/replace the contract manifest in *provider*'s storage directory.

    Always uses parquet format regardless of ``FETCH_STORAGE_FORMAT``
    (the manifest is an internal index, not user-facing data).

    Deduplicates by ``tradingsymbol`` so each contract appears only once.
    The manifest enables O(1) expiry-based queries without loading
    individual parquet files.

    Note:
        The incoming DataFrame may use column ``name`` (from the CSV source)
        instead of ``underlying_name``. The manifest always stores it as
        ``underlying_name``.
    """
    if contracts_df.empty:
        return

    path = manifest_path(provider)
    df = contracts_df.copy()

    # Normalise column names: CSV uses 'name', manifest uses 'underlying_name'
    if "name" in df.columns and "underlying_name" not in df.columns:
        df.rename(columns={"name": "underlying_name"}, inplace=True)
    elif "name" in df.columns and "underlying_name" in df.columns:
        # Both exist — drop 'name' to avoid confusion
        df.drop(columns=["name"], inplace=True)

    cols = [c for c in MANIFEST_COLUMNS if c in df.columns]
    engine = _parquet_engine()

    if path.exists():
        existing = pd.read_parquet(path, engine=engine)
        combined = pd.concat([existing, df[cols]], ignore_index=True)
        combined = combined.drop_duplicates(subset=["tradingsymbol"], keep="last")
    else:
        combined = df[cols].copy()

    # Normalise expiry to string for consistent storage
    if "expiry" in combined.columns:
        combined["expiry"] = combined["expiry"].astype(str)

    combined.to_parquet(path, index=False, compression="gzip", engine=engine)


def load_contract_manifest(provider: str) -> pd.DataFrame:
    """Load the contract manifest for *provider*.

    Always reads parquet regardless of ``FETCH_STORAGE_FORMAT``.

    Returns empty DataFrame if no manifest exists.
    """
    path = manifest_path(provider)
    if not path.exists():
        return pd.DataFrame()
    engine = _parquet_engine()
    df = pd.read_parquet(path, engine=engine)
    # Parse expiry back to date
    if "expiry" in df.columns:
        df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    return df


def query_contracts(
    provider: str,
    underlying_name: str | None = None,
    expiry: str | date | None = None,
    option_type: str | None = None,
    instrument_type: str | None = None,
) -> pd.DataFrame:
    """Query the contract manifest with optional filters.

    Args:
        provider: Provider name (e.g. ``"upstox_options"``).
        underlying_name: Filter by underlying name (company or index name).
        expiry: Filter by expiry date (string ``"YYYY-MM-DD"`` or ``date``).
        option_type: Filter by ``"CE"`` or ``"PE"``.
        instrument_type: Filter by ``"OPTSTK"``, ``"OPTIDX"``, etc.

    Returns:
        Filtered DataFrame from the manifest, or empty if no matches.
    """
    df = load_contract_manifest(provider)
    if df.empty:
        return df
    if underlying_name is not None:
        df = df[df["underlying_name"] == underlying_name]
    if expiry is not None:
        expiry_str = str(expiry)
        df = df[df["expiry"].astype(str) == expiry_str]
    if option_type is not None:
        df = df[df["option_type"] == option_type]
    if instrument_type is not None:
        df = df[df["instrument_type"] == instrument_type]
    return df
