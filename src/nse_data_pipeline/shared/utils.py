"""
Shared helper utilities.

Moved from the old ``analytics/utils.py`` — only the functions needed by
the pipeline are kept here.
"""

from __future__ import annotations

from datetime import datetime, timedelta


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
