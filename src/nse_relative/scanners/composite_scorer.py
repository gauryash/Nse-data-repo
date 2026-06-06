"""
Composite Score scanner.

Fetches multi-factor valuation data from screener.in and computes
decile-based composite rankings. Sends top stocks to Telegram.
"""

import time
from pathlib import Path
from typing import Optional

import pandas as pd

from nse_relative.scanners.base import BaseScanner
from nse_relative.scanners.telegram_notifier import send_telegram_message
from nse_relative.config.settings import BOT_TOKEN, CHAT_ID_ALERT, DATA_DIR
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)


class CompositeScorer(BaseScanner):
    """Multi-factor composite ranking using screener.in data."""

    @property
    def name(self) -> str:
        return "composite"

    @staticmethod
    def _fetch_table(link: str, max_pages: int = 2) -> pd.DataFrame:
        """Fetch paginated tables from a screener.in URL."""
        data = pd.DataFrame()
        for page in range(1, max_pages + 1):
            url = f"{link}?page={page}"
            tables = pd.read_html(url, flavor="bs4")
            df = pd.concat(tables)
            df = df.drop(df[df["S.No."].isnull()].index)
            data = pd.concat([data, df], ignore_index=True)
            if len(df.index) < 26:
                break
            time.sleep(1)
        data = data.iloc[0:].drop(data[data["S.No."] == "S.No."].index)
        return data

    def run(self, output_dir: Optional[str | Path] = None) -> None:
        """Run the composite scoring pipeline.

        Fetches P/E, Dividend Yield, BV, Momentum, Cashflow, EV, and Sales
        from screener.in, merges, computes decile ranks, saves Excel, and
        sends top stocks to Telegram.

        Args:
            output_dir: Where to save Excel files. Defaults to ``DATA_DIR``.
        """
        if output_dir is None:
            output_dir = DATA_DIR
        output_dir = Path(output_dir)

        # --- Fetch each factor ---
        logger.info("Composite: fetching P/BV …")
        pbv = self._fetch_table(
            "https://www.screener.in/screens/2112737/trendvalue_pricebookvalue/"
        )
        pbv = pbv[["Name", "P/E", "Div Yld  %", "CMP / BV"]].fillna(
            {"P/E": "100000", "CMP / BV": "100000", "Div Yld  %": "0"}
        ).dropna()
        merged = pbv

        logger.info("Composite: fetching momentum …")
        mom = self._fetch_table(
            "https://www.screener.in/screens/2112742/trendvalue_momentum/"
        )
        mom = mom[["Name", "6mth return  %"]].fillna({"6mth return  %": "-100000"}).dropna()
        merged = merged.merge(mom, on="Name", how="inner")

        logger.info("Composite: fetching cashflow …")
        cf = self._fetch_table(
            "https://www.screener.in/screens/2112756/trendvalue_cashflow/"
        )
        cf = cf[["Name", "CMP / OCF"]].fillna({"CMP / OCF": "100000"}).dropna()
        merged = merged.merge(cf, on="Name", how="inner")

        logger.info("Composite: fetching EV/EBITDA …")
        ev = self._fetch_table(
            "https://www.screener.in/screens/2112767/trendvalue_ev/"
        )
        ev = ev[["Name", "EV / EBITDA"]].fillna({"EV / EBITDA": "100000"}).dropna()
        merged = merged.merge(ev, on="Name", how="inner")

        logger.info("Composite: fetching P/Sales …")
        sales = self._fetch_table(
            "https://www.screener.in/screens/2112772/trendvalue_pricesales/"
        )
        sales = sales[["Name", "CMP / Sales"]].fillna({"CMP / Sales": "100000"}).dropna()
        merged = merged.merge(sales, on="Name", how="inner")

        merged.columns = ["Stock", "PE", "Div", "BV", "6mo Return", "Cashflow", "EV", "Sales"]

        # --- Numeric conversion ---
        for col in ["PE", "Div", "BV", "6mo Return", "Cashflow", "EV", "Sales"]:
            merged[col] = pd.to_numeric(
                merged[col].astype(str).str.replace(",", ""), errors="coerce"
            )

        # --- Decile rankings ---
        def _decile(series, ascending=True):
            rank = series.rank(ascending=ascending)
            return pd.qcut(rank, q=10, labels=False, duplicates="drop") + 1

        merged["PE_Decile"] = _decile(merged["PE"], ascending=True)
        merged["Div_Decile"] = _decile(merged["Div"], ascending=False)
        merged["BV_Decile"] = _decile(merged["BV"], ascending=True)
        merged["Cashflow_Decile"] = _decile(merged["Cashflow"], ascending=True)
        merged["EV_Decile"] = _decile(merged["EV"], ascending=True)
        merged["Sales_Decile"] = _decile(merged["Sales"], ascending=True)

        merged["Consolidated_Rank"] = (
            merged["PE_Decile"] + merged["Div_Decile"] + merged["BV_Decile"]
            + merged["Cashflow_Decile"] + merged["EV_Decile"] + merged["Sales_Decile"]
        )
        merged["Consolidated_Decile"] = _decile(merged["Consolidated_Rank"], ascending=True)

        # --- Save merged ---
        merged_path = output_dir / "composite_merged.xlsx"
        merged.to_excel(str(merged_path), index=False)
        logger.info("Saved merged composite to %s (%d rows)", merged_path, len(merged))

        # --- Top decile ---
        final = merged[merged["Consolidated_Decile"] == 1].sort_values(
            "6mo Return", ascending=False
        )
        final_path = output_dir / "composite_final.xlsx"
        final.to_excel(str(final_path), index=False)
        logger.info("Saved top-decile composite to %s (%d rows)", final_path, len(final))

        # --- Telegram ---
        top10 = final.head(10)["Stock"].tolist()
        if top10:
            msg = "Composite Score - Top Stocks\n\n" + "\n".join(f"- {s}" for s in top10)
            send_telegram_message(
                bot_token=BOT_TOKEN, chat_id=CHAT_ID_ALERT, message=msg,
            )
