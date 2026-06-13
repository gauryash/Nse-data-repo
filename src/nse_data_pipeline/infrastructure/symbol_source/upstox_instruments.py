"""
Upstox instrument master download and filtering.

The Upstox instrument master CSV (``complete.csv.gz`` from Upstox assets)
contains all exchange-traded instruments.  This module provides classes
to filter it for NSE equities (by ISIN) and NSE F&O contracts (by
instrument type and underlying name).

Cache note: the instrument master is NOT cached by default because it
changes daily (new contracts added, expired contracts removed).
Each call downloads the latest version.
"""

from __future__ import annotations

from datetime import date as date_type
from pathlib import Path

import pandas as pd

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.config.settings import settings
from nse_data_pipeline.domain.models import OptionContract

logger = get_logger(__name__)


class InstrumentMaster:
    """Downloads and parses the Upstox instrument master CSV.

    Provides low-level filtering helpers for NSE_EQ and NSE_FO instruments.
    """

    def __init__(self, url: str = "") -> None:
        self._url = url or settings.upstox_instruments_url
        self._df: pd.DataFrame | None = None

    def download(self) -> pd.DataFrame:
        """Download and parse the full instrument master CSV.

        Returns:
            DataFrame with columns from the master CSV, plus a derived
            ``ISIN_NUMBER`` column.
        """
        if self._df is not None:
            return self._df
        df = pd.read_csv(self._url, compression="gzip")
        df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
        df["ISIN_NUMBER"] = df["instrument_key"].str.split("|").str[-1]
        self._df = df
        return df

    def invalidate_cache(self) -> None:
        """Force the next call to :meth:`download` to re-fetch."""
        self._df = None

    def get_equities(self) -> pd.DataFrame:
        """Return all NSE_EQ instruments."""
        return self.download()[self.download()["exchange"] == "NSE_EQ"]

    def get_fno(self) -> pd.DataFrame:
        """Return all NSE_FO instruments."""
        return self.download()[self.download()["exchange"] == "NSE_FO"].copy()

    def filter_by_isin(self, isin_set: set[str]) -> pd.DataFrame:
        """Filter NSE_EQ instruments by an ISIN whitelist."""
        eq = self.get_equities()
        return eq[eq["ISIN_NUMBER"].isin(isin_set)].copy()

    def filter_fno_by_types(
        self,
        instrument_types: list[str],
    ) -> pd.DataFrame:
        """Filter NSE_FO instruments by instrument type list."""
        fno = self.get_fno()
        return fno[fno["instrument_type"].isin(instrument_types)]


class SymbolExporter:
    """Handles saving and loading ISIN-filtered equity symbol lists
    as Excel files for reuse."""

    def __init__(self, master: InstrumentMaster | None = None) -> None:
        self._master = master or InstrumentMaster()

    def export_equity_symbols(
        self,
        isin_set: set[str],
        index_name: str = "",
        output_path: str | Path | None = None,
    ) -> pd.DataFrame:
        """Filter Upstox NSE_EQ instruments by an ISIN whitelist and
        optionally persist as Excel.

        Args:
            isin_set: Set of ISIN codes (from an NSE index).
            index_name: If provided, derives a default output path.
            output_path: Explicit output path override.

        Returns:
            Filtered DataFrame of NSE_EQ instruments.
        """
        filtered = self._master.filter_by_isin(isin_set)
        if index_name and output_path is None:
            output_path = settings.data_dir / f"SymbolList_{index_name}.xlsx"
        if output_path is not None:
            filtered.to_excel(str(output_path), index=False)
            logger.info("Saved %d Upstox symbols to %s", len(filtered), output_path)
        return filtered

    def load_or_rebuild(
        self,
        index_name: str = "",
        excel_path: str | Path | None = None,
    ) -> pd.DataFrame:
        """Load a previously-built symbol list (rebuilds from master if missing).

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
            from nse_data_pipeline.infrastructure.symbol_source.nse_index_csv import (
                NseIndexConstituents,
            )

            idx = NseIndexConstituents()
            isin_set = idx.get_isin_set(index_name)
            return self.export_equity_symbols(
                isin_set, index_name=index_name, output_path=excel_path
            )
        return pd.read_excel(str(excel_path))


class FnoFilter:
    """Filters NSE_FO instruments by type, optionally including futures."""

    @staticmethod
    def resolve_types(
        instrument_types: str | list[str] | None = None,
        include_futures: bool = False,
    ) -> list[str]:
        """Normalise instrument type input into a canonical list."""
        if instrument_types is None:
            types_list = ["OPTSTK", "OPTIDX"]
        elif isinstance(instrument_types, str):
            types_list = [
                t.strip() for t in instrument_types.replace(",", " ").split() if t.strip()
            ]
        else:
            types_list = list(instrument_types)
        if include_futures:
            for ft in ("FUTSTK", "FUTIDX"):
                if ft not in types_list:
                    types_list.append(ft)
        return types_list

    @staticmethod
    def split_by_class(types_list: list[str]) -> tuple[set[str], set[str]]:
        """Split a type list into stock-types and index-types."""
        stock_types = {t for t in types_list if t in ("OPTSTK", "FUTSTK")}
        index_types = {t for t in types_list if t in ("OPTIDX", "FUTIDX")}
        return stock_types, index_types

    @staticmethod
    def select_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Return only the columns that match ``OptionContract._CONTRACT_COLUMNS``."""
        return df[OptionContract._CONTRACT_COLUMNS]


