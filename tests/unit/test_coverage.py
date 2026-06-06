"""Unit tests for coverage / checkpoint domain models."""

from datetime import datetime

from nse_relative.domain.coverage import CoverageRange, CheckpointData


class TestCoverageRange:
    def test_covers_exact_range(self):
        cov = CoverageRange(date_min="2026-01-01", date_max="2026-06-01")
        assert cov.covers(
            datetime(2026, 1, 1),
            datetime(2026, 6, 1),
        )

    def test_covers_subrange(self):
        cov = CoverageRange(date_min="2026-01-01", date_max="2026-06-01")
        assert cov.covers(
            datetime(2026, 2, 1),
            datetime(2026, 5, 1),
        )

    def test_does_not_cover_outside(self):
        cov = CoverageRange(date_min="2026-02-01", date_max="2026-06-01")
        assert not cov.covers(
            datetime(2026, 1, 1),
            datetime(2026, 6, 1),
        )

    def test_merge(self):
        a = CoverageRange(date_min="2026-01-01", date_max="2026-03-01", rows=100)
        b = CoverageRange(date_min="2026-02-01", date_max="2026-06-01", rows=200)
        merged = a.merge(b)
        assert merged.date_min == "2026-01-01"
        assert merged.date_max == "2026-06-01"
        assert merged.rows == 200  # max of both


class TestCheckpointData:
    def test_empty_defaults(self):
        cp = CheckpointData()
        assert cp.last_updated == ""
        assert cp.fetch_params == {}
        assert cp.symbols == {}
