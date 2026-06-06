"""
12-step signal-processing pipeline for alpha extraction.

Reference formulas (from the quant memo):
─────────────────────────────────────────
Phase 1 — Preprocessing (Steps 1–4)
  1. X(i,s) = R(i,s) - mean(R(i,:))          … linear demeaning
  2. σ²(i)  = mean(X(i,:)²)                  … variance estimation
  3. Y(i,s) = X(i,s) / σ(i)                  … z-score normalisation
  4. truncate to M–1 periods                 … time-series truncation

Phase 2 — Cross-sectional adjustment (Steps 5–6)
  5. Λ(i,s) = Y(i,s) - mean(Y(:,s))          … cross-sectional demeaning
  6. final trim to match estimation window   … trimming

Phase 3 — Alpha extraction & weighting (Steps 7–12)
  7. E(i)   = mean(R(i, last d periods))       … expected return
  8. Eₙ(i)  = E(i) / σ(i)                     … vol normalisation
  9. ε(i)   = orthogonalise Eₙ(i) on Λ(i,·)   … pure alpha (residual)
  10. w(i)  = η · ε(i) / σ(i)                 … inverse-vol weighting
  11. Σ|w|  = 1                               … budget constraint
  12. CS    = Σ w(i) · S(i)                   … combined signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from nse_relative.config.logger import get_logger

logger = get_logger(__name__)


# ===================================================================
# Result container
# ===================================================================

@dataclass
class AlphaResult:
    """Output of the full 12-step alpha pipeline."""

    # Final outputs
    weights: pd.Series               # w(i)    — normalised portfolio weights
    alpha: pd.Series                 # ε(i)    — pure alpha residuals
    combined_signal: float           # Σ w·S   — scalar portfolio signal

    # Per-stock diagnostics
    volatility: pd.Series            # σ(i)
    expected_return: pd.Series       # E(i)
    risk_adjusted_return: pd.Series  # Eₙ(i)

    # Cross-sectional diagnostics
    normalised_signal: pd.Series     # Λ(i, M)  — most recent Λ
    market_bias: pd.Series           # mean(Y(:,s))  — common factor at each time

    # Pipeline intermediate (for inspection)
    intermediate: dict = field(default_factory=dict)

    # Ranking
    ranking: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Metadata
    n_stocks: int = 0
    n_periods: int = 0
    lookback: int = 252
    estimation_periods: int = 20
    eta: float = 1.0

    def top(self, n: int = 10) -> pd.DataFrame:
        """Return the top *n* ranked stocks by alpha."""
        return self.ranking.head(n)

    def bottom(self, n: int = 10) -> pd.DataFrame:
        """Return the bottom *n* ranked stocks by alpha."""
        return self.ranking.tail(n)


# ===================================================================
# 12‑step pipeline
# ===================================================================

class AlphaPipeline:
    """Implements the 12‑step alpha extraction pipeline.

    Parameters
    ----------
    lookback : int
        Number of historical periods *M* to use (default 252 ≈ 1 trading year).
    estimation_periods : int
        Recent *d* periods used for expected return (default 20 ≈ 1 trading month).
    eta : float
        Scaling constant for raw weights (default 1.0).
    min_stocks : int
        Minimum number of stocks required to run (default 5).
    """

    def __init__(
        self,
        lookback: int = 252,
        estimation_periods: int = 20,
        eta: float = 1.0,
        min_stocks: int = 5,
    ):
        self.M = lookback
        self.d = estimation_periods
        self.eta = eta
        self.min_stocks = min_stocks
        self._result: AlphaResult | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        returns: pd.DataFrame,
        benchmark_returns: pd.Series | None = None,
    ) -> AlphaResult:
        """Execute the full pipeline on a returns matrix.

        Parameters
        ----------
        returns : pd.DataFrame
            Shape ``(T, N)`` — rows = time periods (oldest first),
            columns = stock symbols. The last *M* rows are used.
        benchmark_returns : pd.Series, optional
            Benchmark returns (e.g. Nifty 50). Not directly used in the
            formulas but stored in ``intermediate`` for reference.

        Returns
        -------
        AlphaResult
        """
        # Validate
        if returns.empty or returns.shape[1] < self.min_stocks:
            raise ValueError(
                f"Need at least {self.min_stocks} stocks, got {returns.shape[1]}"
            )
        if self.M < self.d:
            raise ValueError(
                f"Lookback M={self.M} must be >= estimation periods d={self.d}"
            )
        if len(returns) < self.M:
            raise ValueError(
                f"Need at least {self.M} periods, got {len(returns)}"
            )

        # Trim to lookback window (last M periods)
        returns = returns.iloc[-self.M:].copy()
        n_stocks = returns.shape[1]
        n_periods = len(returns)

        logger.info(
            "AlphaPipeline - M=%d  d=%d  eta=%.2f  stocks=%d  periods=%d",
            self.M, self.d, self.eta, n_stocks, n_periods,
        )

        # ── Phase 1: Preprocessing ──────────────────────────────────

        # Step 1 — Linear Demeaning
        #   X(i,s) = R(i,s) - mean_s(R(i,s))
        demeaned = returns.sub(returns.mean(), axis=1)
        logger.debug("Step 1 done - X shape %s", demeaned.shape)

        # Step 2 — Variance Estimation
        #   σ²(i) = mean_s(X(i,s)²)
        variance = (demeaned ** 2).mean()
        std = variance.pow(0.5)
        # Guard against zero vol
        std = std.replace(0, np.nan)
        logger.debug("Step 2 done - sigma range [%.4f, %.4f]",
                      std.min(), std.max())

        # Step 3 — Z-score Normalisation
        #   Y(i,s) = X(i,s) / σ(i)
        Y = demeaned.div(std, axis=1)
        logger.debug("Step 3 done - Y shape %s", Y.shape)

        # Step 4 — Time-series Truncation → use M-1 periods
        Y_trunc = Y.iloc[:-1].copy()
        logger.debug("Step 4 done - Y_trunc shape %s", Y_trunc.shape)

        # ── Phase 2: Cross-sectional Adjustment ─────────────────────

        # Step 5 — Cross-sectional Demeaning
        #   Λ(i,s) = Y(i,s) - mean_i(Y(i,s))
        market_bias = Y_trunc.mean(axis=1)   # mean across stocks at each time
        Lambda = Y_trunc.sub(market_bias, axis=0)
        logger.debug("Step 5 done - Lambda shape %s", Lambda.shape)

        # Step 6 — Final Trimming
        #   Align Λ to the estimation window (last d periods)
        Lambda_trim = Lambda.iloc[-self.d:].copy()
        logger.debug("Step 6 done - Lambda_trim shape %s", Lambda_trim.shape)

        # ── Phase 3: Alpha Extraction & Weighting ───────────────────

        # Step 7 — Expected Return Estimation
        #   E(i) = mean(R(i, M-d+1 … M))
        E = returns.iloc[-self.d:].mean()
        logger.debug("Step 7 done - E range [%.6f, %.6f]",
                      E.min(), E.max())

        # Step 8 — Volatility Normalisation
        #   Eₙ(i) = E(i) / σ(i)
        E_norm = E / std
        logger.debug("Step 8 done - E_norm range [%.4f, %.4f]",
                      E_norm.min(), E_norm.max())

        # Step 9 — Orthogonalisation (Residual Extraction)
        #   Regress E_norm(i) ~ mean(Lambda(i,:)) across stocks -> residuals = pure alpha
        #   Lambda_recent(i) = mean_s(Lambda(i, s)) over the last d periods
        Lambda_recent = Lambda_trim.mean()
        #   Drop NaN stocks before regression
        valid_mask = ~(Lambda_recent.isna() | E_norm.isna() | std.isna())
        L_valid = Lambda_recent[valid_mask]
        E_valid = E_norm[valid_mask]

        #   Cross-sectional OLS: E_norm = b0 + b1 * Lambda_recent + epsilon
        if len(L_valid) > 2:
            # Use np.linalg.lstsq for single-regressor OLS
            X_ = np.column_stack([np.ones(len(L_valid)), L_valid.values])
            coef, *_ = np.linalg.lstsq(X_, E_valid.values, rcond=None)
            beta_0, beta_1 = coef
            E_pred = beta_0 + beta_1 * L_valid.values
            epsilon_series = pd.Series(
                E_valid.values - E_pred,
                index=L_valid.index,
                name="alpha",
            )
            r2 = 1 - (epsilon_series ** 2).sum() / ((E_valid - E_valid.mean()) ** 2).sum()
            logger.debug(
                "Step 9 done - b0=%.4f  b1=%.4f  R2=%.4f",
                beta_0, beta_1, r2,
            )
        else:
            epsilon_series = pd.Series(dtype=float)
            logger.warning("Step 9 - Too few valid stocks (%d), skipping regression", len(L_valid))

        #   Reindex to full universe (NaN for dropped stocks)
        epsilon = pd.Series(np.nan, index=returns.columns)
        epsilon.loc[epsilon_series.index] = epsilon_series
        logger.debug("Step 9 done - epsilon has %d non-NaN values", epsilon.notna().sum())

        # Step 10 — Signal Weighting
        #   w_raw(i) = eta * epsilon(i) / sigma(i)
        w_raw = self.eta * epsilon / std
        logger.debug("Step 10 done - w_raw range [%.4f, %.4f]",
                      w_raw.min(), w_raw.max())

        # Step 11 — Budget Constraint
        #   sum(|w(i)|) = 1
        abs_sum = w_raw.abs().sum()
        if abs_sum > 0 and not np.isnan(abs_sum):
            w = w_raw / abs_sum
        else:
            w = w_raw * 0.0
        logger.debug("Step 11 done - sum|w| = %.4f", w.abs().sum())

        # Step 12 — Combined Signal
        #   CS = sum(w(i) * S(i))
        #   S(i) = average return over estimation period (step 7)
        S = E  # signal = expected return
        combined_signal = float((w * S).sum())
        logger.debug(
            "Step 12 done - CS = %.6f  (long=%.4f  short=%.4f)",
            combined_signal,
            w[w > 0].sum(),
            w[w < 0].sum(),
        )

        # ── Build ranking ────────────────────────────────────────────
        ranking = pd.DataFrame({
            "weight": w,
            "alpha": epsilon,
            "expected_return": E,
            "risk_adj_return": E_norm,
            "volatility": std,
            "normalised_signal": Lambda.iloc[-1] if len(Lambda) > 0 else pd.Series(dtype=float),
            "recent_signal_avg": Lambda_recent,
        })
        ranking = ranking.sort_values("alpha", ascending=False)
        ranking["rank"] = range(1, len(ranking) + 1)
        ranking = ranking[["rank"] + [c for c in ranking.columns if c != "rank"]]

        # ── Assemble result ──────────────────────────────────────────
        self._result = AlphaResult(
            weights=w,
            alpha=epsilon,
            combined_signal=combined_signal,
            volatility=std,
            expected_return=E,
            risk_adjusted_return=E_norm,
            normalised_signal=Lambda.iloc[-1] if len(Lambda) > 0 else pd.Series(dtype=float),
            market_bias=market_bias,
            intermediate={
                "returns": returns,
                "demeaned": demeaned,
                "Y": Y,
                "Y_trunc": Y_trunc,
                "Lambda": Lambda,
                "Lambda_trim": Lambda_trim,
                "variance": variance,
                "std": std,
                "E": E,
                "E_norm": E_norm,
                "Lambda_recent": Lambda_recent,
                "epsilon_raw": epsilon_series,
                "w_raw": w_raw,
                "benchmark_returns": benchmark_returns,
                "beta_0": beta_0 if len(L_valid) > 2 else None,
                "beta_1": beta_1 if len(L_valid) > 2 else None,
            },
            ranking=ranking,
            n_stocks=n_stocks,
            n_periods=n_periods,
            lookback=self.M,
            estimation_periods=self.d,
            eta=self.eta,
        )

        return self._result

    # ------------------------------------------------------------------
    # Step-by-step accessors (useful for debugging / teaching)
    # ------------------------------------------------------------------

    @property
    def result(self) -> AlphaResult | None:
        return self._result

    # Convenience methods for each step (documentation helpers)

    @staticmethod
    def step1_demean(returns: pd.DataFrame) -> pd.DataFrame:
        """X(i,s) = R(i,s) - mean(R(i,:)) — removes drift per stock."""
        return returns.sub(returns.mean(), axis=1)

    @staticmethod
    def step2_variance(X: pd.DataFrame) -> pd.Series:
        """σ²(i) = mean(X(i,:)²) — historical variance."""
        return (X ** 2).mean()

    @staticmethod
    def step3_normalise(X: pd.DataFrame, std: pd.Series) -> pd.DataFrame:
        """Y(i,s) = X(i,s) / σ(i) — z-score normalisation."""
        return X.div(std.replace(0, np.nan), axis=1)

    @staticmethod
    def step4_truncate(Y: pd.DataFrame) -> pd.DataFrame:
        """Drop the most recent period → M-1 length."""
        return Y.iloc[:-1].copy()

    @staticmethod
    def step5_cross_demean(Y_trunc: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        """Λ(i,s) = Y(i,s) - mean(Y(:,s)) — removes market-wide bias."""
        market = Y_trunc.mean(axis=1)
        return Y_trunc.sub(market, axis=0), market

    @staticmethod
    def step6_trim(Lambda: pd.DataFrame, d: int) -> pd.DataFrame:
        """Keep only the last *d* periods."""
        return Lambda.iloc[-d:].copy()

    @staticmethod
    def step7_expected_return(returns: pd.DataFrame, d: int) -> pd.Series:
        """E(i) = mean(R(i, last d periods))."""
        return returns.iloc[-d:].mean()

    @staticmethod
    def step8_vol_norm(E: pd.Series, std: pd.Series) -> pd.Series:
        """Eₙ(i) = E(i) / σ(i) — Sharpe-like ratio."""
        return E / std.replace(0, np.nan)

    @staticmethod
    def step9_orthogonalise(
        E_norm: pd.Series,
        Lambda_recent: pd.Series,
    ) -> pd.Series:
        """Cross-sectional regression → residual = pure alpha."""
        valid = ~(E_norm.isna() | Lambda_recent.isna())
        x = Lambda_recent[valid].values
        y = E_norm[valid].values
        if len(x) < 3:
            return pd.Series(np.nan, index=E_norm.index)
        X_mat = np.column_stack([np.ones(len(x)), x])
        coef, *_ = np.linalg.lstsq(X_mat, y, rcond=None)
        eps = pd.Series(y - (coef[0] + coef[1] * x), index=Lambda_recent[valid].index)
        result = pd.Series(np.nan, index=E_norm.index)
        result.loc[eps.index] = eps
        return result

    @staticmethod
    def step10_weight(epsilon: pd.Series, std: pd.Series, eta: float = 1.0) -> pd.Series:
        """w(i) = η · ε(i) / σ(i)."""
        return eta * epsilon / std.replace(0, np.nan)

    @staticmethod
    def step11_budget(w_raw: pd.Series) -> pd.Series:
        """Normalise so Σ |w(i)| = 1."""
        abs_sum = w_raw.abs().sum()
        if abs_sum > 0 and not np.isnan(abs_sum):
            return w_raw / abs_sum
        return w_raw * 0.0

    @staticmethod
    def step12_combine(w: pd.Series, S: pd.Series) -> float:
        """CS = Σ w(i) · S(i)."""
        return float((w * S).sum())
