"""
NSE website API provider.

Fetches:
  - Equity historical data via ``getHistoricalTradeData``
  - Nifty 500 index data via ``getIndexChart``

Supports:
  - Configurable ``start_date`` / ``end_date`` (DD-MM-YYYY)
  - Checkpoint tracking to skip symbols already covered
  - ``force=True`` to bypass checkpoint
  - Per-symbol checkpoint (bulk fetch still uses the existing dedup logic)
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import requests
import pandas as pd

from nse_relative.pipeline.base import DataProvider
from nse_relative.pipeline.rate_limiter import RateLimiter
from nse_relative.pipeline import storage as store
from nse_relative.pipeline import checkpoint as cp
from nse_relative.pipeline.symbol_manager import get_nse_symbols, DEFAULT_NSE_INDEX
from nse_relative.config.settings import (
    BASE_URL,
    INDEX_HISTORICAL_URL,
    NIFTY_BENCHMARK,
    FETCH_START_DATE,
    FETCH_END_DATE,
    FETCH_CHUNK_DAYS,
    FETCH_MAX_RETRIES,
    FETCH_SLEEP_INTERVAL,
    RATE_MAX_WORKERS,
)
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

_DATE_FMT = "%d-%m-%Y"


class NSEProvider(DataProvider):
    """Fetch equity + index data from the public NSE India website API."""

    def __init__(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        max_workers: int = RATE_MAX_WORKERS,
        index: str = DEFAULT_NSE_INDEX,
        force: bool = False,
    ) -> None:
        self._start = start_date or FETCH_START_DATE
        self._end = end_date or FETCH_END_DATE
        self._index = index
        self._force = force
        self._rate_limiter = RateLimiter(max_workers=max_workers)

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
    # API helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _session() -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        })
        return s

    def _fetch_historical(
        self, symbol: str, from_date: str, to_date: str,
    ) -> list:
        """Raw JSON response for one symbol over one date range."""
        url = (
            f"{BASE_URL}?functionName=getHistoricalTradeData"
            f"&symbol={symbol}&series=EQ"
            f"&fromDate={from_date}&toDate={to_date}"
        )
        s = self._session()
        for attempt in range(FETCH_MAX_RETRIES):
            try:
                s.get("https://www.nseindia.com", timeout=10)
                r = s.get(url, timeout=10)
                if r.status_code == 200:
                    self._rate_limiter.success(symbol)
                    return r.json()
                if r.status_code == 429:
                    self._rate_limiter.backoff(symbol)
                    self._rate_limiter.wait(symbol)
                    continue
                logger.warning("%s HTTP %s", symbol, r.status_code)
                return []
            except requests.RequestException as e:
                logger.warning(
                    "%s attempt %d/%d: %s", symbol, attempt + 1, FETCH_MAX_RETRIES, e,
                )
                if attempt < FETCH_MAX_RETRIES - 1:
                    self._rate_limiter.wait(symbol)
                else:
                    return []
        return []

    # ------------------------------------------------------------------
    # Data parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_equity(data: list, symbol: str) -> pd.DataFrame:
        """Convert raw NSE API response → normalized DataFrame."""
        if not isinstance(data, list) or not data:
            return pd.DataFrame()
        df = pd.DataFrame(data).rename(columns={
            "chPreviousClsPrice": "Prev_Close",
            "chOpeningPrice": "Open",
            "chTradeHighPrice": "High",
            "chTradeLowPrice": "Low",
            "chLastTradedPrice": "Last_Price",
            "chClosingPrice": "Close",
            "vwap": "VWAP",
            "chTotTradedQty": "Volume",
            "chTotTradedVal": "Turnover",
            "chTotalTrades": "Trades",
            "ch52WeekHighPrice": "52W_High",
            "ch52WeekLowPrice": "52W_Low",
            "mtimestamp": "Date",
        })
        df["Symbol"] = symbol
        df["Date"] = pd.to_datetime(df["Date"], format="%d-%b-%Y")
        cols = [
            "Symbol", "Date", "Open", "High", "Low", "Close",
            "Prev_Close", "Volume", "VWAP", "52W_High", "52W_Low",
        ]
        return df[[c for c in cols if c in df.columns]]

    @staticmethod
    def _parse_index(data: list, ticker: str) -> list[dict]:
        """Convert raw NSE index chart response → list of dicts."""
        rows: list[dict] = []
        for point in data:
            rows.append({
                "Symbol": ticker,
                "Date": pd.to_datetime(point[0], unit="ms"),
                "Close": point[1],
            })
        return rows

    # ------------------------------------------------------------------
    # Date chunking
    # ------------------------------------------------------------------

    @staticmethod
    def _date_chunks(start_str: str, end_str: str) -> list[tuple[str, str]]:
        """Split date range into *chunk_days*-sized chunks.

        NSE API returns at most 70 records per call (~100 trading days).
        Using 110-calendar-day chunks ensures each call returns all
        records in the window without hitting the cap and leaving gaps.
        """
        from nse_relative.analytics.utils import make_date_chunks

        return make_date_chunks(start_str, end_str, chunk_days=FETCH_CHUNK_DAYS)

    # ------------------------------------------------------------------
    # Fetch implementation
    # ------------------------------------------------------------------

    def _fetch_one_symbol(self, symbol: str, date_chunks: list) -> Optional[pd.DataFrame]:
        """Fetch all chunks for a single symbol and return combined DataFrame."""
        parts: list[pd.DataFrame] = []
        for fd, td in date_chunks:
            data = self._fetch_historical(symbol, fd, td)
            df = self._parse_equity(data, symbol)
            if not df.empty:
                parts.append(df)
            time.sleep(FETCH_SLEEP_INTERVAL)
        if parts:
            combined = pd.concat(parts, ignore_index=True)
            return combined.drop_duplicates(subset=["Symbol", "Date"]).sort_values("Date")
        return None

    def fetch_equities(self, symbols: Optional[list[str]] = None) -> None:
        """Fetch historical daily data for NSE symbols and persist.

        If *symbols* is ``None``, fetches all constituents of the configured index.
        When *force* is ``False``, the checkpoint is consulted per-symbol to
        skip symbols whose date range is already covered.
        """
        if symbols is None:
            symbols = get_nse_symbols(self._index)

        date_chunks = self._date_chunks(self._start, self._end)
        req_start = datetime.strptime(self._start, _DATE_FMT)
        req_end = datetime.strptime(self._end, _DATE_FMT)

        logger.info(
            "NSE equities: %d symbols, %s → %s (%d chunk(s)), force=%s",
            len(symbols), self._start, self._end, len(date_chunks), self._force,
        )

        # ── Filter by checkpoint ──────────────────────────────────────
        if not self._force:
            before = len(symbols)
            symbols = [
                s for s in symbols
                if cp.coverage_needed(self.provider, s, req_start, req_end)
            ]
            skipped = before - len(symbols)
            if skipped:
                logger.info("Checkpoint skipped %d symbols (already covered)", skipped)

        all_data: list[pd.DataFrame] = []
        with ThreadPoolExecutor(max_workers=self._rate_limiter.max_workers) as pool:
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
                        # Update checkpoint immediately
                        dates = result["Date"]
                        cp.update_symbol_coverage(
                            self.provider, sym,
                            str(dates.min().date()),
                            str(dates.max().date()),
                            rows=len(result),
                        )
                    logger.info("[%d/%d] %s", i, len(symbols), sym)
                except Exception as e:
                    logger.error("[%d/%d] %s error: %s", i, len(symbols), sym, e)

        if all_data:
            final = pd.concat(all_data, ignore_index=True)
            store.save_equities(final, self.provider)
            logger.info(
                "NSE done: %d symbols, %d rows",
                final["Symbol"].nunique(), len(final),
            )

    def fetch_index(self) -> None:
        """Fetch Nifty 500 index data and persist."""
        logger.info("NSE index: fetching %s …", NIFTY_BENCHMARK)

        s = self._session()
        s.get("https://www.nseindia.com", timeout=10)
        for attempt in range(FETCH_MAX_RETRIES):
            try:
                r = s.get(
                    INDEX_HISTORICAL_URL,
                    params={
                        "functionName": "getIndexChart",
                        "index": NIFTY_BENCHMARK,
                        "flag": "30Y",
                    },
                    timeout=10,
                )
                if r.status_code == 200:
                    self._rate_limiter.success(NIFTY_BENCHMARK)
                    graph_data = r.json().get("data", {}).get("grapthData", [])
                    rows = self._parse_index(graph_data, NIFTY_BENCHMARK)
                    if rows:
                        df = pd.DataFrame(rows)
                        store.save_index(df, self.provider)
                        logger.info("NSE index saved: %d rows", len(df))
                    return
                if r.status_code == 429:
                    self._rate_limiter.backoff(NIFTY_BENCHMARK)
                    self._rate_limiter.wait(NIFTY_BENCHMARK)
                    continue
                logger.warning("Index HTTP %s", r.status_code)
                return
            except requests.RequestException as e:
                logger.warning("Index error attempt %d/%d: %s", attempt + 1, FETCH_MAX_RETRIES, e)
                if attempt < FETCH_MAX_RETRIES - 1:
                    self._rate_limiter.wait(NIFTY_BENCHMARK)
                else:
                    return

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_symbols(self) -> list[str]:
        return get_nse_symbols(self._index)
