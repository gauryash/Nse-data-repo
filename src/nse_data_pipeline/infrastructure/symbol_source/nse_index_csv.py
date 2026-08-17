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
from typing import ClassVar

import pandas as pd
import requests

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.config.settings import settings

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Index CSV catalog
# ---------------------------------------------------------------------------

_CSV_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
}
_CSV_TIMEOUT: int = 20


class IndexCsvCatalog:
    """Registry of NSE index names → (config_field, filename) mappings.

    URLs are constructed dynamically from configurable base URLs in
    *settings* so that if NSE changes their CDN domain only an env var
    needs updating.
    """

    _ARCHIVES = "nse_index_csv_base"
    _NIFTY = "niftyindices_base"

    _FILES: ClassVar[dict[str, tuple[str, str]]] = {
        "nifty50": (_ARCHIVES, "ind_nifty50list.csv"),
        "nifty100": (_ARCHIVES, "ind_nifty100list.csv"),
        "nifty200": (_ARCHIVES, "ind_nifty200list.csv"),
        "nifty500": (_ARCHIVES, "ind_nifty500list.csv"),
        "nifty_total_market": (_ARCHIVES, "ind_niftytotalmarket_list.csv"),
        "nifty_next_50": (_ARCHIVES, "ind_niftynext50list.csv"),
        "nifty500_multicap_50_25_25": (_ARCHIVES, "ind_nifty500Multicap502525_list.csv"),
        "nifty500_large_mid_small_equal": (
            _NIFTY,
            "ind_nifty500LargeMidSmallEqualCapWeighted_list.csv",
        ),
        "nifty_midcap_50": (_ARCHIVES, "ind_niftymidcap50list.csv"),
        "nifty_midcap_150": (_ARCHIVES, "ind_niftymidcap150list.csv"),
        "nifty_smallcap_50": (_ARCHIVES, "ind_niftysmallcap50list.csv"),
        "nifty_smallcap_100": (_ARCHIVES, "ind_niftysmallcap100list.csv"),
        "nifty_smallcap_250": (_ARCHIVES, "ind_niftysmallcap250list.csv"),
        "nifty_microcap_250": (_ARCHIVES, "ind_niftymicrocap250_list.csv"),
        "nifty_large_midcap_250": (_ARCHIVES, "ind_niftylargemidcap250list.csv"),
        "nifty_mid_smallcap_400": (_ARCHIVES, "ind_niftymidsmallcap400list.csv"),
        "nifty200_momentum_30": (_NIFTY, "ind_nifty200Momentum30_list.csv"),
        "nifty_midcap150_momentum_50": (_NIFTY, "ind_niftymidcap150momentum50_list.csv"),
        "nifty500_momentum_50": (_NIFTY, "ind_nifty500Momentum50_list.csv"),
        "nifty_mid_smallcap400_momentum_quality_100": (
            _NIFTY,
            "ind_niftyMidSmallcap400MomentumQuality100_list.csv",
        ),
        "nifty_smallcap250_momentum_quality_100": (
            _NIFTY,
            "ind_niftySmallcap250MomentumQuality100_list.csv",
        ),
    }

    @classmethod
    def urls(cls) -> dict[str, str]:
        """Build the full URL for every known index."""
        return {
            name: f"{getattr(settings, base)}/{file}" for name, (base, file) in cls._FILES.items()
        }

    @classmethod
    def names(cls) -> list[str]:
        return sorted(cls.urls().keys())

    @classmethod
    def url_for(cls, index_name: str) -> str:
        urls = cls.urls()
        if index_name not in urls:
            msg = f"Unknown index '{index_name}'. Choose from: {', '.join(cls.names())}"
            raise ValueError(msg)
        return urls[index_name]


DEFAULT_NSE_INDEX = "nifty500"
NSE_INDEX_NAMES: list[str] = IndexCsvCatalog.names()
NSE_INDEX_URLS: dict[str, str] = IndexCsvCatalog.urls()


class NseIndexConstituents:
    """Resolve NSE index constituents to symbols and ISIN codes.

    Results are cached per-instance so repeated lookups for the same
    index don't re-download the CSV.

    Usage::

        idx = NseIndexConstituents()
        symbols = idx.get_symbols("nifty500")
        isin_set = idx.get_isin_set("nifty50")
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        self._cache: dict[str, pd.DataFrame] = {}
        self._session = session or requests.Session()

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
        if index_name in self._cache:
            return self._cache[index_name]

        url = IndexCsvCatalog.url_for(index_name)
        logger.info("Fetching NSE index CSV: %s (%s)", index_name, url)
        resp = self._session.get(url, headers=_CSV_HEADERS, timeout=_CSV_TIMEOUT)
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
