"""
Upstox instrument master download and filtering.

The Upstox instrument master CSV (``complete.csv.gz`` from Upstox assets)
contains all exchange-traded instruments.  This module provides functions
to filter it for NSE equities (by ISIN) and NSE F&O contracts (by
instrument type and underlying name).

Cache note: these functions do NOT cache by default because the instrument
master changes daily (new contracts added, expired contracts removed).
Each call downloads the latest version.
"""

from __future__ import annotations

from datetime import date as date_type
from pathlib import Path
from typing import Optional

import pandas as pd

from nse_relative.config.settings import settings
from nse_relative.config.logger import get_logger
from nse_relative.domain.models import AssetType, OptionContract

logger = get_logger(__name__)


def download_instruments(url: str = "") -> pd.DataFrame:
    """Download the full Upstox instrument master CSV.

    Args:
        url: Override URL (default from settings).

    Returns:
        DataFrame with all instruments from the master CSV.
    """
    url = url or settings.upstox_instruments_url
    df = pd.read_csv(url, compression="gzip")
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    df["ISIN_NUMBER"] = df["instrument_key"].str.split("|").str[-1]
    return df


def get_equity_symbols(
    isin_set: set[str],
    index_name: str = "",
    output_path: str | Path | None = None,
) -> pd.DataFrame:
    """Filter Upstox NSE_EQ instruments by an ISIN whitelist.

    Args:
        isin_set: Set of ISIN codes to filter by (from an NSE index).
        index_name: Optional — if provided, saves a SymbolList excel file.
        output_path: Where to save the Excel file (optional).

    Returns:
        Filtered DataFrame of NSE_EQ instruments.
    """
    df = download_instruments()
    df = df[df["exchange"] == "NSE_EQ"]
    filtered = df[df["ISIN_NUMBER"].isin(isin_set)]

    if index_name and output_path is None:
        output_path = settings.data_dir / f"SymbolList_{index_name}.xlsx"
    if output_path is not None:
        filtered.to_excel(str(output_path), index=False)
        logger.info(
            "Saved %d Upstox symbols to %s", len(filtered), output_path
        )

    return filtered


def load_equity_symbols(
    index_name: str = "",
    excel_path: str | Path | None = None,
) -> pd.DataFrame:
    """Load an already-built Upstox symbol list (rebuilds if missing).

    Args:
        index_name: NSE index name (for filename resolution).
        excel_path: Explicit path to the Excel file.

    Returns:
        DataFrame of Upstox equity symbols.
    """
    if excel_path is None:
        excel_path = settings.data_dir / f"SymbolList_{index_name}.xlsx"
    excel_path = Path(excel_path)
    if not excel_path.exists():
        logger.info(
            "Symbol list not found at %s — rebuilding from instrument master ...",
            excel_path,
        )
        isin_set = set()
        from nse_relative.infrastructure.symbol_source.nse_index_csv import (
            NseIndexConstituents,
        )
        idx = NseIndexConstituents()
        isin_set = idx.get_isin_set(index_name)
        return get_equity_symbols(
            isin_set, index_name=index_name, output_path=excel_path
        )
    return pd.read_excel(str(excel_path))


# ======================================================================
# F&O instrument discovery
# ======================================================================


def get_fno_symbols(
    instrument_types: str | list[str] = "OPTSTK",
    include_futures: bool = False,
) -> pd.DataFrame:
    """Fetch and filter Upstox NSE_FO instruments by type.

    Args:
        instrument_types: One or more instrument types.
        include_futures: Shortcut to add FUTSTK/FUTIDX.

    Returns:
        DataFrame of NSE_FO instruments matching the given types.
    """
    if isinstance(instrument_types, str):
        types_list = [t.strip() for t in instrument_types.replace(",", " ").split() if t.strip()]
    else:
        types_list = list(instrument_types)
    if include_futures:
        for ft in ("FUTSTK", "FUTIDX"):
            if ft not in types_list:
                types_list.append(ft)

    df = download_instruments()
    fno_df = df[df["exchange"] == "NSE_FO"].copy()
    fno_df = fno_df[fno_df["instrument_type"].isin(types_list)]
    return fno_df[
        [
            "instrument_key", "tradingsymbol", "name", "instrument_type",
            "option_type", "expiry", "strike", "lot_size", "exchange", "tick_size",
        ]
    ]


def discover_index_option_names() -> list[str]:
    """Auto-discover available index option names from the Upstox instrument master.

    Returns:
        Sorted list of unique index ``name`` values for OPTIDX instruments.
    """
    try:
        df = download_instruments()
        optidx = df[df["instrument_type"] == "OPTIDX"]
        names = sorted(optidx["name"].dropna().str.strip().unique())
        logger.info("Discovered %d index option names", len(names))
        return names
    except Exception as e:
        logger.warning("Failed to discover index options: %s", e)
        return []


