"""
Chartink screener scanner.

Fetches stock screener data from chartink.com and sends results via Telegram.
"""

import requests
from bs4 import BeautifulSoup as bs
import pandas as pd

from nse_relative.scanners.base import BaseScanner
from nse_relative.scanners.queries import (
    QUERY_MONTHLY_ATH,
    QUERY_POTENTIAL_BREAKOUTS,
    QUERY_5MIN_INTRADAY_VOLUME_BURST,
)
from nse_relative.scanners.telegram_notifier import (
    send_telegram_message,
    dataframe_to_telegram_chunks,
)
from nse_relative.config.settings import BOT_TOKEN, CHAT_ID_ALERT
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://chartink.com"


class ChartinkScanner(BaseScanner):
    """Run Chartink screeners and send results to Telegram."""

    @property
    def name(self) -> str:
        return "chartink"

    @staticmethod
    def _get_csrf_token(session: requests.Session, url: str) -> str:
        """Fetch CSRF token from a Chartink page."""
        resp = session.get(url)
        soup = bs(resp.content, "lxml")
        return soup.select_one("[name=csrf-token]")["content"]

    @staticmethod
    def _fetch_screener_data(scan_clause: str) -> pd.DataFrame:
        """Fetch screener results from chartink.com.

        Raises:
            RuntimeError: If the API returns a ``scan_error``.
        """
        with requests.Session() as session:
            token = ChartinkScanner._get_csrf_token(
                session, f"{BASE_URL}/screener/time-pass-48"
            )
            session.headers.update({"X-CSRF-TOKEN": token})
            payload = {"scan_clause": scan_clause}
            resp = session.post(f"{BASE_URL}/screener/process", data=payload, timeout=30)
            resp.raise_for_status()
            body = resp.json()

            # Chartink returns {scan_error: "..."} on invalid queries
            if "scan_error" in body:
                raise RuntimeError(body["scan_error"])

            return pd.DataFrame(body.get("data", []))

    def run(self) -> None:
        """Execute all Chartink screeners and send results via Telegram."""
        screeners = [
            {"query": QUERY_MONTHLY_ATH, "title": "🚀 Monthly ATH", "full_df": False},
            {"query": QUERY_POTENTIAL_BREAKOUTS, "title": "🚀 Potential breakouts", "full_df": False},
            {"query": QUERY_5MIN_INTRADAY_VOLUME_BURST, "title": "5Min-Burst", "full_df": False},
        ]

        for s in screeners:
            try:
                df = self._fetch_screener_data(s["query"])
                messages = dataframe_to_telegram_chunks(
                    df, title=s["title"], max_rows=20, full_df=s["full_df"],
                )
                for msg in messages:
                    send_telegram_message(
                        bot_token=BOT_TOKEN,
                        chat_id=CHAT_ID_ALERT,
                        message=msg,
                    )
                logger.info("Sent screener: %s (%d rows)", s["title"], len(df))
            except Exception as e:
                logger.error("Chartink '%s' failed: %s", s["title"], e)
