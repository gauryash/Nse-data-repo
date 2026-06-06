"""
Rolling monthly backtest — long-only, top 10 %, VectorBT-powered.

For each month-end rebalancing date:
  1. Take the trailing M periods of returns up to that date
  2. Run the 12-step AlphaPipeline to obtain alpha scores
  3. Keep only stocks with **positive alpha** (long-only)
  4. Select the **top k %** (default top 10 %) by alpha rank
  5. **Equal-weight** the selected stocks and record the portfolio
  6. Compute portfolio NAV via `vbt.Portfolio.from_holding()`

Outputs (all saved to ``analysis/``):
  - ``portfolio_weights.csv``         — daily weight matrix
  - ``rankings/{YYYY-MM}.csv``        — per-month ranking
  - ``backtest_summary.csv``          — one row per rebalance event
  - ``equity_curve.csv``              — portfolio NAV
  - ``performance_metrics.csv``       — Sharpe, drawdown, etc.
  - ``backtest_log.txt``              — human-readable log
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from nse_relative.alphaextraction.signal_pipeline import AlphaPipeline, AlphaResult
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "analysis"  # project_root/analysis/


# ===================================================================
# Backtest Engine
# ===================================================================

class AlphaBacktest:
    """Rolling monthly backtest (long-only, top-k, equal-weight).

    Parameters
    ----------
    lookback : int
        Trailing window *M* in daily periods (default 252 ≈ 1 trading year).
    estimation_periods : int
        Estimation window *d* (default 20).
    eta : float
        Weighting scale (default 1.0).
    top_pct : float
        Fraction of stocks to keep (default 0.10 = top 10 %).
    min_stocks : int
        Minimum number of stocks to keep per month (default 5).
    output_dir : str | Path
        Output folder (default ``project_root/analysis/``).
    """

    def __init__(
        self,
        lookback: int = 252,
        estimation_periods: int = 20,
        eta: float = 1.0,
        top_pct: float = 0.10,
        min_stocks: int = 5,
        output_dir: str | Path = OUTPUT_DIR,
    ):
        self.M = lookback
        self.d = estimation_periods
        self.eta = eta
        self.top_pct = top_pct
        self.min_stocks = min_stocks
        self.output_dir = Path(output_dir)

        self._pipeline = AlphaPipeline(
            lookback=self.M,
            estimation_periods=self.d,
            eta=self.eta,
            min_stocks=self.min_stocks,
        )
        self._results: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        returns: pd.DataFrame,
        benchmark_returns: pd.Series | None = None,
    ) -> dict:
        """Run the rolling monthly backtest.

        Parameters
        ----------
        returns : pd.DataFrame
            Shape ``(T, N)`` — daily returns, oldest first.
        benchmark_returns : pd.Series, optional
            Benchmark return series.

        Returns
        -------
        dict
            ``{'weights': pd.DataFrame, 'metrics': dict, 'equity': pd.Series}``
        """
        if returns.empty or returns.shape[1] < self.min_stocks:
            raise ValueError(
                f"Need at least {self.min_stocks} stocks, got {returns.shape[1]}"
            )

        logger.info(
            "AlphaBacktest - M=%d  d=%d  top_pct=%.0f%%  min_stocks=%d  "
            "stocks=%d  total_periods=%d",
            self.M, self.d, self.top_pct * 100, self.min_stocks,
            returns.shape[1], len(returns),
        )

        # ── Rebalancing calendar ──────────────────────────────────
        rebal_dates = self._month_end_dates(returns.index)
        rebal_dates = [
            d for d in rebal_dates
            if returns.index.get_loc(d) >= self.M - 1
        ]
        logger.info(
            "Rebalancing calendar: %d month-end dates (%s .. %s)",
            len(rebal_dates),
            rebal_dates[0].strftime("%Y-%m-%d") if rebal_dates else "-",
            rebal_dates[-1].strftime("%Y-%m-%d") if rebal_dates else "-",
        )

        # ── Prepare folders ───────────────────────────────────────
        self.output_dir.mkdir(parents=True, exist_ok=True)
        monthly_dir = self.output_dir / "rankings"
        monthly_dir.mkdir(exist_ok=True)

        # ── Weight matrix (initialised with NaN) ─────────────────
        #   At each rebal date we write weights for SELECTED stocks.
        #   By first setting ALL stocks to 0.0 on that date and then
        #   overwriting selected stocks with their target weight, the
        #   forward-fill correctly resets deselected stocks to zero.
        weights = pd.DataFrame(np.nan, index=returns.index, columns=returns.columns)
        self._results = []

        for rebal_date in rebal_dates:
            # Trailing window
            idx = returns.index.get_loc(rebal_date)
            start_idx = max(0, idx - self.M + 1)
            window_returns = returns.iloc[start_idx: idx + 1]

            # ── Run pipeline ──────────────────────────────────────
            try:
                result = self._pipeline.run(
                    window_returns, benchmark_returns=benchmark_returns,
                )
            except (ValueError, RuntimeError) as exc:
                logger.warning("Skipping %s: %s", rebal_date.strftime("%Y-%m-%d"), exc)
                continue

            # ── Long-only filter ──────────────────────────────────
            ranking = result.ranking[result.ranking["alpha"] > 0].copy()
            if ranking.empty:
                logger.info("  %s: no positive-alpha stocks", rebal_date.strftime("%Y-%m-%d"))
                continue

            # ── Top-k with alpha-proportional weights ─────────────
            n_keep = max(self.min_stocks, int(len(ranking) * self.top_pct))
            n_keep = min(n_keep, len(ranking))
            top = ranking.head(n_keep)

            # Weight proportionally by alpha (not equal-weight)
            total_alpha = top["alpha"].sum()
            if total_alpha > 0:
                alpha_w = (top["alpha"] / total_alpha).values
            else:
                alpha_w = np.full(n_keep, 1.0 / n_keep)

            # CRITICAL FIX: clear ALL weights at this date first,
            # then set only selected stocks. This drops any stock
            # not re-selected (fixes weight accumulation bug).
            weights.loc[rebal_date] = 0.0
            weights.loc[rebal_date, top.index] = alpha_w

            # ── Save monthly ranking ──────────────────────────────
            rank_path = monthly_dir / f"rankings_{rebal_date.strftime('%Y-%m')}.csv"
            top.to_csv(rank_path, float_format="%.6f")

            # ── Store ─────────────────────────────────────────────
            self._results.append({
                "date": rebal_date,
                "n_stocks": n_keep,
                "n_positive": len(ranking),
                "combined_signal": result.combined_signal,
                "top_stocks": list(top.index),
            })
            logger.info(
                "  %s  selected=%d/%d  CS=%+.6f",
                rebal_date.strftime("%Y-%m-%d"), n_keep, len(ranking),
                result.combined_signal,
            )

        # ── Forward-fill weights to get daily positions ──────────
        #   Before first rebal date: all NaN → fillna(0) = flat zero
        #   On rebal dates: selected=alpha_w, deselected=0.0
        #   Between rebal dates: ffill carries the last portfolio forward
        daily_w = weights.ffill().fillna(0.0)

        # ── Compute portfolio daily returns ──────────────────────
        #   R_portfolio(t) = sum(w(t-1) * R_i(t))
        #   shift(1) avoids look-ahead (weights set at t are used at t+1)
        port_rets = (daily_w.shift(1) * returns).sum(axis=1)

        # ── Handle NaN returns (trading halts, missing data) ──────
        #   If a held stock has NaN return, treat it as 0% that day
        port_rets = port_rets.fillna(0.0)

        # ── Protect against unadjusted corporate actions ──────────
        #   Daily portfolio loss capped at -30%; gain at +30%
        #   (genuine moves beyond this are extremely rare for a
        #    diversified portfolio; larger moves are data errors)
        port_rets = port_rets.clip(lower=-0.30, upper=0.30)

        # ── Build equity curve ────────────────────────────────────
        equity = (1 + port_rets).cumprod()

        # ── VectorBT performance analysis ─────────────────────────
        metrics = self._vectorbt_analysis(equity, returns, daily_w)

        # ── Save all outputs ──────────────────────────────────────
        weights.to_csv(self.output_dir / "portfolio_weights.csv", float_format="%.6f")
        equity.to_csv(self.output_dir / "equity_curve.csv", float_format="%.6f")
        pd.DataFrame([metrics]).to_csv(
            self.output_dir / "performance_metrics.csv", index=False, float_format="%.6f"
        )
        self._save_summary()
        self._save_log()

        logger.info(
            "Backtest complete - Sharpe=%.2f  Return=%.1f%%  DD=%.1f%%",
            metrics.get("sharpe_ratio", 0),
            metrics.get("total_return", 0) * 100,
            metrics.get("max_drawdown", 0) * 100,
        )

        return {
            "weights": weights,
            "metrics": metrics,
            "equity": equity,
        }

    # ------------------------------------------------------------------
    # VectorBT analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _vectorbt_analysis(
        equity: pd.Series,
        returns: pd.DataFrame,
        daily_w: pd.DataFrame,
    ) -> dict:
        """Compute portfolio metrics using vectorbt."""
        try:
            import vectorbt as vbt
        except ImportError:
            logger.warning("vectorbt not installed; computing basic metrics manually")
            return _basic_metrics(equity, returns, daily_w)

        # Build a single-column DataFrame for from_holding
        price_df = equity.to_frame("portfolio")
        pf = vbt.Portfolio.from_holding(
            price_df,
            init_cash=1.0,
            freq="D",
        )

        # Core vectorbt metrics (avoid pf.trades — too slow)
        total_ret = pf.total_return()
        total_ret = float(total_ret.iloc[0]) if hasattr(total_ret, 'iloc') else float(total_ret)
        sharpe = pf.sharpe_ratio()
        sharpe = float(sharpe.iloc[0]) if hasattr(sharpe, 'iloc') else float(sharpe)
        max_dd = pf.max_drawdown()
        max_dd = float(max_dd.iloc[0]) if hasattr(max_dd, 'iloc') else float(max_dd)
        ann_vol = pf.annualized_volatility()
        ann_vol = float(ann_vol.iloc[0]) if hasattr(ann_vol, 'iloc') else float(ann_vol)
        ann_ret = pf.annualized_return()
        ann_ret = float(ann_ret.iloc[0]) if hasattr(ann_ret, 'iloc') else float(ann_ret)
        calmar = pf.calmar_ratio()
        calmar = float(calmar.iloc[0]) if hasattr(calmar, 'iloc') else float(calmar)
        sortino = pf.sortino_ratio()
        sortino = float(sortino.iloc[0]) if hasattr(sortino, 'iloc') else float(sortino)
        profit = pf.total_profit()
        profit = float(profit.iloc[0]) if hasattr(profit, 'iloc') else float(profit)

        turnover = float(daily_w.diff().abs().sum(axis=1).mean())

        metrics = {
            "total_return": total_ret,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "annualized_volatility": ann_vol,
            "annualized_return": ann_ret,
            "calmar_ratio": calmar,
            "sortino_ratio": sortino,
            "total_profit": profit,
            "avg_daily_turnover": turnover,
        }

        return metrics

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _month_end_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
        months = index.to_period("M").unique()
        return sorted({index[index.to_period("M") == m][-1] for m in months})

    def _save_summary(self) -> None:
        if not self._results:
            return
        rows = []
        for r in self._results:
            rows.append({
                "date": r["date"].strftime("%Y-%m-%d"),
                "n_positive": r["n_positive"],
                "n_selected": r["n_stocks"],
                "combined_signal": round(r["combined_signal"], 6),
                "top_stocks": ", ".join(r["top_stocks"][:5]),
            })
        pd.DataFrame(rows).to_csv(
            self.output_dir / "backtest_summary.csv", index=False
        )

    def _save_log(self) -> None:
        lines = [
            "=" * 64,
            f"  ALPHA BACKTEST LOG  |  {datetime.now():%Y-%m-%d %H:%M}",
            "=" * 64,
            f"  Parameters:  M={self.M}  d={self.d}  eta={self.eta}",
            f"  Top percentile: {self.top_pct:.0%}  Min stocks: {self.min_stocks}",
            f"  Total rebalancing events: {len(self._results)}",
            "",
            "  Monthly selections:",
            "  " + "-" * 60,
        ]
        for r in self._results:
            top = r["top_stocks"][:5]
            s = ", ".join(top)
            if len(r["top_stocks"]) > 5:
                s += f" (+{len(r['top_stocks'])-5} more)"
            lines.append(
                f"  {r['date'].strftime('%Y-%m-%d'):>12s}  "
                f"n={r['n_stocks']:>2d}  CS={r['combined_signal']:+.6f}  [{s}]"
            )
        lines.append("=" * 64)
        (self.output_dir / "backtest_log.txt").write_text(
            "\n".join(lines), encoding="utf-8"
        )


# ===================================================================
# Fallback metrics (when vectorbt is not installed)
# ===================================================================

def _basic_metrics(equity: pd.Series, returns: pd.DataFrame, daily_w: pd.DataFrame) -> dict:
    """Compute basic performance metrics without vectorbt."""
    port_rets = equity.pct_change().dropna()
    total_ret = float(equity.iloc[-1] / equity.iloc[0] - 1) if len(equity) > 1 else 0.0
    ann_ret = float((1 + total_ret) ** (252 / len(port_rets)) - 1) if len(port_rets) > 0 else 0.0
    ann_vol = float(port_rets.std() * np.sqrt(252)) if len(port_rets) > 0 else 0.0
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0

    # Max drawdown
    cummax = equity.cummax()
    dd = (equity - cummax) / cummax
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0

    turnover = float(daily_w.diff().abs().sum(axis=1).mean())

    return {
        "total_return": total_ret,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "annualized_return": ann_ret,
        "annualized_volatility": ann_vol,
        "calmar_ratio": ann_ret / abs(max_dd) if max_dd != 0 else 0.0,
        "avg_daily_turnover": turnover,
    }


# ===================================================================
# Convenience
# ===================================================================

def run_alpha_backtest(
    returns: pd.DataFrame,
    benchmark_returns: pd.Series | None = None,
    lookback: int = 252,
    estimation_periods: int = 20,
    eta: float = 1.0,
    top_pct: float = 0.10,
    min_stocks: int = 5,
    output_dir: str | Path = OUTPUT_DIR,
) -> dict:
    bt = AlphaBacktest(
        lookback=lookback,
        estimation_periods=estimation_periods,
        eta=eta,
        top_pct=top_pct,
        min_stocks=min_stocks,
        output_dir=output_dir,
    )
    return bt.run(returns, benchmark_returns)
