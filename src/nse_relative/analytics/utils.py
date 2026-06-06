"""
Shared helper utilities used by multiple analytics modules.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional


def resample_weekly(df: pd.DataFrame, close_col: str = "Close") -> pd.DataFrame:
    """Resample daily data to weekly bars anchored on Friday.

    Args:
        df: DataFrame with ``Date`` and *close_col* columns.
        close_col: Name of the price column to aggregate.

    Returns:
        Weekly DataFrame with one row per Friday.
    """
    return (
        df.set_index("Date")
        .resample("W-FRI")
        .agg({close_col: "last"})
        .dropna()
        .reset_index()
    )


def make_date_chunks(
    start_str: str,
    end_str: str,
    chunk_days: int = 110,
) -> list[tuple[str, str]]:
    """Split a date range into *chunk_days*-sized chunks.

    The NSE API returns at most 70 records per call (~100 trading days).
    Using 110-calendar-day chunks ensures each call gets all available
    records for that window without hitting the API cap and leaving gaps.

    Args:
        start_str: Start date in ``DD-MM-YYYY``.
        end_str: End date in ``DD-MM-YYYY``.
        chunk_days: Size of each chunk in calendar days (default 110).

    Returns:
        List of ``(from_date, to_date)`` string tuples.
    """
    start = datetime.strptime(start_str, "%d-%m-%Y")
    end = datetime.strptime(end_str, "%d-%m-%Y")
    chunks: list[tuple[str, str]] = []
    cur = start
    while cur < end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        chunks.append((cur.strftime("%d-%m-%Y"), chunk_end.strftime("%d-%m-%Y")))
        cur = chunk_end + timedelta(days=1)
    return chunks


def clean_corporate_actions(
    returns: pd.DataFrame,
    max_daily_change: float = 0.30,
) -> pd.DataFrame:
    """Neutralise returns caused by unadjusted corporate actions.

    Stock splits, bonus issues, and rights issues cause raw NSE prices
    to drop by 50-90% overnight.  These are data artifacts, not real
    trading losses.  This function replaces any daily return exceeding
    ``max_daily_change`` (default 30%) with the median return of the
    other stocks on that day (preserving the market move while removing
    the split artifact).

    Args:
        returns: DataFrame (T x N) of daily returns.
        max_daily_change: Threshold beyond which a return is flagged.

    Returns:
        Cleaned DataFrame with extreme returns replaced by cross-
        sectional median on that day.
    """
    df = returns.copy()
    mask = df.abs() > max_daily_change
    if mask.any().any():
        daily_median = df.median(axis=1)  # market move that day
        n_replaced = mask.sum().sum()
        # Replace each flagged cell with that day's cross-sectional median
        for col in df.columns:
            col_mask = mask[col]
            if col_mask.any():
                df.loc[col_mask, col] = daily_median[col_mask]
        from nse_relative.config.logger import get_logger
        get_logger(__name__).info(
            "Cleaned %d extreme returns (|r| > %.0f%%) — likely corp actions",
            n_replaced, max_daily_change * 100,
        )
    return df


def validate_lookback(df: pd.DataFrame, lookback: int, label: str = "data") -> bool:
    """Check that a DataFrame has at least *lookback* + 1 rows.

    Returns ``True`` if sufficient, logs warning and returns ``False`` otherwise.
    """
    from nse_relative.config.logger import get_logger

    logger = get_logger(__name__)
    if len(df) < lookback + 1:
        logger.warning("%s: %d rows < %d needed", label, len(df), lookback + 1)
        return False
    return True
