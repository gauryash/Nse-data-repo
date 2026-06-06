"""
JSON-based checkpoint for incremental data fetching.

Each provider stores a ``_checkpoint.json`` in its storage directory that
tracks, per symbol, the date range already fetched.  Before fetching, the
provider consults this checkpoint to avoid re-downloading data that already
exists locally.

Checkpoint JSON structure::

    {
      "last_updated": "2026-06-06T12:00:00",
      "fetch_params": {
        "interval": "day",
        "index": "nifty500"
      },
      "symbols": {
        "RELIANCE": {
          "date_min": "2026-01-01",
          "date_max": "2026-06-01",
          "rows": 102,
          "meta": {"isin": "INE002A01018"}
        }
      }
    }
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

_DATE_FMT = "%Y-%m-%d"


class JsonCheckpoint:
    """Per-provider checkpoint for incremental fetch tracking.

    Args:
        checkpoint_path: Path to the JSON checkpoint file.
        fetch_params: Optional dict of fetch parameters to store with
            the checkpoint (e.g. ``{"interval": "day", "index": "nifty500"}``).
    """

    def __init__(
        self,
        checkpoint_path: Path,
        fetch_params: dict[str, Any] | None = None,
    ) -> None:
        self._path = checkpoint_path
        self._fetch_params = fetch_params or {}
        self._lock = None  # Could add threading.Lock for thread safety

    # ------------------------------------------------------------------
    # Read / Write
    # ------------------------------------------------------------------

    def read(self) -> dict[str, Any]:
        """Load the checkpoint dict (empty dict if missing or corrupt)."""
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "Corrupt checkpoint %s: %s — starting fresh", self._path, e
            )
            return {}

    def write(self, data: dict[str, Any]) -> None:
        """Persist the checkpoint dict."""
        data["last_updated"] = datetime.now().isoformat(timespec="seconds")
        self._path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Per-symbol operations
    # ------------------------------------------------------------------

    def get_coverage(self, symbol: str) -> tuple[Optional[datetime], Optional[datetime]]:
        """Return ``(date_min, date_max)`` for a symbol, or ``(None, None)``.

        Dates are timezone-naive ``datetime`` objects.
        """
        cp = self.read()
        entry = cp.get("symbols", {}).get(symbol)
        if entry is None:
            return None, None
        dmin = (
            datetime.strptime(entry["date_min"], _DATE_FMT)
            if entry.get("date_min")
            else None
        )
        dmax = (
            datetime.strptime(entry["date_max"], _DATE_FMT)
            if entry.get("date_max")
            else None
        )
        return dmin, dmax

    def coverage_needed(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> bool:
        """Return ``True`` if the symbol needs fetching.

        Returns ``False`` if the checkpoint shows the range is already covered.
        """
        dmin, dmax = self.get_coverage(symbol)
        if dmin is None or dmax is None:
            return True  # No data yet
        return not (dmin <= start_date and dmax >= end_date)

    def update_symbol(
        self,
        symbol: str,
        date_min: str | datetime,
        date_max: str | datetime,
        rows: int = 0,
        meta: dict | None = None,
    ) -> None:
        """Record that a symbol's data now covers ``[date_min, date_max]``.

        Args:
            symbol: Trading symbol.
            date_min: Start of coverage (date string ``YYYY-MM-DD`` or datetime).
            date_max: End of coverage.
            rows: Number of data rows fetched.
            meta: Optional metadata dict (e.g. ISIN, contract info).
        """
        fmt = lambda d: d if isinstance(d, str) else d.strftime(_DATE_FMT)

        cp = self.read()
        symbols = cp.setdefault("symbols", {})
        existing = symbols.get(symbol, {})

        # Merge date ranges (expand if the new range is wider)
        old_min = existing.get("date_min")
        old_max = existing.get("date_max")
        new_min = fmt(date_min)
        new_max = fmt(date_max)
        if old_min and old_min < new_min:
            new_min = old_min
        if old_max and old_max > new_max:
            new_max = old_max

        entry = {
            "date_min": new_min,
            "date_max": new_max,
            "rows": max(rows, existing.get("rows", 0)),
        }
        if meta:
            existing_meta = existing.get("meta", {})
            existing_meta.update(meta)
            entry["meta"] = existing_meta

        symbols[symbol] = entry
        self.write(cp)
