"""
Alpha extraction pipeline — 12-step signal processing.

Exposes:
    AlphaPipeline   — the full 12-step pipeline
    AlphaResult     — typed result container
    run_analysis    — convenience function for CLI usage
"""

from nse_relative.alphaextraction.signal_pipeline import AlphaPipeline, AlphaResult
from nse_relative.alphaextraction.reporting import format_alpha_table, send_alpha_report, save_alpha_csv
from nse_relative.alphaextraction.backtest import AlphaBacktest, run_alpha_backtest

__all__ = [
    "AlphaPipeline",
    "AlphaResult",
    "AlphaBacktest",
    "run_alpha_backtest",
    "format_alpha_table",
    "send_alpha_report",
    "save_alpha_csv",
]
