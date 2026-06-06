"""
Upstox API provider — equities.

Fetches historical candle data (day / week / month) for a symbol list
built by ISIN-filtering the Upstox instrument master against an NSE index.

Dependencies (UpstoxClient, storage) are constructor-injected.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import pandas as pd

from nse_relative.config.settings import settings
from nse_relative.config.logger import get_logger
from nse_relative.pipeline.base import DataProvider
from nse_relative.infrastructure.api.upstox_client import UpstoxClient, TIME_ZONE as UPSTOX_TIME_ZONE
from nse_relative.infrastructure.storage.file_repository import FileStorageRepository
from nse_relative.infrastructure.checkpoint.json_checkpoint import JsonCheckpoint
from nse_relative.infrastructure.symbol_source import upstox_instruments as upstox_src
from nse_relative.infrastructure.symbol_source.nse_index_csv import DEFAULT_NSE_INDEX

logger = get_logger(__name__)


class UpstoxProvider(DataProvider):
    """Fetch historical candle data from the Upstox API for equities.

    Args:
        interval: Candle interval (``'day'``, ``'week'``, ``'month'``).
        index: NSE index name for ISIN-based symbol filtering.
        start_date: Fetch start in ``DD-MM-YYYY``.
        end_date: Fetch end in ``DD-MM-YYYY``.
        force: Ignore checkpoint and re-fetch.
        client: Injected UpstoxClient.
        storage: Injected FileStorageRepository.
    """

    def __init__(
        self,
        interval: str = "",
        index: str = DEFAULT_NSE_INDEX,
        start_date: str | None = None,
        end_date: str | None = None,
        force: bool = False,
        client: UpstoxClient | None = None,
        storage: FileStorageRepository | None = None,
    ) -> None:
        self._interval = interval or settings.upstox_interval.value
        if self._interval not in ("day", "week", "month", "1minute", "30minute"):
            raise ValueError(f"Unsupported interval: {self._interval}")

        self._index = index
        self._force = force
        self._client = client or UpstoxClient()
        self._storage = storage or FileStorageRepository()

        # Date range
        self._start = (
            self._client.parse_date(start_date)
            if start_date
            else self._client.parse_date(settings.upstox_fetch_start)
        )
        self._end = (
            self._client.parse_date(end_date)
            if end_date
            else datetime.now(UPSTOX_TIME_ZONE)
        )
        if self._end < self._start:
            raise ValueError(
                f"end_date ({end_date}) < start_date ({start_date})"
            )

        # Build checkpoint
        cp_path = self._storage.checkpoint_path(self.provider)
        self._checkpoint = JsonCheckpoint(
            cp_path,
            fetch_params={"interval": self._interval, "index": index},
        )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "upstox"

    @property
    def provider(self) -> str:
        return "upstox"

    # ------------------------------------------------------------------
    # Fetch implementation
    # ------------------------------------------------------------------

    def _fetch_one_symbol(self, sym_info: pd.Series) -> pd.DataFrame | None:
        """Fetch missing date chunks for a single symbol."""
        symbol = sym_info["tradingsymbol"]
        instrument_key = sym_info["instrument_key"]

        # Checkpoint check
        if not self._force:
            if not self._checkpoint.coverage_needed(
                symbol,
                self._start.replace(tzinfo=None),
                self._end.replace(tzinfo=None),
            ):
                logger.debug("%s: checkpoint covers range, skip", symbol)
                return None

        # Fetch via shared client
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

    def fetch_equities(self, symbols: Optional[list[str]] = None) -> None:
        """Fetch historical data for all Upstox symbols."""
        symboldf = upstox_src.load_equity_symbols(index_name=self._index)
        if symboldf.empty:
            logger.error(
                "Upstox symbol list is empty. "
                "Run 'nse-relative fetch --provider upstox' first."
            )
            return

        if symbols is not None:
            symboldf = symboldf[symboldf["tradingsymbol"].isin(symbols)]

        logger.info(
            "Upstox: %d symbols, interval=%s, range=[%s … %s], force=%s",
            len(symboldf), self._interval,
            self._start.strftime("%Y-%m-%d"),
            self._end.strftime("%Y-%m-%d"),
            self._force,
        )

        with ThreadPoolExecutor(
            max_workers=settings.upstox_max_workers
        ) as pool:
            fut_map = {
                pool.submit(self._fetch_one_symbol, symboldf.loc[i]): i
                for i in symboldf.index
            }
            for future in as_completed(fut_map):
                idx = fut_map[future]
                row = symboldf.loc[idx]
                symbol = row["tradingsymbol"]
                try:
                    df = future.result()
                    if df is not None:
                        self._storage.save_symbol(df, self.provider, symbol)
                        dmin = df["date"].min()
                        dmax = df["date"].max()
                        self._checkpoint.update_symbol(
                            symbol,
                            dmin.strftime("%Y-%m-%d"),
                            dmax.strftime("%Y-%m-%d"),
                            rows=len(df),
                        )
                except Exception as e:
                    logger.error("%s fetch error: %s", symbol, e)

        logger.info("Upstox fetch complete.")

    def fetch_index(self) -> None:
        """Upstox does not provide index data."""
        logger.info("Upstox: index fetching not implemented — skip.")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_symbols(self) -> list[str]:
        return self._storage.list_symbols(self.provider)
