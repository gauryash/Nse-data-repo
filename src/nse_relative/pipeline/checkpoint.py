"""
Checkpoint / metadata tracking for incremental data fetching.

Each provider stores a ``_checkpoint.json`` in its storage directory that
tracks, per symbol, the date range already fetched.  Before fetching, the
provider consults this checkpoint to avoid re-downloading data that already
exists locally.

Checkpoint JSON structure::

    {
      "last_updated": "2026-05-23T18:00:00",
      "fetch_params": {
        "interval": "day",
        "index": "nifty500"
      },
      "symbols": {
        "RELIANCE": {
          "date_min": "2026-01-01",
          "date_max": "2026-05-10",
          "rows": 87
        }
      }
    }
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from nse_relative.pipeline import storage as store
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

_DATE_FMT = "%Y-%m-%d"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def checkpoint_path(provider: str) -> Path:
    """Path to the checkpoint JSON file for a provider."""
    return store._base_dir(provider) / "_checkpoint.json"


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def read_checkpoint(provider: str) -> dict[str, Any]:
    """Load the checkpoint dict for *provider* (empty dict if missing)."""
    path = checkpoint_path(provider)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Corrupt checkpoint for %s: %s — starting fresh", provider, e)
        return {}


def write_checkpoint(provider: str, data: dict[str, Any]) -> None:
    """Persist the checkpoint dict for *provider*."""
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    path = checkpoint_path(provider)
    path.write_text(
        json.dumps(data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Per-symbol helpers
# ---------------------------------------------------------------------------

def get_symbol_coverage(
    provider: str,
    symbol: str,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Return ``(date_min, date_max)`` for a symbol, or ``(None, None)``.

    Dates are timezone-naive ``datetime`` objects.
    """
    cp = read_checkpoint(provider)
    entry = cp.get("symbols", {}).get(symbol)
    if entry is None:
        return None, None
    dmin = datetime.strptime(entry["date_min"], _DATE_FMT) if entry.get("date_min") else None
    dmax = datetime.strptime(entry["date_max"], _DATE_FMT) if entry.get("date_max") else None
    return dmin, dmax


def update_symbol_coverage(
    provider: str,
    symbol: str,
    date_min: str | datetime,
    date_max: str | datetime,
    rows: int = 0,
) -> None:
    """Record that a symbol's data now covers ``[date_min, date_max]``."""
    def _fmt(d):
        return d if isinstance(d, str) else d.strftime(_DATE_FMT)

    cp = read_checkpoint(provider)
    symbols = cp.setdefault("symbols", {})
    existing = symbols.get(symbol, {})

    # Merge date ranges (expand if the new range is wider)
    old_min = existing.get("date_min")
    old_max = existing.get("date_max")
    new_min = _fmt(date_min)
    new_max = _fmt(date_max)
    if old_min and old_min < new_min:
        new_min = old_min
    if old_max and old_max > new_max:
        new_max = old_max

    symbols[symbol] = {
        "date_min": new_min,
        "date_max": new_max,
        "rows": max(rows, existing.get("rows", 0)),
    }
    write_checkpoint(provider, cp)


def coverage_needed(
    provider: str,
    symbol: str,
    start_date: datetime,
    end_date: datetime,
) -> bool:
    """Return ``True`` if the symbol needs fetching for ``[start_date, end_date]``.

    Returns ``False`` if the checkpoint shows the range is already fully covered.
    """
    dmin, dmax = get_symbol_coverage(provider, symbol)
    if dmin is None or dmax is None:
        return True  # no data yet
    return not (dmin <= start_date and dmax >= end_date)
