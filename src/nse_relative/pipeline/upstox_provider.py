"""
Upstox API provider.

Fetches historical candle data (day / week / month) for a symbol list
built by ISIN-filtering the Upstox instrument master against an NSE index.

Supports:
  - Configurable ``start_date`` / ``end_date`` (DD-MM-YYYY)
  - Checkpoint tracking so only missing date ranges are fetched
  - ``force=True`` to bypass checkpoint and re-fetch everything
  - Per-symbol parquet storage in ``data/upstox/``
"""

from __future__ import annotations

import urllib.parse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pytz
import requests

from nse_relative.pipeline.base import DataProvider
from nse_relative.pipeline import storage as store
from nse_relative.pipeline import checkpoint as cp
from nse_relative.pipeline.symbol_manager import get_upstox_symbols, DEFAULT_NSE_INDEX
from nse_relative.config.settings import (
    UPSTOX_BASE_URL,
    UPSTOX_MAX_WORKERS,
    UPSTOX_CHUNK_YEARS,
    UPSTOX_INTERVAL,
    UPSTOX_FETCH_START,
)
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

TIME_ZONE = pytz.timezone("Asia/Kolkata")
CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "vol", "oi"]
_DATE_FMT = "%d-%m-%Y"


def _parse_date(dd_mm_yy: str) -> datetime:
    """Convert ``DD-MM-YYYY`` → timezone-aware datetime."""
    naive = datetime.strptime(dd_mm_yy, _DATE_FMT)
    return TIME_ZONE.localize(naive)


def _fmt_url_date(dt: datetime) -> str:
    """Format a datetime as ``YYYY-MM-DD`` (Upstox API format)."""
    return dt.strftime("%Y-%m-%d")


class UpstoxProvider(DataProvider):
    """Fetch historical candle data from the Upstox API."""

    def __init__(
        self,
        interval: str = UPSTOX_INTERVAL,
        max_workers: int = UPSTOX_MAX_WORKERS,
        chunk_years: int = UPSTOX_CHUNK_YEARS,
        index: str = DEFAULT_NSE_INDEX,
        start_date: str | None = None,
        end_date: str | None = None,
        force: bool = False,
    ) -> None:
        if interval not in ("day", "week", "month", "1minute", "30minute"):
            raise ValueError(f"Unsupported interval: {interval}")
        self._interval = interval
        self._max_workers = max_workers
        self._chunk_years = chunk_years
        self._index = index
        self._force = force

        # Date range
        self._start = (
            _parse_date(start_date)
            if start_date
            else _parse_date(UPSTOX_FETCH_START)
        )
        self._end = (
            _parse_date(end_date)
            if end_date
            else datetime.now(TIME_ZONE)
        )
        if self._end < self._start:
            raise ValueError(f"end_date ({end_date}) < start_date ({start_date})")

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

    def _fetch_chunk(
        self, sym_info: pd.Series, chunk_start: datetime, chunk_end: datetime,
    ) -> pd.DataFrame | None:
        """Fetch a single 5-year chunk for one symbol."""
        parse_key = urllib.parse.quote(sym_info["instrument_key"])
        url = (
            f"{UPSTOX_BASE_URL}/{parse_key}/{self._interval}"
            f"/{_fmt_url_date(chunk_end)}/{_fmt_url_date(chunk_start)}"
        )
        try:
            r = requests.get(url, headers={"accept": "application/json"}, timeout=30)
            candles = r.json().get("data", {}).get("candles", [])
            if not candles:
                return None
            df = pd.DataFrame(candles, columns=CANDLE_COLUMNS)
            df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(TIME_ZONE)
            df["symbol"] = sym_info["tradingsymbol"]
            return df
        except Exception as e:
            logger.warning(
                "%s | %s → %s | %s",
                sym_info["tradingsymbol"], _fmt_url_date(chunk_start),
                _fmt_url_date(chunk_end), e,
            )
            return None

    def _fetch_one_symbol(self, sym_info: pd.Series) -> pd.DataFrame | None:
        """Fetch *missing* date chunks for a single symbol.

        Uses the checkpoint to determine what range is already covered,
        and only fetches what's needed.  In ``force`` mode the entire
        requested range is re-fetched.
        """
        symbol = sym_info["tradingsymbol"]

        # ── Checkpoint check ──────────────────────────────────────────
        if not self._force:
            if not cp.coverage_needed(
                self.provider, symbol,
                self._start.replace(tzinfo=None),
                self._end.replace(tzinfo=None),
            ):
                logger.debug("%s: checkpoint covers range, skip", symbol)
                return None

        # ── Fetch in 5-year chunks ────────────────────────────────────
        parts: list[pd.DataFrame] = []
        cur = self._start
        while cur < self._end:
            chunk_end = min(cur + timedelta(days=365 * self._chunk_years), self._end)
            df = self._fetch_chunk(sym_info, cur, chunk_end)
            if df is not None:
                parts.append(df)
            cur = chunk_end + timedelta(days=1)
            time.sleep(0.05)

        if not parts:
            return None

        combined = pd.concat(parts, ignore_index=True).drop_duplicates(
            subset=["date", "symbol"],
        ).sort_values("date")

        logger.info("%s: %d rows [%s … %s]", symbol, len(combined),
                     combined["date"].min().strftime("%Y-%m-%d"),
                     combined["date"].max().strftime("%Y-%m-%d"))
        return combined

    def fetch_equities(self, symbols: Optional[list[str]] = None) -> None:
        """Fetch historical data for all Upstox symbols.

        Args:
            symbols: Optional list of ``tradingsymbol`` to restrict fetching.
        """
        symboldf = get_upstox_symbols(index_name=self._index)
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
            self._start.strftime("%Y-%m-%d"), self._end.strftime("%Y-%m-%d"),
            self._force,
        )

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
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
                        store.save_symbol(df, self.provider)
                        # Update checkpoint
                        dmin = df["date"].min()
                        dmax = df["date"].max()
                        cp.update_symbol_coverage(
                            self.provider, symbol,
                            dmin.strftime("%Y-%m-%d"),
                            dmax.strftime("%Y-%m-%d"),
                            rows=len(df),
                        )
                except Exception as e:
                    logger.error("%s fetch error: %s", symbol, e)

        logger.info("Upstox fetch complete.")

    def fetch_index(self) -> None:
        """Upstox does not provide index data (for now)."""
        logger.info("Upstox: index fetching not implemented — skip.")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_symbols(self) -> list[str]:
        return store.list_symbols(self.provider)
