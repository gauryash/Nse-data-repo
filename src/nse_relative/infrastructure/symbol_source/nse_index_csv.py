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

import pandas as pd
import requests

from nse_relative.config.logger import get_logger
from nse_relative.config.settings import settings

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Index CSV filenames keyed by index name.
#
# URLs are constructed dynamically from configurable base URLs in settings
# so that if NSE changes their CDN domain only an env var needs updating.
# ---------------------------------------------------------------------------

# Indices hosted on nsearchives.nseindia.com
_NSEARCHIVES = "nse_index_csv_base"

# Indices hosted on niftyindices.com
_NIFTYINDICES = "niftyindices_base"

_NSE_INDEX_FILES: dict[str, tuple[str, str]] = {
    # (config_field, filename)
    "nifty50": (_NSEARCHIVES, "ind_nifty50list.csv"),
    "nifty100": (_NSEARCHIVES, "ind_nifty100list.csv"),
    "nifty200": (_NSEARCHIVES, "ind_nifty200list.csv"),
    "nifty500": (_NSEARCHIVES, "ind_nifty500list.csv"),
    "nifty_total_market": (_NSEARCHIVES, "ind_niftytotalmarket_list.csv"),
    "nifty_next_50": (_NSEARCHIVES, "ind_niftynext50list.csv"),
    "nifty500_multicap_50_25_25": (_NSEARCHIVES, "ind_nifty500Multicap502525_list.csv"),
    "nifty500_large_mid_small_equal": (
        _NIFTYINDICES,
        "ind_nifty500LargeMidSmallEqualCapWeighted_list.csv",
    ),
    "nifty_midcap_50": (_NSEARCHIVES, "ind_niftymidcap50list.csv"),
    "nifty_midcap_150": (_NSEARCHIVES, "ind_niftymidcap150list.csv"),
    "nifty_smallcap_50": (_NSEARCHIVES, "ind_niftysmallcap50list.csv"),
    "nifty_smallcap_100": (_NSEARCHIVES, "ind_niftysmallcap100list.csv"),
    "nifty_smallcap_250": (_NSEARCHIVES, "ind_niftysmallcap250list.csv"),
    "nifty_microcap_250": (_NSEARCHIVES, "ind_niftymicrocap250_list.csv"),
    "nifty_large_midcap_250": (_NSEARCHIVES, "ind_niftylargemidcap250list.csv"),
    "nifty_mid_smallcap_400": (_NSEARCHIVES, "ind_niftymidsmallcap400list.csv"),
    "nifty200_momentum_30": (_NIFTYINDICES, "ind_nifty200Momentum30_list.csv"),
    "nifty_midcap150_momentum_50": (_NIFTYINDICES, "ind_niftymidcap150momentum50_list.csv"),
    "nifty500_momentum_50": (_NIFTYINDICES, "ind_nifty500Momentum50_list.csv"),
    "nifty_mid_smallcap400_momentum_quality_100": (
        _NIFTYINDICES,
        "ind_niftyMidSmallcap400MomentumQuality100_list.csv",
    ),
    "nifty_smallcap250_momentum_quality_100": (
        _NIFTYINDICES,
        "ind_niftySmallcap250MomentumQuality100_list.csv",
    ),
}

NSE_INDEX_URLS: dict[str, str] = {
    name: f"{getattr(settings, base)}/{file}" for name, (base, file) in _NSE_INDEX_FILES.items()
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
                f"Unknown index '{index_name}'. Choose from: {', '.join(NSE_INDEX_NAMES)}"
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
