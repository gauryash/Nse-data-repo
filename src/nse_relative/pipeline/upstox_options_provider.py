"""
Upstox F&O (Options & Futures) historical data provider.

Fetches historical candle data for NSE F&O contracts (stock options,
index options, stock futures, index futures) via the Upstox API.

Key features:
  - **Unified discovery**: discovers both OPTSTK (filtered by NSE index ISIN)
    and OPTIDX (auto-discovered from instrument master).
  - **Expiry-aware filtering**: by default only fetches contracts for the
    next N expiry cycles per underlying.
  - **Contract manifest**: maintains a ``_contracts.parquet`` catalog.
  - **Checkpoint**: incremental fetch with per-contract date tracking.

Dependencies (UpstoxClient, storage) are constructor-injected.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Optional

import pandas as pd

from nse_relative.config.settings import settings
from nse_relative.config.logger import get_logger
from nse_relative.pipeline.base import DataProvider
from nse_relative.infrastructure.api.upstox_client import UpstoxClient
from nse_relative.infrastructure.storage.file_repository import FileStorageRepository
from nse_relative.infrastructure.storage.manifest import ContractManifest
from nse_relative.infrastructure.checkpoint.json_checkpoint import JsonCheckpoint
from nse_relative.infrastructure.symbol_source import upstox_instruments as upstox_src
from nse_relative.infrastructure.symbol_source.nse_index_csv import DEFAULT_NSE_INDEX

logger = get_logger(__name__)

_PROVIDER = "upstox_options"


class UpstoxOptionsProvider(DataProvider):
    """Fetch historical candle data for NSE F&O contracts from the Upstox API.

    Args:
        interval: Candle interval.
        index: NSE index name for OPTSTK symbol filtering.
        instrument_types: F&O types (comma-separated or list).
        include_futures: Also fetch FUTSTK/FUTIDX.
        n_expiries: Number of upcoming expiry cycles per underlying.
        start_date: Fetch start in DD-MM-YYYY.
        end_date: Fetch end in DD-MM-YYYY.
        force: Ignore checkpoint and re-fetch.
        client: Injected UpstoxClient.
        storage: Injected FileStorageRepository.
    """

    def __init__(
        self,
        interval: str = "",
        index: str = DEFAULT_NSE_INDEX,
        instrument_types: str | list[str] | None = None,
        include_futures: bool = False,
        n_expiries: int = 2,
        start_date: str | None = None,
        end_date: str | None = None,
        force: bool = False,
        client: UpstoxClient | None = None,
        storage: FileStorageRepository | None = None,
    ) -> None:
        self._interval = interval or settings.upstox_options_interval.value
        if self._interval not in ("day", "week", "month", "1minute", "30minute"):
            raise ValueError(f"Unsupported interval: {self._interval}")

        self._index = index
        self._force = force
        self._include_futures = include_futures
        self._n_expiries = n_expiries
        self._client = client or UpstoxClient()
        self._storage = storage or FileStorageRepository()
        self._manifest = ContractManifest(self._storage, _PROVIDER)

        # Parse instrument types
        if instrument_types is None:
            self._instrument_types = [
                t.strip()
                for t in settings.upstox_options_types.replace(",", " ").split()
                if t.strip()
            ]
        elif isinstance(instrument_types, str):
            self._instrument_types = [
                t.strip()
                for t in instrument_types.replace(",", " ").split()
                if t.strip()
            ]
        else:
            self._instrument_types = list(instrument_types)

        # Date range
        self._start = (
            self._client.parse_date(start_date)
            if start_date
            else self._client.parse_date(settings.upstox_options_fetch_start)
        )
        self._end = (
            self._client.parse_date(end_date)
            if end_date
            else datetime.now(UpstoxClient.TIME_ZONE)
        )
        if self._end < self._start:
            raise ValueError(
                f"end_date ({end_date}) < start_date ({start_date})"
            )

        # Build checkpoint
        cp_path = self._storage.checkpoint_path(self.provider)
        self._checkpoint = JsonCheckpoint(
            cp_path,
            fetch_params={
                "interval": self._interval,
                "index": index,
                "instrument_types": self._instrument_types,
            },
        )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "upstox_options"

    @property
    def provider(self) -> str:
        return _PROVIDER

    # ------------------------------------------------------------------
    # Abstract method stubs
    # ------------------------------------------------------------------

    def fetch_equities(self, symbols: Optional[list[str]] = None) -> None:
        """Not applicable — use ``UpstoxProvider`` for equity data."""
        logger.info("UpstoxOptions: equity fetching not applicable — skip.")

    def fetch_index(self) -> None:
        """Not applicable — use ``NSEProvider`` for index data."""
        logger.info("UpstoxOptions: index fetching not applicable — skip.")

    # ------------------------------------------------------------------
    # Main fetch method
    # ------------------------------------------------------------------

    def fetch_options(
        self,
        symbols: Optional[list[str]] = None,
        n_expiries: int | None = None,
    ) -> None:
        """Fetch historical candle data for F&O contracts and persist.

        Args:
            symbols: Optional list of tradingsymbols to restrict fetching.
            n_expiries: Override number of upcoming expiry cycles.
        """
        effective_n = self._n_expiries if n_expiries is None else n_expiries

        # Resolve symbol universe
        if symbols is not None:
            symboldf = self._resolve_provided_symbols(symbols)
        else:
            symboldf = upstox_src.discover_option_contracts(
                instrument_types=self._instrument_types,
                index_name=self._index,
                include_futures=self._include_futures,
            )
            if effective_n > 0:
                symboldf = upstox_src.filter_by_expiry(
                    symboldf, n_expiries=effective_n
                )

        if symboldf.empty:
            logger.error(
                "UpstoxOptions: symbol list is empty. "
                "Check the instrument master CSV or NSE index name."
            )
            return

        logger.info(
            "UpstoxOptions: %d contracts, interval=%s, types=%s, "
            "n_expiries=%s, range=[%s … %s], force=%s",
            len(symboldf), self._interval, self._instrument_types,
            effective_n if symbols is None else "ALL",
            self._start.strftime("%Y-%m-%d"),
            self._end.strftime("%Y-%m-%d"),
            self._force,
        )

        # Fetch each contract in parallel
        with ThreadPoolExecutor(
            max_workers=settings.upstox_options_max_workers
        ) as pool:
            fut_map = {
                pool.submit(self._fetch_one_contract, symboldf.loc[i]): i
                for i in symboldf.index
            }
            for future in as_completed(fut_map):
                idx = fut_map[future]
                row = symboldf.loc[idx]
                symbol = row["tradingsymbol"]
                try:
                    df = future.result()
                    if df is not None:
                        df = self._attach_metadata(df, row)
                        self._storage.save_option(df, self.provider, symbol)
                        dmin = df["date"].min()
                        dmax = df["date"].max()
                        meta = self._manifest.build_checkpoint_entry(row)
                        self._checkpoint.update_symbol(
                            symbol,
                            dmin.strftime("%Y-%m-%d"),
                            dmax.strftime("%Y-%m-%d"),
                            rows=len(df),
                            meta=meta,
                        )
                except Exception as e:
                    logger.error("%s fetch error: %s", symbol, e)

        # Save contract manifest
        if not symboldf.empty:
            self._manifest.save(symboldf)
            logger.info(
                "Contract manifest updated (%d contracts)", len(symboldf)
            )

        logger.info("UpstoxOptions fetch complete.")

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_one_contract(self, row: pd.Series) -> pd.DataFrame | None:
        """Fetch missing date chunks for a single contract."""
        symbol = row["tradingsymbol"]
        instrument_key = row["instrument_key"]

        # Skip if contract expired before our start date
        contract_expiry = row.get("expiry")
        if contract_expiry is not None and isinstance(contract_expiry, date):
            if contract_expiry < self._start.date():
                logger.debug(
                    "%s: expired %s before fetch start %s — skip",
                    symbol, contract_expiry,
                    self._start.strftime("%Y-%m-%d"),
                )
                return None

        # Checkpoint check
        if not self._force:
            if not self._checkpoint.coverage_needed(
                symbol,
                self._start.replace(tzinfo=None),
                self._end.replace(tzinfo=None),
            ):
                logger.debug("%s: checkpoint covers range, skip", symbol)
                return None

        # Fetch via shared UpstoxClient
        df = self._client.fetch_candles(
            instrument_key=instrument_key,
            interval=self._interval,
            start=self._start,
            end=self._end,
        )

        if df is not None and not df.empty:
            df["symbol"] = symbol
            logger.info(
                "%s: %d rows [%s … %s]",
                symbol, len(df),
                df["date"].min().strftime("%Y-%m-%d"),
                df["date"].max().strftime("%Y-%m-%d"),
            )
            return df
        return None

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _attach_metadata(df: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
        """Add contract metadata columns to the candle DataFrame."""
        df["instrument_type"] = row.get("instrument_type", "")
        df["option_type"] = row.get("option_type", "")
        df["expiry"] = (
            pd.to_datetime(row["expiry"]).date()
            if pd.notna(row.get("expiry"))
            else None
        )
        df["strike"] = (
            float(row["strike"]) if pd.notna(row.get("strike")) else None
        )
        df["lot_size"] = (
            int(row["lot_size"]) if pd.notna(row.get("lot_size")) else None
        )
        df["underlying_name"] = row.get("name", "")
        return df

    # ------------------------------------------------------------------
    # Symbol resolution (when user provides tradingsymbols)
    # ------------------------------------------------------------------

    def _resolve_provided_symbols(
        self, symbols: list[str]
    ) -> pd.DataFrame:
        """Look up contract metadata for user-provided tradingsymbols."""
        from nse_relative.domain.models import AssetType

        df = upstox_src.download_instruments()
        df = df[df["exchange"] == "NSE_FO"]
        matched = df[df["tradingsymbol"].isin(symbols)].copy()
        found = len(matched)
        if found < len(symbols):
            missing = set(symbols) - set(matched["tradingsymbol"])
            logger.warning(
                "%d tradingsymbol(s) not found in NSE_FO master: %s",
                len(missing), sorted(missing),
            )
        matched["underlying_type"] = matched["instrument_type"].apply(
            lambda t: AssetType.from_instrument_type(t).value
        )
        return matched[
            [
                "instrument_key", "tradingsymbol", "name", "underlying_type",
                "instrument_type", "option_type", "expiry", "strike",
                "lot_size", "tick_size",
            ]
        ]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_symbols(self) -> list[str]:
        return self._storage.list_option_symbols(self.provider)