def discover_option_contracts(
    instrument_types: str | list[str] | None = None,
    index_name: str = "",
    include_futures: bool = False,
) -> pd.DataFrame:
    """Unified F&O contract discovery.

    Handles both:
      - **OPTSTK / FUTSTK** — filtered by underlying company name matching
        the NSE index equity ISIN set.
      - **OPTIDX / FUTIDX** — discovered from the instrument master CSV's
        OPTIDX section.

    Args:
        instrument_types: Which instrument types to include.
            ``None`` defaults to ``["OPTSTK", "OPTIDX"]``.
        index_name: NSE index for filtering stock option underlyings.
        include_futures: Shortcut to add FUTSTK / FUTIDX.

    Returns:
        DataFrame with columns matching ``OptionContract._CONTRACT_COLUMNS``:
        ``instrument_key, tradingsymbol, name, underlying_type,
        instrument_type, option_type, expiry, strike, lot_size, tick_size``.
    """
    if instrument_types is None:
        types_list = ["OPTSTK", "OPTIDX"]
    elif isinstance(instrument_types, str):
        types_list = [
            t.strip()
            for t in instrument_types.replace(",", " ").split()
            if t.strip()
        ]
    else:
        types_list = list(instrument_types)
    if include_futures:
        for ft in ("FUTSTK", "FUTIDX"):
            if ft not in types_list:
                types_list.append(ft)

    stock_types = {t for t in types_list if t in ("OPTSTK", "FUTSTK")}
    index_types = {t for t in types_list if t in ("OPTIDX", "FUTIDX")}

    logger.info(
        "Discovering option contracts: stock_types=%s, index_types=%s, index=%s",
        stock_types, index_types, index_name,
    )

    df = download_instruments()
    fno_df = df[df["exchange"] == "NSE_FO"].copy()
    all_parts: list[pd.DataFrame] = []

    # Stock options
    if stock_types:
        stock_fno = fno_df[fno_df["instrument_type"].isin(stock_types)]
        if not stock_fno.empty:
            from nse_relative.infrastructure.symbol_source.nse_index_csv import (
                NseIndexConstituents,
            )
            idx = NseIndexConstituents()
            isin_set = idx.get_isin_set(index_name)
            eq_df = df[
                (df["exchange"] == "NSE_EQ")
                & (df["ISIN_NUMBER"].isin(isin_set))
            ]
            underlying_names = set(eq_df["name"].dropna().str.strip().unique())
            if underlying_names:
                matched = stock_fno[
                    stock_fno["name"].str.strip().isin(underlying_names)
                ].copy()
                matched["underlying_type"] = "STOCK"
                all_parts.append(matched)

    # Index options
    if index_types:
        index_fno = fno_df[fno_df["instrument_type"].isin(index_types)]
        if not index_fno.empty:
            configured = settings.upstox_options_index_names.strip()
            if configured:
                allowed_names = {
                    n.strip() for n in configured.split(",") if n.strip()
                }
                matched = index_fno[
                    index_fno["name"].str.strip().isin(allowed_names)
                ].copy()
            else:
                matched = index_fno.copy()
            matched["underlying_type"] = "INDEX"
            all_parts.append(matched)

    if not all_parts:
        logger.warning("No contracts discovered for types=%s", types_list)
        return pd.DataFrame()

    result = pd.concat(all_parts, ignore_index=True)
    result = result[OptionContract._CONTRACT_COLUMNS]
    result.dropna(subset=["tradingsymbol"], inplace=True)
    logger.info("Total discovered: %d contracts", len(result))
    return result


def filter_by_expiry(
    contracts_df: pd.DataFrame,
    n_expiries: int = 2,
    expiry_date_col: str = "expiry",
    group_by_col: str = "name",
) -> pd.DataFrame:
    """Keep only contracts belonging to the next *n_expiries* expiry dates
    per underlying group.

    Args:
        contracts_df: DataFrame with at minimum an ``expiry`` date column
            and a ``name`` (underlying name) column.
        n_expiries: Number of upcoming expiry cycles to keep.
            Pass ``0`` to disable filtering.
        expiry_date_col: Name of the expiry date column.
        group_by_col: Name of the column to group by.

    Returns:
        Filtered DataFrame sorted by (group_by_col, expiry, strike, option_type).
    """
    if n_expiries <= 0 or contracts_df.empty:
        return contracts_df

    df = contracts_df.copy()

    # Ensure expiry is a date column
    from datetime import date as date_type

    if not isinstance(df[expiry_date_col].iloc[0], date_type):
        df[expiry_date_col] = pd.to_datetime(df[expiry_date_col]).dt.date

    today = date_type.today()

    # Filter out already-expired contracts
    upcoming = df[df[expiry_date_col] >= today].copy()
    if upcoming.empty:
        logger.info("No upcoming contracts found (all expired).")
        return df

    # For each underlying group, keep the next N unique expiry dates
    parts: list[pd.DataFrame] = []
    for _name, group in upcoming.groupby(group_by_col, group_keys=False):
        unique_expiries = sorted(group[expiry_date_col].unique())
        keep_expiries = set(unique_expiries[:n_expiries])
        parts.append(group[group[expiry_date_col].isin(keep_expiries)])

    result = pd.concat(parts, ignore_index=True)
    result = result.sort_values(
        [group_by_col, expiry_date_col, "strike", "option_type"]
    )
    result.reset_index(drop=True, inplace=True)

    logger.info(
        "Expiry filter: %d -> %d contracts (next %d expiry(ies) per %d underlyings)",
        len(contracts_df), len(result), n_expiries, result[group_by_col].nunique(),
    )
    return result
