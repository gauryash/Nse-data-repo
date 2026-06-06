"""
Anchored VWAP proximity screener.

Reads individual symbol parquet files from the Upstox storage directory,
calculates anchored VWAPs from historical highs / lows, and identifies
stocks trading within a configurable threshold of those VWAP levels.
"""

import os
from pathlib import Path
from typing import Optional

import pandas as pd

from nse_relative.analytics.base import BaseAnalyzer
from nse_relative.pipeline import storage as store
from nse_relative.config.settings import (
    UPSTOX_STORAGE_DIR,
    DATA_DIR,
    VWAP_LOOKBACK_YEARS,
    VWAP_THRESHOLD,
    VWAP_MIN_ANCHOR_AGE_MONTHS,
)
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)


class AnchoredVWAP(BaseAnalyzer):
    """Anchored VWAP calculator + proximity screener for Upstox data."""

    def __init__(
        self,
        lookback_years: list[int] | None = None,
        threshold: float = VWAP_THRESHOLD,
        min_anchor_age_months: int = VWAP_MIN_ANCHOR_AGE_MONTHS,
    ) -> None:
        self._lookback_years = lookback_years or VWAP_LOOKBACK_YEARS
        self._threshold = threshold
        self._min_anchor_age = min_anchor_age_months
        self._provider = "upstox"

    @property
    def name(self) -> str:
        return "vwap"

    # ------------------------------------------------------------------
    # VWAP calculation
    # ------------------------------------------------------------------

    def _calculate_anchored_vwap(
        self,
        df: pd.DataFrame,
        price_type: str,  # "high" or "low"
    ) -> pd.DataFrame:
        """Add anchored VWAP columns for every lookback year to *df*.

        Args:
            df: Candle data with columns date, vol, high, low, close, symbol.
            price_type: ``'high'`` or ``'low'``.

        Returns:
            Copy of *df* with additional ``AnchoredVwap_{type}_{yr}yr`` columns.
        """
        if not {"date", "vol", price_type}.issubset(df.columns):
            return df

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date")
        latest = df["date"].max()

        for lookback in self._lookback_years:
            # Define boundaries for this lookback window
            window_start = pd.to_datetime(f"{latest.year - lookback}-01-01")
            chunk = df[(df["date"] >= window_start) & (df["date"] <= latest)].copy()
            if chunk.empty:
                continue

            extreme = chunk[price_type].min() if price_type == "low" else chunk[price_type].max()
            anchor_row = chunk[chunk[price_type] == extreme]
            if anchor_row.empty:
                continue

            anchor_date = anchor_row.iloc[0]["date"]

            # Skip if anchor is too recent
            months = (latest.year - anchor_date.year) * 12 + (latest.month - anchor_date.month)
            if months < self._min_anchor_age:
                continue

            idx = df[df["date"] == anchor_date].index[0]
            df["_cpv"] = (df.loc[idx:, price_type] * df.loc[idx:, "vol"]).cumsum()
            df["_cv"] = df.loc[idx:, "vol"].cumsum()

            col = f"AnchoredVwap_{price_type}_{lookback}yr"
            df[col] = 0.0
            df.loc[idx:, col] = round(df.loc[idx:, "_cpv"] / df.loc[idx:, "_cv"], 2)

            date_col = f"AnchorDate_{price_type}_{lookback}yr"
            df[date_col] = pd.NaT
            df.loc[idx:, date_col] = anchor_date

            df.drop(columns=["_cpv", "_cv"], inplace=True)

        df["date"] = df["date"].dt.date
        return df

    # ------------------------------------------------------------------
    # Proximity check
    # ------------------------------------------------------------------

    def _check_proximity(self, df: pd.DataFrame, price_type: str) -> dict | None:
        """Check if latest close is within *threshold* of any anchored VWAP."""
        last = df.iloc[-1]
        close = last["close"]
        result = {
            "symbol": last.get("symbol", ""),
            "date": last["date"],
            "close": close,
        }
        match = False
        for col in df.columns:
            if not col.startswith(f"AnchoredVwap_{price_type}_"):
                continue
            vwap = last[col]
            if vwap is None or vwap == 0:
                continue
            date_col = col.replace("AnchoredVwap", "AnchorDate")
            if abs(close - vwap) / vwap <= self._threshold:
                result[col] = vwap
                result[date_col] = last[date_col]
                match = True
        return result if match else None

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, output_path: Optional[str | Path] = None, **kwargs) -> None:
        """Read Upstox parquet files, compute VWAPs, check proximity, save results.

        Args:
            output_path: Destination Excel. Defaults to
                ``data/ScreenerList_VWAP_Proximity.xlsx``.
        """
        if output_path is None:
            output_path = DATA_DIR / "ScreenerList_VWAP_Proximity.xlsx"
        output_path = Path(output_path)

        data_dir = UPSTOX_STORAGE_DIR
        vwap_types = ["high", "low"]
        screener: dict[str, list] = {"high": [], "low": []}

        parquet_files = list(data_dir.glob("*.parquet"))
        if not parquet_files:
            logger.warning("No Upstox parquet files found in %s", data_dir)
            return

        logger.info("VWAP scan: %d files, threshold=%.1f%%", len(parquet_files), self._threshold * 100)

        for fpath in parquet_files:
            try:
                df = pd.read_parquet(fpath)
                if df.empty or "symbol" not in df.columns:
                    continue
                df = df.sort_values("date")
                for vt in vwap_types:
                    df = self._calculate_anchored_vwap(df, vt)
                    result = self._check_proximity(df, vt)
                    if result:
                        screener[vt].append(result)
            except Exception as e:
                logger.warning("Error processing %s: %s", fpath.name, e)

        # Write Excel
        with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
            for vt in vwap_types:
                out_df = pd.DataFrame(screener[vt])
                out_df.to_excel(writer, sheet_name=vt.capitalize(), index=False)

        logger.info(
            "VWAP results saved to %s (high=%d, low=%d)",
            output_path, len(screener["high"]), len(screener["low"]),
        )
