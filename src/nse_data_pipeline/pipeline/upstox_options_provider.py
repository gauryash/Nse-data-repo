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

import pandas as pd

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.config.settings import settings
from nse_data_pipeline.infrastructure.api.upstox_client import TIME_ZONE as UPSTOX_TIME_ZONE
from nse_data_pipeline.infrastructure.api.upstox_client import UpstoxClient
from nse_data_pipeline.infrastructure.checkpoint.json_checkpoint import JsonCheckpoint
from nse_data_pipeline.infrastructure.storage.file_repository import FileStorageRepository
from nse_data_pipeline.infrastructure.storage.manifest import ContractManifest
from nse_data_pipeline.infrastructure.storage.symbol_parser import FnoSymbolParser
from nse_data_pipeline.infrastructure.symbol_source import upstox_instruments as upstox_src
from nse_data_pipeline.infrastructure.symbol_source.nse_index_csv import DEFAULT_NSE_INDEX
from nse_data_pipeline.pipeline.base import DataProvider

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
                t.strip() for t in instrument_types.replace(",", " ").split() if t.strip()
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
            self._client.parse_date(end_date) if end_date else datetime.now(UPSTOX_TIME_ZONE)
        )
        if self._end < self._start:
            raise ValueError(f"end_date ({end_date}) < start_date ({start_date})")

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
    # Main fetch method
    # ------------------------------------------------------------------

    def fetch_options(
        self,
        symbols: list[str] | None = None,
        n_expiries: int | None = None,
        underlying: str | None = None,
        underlyings: list[str] | None = None,
    ) -> None:
        """Fetch historical candle data for F&O contracts and persist.

        Args:
            symbols: Optional list of tradingsymbols to restrict fetching.
            n_expiries: Override number of upcoming expiry cycles.
            underlying: Single underlying stock/index name to restrict to
                        (e.g. "WIPRO", "NIFTY"). Filters on the ``name``
                        column of the contract discovery DataFrame.
            underlyings: Multiple underlying names to restrict to
                        (OPTSTK only). Takes precedence over ``underlying``.
                        Matches against the tradingsymbol's leading alpha
                        characters.
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
                symboldf = upstox_src.filter_by_expiry(symboldf, n_expiries=effective_n)

        if symboldf.empty:
            logger.error(
                "UpstoxOptions: symbol list is empty. "
                "Check the instrument master CSV or NSE index name."
            )
            return

        # Filter to a list of underlying names (takes precedence over single)
        if underlyings is not None and symbols is None:
            symboldf = self._filter_by_underlyings(symboldf, underlyings)
            if symboldf.empty:
                return
        # Filter to a single underlying stock/index (e.g. "WIPRO", "NIFTY")
        elif underlying is not None and symbols is None:
            before = len(symboldf)
            symboldf = symboldf.copy()
            symboldf["_underlying_short"] = symboldf["tradingsymbol"].apply(
                FnoSymbolParser.extract_underlying
            )
            matches = symboldf["_underlying_short"] == underlying.upper()
            symboldf = symboldf[matches]
            if symboldf.empty:
                logger.warning(
                    "Underlying '%s' not found among %d discovered contracts — "
                    "check spelling (expected: RELIANCE, WIPRO, NIFTY, etc.)",
                    underlying,
                    before,
                )
                return
            logger.info(
                "Underlying filter '%s': %d -> %d contracts",
                underlying,
                before,
                len(symboldf),
            )

        # Ensure unique integer index to avoid .loc[i] returning a DataFrame
        symboldf = symboldf.reset_index(drop=True)

        logger.info(
            "UpstoxOptions: %d contracts, interval=%s, types=%s, "
            "n_expiries=%s, range=[%s .. %s], force=%s",
            len(symboldf),
            self._interval,
            self._instrument_types,
            effective_n if symbols is None else "ALL",
            self._start.strftime("%Y-%m-%d"),
            self._end.strftime("%Y-%m-%d"),
            self._force,
        )

        # Fetch each contract in parallel
        with ThreadPoolExecutor(max_workers=settings.upstox_options_max_workers) as pool:
            fut_map = {
                pool.submit(self._fetch_one_contract, symboldf.loc[i]): i for i in symboldf.index
            }
            for future in as_completed(fut_map):
                idx = fut_map[future]
                row = symboldf.loc[idx]
                symbol = row["tradingsymbol"]
                # Extract short underlying name from tradingsymbol for folder structure
                underlying_short = FnoSymbolParser.extract_underlying(symbol)
                # Get expiry date from row metadata
                expiry_val = row.get("expiry")
                expiry_date_str = str(expiry_val) if pd.notna(expiry_val) else None
                try:
                    df = future.result()
                    if df is not None:
                        df = self._attach_metadata(df, row)
                        self._storage.save_option(
                            df,
                            self.provider,
                            symbol,
                            underlying=underlying_short,
                            expiry_date=expiry_date_str,
                        )
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
            logger.info("Contract manifest updated (%d contracts)", len(symboldf))

        logger.info("UpstoxOptions fetch complete.")

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def _filter_by_underlyings(
        self,
        symboldf: pd.DataFrame,
        underlyings: list[str],
    ) -> pd.DataFrame:
        """Restrict ``symboldf`` to contracts whose underlying short name
        is in the given list.

        The filter is applied **only to OPTSTK (and FUTSTK)** rows. Index
        options (OPTIDX) and index futures (FUTIDX) are preserved as-is,
        so a single fetch command can combine a stock-options subset
        with the full index-options universe.
        """
        targets = {u.strip().upper() for u in underlyings if u and u.strip()}
        before = len(symboldf)
        if not targets:
            logger.warning("underlyings list is empty after normalization")
            return symboldf.iloc[0:0].copy()
        if symboldf.empty:
            return symboldf

        is_stock_type = symboldf["instrument_type"].isin({"OPTSTK", "FUTSTK"})
        stock_part = symboldf[is_stock_type].copy()
        index_part = symboldf[~is_stock_type].copy()

        if stock_part.empty:
            logger.info(
                "Underlyings filter %s: no OPTSTK/FUTSTK rows to filter (preserving %d index rows)",
                sorted(targets),
                len(index_part),
            )
            return symboldf.reset_index(drop=True)

        stock_part["_underlying_short"] = stock_part["tradingsymbol"].apply(
            FnoSymbolParser.extract_underlying
        )
        kept_stocks = stock_part[stock_part["_underlying_short"].isin(targets)]
        missing = targets - set(kept_stocks["_underlying_short"].unique())
        if missing:
            logger.warning("Underlyings with no OPTSTK/FUTSTK contracts: %s", sorted(missing))
        logger.info(
            "Underlyings filter %s: OPTSTK/FUTSTK %d -> %d, "
            "OPTIDX/FUTIDX preserved: %d (total %d -> %d)",
            sorted(targets),
            len(stock_part),
            len(kept_stocks),
            len(index_part),
            before,
            len(kept_stocks) + len(index_part),
        )
        out = pd.concat([kept_stocks, index_part], ignore_index=True)
        return out
        missing = targets - set(out["_underlying_short"].unique())
        if missing:
            logger.warning("Underlyings with no contracts: %s", sorted(missing))
        logger.info(
            "Underlyings filter %s: %d -> %d contracts",
            sorted(targets),
            before,
            len(out),
        )
        return out

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_one_contract(self, row: pd.Series) -> pd.DataFrame | None:
        """Fetch missing date chunks for a single contract."""
        symbol = row["tradingsymbol"]
        instrument_key = row["instrument_key"]

        # Skip if contract expired before our start date
        contract_expiry = row.get("expiry")
        if (
            contract_expiry is not None
            and isinstance(contract_expiry, date)
            and contract_expiry < self._start.date()
        ):
            logger.debug(
                "%s: expired %s before fetch start %s — skip",
                symbol,
                contract_expiry,
                self._start.strftime("%Y-%m-%d"),
            )
            return None

        # Checkpoint check
        if not self._force and not self._checkpoint.coverage_needed(
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
                "%s: %d rows [%s .. %s]",
                symbol,
                len(df),
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
        df = df.copy()
        df["instrument_type"] = str(row.get("instrument_type", ""))
        df["option_type"] = str(row.get("option_type", ""))

        # Expiry: safely convert to string for parquet compatibility
        raw_expiry = row.get("expiry")
        if pd.notna(raw_expiry):
            try:
                expiry_str = str(pd.to_datetime(raw_expiry).date())
            except Exception:
                expiry_str = str(raw_expiry)
        else:
            expiry_str = ""
        df["expiry"] = expiry_str

        df["strike"] = float(row["strike"]) if pd.notna(row.get("strike")) else 0.0
        df["lot_size"] = int(row["lot_size"]) if pd.notna(row.get("lot_size")) else 0
        df["underlying_name"] = str(row.get("name", ""))
        return df

    # ------------------------------------------------------------------
    # Symbol resolution (when user provides tradingsymbols)
    # ------------------------------------------------------------------

    def _resolve_provided_symbols(self, symbols: list[str]) -> pd.DataFrame:
        """Look up contract metadata for user-provided tradingsymbols."""
        from nse_data_pipeline.domain.models import AssetType

        df = upstox_src.download_instruments()
        df = df[df["exchange"] == "NSE_FO"]
        matched = df[df["tradingsymbol"].isin(symbols)].copy()
        found = len(matched)
        if found < len(symbols):
            missing = set(symbols) - set(matched["tradingsymbol"])
            logger.warning(
                "%d tradingsymbol(s) not found in NSE_FO master: %s",
                len(missing),
                sorted(missing),
            )
        matched["underlying_type"] = matched["instrument_type"].apply(
            lambda t: AssetType.from_instrument_type(t).value
        )
        return matched[
            [
                "instrument_key",
                "tradingsymbol",
                "name",
                "underlying_type",
                "instrument_type",
                "option_type",
                "expiry",
                "strike",
                "lot_size",
                "tick_size",
            ]
        ]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_symbols(self) -> list[str]:
        return self._storage.list_option_symbols(self.provider)
