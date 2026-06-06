"""
Reporting utilities for the alpha pipeline.

Formats results as tables, saves to CSV, and sends Telegram alerts.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from nse_relative.alphaextraction.signal_pipeline import AlphaResult


def format_alpha_table(
    result: AlphaResult,
    top_n: int = 10,
    bottom_n: int = 5,
    include_weights: bool = True,
) -> str:
    """Build a human-readable summary of alpha results.

    Returns
    -------
    str
        Multi-line string suitable for console or Telegram.
    """
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"  ALPHA PIPELINE REPORT  |  "
                 f"{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"  Universe: {result.n_stocks} stocks  |  "
                 f"{result.n_periods} daily periods  |  "
                 f"Lookback M={result.lookback}  Est d={result.estimation_periods}")
    lines.append(f"  Combined Signal: {result.combined_signal:+.6f}")
    lines.append("=" * 60)

    # ── Statistics ──────────────────────────────────────────────
    n_long = (result.weights > 0).sum()
    n_short = (result.weights < 0).sum()
    n_neut = (result.weights == 0).sum()
    long_w = result.weights[result.weights > 0].sum()
    short_w = result.weights[result.weights < 0].sum()
    lines.append(f"\n  Long:  {n_long} stocks  (total weight {long_w:.2%})")
    lines.append(f"  Short: {n_short} stocks  (total weight {short_w:.2%})")
    lines.append(f"  Neutral: {n_neut} stocks")
    lines.append(
        f"  Avg |alpha|: {result.alpha.abs().mean():.4f}  "
        f"Max alpha: {result.alpha.max():.4f}  "
        f"Min alpha: {result.alpha.min():.4f}"
    )

    # ── Top stocks (highest alpha) ──────────────────────────────
    lines.append(f"\n  ── TOP {top_n} (HIGHEST ALPHA) ──")
    lines.append(f"  {'Rank':>5}  {'Symbol':>12}  "
                 f"{'Weight':>9}  {'Alpha':>9}  "
                 f"{'E[R]':>9}  {'Vol':>7}")
    lines.append(f"  {'-'*5}  {'-'*12}  {'-'*9}  {'-'*9}  "
                 f"{'-'*9}  {'-'*7}")
    for _, row in result.top(top_n).iterrows():
        lines.append(
            f"  {int(row['rank']):>5d}  {row.name:>12s}  "
            f"{row['weight']:>+9.4f}  {row['alpha']:>+9.4f}  "
            f"{row['expected_return']:>+9.6f}  "
            f"{row['volatility']:>7.4f}"
        )

    # ── Bottom stocks (lowest alpha) ────────────────────────────
    lines.append(f"\n  ── BOTTOM {bottom_n} (LOWEST ALPHA) ──")
    lines.append(f"  {'Rank':>5}  {'Symbol':>12}  "
                 f"{'Weight':>9}  {'Alpha':>9}")
    lines.append(f"  {'-'*5}  {'-'*12}  {'-'*9}  {'-'*9}")
    for _, row in result.bottom(bottom_n).iterrows():
        lines.append(
            f"  {int(row['rank']):>5d}  {row.name:>12s}  "
            f"{row['weight']:>+9.4f}  {row['alpha']:>+9.4f}"
        )

    # ── Combined signal components ──────────────────────────────
    lines.append(f"\n  ── COMBINED SIGNAL COMPOSITION ──")
    lines.append(f"  Combined Signal = {result.combined_signal:+.6f}")
    if include_weights:
        top_contrib = (result.weights * result.expected_return).sort_values(
            ascending=False
        ).head(5)
        lines.append(f"  Top 5 contributors:")
        for sym, val in top_contrib.items():
            lines.append(f"    {sym:>12s}  {val:+.6f}")
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def save_alpha_csv(result: AlphaResult, path: str | Path = "alpha_ranking.csv") -> Path:
    """Save the ranking DataFrame to CSV."""
    path = Path(path)
    df = result.ranking.copy()
    df.to_csv(path, index=True, float_format="%.6f")
    return path


def send_alpha_report(
    result: AlphaResult,
    notifier,
    top_n: int = 10,
) -> None:
    """Send alpha results via Telegram (or any notifier with ``send_message``)."""
    text = format_alpha_table(result, top_n=top_n)
    notifier.send_message(text)
