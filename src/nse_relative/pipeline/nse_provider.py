"""
NSE website API provider.

Fetches:
  - Equity historical data via ``getHistoricalTradeData``
  - Nifty 500 index data via ``getIndexChart``

Dependencies (NseClient, storage) are constructor-injected.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import pandas as pd

from nse_relative.config.settings import settings
from nse_relative.config.logger import get_logger
from nse_relative.pipeline.base import DataProvider
from nse_relative.infrastructure.api.nse_client import NseClient
from nse_relative.infrastructure.storage.file_repository import FileStorageRepository
from nse_relative.infrastructure.checkpoint.json_checkpoint import JsonCheckpoint
from nse_relative.infrastructure.symbol_source.nse_index_csv import (
    NseIndexConstituents,
    DEFAULT_NSE_INDEX,
)
from nse_relative.shared.utils import make_date_chunks

logger = get_logger(__name__)

_DATE_FMT = "%d-%m-%Y"


class NSEProvider(DataProvider):
    """Fetch equity + index data from the public NSE India website API.

    Args:
        start_date: Fetch start in ``DD-MM-YYYY``.
        end_date: Fetch end in ``DD-MM-YYYY``.
        index: NSE index name for symbol sourcing (default ``nifty500``).
        force: Ignore checkpoint and re-fetch.
        client: Injected NseClient. Creates default if not provided.
        storage: Injected FileStorageRepository. Creates default if not provided.
        symbol_source: Injected NseIndexConstituents. Creates default if not provided.
    """

    def __init__(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        index: str = DEFAULT_NSE_INDEX,
        force: bool = False,
        client: NseClient | None = None,
        storage: FileStorageRepository | None = None,
        symbol_source: NseIndexConstituents | None = None,
    ) -> None:
        self._start = start_date or settings.nse_fetch_start
        self._end = end_date or settings.nse_fetch_end
        self._index = index
        self._force = force
        self._client = client or NseClient()
        self._storage = storage or FileStorageRepository()
        self._symbol_source = symbol_source or NseIndexConstituents()

        # Build checkpoint from storage path
        cp_path = self._storage.checkpoint_path(self.provider)
        self._checkpoint = JsonCheckpoint(
            cp_path,
            fetch_params={"interval": "day", "index": index},
        )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "nse"

    @property
    def provider(self) -> str:
        return "nse"

    # ------------------------------------------------------------------
    # Fetch implementation
    # ------------------------------------------------------------------

    def _fetch_one_symbol(
        self, symbol: str, date_chunks: list
    ) -> Optional[pd.DataFrame]:
        """Fetch all chunks for a single symbol and return combined DataFrame."""
        parts: list[pd.DataFrame] = []
        for fd, td in date_chunks:
            data = self._client.fetch_historical(symbol, fd, td)
            df = self._client.parse_equity_response(data, symbol)
            if not df.empty:
                parts.append(df)
            time.sleep(settings.nse_fetch_sleep)
        if parts:
            combined = pd.concat(parts, ignore_index=True)
            return (
                combined.drop_duplicates(subset=["Symbol", "Date"])
                .sort_values("Date")
            )
        return None

    def fetch_equities(self, symbols: Optional[list[str]] = None) -> None:
        """Fetch historical daily data for NSE symbols and persist."""
        if symbols is None:
            symbols = self._symbol_source.get_symbols(self._index)

        date_chunks = make_date_chunks(
            self._start, self._end, settings.nse_fetch_chunk_days
        )
        req_start = datetime.strptime(self._start, _DATE_FMT)
        req_end = (
            datetime.strptime(self._end, _DATE_FMT)
            if self._end
            else datetime.now()
        )

        logger.info(
            "NSE equities: %d symbols, %s -> %s (%d chunk(s)), force=%s",
            len(symbols), self._start, self._end,
            len(date_chunks), self._force,
        )

        # Filter by checkpoint
        if not self._force:
            before = len(symbols)
            symbols = [
                s
                for s in symbols
                if self._checkpoint.coverage_needed(s, req_start, req_end)
            ]
            skipped = before - len(symbols)
            if skipped:
                logger.info(
                    "Checkpoint skipped %d symbols (already covered)", skipped
                )

        all_data: list[pd.DataFrame] = []
        with ThreadPoolExecutor(
            max_workers=settings.nse_rate_max_workers
        ) as pool:
            futures = {
                pool.submit(self._fetch_one_symbol, sym, date_chunks): sym
                for sym in symbols
            }
            for i, future in enumerate(as_completed(futures), 1):
                sym = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        all_data.append(result)
                        dates = result["Date"]
                        self._checkpoint.update_symbol(
                            sym,
                            str(dates.min().date()),
                            str(dates.max().date()),
                            rows=len(result),
                        )
                    logger.info("[%d/%d] %s", i, len(symbols), sym)
                except Exception as e:
                    logger.error(
                        "[%d/%d] %s error: %s", i, len(symbols), sym, e
                    )

        if all_data:
            final = pd.concat(all_data, ignore_index=True)
            self._storage.save_equities(final, self.provider)
            logger.info(
                "NSE done: %d symbols, %d rows",
                final["Symbol"].nunique(), len(final),
            )

    def fetch_index(self) -> None:
        """Fetch Nifty 500 index data and persist."""
        logger.info("NSE index: fetching %s ..", settings.nse_benchmark)

        graph_data = self._client.fetch_index_chart(settings.nse_benchmark)
        if graph_data:
            rows = self._client.parse_index_response(
                graph_data, settings.nse_benchmark
            )
            if rows:
                df = pd.DataFrame(rows)
                self._storage.save_index(df, self.provider)
                logger.info("NSE index saved: %d rows", len(df))
        else:
            logger.warning("NSE index: no data returned")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_symbols(self) -> list[str]:
        return self._symbol_source.get_symbols(self._index)
