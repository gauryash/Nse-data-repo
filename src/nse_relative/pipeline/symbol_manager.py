"""
Symbol universes per data provider.

Both NSE and Upstox derive their symbol lists from NSE index constituent CSVs.

Each CSV has the same schema::

    Company Name,Industry,Symbol,Series,ISIN Code

These are fetched live from ``nsearchives.nseindia.com`` and ``niftyindices.com``,
so there is never a stale hardcoded list or a static reference CSV.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from nse_relative.config.settings import (
    DATA_DIR,
    NIFTY_BENCHMARK,
    UPSTOX_INSTRUMENTS_URL,
    UPSTOX_OPTIONS_INDEX_NAMES,
)
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

# ======================================================================
# NSE index constituent URLs
# ======================================================================

NSE_INDEX_URLS: dict[str, str] = {
    # Broad market
    "nifty50": "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty100": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nifty200": "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
    "nifty500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "nifty_total_market": "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
    # Next 50
    "nifty_next_50": "https://nsearchives.nseindia.com/content/indices/ind_niftynext50list.csv",
    # Multi-cap
    "nifty500_multicap_50_25_25": "https://nsearchives.nseindia.com/content/indices/ind_nifty500Multicap502525_list.csv",
    "nifty500_large_mid_small_equal": "https://niftyindices.com/IndexConstituent/ind_nifty500LargeMidSmallEqualCapWeighted_list.csv",
    # Mid-cap
    "nifty_midcap_50": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap50list.csv",
    "nifty_midcap_150": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    # Small-cap
    "nifty_smallcap_50": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap50list.csv",
    "nifty_smallcap_100": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap100list.csv",
    "nifty_smallcap_250": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    # Micro-cap
    "nifty_microcap_250": "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
    # Large+Mid / Mid+Small
    "nifty_large_midcap_250": "https://nsearchives.nseindia.com/content/indices/ind_niftylargemidcap250list.csv",
    "nifty_mid_smallcap_400": "https://nsearchives.nseindia.com/content/indices/ind_niftymidsmallcap400list.csv",
    # Momentum / Quality factor indices
    "nifty200_momentum_30": "https://www.niftyindices.com/IndexConstituent/ind_nifty200Momentum30_list.csv",
    "nifty_midcap150_momentum_50": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150momentum50_list.csv",
    "nifty500_momentum_50": "https://www.niftyindices.com/IndexConstituent/ind_nifty500Momentum50_list.csv",
    "nifty_mid_smallcap400_momentum_quality_100": "https://www.niftyindices.com/IndexConstituent/ind_niftyMidSmallcap400MomentumQuality100_list.csv",
    "nifty_smallcap250_momentum_quality_100": "https://www.niftyindices.com/IndexConstituent/ind_niftySmallcap250MomentumQuality100_list.csv",
}

DEFAULT_NSE_INDEX = "nifty500"

NSE_INDEX_NAMES: list[str] = sorted(NSE_INDEX_URLS.keys())

# Common HTTP headers for fetching CSVs
_CSV_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
}

_CSV_TIMEOUT = 20  # seconds

# ======================================================================
# NSE index symbol fetcher
# ======================================================================

_NSE_INDEX_CACHE: dict[str, pd.DataFrame] = {}


def fetch_nse_index_csv(index_name: str) -> pd.DataFrame:
    """Download and parse an NSE index constituent CSV.

    The CSV is cached in memory for the lifetime of the process.

    Args:
        index_name: One of the keys in ``NSE_INDEX_URLS`` (e.g. ``'nifty500'``).

    Returns:
        DataFrame with columns ``Company Name, Industry, Symbol, Series, ISIN Code``.

    Raises:
        ValueError: If *index_name* is unknown.
        requests.RequestException: If the download fails.
    """
    if index_name not in NSE_INDEX_URLS:
        raise ValueError(
            f"Unknown index '{index_name}'. "
            f"Choose from: {', '.join(NSE_INDEX_NAMES)}"
        )

    if index_name in _NSE_INDEX_CACHE:
        return _NSE_INDEX_CACHE[index_name]

    url = NSE_INDEX_URLS[index_name]
    logger.info("Fetching NSE index CSV: %s (%s)", index_name, url)
    resp = requests.get(url, headers=_CSV_HEADERS, timeout=_CSV_TIMEOUT)
    resp.raise_for_status()
    # Handle potential BOM / encoding
    text = resp.content.decode("utf-8-sig")
    df = pd.read_csv(StringIO(text))
    df.dropna(subset=["Symbol", "ISIN Code"], inplace=True)
    _NSE_INDEX_CACHE[index_name] = df
    logger.info("Fetched %d constituents for %s", len(df), index_name)
    return df


def get_nse_symbols(index_name: str = DEFAULT_NSE_INDEX) -> list[str]:
    """Return the list of trading symbols for a given NSE index.

    This is the dynamic replacement for the old hardcoded ``NSE_ALL_SYMBOLS`` list.
    """
    df = fetch_nse_index_csv(index_name)
    return df["Symbol"].str.strip().tolist()


def get_nse_isin_set(index_name: str = DEFAULT_NSE_INDEX) -> set[str]:
    """Return the set of ISIN codes for a given NSE index.

    Used by ``UpstoxProvider`` to filter Upstox instruments.
    """
    df = fetch_nse_index_csv(index_name)
    return set(df["ISIN Code"].str.strip())


# Keep a backward-compatible name for code that hasn't been updated yet
def get_nse_all_symbols() -> list[str]:
    """Return the default NSE symbol list (Nifty 500)."""
    return get_nse_symbols(DEFAULT_NSE_INDEX)


# ======================================================================
# Upstox  –  ISIN-filtered instrument list
# ======================================================================


def download_upstox_instruments(url: str = UPSTOX_INSTRUMENTS_URL) -> pd.DataFrame:
    """Download the full Upstox instrument master CSV."""
    df = pd.read_csv(url, compression="gzip")
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    df["ISIN_NUMBER"] = df["instrument_key"].str.split("|").str[-1]
    return df


def build_upstox_symbol_list(
    index_name: str = DEFAULT_NSE_INDEX,
    output_path: str | Path | None = None,
) -> pd.DataFrame:
    """Filter Upstox instruments against an NSE index ISIN set and save result.

    Args:
        index_name: Which NSE index to use as the ISIN whitelist.
        output_path: Where to save ``SymbolList.xlsx``. Defaults to
            ``data/SymbolList_{index_name}.xlsx``.

    Returns:
        Filtered Upstox DataFrame.
    """
    if output_path is None:
        output_path = DATA_DIR / f"SymbolList_{index_name}.xlsx"

    logger.info("Upstox: downloading instrument master …")
    upstox_df = download_upstox_instruments()
    upstox_df = upstox_df[upstox_df["exchange"] == "NSE_EQ"]

    logger.info("Upstox: fetching NSE index '%s' ISIN set …", index_name)
    isin_set = get_nse_isin_set(index_name)

    logger.info("Upstox: filtering %d instruments by %d ISIN codes …",
                len(upstox_df), len(isin_set))
    filtered = upstox_df[upstox_df["ISIN_NUMBER"].isin(isin_set)]

    filtered.to_excel(str(output_path), index=False)
    logger.info("Upstox: saved %d symbols to %s", len(filtered), output_path)
    return filtered


def get_upstox_symbols(
    index_name: str = DEFAULT_NSE_INDEX,
    excel_path: str | Path | None = None,
) -> pd.DataFrame:
    """Load an already-built Upstox symbol list (rebuilds if missing).

    The filename encodes the NSE index name so different indices can coexist.
    """
    if excel_path is None:
        excel_path = DATA_DIR / f"SymbolList_{index_name}.xlsx"
    excel_path = Path(excel_path)
    if not excel_path.exists():
        return build_upstox_symbol_list(index_name=index_name, output_path=excel_path)
    return pd.read_excel(str(excel_path))


# ======================================================================
# Upstox F&O  –  options & futures instrument list
# ======================================================================


def get_upstox_fno_symbols(
    index_name: str = DEFAULT_NSE_INDEX,
    instrument_types: str | list[str] = "OPTSTK",
    include_futures: bool = False,
) -> pd.DataFrame:
    """Fetch and filter Upstox F&O instruments whose underlying is in a given NSE index.

    Works by:
      1. Downloading the Upstox instrument master CSV.
      2. Filtering to ``exchange == 'NSE_FO'``.
      3. Matching the company ``name`` column against the NSE index
         equity instruments (which have ISINs from the index).

    Args:
        index_name: NSE index name (e.g. ``'nifty500'``).
        instrument_types: Which instrument type(s) to include.
            Can be a single string or a list. Valid: ``OPTSTK``, ``OPTIDX``,
            ``FUTSTK``, ``FUTIDX``. Default is only ``OPTSTK``.
        include_futures: Shortcut to add ``FUTSTK`` (stock futures). Ignored if
            *instrument_types* is explicitly provided.

    Returns:
        DataFrame with columns:
        ``instrument_key, tradingsymbol, name, instrument_type, option_type,
        expiry, strike, lot_size, exchange, tick_size``.
    """
    # Normalise instrument_types
    if isinstance(instrument_types, str):
        types_list = [instrument_types]
    else:
        types_list = list(instrument_types)
    if include_futures and "FUTSTK" not in types_list:
        types_list.append("FUTSTK")

    logger.info(
        "Upstox F&O: downloading instrument master, filtering types=%s …",
        types_list,
    )
    upstox_df = download_upstox_instruments()
    fno_df = upstox_df[upstox_df["exchange"] == "NSE_FO"].copy()
    fno_df = fno_df[fno_df["instrument_type"].isin(types_list)]

    if fno_df.empty:
        logger.warning("No NSE_FO instruments found for types %s", types_list)
        return fno_df

    # ── Get the set of company names for the NSE index ──────────────
    # First get NSE_EQ instruments that match the index ISIN set,
    # then use their company names to filter F&O instruments.
    isin_set = get_nse_isin_set(index_name)
    eq_df = upstox_df[
        (upstox_df["exchange"] == "NSE_EQ")
        & (upstox_df["ISIN_NUMBER"].isin(isin_set))
    ]
    underlying_names = set(eq_df["name"].dropna().str.strip().unique())

    if not underlying_names:
        logger.warning("No equity names found for index '%s' — returning all F&O.", index_name)
        return fno_df

    # ── Filter F&O by underlying company name ───────────────────────
    before = len(fno_df)
    fno_df = fno_df[fno_df["name"].str.strip().isin(underlying_names)]
    logger.info(
        "Upstox F&O: %d → %d instruments (filtered by %d underlying names from '%s')",
        before, len(fno_df), len(underlying_names), index_name,
    )

    return fno_df[["instrument_key", "tradingsymbol", "name", "instrument_type",
                    "option_type", "expiry", "strike", "lot_size",
                    "exchange", "tick_size"]]


def get_upstox_option_tradingsymbols(
    index_name: str = DEFAULT_NSE_INDEX,
    instrument_types: str | list[str] = "OPTSTK",
    include_futures: bool = False,
) -> list[str]:
    """Convenience: return just the tradingsymbol list for Upstox F&O instruments."""
    df = get_upstox_fno_symbols(
        index_name=index_name,
        instrument_types=instrument_types,
        include_futures=include_futures,
    )
    return df["tradingsymbol"].str.strip().tolist()


# ======================================================================
# Domain model & discovery  –  used by UpstoxOptionsProvider
# ======================================================================


@dataclass
class OptionContract:
    """Value object representing a single F&O contract.

    Composed from the Upstox instrument master CSV row.
    """
    instrument_key: str
    tradingsymbol: str
    underlying_name: str           # company name for OPTSTK, index name for OPTIDX
    underlying_type: str           # "STOCK" or "INDEX"
    instrument_type: str           # OPTSTK, OPTIDX, FUTSTK, FUTIDX
    option_type: str               # CE, PE, or FF for futures
    expiry: date_type | None       # contract expiry date
    strike: float | None           # strike price (None for futures)
    lot_size: int
    tick_size: float

    _CONTRACT_COLUMNS = [
        "instrument_key", "tradingsymbol", "name", "underlying_type",
        "instrument_type", "option_type", "expiry", "strike",
        "lot_size", "tick_size",
    ]

    @classmethod
    def from_dataframe_row(cls, row: pd.Series) -> "OptionContract":
        """Build from a row of the Upstox instrument master CSV."""
        return cls(
            instrument_key=row["instrument_key"],
            tradingsymbol=row["tradingsymbol"],
            underlying_name=row.get("name", ""),
            underlying_type=_derive_underlying_type(row.get("instrument_type", "")),
            instrument_type=row.get("instrument_type", ""),
            option_type=row.get("option_type", ""),
            expiry=row["expiry"] if pd.notna(row.get("expiry")) else None,
            strike=float(row["strike"]) if pd.notna(row.get("strike")) else None,
            lot_size=int(row["lot_size"]) if pd.notna(row.get("lot_size")) else 0,
            tick_size=float(row["tick_size"]) if pd.notna(row.get("tick_size")) else 0.05,
        )

    def to_dict(self) -> dict:
        """Serialize to dict for DataFrame construction / checkpoint storage."""
        return {
            "instrument_key": self.instrument_key,
            "tradingsymbol": self.tradingsymbol,
            "underlying_name": self.underlying_name,
            "underlying_type": self.underlying_type,
            "instrument_type": self.instrument_type,
            "option_type": self.option_type,
            "expiry": str(self.expiry) if self.expiry else None,
            "strike": self.strike,
            "lot_size": self.lot_size,
            "tick_size": self.tick_size,
        }


def _derive_underlying_type(instrument_type: str) -> str:
    """Map instrument type to its underlying asset class."""
    if instrument_type in ("OPTSTK", "FUTSTK"):
        return "STOCK"
    if instrument_type in ("OPTIDX", "FUTIDX"):
        return "INDEX"
    return "UNKNOWN"


# -----------------------------------------------------------------------
# Index option discovery
# -----------------------------------------------------------------------

_INDEX_OPTION_CACHE: dict[str, list[str]] = {}


def discover_index_option_names() -> list[str]:
    """Auto-discover available index option names from the Upstox instrument master.

    Returns sorted list of unique index ``name`` values for OPTIDX instruments
    (e.g. ``["BANK NIFTY", "FINNIFTY", "NIFTY 50", …]``).

    Results are cached in memory for the lifetime of the process.
    """
    if _INDEX_OPTION_CACHE:
        return _INDEX_OPTION_CACHE.get("names", [])

    try:
        df = download_upstox_instruments()
        optidx = df[df["instrument_type"] == "OPTIDX"]
        names = sorted(optidx["name"].dropna().str.strip().unique())
        _INDEX_OPTION_CACHE["names"] = names
        logger.info("Discovered %d index option names: %s", len(names), names)
        return names
    except Exception as e:
        logger.warning("Failed to discover index options: %s", e)
        return []


# -----------------------------------------------------------------------
# Unified contract discovery
# -----------------------------------------------------------------------

_DISCOVER_CONTRACTS_CACHE: dict[str, pd.DataFrame] = {}


def discover_option_contracts(
    instrument_types: str | list[str] | None = None,
    index_name: str = DEFAULT_NSE_INDEX,
    include_futures: bool = False,
    cache_key: str | None = None,
) -> pd.DataFrame:
    """Discover all F&O contracts matching the given criteria.

    This is the unified discovery function that handles **both**:
      - **OPTSTK / FUTSTK** — filtered by underlying company name matching the
        NSE index equity ISIN set.
      - **OPTIDX / FUTIDX** — discovered from the instrument master CSV's
        OPTIDX section (all available index names are included).

    Args:
        instrument_types: Which instrument type(s) to include.
            ``None`` uses the default ``["OPTSTK", "OPTIDX"]``.
        index_name: NSE index for filtering stock option underlyings
            (default: ``nifty500``).
        include_futures: Shortcut to add ``FUTSTK`` / ``FUTIDX``.
        cache_key: Optional cache key. If provided, results are cached
            in memory under this key for the process lifetime.

    Returns:
        DataFrame with columns matching ``OptionContract._CONTRACT_COLUMNS``:
        ``instrument_key, tradingsymbol, name, underlying_type,
        instrument_type, option_type, expiry, strike, lot_size, tick_size``.
    """
    import hashlib

    # Compute cache key
    if cache_key is None:
        parts = [
            str(instrument_types or "OPTSTK,OPTIDX"),
            index_name,
            str(include_futures),
        ]
        cache_key = hashlib.md5("|".join(parts).encode()).hexdigest()

    if cache_key in _DISCOVER_CONTRACTS_CACHE:
        return _DISCOVER_CONTRACTS_CACHE[cache_key]

    # Normalise instrument types
    if instrument_types is None:
        types_list = ["OPTSTK", "OPTIDX"]
    elif isinstance(instrument_types, str):
        types_list = [t.strip() for t in instrument_types.replace(",", " ").split() if t.strip()]
    else:
        types_list = list(instrument_types)
    if include_futures:
        for ft in ("FUTSTK", "FUTIDX"):
            if ft not in types_list:
                types_list.append(ft)

    # Separate stock vs index instrument types
    stock_types = {t for t in types_list if t in ("OPTSTK", "FUTSTK")}
    index_types = {t for t in types_list if t in ("OPTIDX", "FUTIDX")}

    logger.info(
        "Discovering option contracts: stock_types=%s, index_types=%s, index=%s",
        stock_types, index_types, index_name,
    )

    # ── Download instrument master ──────────────────────────────────
    upstox_df = download_upstox_instruments()
    fno_df = upstox_df[upstox_df["exchange"] == "NSE_FO"].copy()

    all_parts: list[pd.DataFrame] = []

    # ── Stock options (OPTSTK / FUTSTK) ─────────────────────────────
    if stock_types:
        stock_fno = fno_df[fno_df["instrument_type"].isin(stock_types)]
        if not stock_fno.empty:
            isin_set = get_nse_isin_set(index_name)
            eq_df = upstox_df[
                (upstox_df["exchange"] == "NSE_EQ")
                & (upstox_df["ISIN_NUMBER"].isin(isin_set))
            ]
            underlying_names = set(eq_df["name"].dropna().str.strip().unique())
            if underlying_names:
                matched = stock_fno[stock_fno["name"].str.strip().isin(underlying_names)].copy()
                matched["underlying_type"] = "STOCK"
                all_parts.append(matched)
                logger.info(
                    "  Stock contracts: %d → %d (filtered by %d names from '%s')",
                    len(stock_fno), len(matched), len(underlying_names), index_name,
                )
            else:
                logger.warning("  No stock underlying names found for index '%s'", index_name)

    # ── Index options (OPTIDX / FUTIDX) ─────────────────────────────
    if index_types:
        index_fno = fno_df[fno_df["instrument_type"].isin(index_types)]
        if not index_fno.empty:
            # Use configured index names, or auto-discover from CSV
            configured = UPSTOX_OPTIONS_INDEX_NAMES.strip()
            if configured:
                allowed_names = {n.strip() for n in configured.split(",") if n.strip()}
                matched = index_fno[index_fno["name"].str.strip().isin(allowed_names)].copy()
            else:
                matched = index_fno.copy()
            matched["underlying_type"] = "INDEX"
            all_parts.append(matched)
            logger.info(
                "  Index contracts: %d (all available)%s",
                len(matched),
                f" filtered by {len(allowed_names)} names" if configured else "",
            )

    if not all_parts:
        logger.warning("No contracts discovered for types=%s", types_list)
        return pd.DataFrame()

    result = pd.concat(all_parts, ignore_index=True)
    result = result[OptionContract._CONTRACT_COLUMNS]

    # Drop rows with missing tradingsymbol
    result.dropna(subset=["tradingsymbol"], inplace=True)

    _DISCOVER_CONTRACTS_CACHE[cache_key] = result
    logger.info("Total discovered: %d contracts", len(result))
    return result


# -----------------------------------------------------------------------
# Expiry-aware filtering
# -----------------------------------------------------------------------


def filter_by_expiry(
    contracts_df: pd.DataFrame,
    n_expiries: int = 2,
    expiry_date_col: str = "expiry",
    group_by_col: str = "name",
) -> pd.DataFrame:
    """Keep only contracts belonging to the next *n_expiries* expiry dates
    per underlying group.

    This enables queries like:
      "Give me all NIFTY and RELIANCE option contracts for the upcoming 2 expiries."

    Args:
        contracts_df: DataFrame with at minimum an ``expiry`` date column
            and a ``name`` (underlying name) column.
        n_expiries: Number of upcoming expiry cycles to keep (default 2).
            Pass ``0`` to disable filtering (return all contracts).
        expiry_date_col: Name of the expiry date column.
        group_by_col: Name of the column to group by (typically ``"name"``,
            which is the company name for stocks or index name for indices).

    Returns:
        Filtered DataFrame with only contracts in the next N expiries per group.
        The DataFrame is sorted by (group_by_col, expiry, strike, option_type).
    """
    if n_expiries <= 0:
        return contracts_df

    if contracts_df.empty:
        return contracts_df

    df = contracts_df.copy()

    # Ensure expiry is a date column
    if not isinstance(df[expiry_date_col].iloc[0], date_type):
        df[expiry_date_col] = pd.to_datetime(df[expiry_date_col]).dt.date

    today = date_type.today()

    # Filter out already-expired contracts
    upcoming = df[df[expiry_date_col] >= today].copy()
    if upcoming.empty:
        logger.info("No upcoming contracts found (all expired). Returning all contracts.")
        return df

    # For each underlying group, keep the next N unique expiry dates
    grouped = upcoming.groupby(group_by_col, group_keys=False)
    parts: list[pd.DataFrame] = []

    for _name, group in grouped:
        unique_expiries = sorted(group[expiry_date_col].unique())
        keep_expiries = set(unique_expiries[:n_expiries])
        parts.append(group[group[expiry_date_col].isin(keep_expiries)])

    result = pd.concat(parts, ignore_index=True)
    result = result.sort_values([group_by_col, expiry_date_col, "strike", "option_type"])
    result.reset_index(drop=True, inplace=True)

    logger.info(
        "Expiry filter: %d → %d contracts (next %d expiry(ies) per %d underlyings)",
        len(contracts_df), len(result), n_expiries, result[group_by_col].nunique(),
    )
    return result
