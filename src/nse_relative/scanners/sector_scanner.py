"""
Sector & Index Scanner.

Fetches sector/industry/index analysis data from Trendlyne and sends
formatted Telegram reports (Top 10 / Bottom 10).
"""

from typing import Optional

import requests
import pandas as pd

from nse_relative.scanners.base import BaseScanner
from nse_relative.scanners.telegram_notifier import send_telegram_message
from nse_relative.config.settings import BOT_TOKEN, CHAT_ID_ALERT
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

_TRENDLYNE_URL = (
    "https://trendlyne.com/equity/sector-industry-analysis/overall/day-changeP/"
)

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://trendlyne.com/",
}

_LABEL_MAP_COMMON = {
    "day_changeP": "Day",
    "week_changeP": "Week",
    "month_changeP": "Month",
    "qtr_changeP": "Qtr",
    "halfyr_changeP": "HalfYr",
    "year_changeP": "Year",
}

_LABEL_MAP_SECTOR = {
    "day_changeP_mcapw_sec": "Day",
    "week_changeP_mcapw_sec": "Week",
    "month_changeP_mcapw_sec": "Month",
    "qtr_changeP_mcapw_sec": "Qtr",
    "halfyr_changeP_mcapw_sec": "HalfYr",
    "year_changeP_mcapw_sec": "Year",
}


class SectorScanner(BaseScanner):
    """Fetch sector **and** index data from Trendlyne and send two Telegram reports."""

    def __init__(self, sort_by: Optional[str] = None) -> None:
        self._sort_by = sort_by

    @property
    def name(self) -> str:
        return "sector"

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_json(url: str = _TRENDLYNE_URL, timeout: int = 15) -> dict:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _extract_df(raw: dict, try_keys: list[tuple[str, ...]]) -> pd.DataFrame:
        """Walk *try_keys* paths in raw JSON to find tableData."""
        table_data = None
        for path in try_keys:
            tmp = raw
            try:
                for k in path:
                    tmp = tmp[k]
                table_data = tmp
                break
            except (KeyError, TypeError):
                continue
        if table_data is None:
            raise KeyError(f"tableData not found under paths: {try_keys}")
        df = pd.json_normalize(table_data, sep=".")
        preferred = [c for c in df.columns if "stockName" in c or "full_name" in c or "pk" in c]
        others = [c for c in df.columns if c not in preferred]
        return df[preferred + others]

    # ------------------------------------------------------------------
    # Report builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_report(
        df: pd.DataFrame,
        *,
        title: str = "Report",
        sort_by: str = "qtr_changeP",
        name_pattern: str = "stockName",
        label_map: dict = None,
    ) -> str:
        """Build a Telegram message with Top 10 / Bottom 10."""
        if df.empty:
            return ""

        if label_map is None:
            label_map = _LABEL_MAP_COMMON

        name_col = [c for c in df.columns if name_pattern in c][0]
        week_col = [c for c in df.columns if "week_change" in c][0]
        month_col = [c for c in df.columns if "month_change" in c][0]

        if sort_by not in df.columns:
            qtr = [c for c in df.columns if "qtr_change" in c]
            sort_by = qtr[0] if qtr else week_col

        sort_label = label_map.get(sort_by, "Period")

        def fmt_row(row):
            name = str(row[name_col])[:30]
            return f"{name:30s} {row[sort_by]:+6.2f}% {row[month_col]:+6.2f}% {row[week_col]:+6.2f}%"

        header = f"{'Name':30s} {sort_label+'%':>7s} {'Month%':>7s} {'Week%':>7s}"
        sep = "-" * 55

        top = df.sort_values(sort_by, ascending=False).head(10)
        bottom = df.sort_values(sort_by, ascending=True).head(10)

        top_lines = [header, sep] + [fmt_row(r) for _, r in top.iterrows()]
        bottom_lines = [header, sep] + [fmt_row(r) for _, r in bottom.iterrows()]

        return (
            f"{title} (sorted by {sort_label})\n\n"
            f"*TOP 10*\n```\n" + "\n".join(top_lines) + "\n```\n\n"
            f"*BOTTOM 10*\n```\n" + "\n".join(bottom_lines) + "\n```"
        )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Fetch sector and index data, send two Telegram reports."""
        raw = self._fetch_json()

        # --- Sector report ---
        sector_sort = self._sort_by or "qtr_changeP_mcapw_sec"
        sector_df = self._extract_df(raw, [
            ("body", "Sector", "tableData"),
            ("body", "sector", "tableData"),
        ])
        logger.info("Sector data: %s rows, columns=%s", len(sector_df), sector_df.columns.tolist()[:5])

        if not sector_df.empty and BOT_TOKEN:
            msg = self._build_report(
                sector_df,
                title="Sector Report",
                sort_by=sector_sort,
                name_pattern="stockName",
                label_map=_LABEL_MAP_SECTOR,
            )
            if msg:
                send_telegram_message(message=msg)

        # --- Index report ---
        index_sort = self._sort_by or "qtr_changeP"
        index_df = self._extract_df(raw, [("body", "index", "tableData")])
        logger.info("Index data: %s rows", len(index_df))

        if not index_df.empty and BOT_TOKEN:
            msg = self._build_report(
                index_df,
                title="Index Report",
                sort_by=index_sort,
                name_pattern="get_full_name",
                label_map=_LABEL_MAP_COMMON,
            )
            if msg:
                send_telegram_message(message=msg)
