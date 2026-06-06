"""
NSE India website API client.

Handles HTTP session management, retry logic, and rate-limit awareness
for the public NSE India APIs used to fetch equity historical data and
index charts.
"""

from __future__ import annotations

import time
import urllib.parse
from datetime import datetime
from typing import Any, Optional

import pandas as pd
import requests

from nse_relative.config.settings import settings
from nse_relative.config.logger import get_logger
from nse_relative.shared.rate_limiter import RateLimiter

logger = get_logger(__name__)

_DATE_FMT = "%d-%m-%Y"


class NseClient:
    """HTTP client for NSE India public APIs.

    Encapsulates session management, retry logic, and rate limiting so
    that providers don't need to deal with HTTP details.

    The NSE warmup/referrer domain is derived from *base_url* so there
    is no hardcoded ``nseindia.com`` — if NSE changes their domain,
    only ``settings.nse_base_url`` needs to be updated.
    """

    def __init__(
        self,
        base_url: str = settings.nse_base_url,
        index_url: str = settings.nse_index_url,
        max_retries: int = settings.nse_fetch_max_retries,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self._base_url = base_url
        self._index_url = index_url
        self._max_retries = max_retries
        self._rate_limiter = rate_limiter or RateLimiter()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _nse_domain(self) -> str:
        """Extract scheme + netloc from the configured base URL.

        E.g. ``https://www.nseindia.com/api/...`` → ``https://www.nseindia.com``
        """
        parsed = urllib.parse.urlparse(self._base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _create_session(self) -> requests.Session:
        """Create a session with browser-like headers."""
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{self._nse_domain()}/",
        })
        return s

    # ------------------------------------------------------------------
    # Fetch methods
    # ------------------------------------------------------------------

    def fetch_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> list:
        """Fetch raw historical trade data for one symbol over one date range.

        Args:
            symbol: Trading symbol (e.g. ``'RELIANCE'``).
            from_date: Start date in ``DD-MM-YYYY``.
            to_date: End date in ``DD-MM-YYYY``.

        Returns:
            Raw JSON response data (list of dicts), or empty list on failure.
        """
        url = (
            f"{self._base_url}?functionName=getHistoricalTradeData"
            f"&symbol={symbol}&series=EQ"
            f"&fromDate={from_date}&toDate={to_date}"
        )

        s = self._create_session()
        for attempt in range(self._max_retries):
            try:
                # Warm-up request to get cookies (domain derived from settings)
                s.get(self._nse_domain(), timeout=10)
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
                    "%s attempt %d/%d: %s",
                    symbol, attempt + 1, self._max_retries, e,
                )
                if attempt < self._max_retries - 1:
                    self._rate_limiter.wait(symbol)
                else:
                    return []
        return []

    def fetch_index_chart(
        self,
        index_name: str,
        years: str = "30Y",
    ) -> list:
        """Fetch index chart data.

        Args:
            index_name: Index display name (e.g. ``'NIFTY 500'``).
            years: Period flag (default ``'30Y'``).

        Returns:
            List of ``[timestamp_ms, close_price]`` arrays, or empty list.
        """
        s = self._create_session()
        s.get(self._nse_domain(), timeout=10)
        for attempt in range(self._max_retries):
            try:
                r = s.get(
                    self._index_url,
                    params={
                        "functionName": "getIndexChart",
                        "index": index_name,
                        "flag": years,
                    },
                    timeout=10,
                )
                if r.status_code == 200:
                    self._rate_limiter.success(index_name)
                    return r.json().get("data", {}).get("grapthData", [])
                if r.status_code == 429:
                    self._rate_limiter.backoff(index_name)
                    self._rate_limiter.wait(index_name)
                    continue
                logger.warning("Index HTTP %s", r.status_code)
                return []
            except requests.RequestException as e:
                logger.warning(
                    "Index error attempt %d/%d: %s",
                    attempt + 1, self._max_retries, e,
                )
                if attempt < self._max_retries - 1:
                    self._rate_limiter.wait(index_name)
                else:
                    return []
        return []

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_equity_response(data: list, symbol: str) -> pd.DataFrame:
        """Convert raw NSE API response to normalized DataFrame."""
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
    def parse_index_response(data: list, ticker: str) -> list[dict]:
        """Convert raw NSE index chart response to list of dicts."""
        rows: list[dict] = []
        for point in data:
            rows.append({
                "Symbol": ticker,
                "Date": pd.to_datetime(point[0], unit="ms"),
                "Close": point[1],
            })
        return rows
