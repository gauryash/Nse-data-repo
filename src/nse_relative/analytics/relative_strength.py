"""
Relative Strength (RS) — weekly outperformance vs Nifty 500.

Formula:
    stock_return  = close_today / close_50_weeks_ago
    nifty_return  = nifty_today / nifty_50_weeks_ago
    RS            = (stock_return / nifty_return) - 1

RS > 0 means the stock outperformed the benchmark over the lookback window.
"""

from pathlib import Path
from typing import Optional

import pandas as pd

from nse_relative.analytics.base import BaseAnalyzer
from nse_relative.analytics.utils import resample_weekly, validate_lookback
from nse_relative.pipeline import storage as store
from nse_relative.config.settings import RS_LOOKBACK, NIFTY_BENCHMARK
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)


class RelativeStrength(BaseAnalyzer):
    """Compute weekly RS for every NSE equity and output a ranked CSV."""

    def __init__(self, lookback: int = RS_LOOKBACK) -> None:
        self._lookback = lookback
        self._provider = "nse"  # RS currently only works with NSE data

    @property
    def name(self) -> str:
        return "rs"

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def _compute(self, equities: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
        """Run the RS calculation for every symbol in *equities*.

        Args:
            equities: Daily NSE equity data (columns: Symbol, Date, Close).
            nifty: Daily Nifty 500 data (columns: Date, Close).

        Returns:
            DataFrame with columns Symbol, Date, Close, RS, sorted descending by RS.
        """
        nifty_w = resample_weekly(nifty, "Close").rename(
            columns={"Close": "NiftyClose"}
        )

        symbols = equities["Symbol"].unique()
        results: list[dict] = []
        skipped = 0

        for sym in symbols:
            sym_df = equities[equities["Symbol"] == sym].copy()
            sym_df = resample_weekly(sym_df, "Close")

            merged = sym_df.merge(nifty_w, on="Date", how="inner").sort_values("Date")

            if not validate_lookback(merged, self._lookback, sym):
                skipped += 1
                continue

            stock_ret = merged["Close"] / merged["Close"].shift(self._lookback)
            nifty_ret = merged["NiftyClose"] / merged["NiftyClose"].shift(self._lookback)
            merged["RS"] = (stock_ret / nifty_ret) - 1
            merged = merged.dropna(subset=["RS"])

            if merged.empty:
                skipped += 1
                continue

            latest = merged.iloc[-1]
            results.append({
                "Symbol": sym,
                "Date": latest["Date"].strftime("%Y-%m-%d"),
                "Close": round(float(latest["Close"]), 2),
                "RS": round(float(latest["RS"]), 4),
            })

        if skipped:
            logger.info("Skipped %d symbols with insufficient weekly data", skipped)

        df = pd.DataFrame(results)
        if df.empty:
            return df
        return df.sort_values("RS", ascending=False).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, output_path: Optional[str | Path] = None, **kwargs) -> None:
        """Load NSE data, compute RS, save ranked CSV.

        Args:
            output_path: Destination CSV. Defaults to ``rs_weekly.csv``.
        """
        if output_path is None:
            output_path = "rs_weekly.csv"
        output_path = Path(output_path)

        equities = store.load_equities(self._provider)
        if equities.empty:
            raise FileNotFoundError(
                "No NSE equities data found. Run 'nse-relative fetch --provider nse' first."
            )

        nifty = store.load_index(self._provider)
        if nifty.empty:
            raise FileNotFoundError(
                "No NSE index data found. Run 'nse-relative fetch --provider nse' first."
            )

        nifty = nifty[nifty["Symbol"] == NIFTY_BENCHMARK].copy()

        results = self._compute(equities, nifty)

        if results.empty:
            logger.warning("No RS results — no symbols had sufficient data")
            return

        results.index += 1
        results.index.name = "Rank"
        results.to_csv(output_path, index=True)

        logger.info(
            "Saved %d symbols to %s (top RS: %.4f, bottom: %.4f)",
            len(results), output_path,
            results["RS"].iloc[0], results["RS"].iloc[-1],
        )