class OptionDiscoverer:
    """Unified F&O contract discovery.

    Handles both:
      - **OPTSTK / FUTSTK** — filtered by underlying company name matching
        the NSE index equity ISIN set.
      - **OPTIDX / FUTIDX** — discovered from the instrument master CSV's
        OPTIDX section.
    """

    def __init__(self, master: InstrumentMaster | None = None) -> None:
        self._master = master or InstrumentMaster()
        self._fno_filter = FnoFilter()

    def discover(
        self,
        instrument_types: str | list[str] | None = None,
        index_name: str = "",
        include_futures: bool = False,
    ) -> pd.DataFrame:
        """Discover F&O contracts matching the given criteria.

        Args:
            instrument_types: Which instrument types to include.
                ``None`` defaults to ``["OPTSTK", "OPTIDX"]``.
            index_name: NSE index for filtering stock option underlyings.
            include_futures: Shortcut to add FUTSTK / FUTIDX.

        Returns:
            DataFrame with columns matching ``OptionContract._CONTRACT_COLUMNS``.
        """
        types_list = self._fno_filter.resolve_types(instrument_types, include_futures)
        stock_types, index_types = self._fno_filter.split_by_class(types_list)

        logger.info(
            "Discovering option contracts: stock_types=%s, index_types=%s, index=%s",
            stock_types,
            index_types,
            index_name,
        )

        master = self._master.download()
        fno = master[master["exchange"] == "NSE_FO"].copy()
        all_parts: list[pd.DataFrame] = []

        # Stock options (OPTSTK / FUTSTK)
        if stock_types:
            all_parts.append(self._discover_stock_options(fno, stock_types, master, index_name))

        # Index options (OPTIDX / FUTIDX)
        if index_types:
            all_parts.append(self._discover_index_options(fno, index_types))

        if not all_parts:
            logger.warning("No contracts discovered for types=%s", types_list)
            return pd.DataFrame()

        result = pd.concat(all_parts, ignore_index=True)
        result = self._fno_filter.select_columns(result)
        result.dropna(subset=["tradingsymbol"], inplace=True)
        logger.info("Total discovered: %d contracts", len(result))
        return result

    def _discover_stock_options(
        self,
        fno: pd.DataFrame,
        stock_types: set[str],
        master: pd.DataFrame,
        index_name: str,
    ) -> pd.DataFrame:
        """Discover stock options (OPTSTK/FUTSTK) by matching NSE index ISINs
        against the company names in the F&O master."""
        stock_fno = fno[fno["instrument_type"].isin(stock_types)]
        if stock_fno.empty:
            return pd.DataFrame()

        from nse_data_pipeline.infrastructure.symbol_source.nse_index_csv import (
            NseIndexConstituents,
        )

        idx = NseIndexConstituents()
        isin_set = idx.get_isin_set(index_name)
        eq_df = master[(master["exchange"] == "NSE_EQ") & (master["ISIN_NUMBER"].isin(isin_set))]
        underlying_names = set(eq_df["name"].dropna().str.strip().unique())
        if not underlying_names:
            return pd.DataFrame()

        matched = stock_fno[stock_fno["name"].str.strip().isin(underlying_names)].copy()
        matched["underlying_type"] = "STOCK"
        return matched

    def _discover_index_options(
        self,
        fno: pd.DataFrame,
        index_types: set[str],
    ) -> pd.DataFrame:
        """Discover index options (OPTIDX/FUTIDX) from the instrument master."""
        index_fno = fno[fno["instrument_type"].isin(index_types)]
        if index_fno.empty:
            return pd.DataFrame()

        configured = settings.upstox_options_index_names.strip()
        if configured:
            allowed_names = {n.strip() for n in configured.split(",") if n.strip()}
            matched = index_fno[index_fno["name"].str.strip().isin(allowed_names)].copy()
        else:
            matched = index_fno.copy()
        matched["underlying_type"] = "INDEX"
        return matched


class ExpiryFilter:
    """Per-underlying expiry filtering for option contracts.

    Keeps only the next *N* unique expiry dates per underlying group,
    with all strikes x option types for those dates.
    """

    @staticmethod
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
        result = result.sort_values([group_by_col, expiry_date_col, "strike", "option_type"])
        result.reset_index(drop=True, inplace=True)

        logger.info(
            "Expiry filter: %d -> %d contracts (next %d expiry(ies) per %d underlyings)",
            len(contracts_df),
            len(result),
            n_expiries,
            result[group_by_col].nunique(),
        )
        return result

    @staticmethod
    def discover_index_option_names() -> list[str]:
        """Auto-discover available index option names from the Upstox
        instrument master.

        Returns:
            Sorted list of unique index ``name`` values for OPTIDX instruments.
        """
        try:
            master = InstrumentMaster()
            df = master.download()
            optidx = df[df["instrument_type"] == "OPTIDX"]
            names = sorted(optidx["name"].dropna().str.strip().unique())
            logger.info("Discovered %d index option names", len(names))
            return names
        except Exception as e:
            logger.warning("Failed to discover index options: %s", e)
            return []


# ======================================================================
# Convenience aliases (backward compatible)
# ======================================================================

download_instruments = InstrumentMaster().download
get_equity_symbols = SymbolExporter().export_equity_symbols
load_equity_symbols = SymbolExporter().load_or_rebuild
get_fno_symbols = FnoFilter  # kept for backward compatibility if used
discover_option_contracts = OptionDiscoverer().discover
filter_by_expiry = ExpiryFilter.filter_by_expiry
discover_index_option_names = ExpiryFilter.discover_index_option_names
