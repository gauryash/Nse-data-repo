"""
Upstox instrument master download and filtering.

The Upstox instrument master BOD file (``complete.json.gz`` from Upstox
assets, refreshed ~6 AM) contains all exchange-traded instruments.  This
module provides classes to filter it for NSE equities (by ISIN) and NSE
F&O contracts (by instrument type and underlying name).

The JSON schema differs from the old CSV: ``instrument_type`` is ``CE`` /
``PE`` / ``FUT`` / ``EQ`` / ``INDEX`` / ``COM``, ``underlying_type`` is
``EQUITY`` / ``INDEX`` / ``COM`` / ``CUR``, ``expiry`` is an epoch-millis
timestamp and there is no ``option_type`` column.  :func:`normalize_json_rows`
converts the JSON rows into the legacy CSV-style DataFrame the rest of the
pipeline consumes (``OPTSTK`` / ``OPTIDX`` / ``FUTSTK`` / ``FUTIDX``, CE/PE,
date-typed ``expiry``, ``strike``, ``tradingsymbol``, ``exchange`` = segment).

Cache note: the instrument master is cached to disk (``data/instruments/``)
for ``settings.upstox_instruments_cache_ttl_hours`` hours.  A stale cache is
refreshed in the background of the request; if the network fails, the stale
copy is used as a fallback.
"""

from __future__ import annotations

import contextlib
import gzip
import json
import time
from datetime import date as date_type
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.config.settings import settings
from nse_data_pipeline.domain.models import OptionContract

logger = get_logger(__name__)

_CACHE_FILENAME = "complete.json.gz"


# ----------------------------------------------------------------------
# JSON BOD → legacy CSV-style schema normalisation
# ----------------------------------------------------------------------


def _epoch_ms_to_date(value: Any) -> date_type | None:
    """Convert an epoch-millis expiry timestamp to a date (UTC)."""
    if value is None:
        return None
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()


def _map_instrument_type(row: dict[str, Any]) -> str:
    """Map JSON instrument_type + underlying_type to legacy F&O types."""
    it = str(row.get("instrument_type") or "")
    ut = str(row.get("underlying_type") or "")
    if it in ("CE", "PE"):
        if ut == "EQUITY":
            return "OPTSTK"
        if ut == "INDEX":
            return "OPTIDX"
        return it  # COM / CUR (MCX, currency) keep CE/PE
    if it == "FUT":
        if ut == "EQUITY":
            return "FUTSTK"
        if ut == "INDEX":
            return "FUTIDX"
        return it
    return it


def _map_option_type(instrument_type: str) -> str:
    """Derive the legacy option_type column from the raw JSON instrument type."""
    return {"CE": "CE", "PE": "PE", "FUT": "FF"}.get(instrument_type, "")


def normalize_json_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert raw BOD JSON rows into the legacy CSV-style DataFrame.

    Emits the same columns the historical pipeline consumes:
    ``instrument_key, exchange_token, tradingsymbol, name, expiry, strike,
    tick_size, lot_size, instrument_type, option_type, exchange, ISIN_NUMBER``
    plus JSON-native columns kept for the live catalog
    (``underlying_type, underlying_symbol, asset_symbol, segment, weekly``).
    """
    records: list[dict[str, Any]] = []
    for row in rows:
        raw_instrument_type = str(row.get("instrument_type") or "")
        instrument_type = _map_instrument_type(row)
        records.append(
            {
                "instrument_key": row.get("instrument_key") or "",
                "exchange_token": row.get("exchange_token") or "",
                "tradingsymbol": row.get("trading_symbol") or "",
                "name": row.get("name") or "",
                "expiry": _epoch_ms_to_date(row.get("expiry")),
                "strike": row.get("strike_price"),
                "tick_size": row.get("tick_size"),
                "lot_size": row.get("lot_size"),
                "instrument_type": instrument_type,
                "option_type": _map_option_type(raw_instrument_type),
                "exchange": row.get("segment") or "",
                "underlying_type": row.get("underlying_type") or "",
                "underlying_symbol": row.get("underlying_symbol") or "",
                "asset_symbol": row.get("asset_symbol") or "",
                "segment": row.get("segment") or "",
                "weekly": row.get("weekly") or False,
            }
        )
    return pd.DataFrame(records)


class InstrumentMaster:
    """Downloads and parses the Upstox instrument master JSON.

    Provides low-level filtering helpers for NSE_EQ and NSE_FO instruments.
    """

    def __init__(
        self,
        url: str = "",
        cache_path: Path | None = None,
        ttl_hours: float | None = None,
    ) -> None:
        self._url = url or settings.upstox_instruments_url
        self._cache_path = cache_path or settings.instruments_cache_dir / _CACHE_FILENAME
        self._ttl_hours = (
            ttl_hours if ttl_hours is not None else settings.upstox_instruments_cache_ttl_hours
        )
        self._rows: list[dict[str, Any]] | None = None
        self._df: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def download_raw(self) -> list[dict[str, Any]]:
        """Return the parsed JSON rows (cache-aware).

        A fresh on-disk cache is reused; a stale cache is refreshed but kept
        as a fallback if the network is unavailable.
        """
        if self._rows is not None:
            return self._rows
        cached = self._cache_path
        if cached.exists() and self._is_fresh(cached):
            self._rows = self._read_cache(cached)
            if self._rows is not None:
                return self._rows
        try:
            rows = self._fetch_rows()
            self._write_cache(rows)
            self._rows = rows
            return rows
        except Exception as e:
            if cached.exists():
                logger.warning(
                    "Instrument master download failed (%s) — using stale cache %s",
                    e,
                    cached,
                )
                fallback = self._read_cache(cached)
                if fallback is not None:
                    self._rows = fallback
                    return fallback
            raise

    def download(self) -> pd.DataFrame:
        """Download and parse the full instrument master JSON.

        Returns:
            DataFrame with the legacy CSV-style columns (see
            :func:`normalize_json_rows`) plus a derived ``ISIN_NUMBER`` column.
        """
        if self._df is not None:
            return self._df
        df = normalize_json_rows(self.download_raw())
        df["ISIN_NUMBER"] = df["instrument_key"].str.split("|").str[-1]
        self._df = df
        return df

    def invalidate_cache(self) -> None:
        """Force the next call to :meth:`download` to re-fetch."""
        self._df = None
        self._rows = None
        with contextlib.suppress(FileNotFoundError):
            self._cache_path.unlink()

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Cache internals
    # ------------------------------------------------------------------

    def _is_fresh(self, path: Path) -> bool:
        age_hours = (time.time() - path.stat().st_mtime) / 3600.0
        return age_hours < self._ttl_hours

    def _read_cache(self, path: Path) -> list[dict[str, Any]] | None:
        try:
            return json.loads(gzip.decompress(path.read_bytes()))
        except Exception as e:
            logger.warning("Failed to read instrument master cache %s: %s", path, e)
            return None

    def _write_cache(self, rows: list[dict[str, Any]]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_bytes(gzip.compress(json.dumps(rows).encode()))
        except Exception as e:
            logger.warning("Failed to write instrument master cache: %s", e)

    def _fetch_rows(self) -> list[dict[str, Any]]:
        logger.info("Downloading Upstox instrument master from %s", self._url)
        r = requests.get(self._url, timeout=120)
        r.raise_for_status()
        return json.loads(gzip.decompress(r.content))


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
discover_option_contracts = OptionDiscoverer().discover
filter_by_expiry = ExpiryFilter.filter_by_expiry
discover_index_option_names = ExpiryFilter.discover_index_option_names
