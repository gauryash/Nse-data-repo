"""
Upstox API client.

Provides a single unified interface for fetching historical candle data
from the Upstox V2 API. Both the equity ``UpstoxProvider`` and the F&O
``UpstoxOptionsProvider`` use this client, eliminating the duplicate
date-formatting and chunk-fetching code they previously had.

Usage::

    client = UpstoxClient()
    df = client.fetch_candles(
        instrument_key="NSE_EQ|INE002A01018",
        interval="month",
        start=datetime(2020, 1, 1),
        end=datetime(2026, 6, 1),
    )
"""

from __future__ import annotations

import time
import urllib.parse
from datetime import datetime, timedelta

import pandas as pd
import pytz
import requests

from nse_relative.config.logger import get_logger
from nse_relative.config.settings import settings

logger = get_logger(__name__)

TIME_ZONE = pytz.timezone("Asia/Kolkata")
CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "vol", "oi"]
_DATE_FMT = "%d-%m-%Y"


class UpstoxClient:
    """HTTP client for the Upstox V2 historical-candle API.

    Both equity and F&O providers share this client.
    """

    def __init__(
        self,
        base_url: str = settings.upstox_base_url,
        chunk_years: int = 5,
        sleep_seconds: float = 0.05,
    ) -> None:
        self._base_url = base_url
        self._chunk_years = chunk_years
        self._sleep = sleep_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_candles(
        self,
        instrument_key: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame | None:
        """Fetch historical candles for a single instrument over the full range.

        The range is automatically split into *chunk_years*-sized pieces so
        the API is not overwhelmed.  Returns a single deduplicated DataFrame
        or ``None`` if no data is returned.

        Args:
            instrument_key: Upstox instrument key (e.g. ``'NSE_EQ|INE002A01018'``).
            interval: Candle interval (``'day'``, ``'week'``, ``'month'``, etc.).
            start: Fetch start (timezone-aware or naive; treated as IST).
            end: Fetch end (timezone-aware or naive; treated as IST).

        Returns:
            DataFrame with columns ``date, open, high, low, close, vol, oi, symbol``,
            or ``None`` if no data.
        """
        parts: list[pd.DataFrame] = []
        cur = start
        while cur < end:
            chunk_end = min(cur + timedelta(days=365 * self._chunk_years), end)
            df = self._fetch_chunk(instrument_key, interval, cur, chunk_end)
            if df is not None:
                parts.append(df)
            cur = chunk_end + timedelta(days=1)
            time.sleep(self._sleep)

        if not parts:
            return None

        return (
            pd.concat(parts, ignore_index=True)
            .drop_duplicates(subset=["date"])
            .sort_values("date")
            .reset_index(drop=True)
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_chunk(
        self,
        instrument_key: str,
        interval: str,
        chunk_start: datetime,
        chunk_end: datetime,
    ) -> pd.DataFrame | None:
        """Fetch a single chunk of candle data from the API."""
        parse_key = urllib.parse.quote(instrument_key)
        url = (
            f"{self._base_url}/{parse_key}/{interval}"
            f"/{self._fmt_date(chunk_end)}/{self._fmt_date(chunk_start)}"
        )
        try:
            r = requests.get(url, headers={"accept": "application/json"}, timeout=30)
            candles = r.json().get("data", {}).get("candles", [])
            if not candles:
                return None
            df = pd.DataFrame(candles, columns=CANDLE_COLUMNS)
            df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(TIME_ZONE)
            return df
        except Exception as e:
            logger.warning(
                "%s | %s -> %s | %s",
                instrument_key,
                self._fmt_date(chunk_start),
                self._fmt_date(chunk_end),
                e,
            )
            return None

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_date(dd_mm_yy: str) -> datetime:
        """Convert ``DD-MM-YYYY`` → timezone-aware datetime (IST)."""
        naive = datetime.strptime(dd_mm_yy, _DATE_FMT)
        return TIME_ZONE.localize(naive)

    @staticmethod
    def _fmt_date(dt: datetime) -> str:
        """Format a datetime as ``YYYY-MM-DD`` (Upstox API format)."""
        return dt.strftime("%Y-%m-%d")
