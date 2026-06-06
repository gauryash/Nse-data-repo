"""Unit tests for JSON checkpoint."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from nse_relative.infrastructure.checkpoint.json_checkpoint import JsonCheckpoint


class TestJsonCheckpoint:
    def test_empty_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_checkpoint.json"
            cp = JsonCheckpoint(path)
            assert cp.read() == {}

    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_checkpoint.json"
            cp = JsonCheckpoint(path)
            cp.write({"symbols": {"RELIANCE": {"date_min": "2026-01-01"}}})
            data = cp.read()
            assert "symbols" in data
            assert data["symbols"]["RELIANCE"]["date_min"] == "2026-01-01"
            assert "last_updated" in data

    def test_get_coverage_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_checkpoint.json"
            cp = JsonCheckpoint(path)
            dmin, dmax = cp.get_coverage("RELIANCE")
            assert dmin is None
            assert dmax is None

    def test_update_symbol_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_checkpoint.json"
            cp = JsonCheckpoint(path)
            cp.update_symbol("RELIANCE", "2026-01-01", "2026-06-01", rows=100)
            dmin, dmax = cp.get_coverage("RELIANCE")
            assert dmin == datetime(2026, 1, 1)
            assert dmax == datetime(2026, 6, 1)

    def test_update_symbol_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_checkpoint.json"
            cp = JsonCheckpoint(path)
            cp.update_symbol("RELIANCE", "2026-03-01", "2026-06-01", rows=50)
            cp.update_symbol("RELIANCE", "2026-01-01", "2026-04-01", rows=100)
            dmin, dmax = cp.get_coverage("RELIANCE")
            # Should have merged to cover both ranges
            assert dmin == datetime(2026, 1, 1)
            assert dmax == datetime(2026, 6, 1)

    def test_coverage_needed_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_checkpoint.json"
            cp = JsonCheckpoint(path)
            assert cp.coverage_needed(
                "RELIANCE",
                datetime(2026, 1, 1),
                datetime(2026, 6, 1),
            )

    def test_coverage_needed_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_checkpoint.json"
            cp = JsonCheckpoint(path)
            cp.update_symbol("RELIANCE", "2026-01-01", "2026-06-01")
            assert not cp.coverage_needed(
                "RELIANCE",
                datetime(2026, 2, 1),
                datetime(2026, 5, 1),
            )
            assert cp.coverage_needed(
                "RELIANCE",
                datetime(2025, 12, 1),
                datetime(2026, 6, 1),
            )

    def test_update_symbol_with_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_checkpoint.json"
            cp = JsonCheckpoint(path)
            cp.update_symbol(
                "NIFTY26JUN23600CE",
                "2026-01-01",
                "2026-06-01",
                meta={"instrument_type": "OPTIDX", "strike": 23600.0},
            )
            data = cp.read()
            meta = data["symbols"]["NIFTY26JUN23600CE"]["meta"]
            assert meta["instrument_type"] == "OPTIDX"
            assert meta["strike"] == 23600.0

    def test_corrupt_checkpoint(self, caplog):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_checkpoint.json"
            path.write_text("{invalid json")
            cp = JsonCheckpoint(path)
            assert cp.read() == {}
