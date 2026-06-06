"""
NSE index constituent CSV fetcher.

Each NSE index has a corresponding CSV file hosted on ``nsearchives.nseindia.com``
or ``niftyindices.com``.  This module downloads and caches those CSVs to
resolve index constituents to trading symbols and ISIN codes.

CSV schema (all indices)::

    Company Name, Industry, Symbol, Series, ISIN Code

Data is cached in memory per-instance for the lifetime of the object.
"""

from __future__ import annotations

from io import StringIO
from typing import Optional

import pandas as pd
import requests

from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

NSE_INDEX_URLS: dict[str, str] = {
    # Broad market
    "nifty50": "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty100": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nifty200": "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
    "nifty500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "nifty_total_market": "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
    # Next 50
    "nifty_next_50": "https://nsearchives.nseindia.com/content/indices/ind_niftynext50list.csv",
    # Multi-cap
    "nifty500_multicap_50_25_25": "https://nsearchives.nseindia.com/content/indices/ind_nifty500Multicap502525_list.csv",
    "nifty500_large_mid_small_equal": "https://niftyindices.com/IndexConstituent/ind_nifty500LargeMidSmallEqualCapWeighted_list.csv",
    # Mid-cap
    "nifty_midcap_50": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap50list.csv",
    "nifty_midcap_150": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    # Small-cap
    "nifty_smallcap_50": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap50list.csv",
    "nifty_smallcap_100": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap100list.csv",
    "nifty_smallcap_250": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    # Micro-cap
    "nifty_microcap_250": "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
    # Large+Mid / Mid+Small
    "nifty_large_midcap_250": "https://nsearchives.nseindia.com/content/indices/ind_niftylargemidcap250list.csv",
    "nifty_mid_smallcap_400": "https://nsearchives.nseindia.com/content/indices/ind_niftymidsmallcap400list.csv",
    # Momentum / Quality factor indices
    "nifty200_momentum_30": "https://www.niftyindices.com/IndexConstituent/ind_nifty200Momentum30_list.csv",
    "nifty_midcap150_momentum_50": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150momentum50_list.csv",
    "nifty500_momentum_50": "https://www.niftyindices.com/IndexConstituent/ind_nifty500Momentum50_list.csv",
    "nifty_mid_smallcap400_momentum_quality_100": "https://www.niftyindices.com/IndexConstituent/ind_niftyMidSmallcap400MomentumQuality100_list.csv",
    "nifty_smallcap250_momentum_quality_100": "https://www.niftyindices.com/IndexConstituent/ind_niftySmallcap250MomentumQuality100_list.csv",
}

DEFAULT_NSE_INDEX = "nifty500"
NSE_INDEX_NAMES: list[str] = sorted(NSE_INDEX_URLS.keys())

_CSV_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
}
_CSV_TIMEOUT = 20  # seconds


class NseIndexConstituents:
    """Resolve NSE index constituents to symbols and ISIN codes.

    Results are cached per-instance so repeated lookups for the same
    index don't re-download the CSV.

    Usage::

        idx = NseIndexConstituents()
        symbols = idx.get_symbols("nifty500")
        isin_set = idx.get_isin_set("nifty50")
    """

    def __init__(self) -> None:
        self._cache: dict[str, pd.DataFrame] = {}

    def fetch_index_csv(self, index_name: str) -> pd.DataFrame:
        """Download and parse an NSE index constituent CSV.

        Args:
            index_name: One of the keys in ``NSE_INDEX_URLS``.

        Returns:
            DataFrame with columns ``Company Name, Industry, Symbol, Series, ISIN Code``.

        Raises:
            ValueError: If *index_name* is unknown.
            requests.RequestException: If the download fails.
        """
        if index_name not in NSE_INDEX_URLS:
            raise ValueError(
                f"Unknown index '{index_name}'. "
                f"Choose from: {', '.join(NSE_INDEX_NAMES)}"
            )

        if index_name in self._cache:
            return self._cache[index_name]

        url = NSE_INDEX_URLS[index_name]
        logger.info("Fetching NSE index CSV: %s (%s)", index_name, url)
        resp = requests.get(url, headers=_CSV_HEADERS, timeout=_CSV_TIMEOUT)
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig")
        df = pd.read_csv(StringIO(text))
        df.dropna(subset=["Symbol", "ISIN Code"], inplace=True)
        self._cache[index_name] = df
        logger.info("Fetched %d constituents for %s", len(df), index_name)
        return df

    def get_symbols(self, index_name: str = DEFAULT_NSE_INDEX) -> list[str]:
        """Return the list of trading symbols for a given NSE index."""
        df = self.fetch_index_csv(index_name)
        return df["Symbol"].str.strip().tolist()

    def get_isin_set(self, index_name: str = DEFAULT_NSE_INDEX) -> set[str]:
        """Return the set of ISIN codes for a given NSE index.

        Used by Upstox providers to filter instruments.
        """
        df = self.fetch_index_csv(index_name)
        return set(df["ISIN Code"].str.strip())
