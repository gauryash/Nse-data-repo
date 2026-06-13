"""
Coverage / checkpoint domain model.

Represents what date ranges have already been fetched for each symbol,
enabling incremental fetching without re-downloading existing data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CoverageRange:
    """Date range coverage for a single symbol."""

    date_min: str  # YYYY-MM-DD
    date_max: str  # YYYY-MM-DD
    rows: int = 0

    def covers(self, start: datetime, end: datetime) -> bool:
        """Check if this coverage fully contains the requested range."""
        dmin = datetime.strptime(self.date_min, "%Y-%m-%d")
        dmax = datetime.strptime(self.date_max, "%Y-%m-%d")
        return dmin <= start and dmax >= end

    def merge(self, other: CoverageRange) -> CoverageRange:
        """Return a new CoverageRange that spans both ranges."""
        dmin = min(self.date_min, other.date_min)
        dmax = max(self.date_max, other.date_max)
        rows = max(self.rows, other.rows)
        return CoverageRange(date_min=dmin, date_max=dmax, rows=rows)


@dataclass
class CheckpointData:
    """Full checkpoint contents for a provider."""

    last_updated: str = ""
    fetch_params: dict = field(default_factory=dict)
    symbols: dict[str, dict] = field(default_factory=dict)
