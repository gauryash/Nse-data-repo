"""Unit tests for file storage repository."""

import tempfile
from pathlib import Path

import pandas as pd

from nse_relative.infrastructure.storage.file_repository import FileStorageRepository


class TestFileStorageRepository:
    def test_save_and_load_equities(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"nse": base / "nse"},
                storage_format="csv",
            )
            df = pd.DataFrame(
                {
                    "Symbol": ["RELIANCE", "TCS"],
                    "Date": ["2026-01-02", "2026-01-03"],
                    "Close": [2500.0, 3800.0],
                }
            )
            storage.save_equities(df, "nse")
            loaded = storage.load_equities("nse")
            assert len(loaded) == 2
            assert "RELIANCE" in loaded["Symbol"].values

    def test_save_and_load_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"upstox": base / "upstox"},
                storage_format="csv",
            )
            df = pd.DataFrame(
                {
                    "date": ["2026-01-02", "2026-01-03"],
                    "close": [2500.0, 2510.0],
                    "symbol": ["RELIANCE", "RELIANCE"],
                }
            )
            storage.save_symbol(df, "upstox", "RELIANCE")
            loaded = storage.load_symbol("upstox", "RELIANCE")
            assert len(loaded) == 2

    def test_save_and_load_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"upstox_options": base / "upstox_options"},
                storage_format="csv",
            )
            df = pd.DataFrame(
                {
                    "date": ["2026-01-02"],
                    "close": [100.0],
                    "symbol": ["NIFTY26JUN23600CE"],
                }
            )
            storage.save_option(df, "upstox_options", "NIFTY26JUN23600CE")
            loaded = storage.load_option("upstox_options", "NIFTY26JUN23600CE")
            assert len(loaded) == 1

    def test_save_and_load_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"nse": base / "nse"},
                storage_format="csv",
            )
            df = pd.DataFrame(
                {
                    "Date": ["2026-01-02"],
                    "Close": [23000.0],
                    "Symbol": ["NIFTY 500"],
                }
            )
            storage.save_index(df, "nse")
            loaded = storage.load_index("nse")
            assert len(loaded) == 1

    def test_list_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"upstox": base / "upstox"},
                storage_format="csv",
            )
            df1 = pd.DataFrame({"date": ["2026-01-02"], "close": [100.0], "symbol": ["RELIANCE"]})
            df2 = pd.DataFrame({"date": ["2026-01-02"], "close": [200.0], "symbol": ["TCS"]})
            storage.save_symbol(df1, "upstox", "RELIANCE")
            storage.save_symbol(df2, "upstox", "TCS")
            symbols = storage.list_symbols("upstox")
            assert sorted(symbols) == ["RELIANCE", "TCS"]

    def test_list_symbols_excludes_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"nse": base / "nse"},
                storage_format="csv",
            )
            # Save equities (creates equities.csv which should be excluded)
            df = pd.DataFrame(
                {
                    "Symbol": ["RELIANCE"],
                    "Date": ["2026-01-02"],
                    "Close": [2500.0],
                }
            )
            storage.save_equities(df, "nse")
            symbols = storage.list_symbols("nse")
            # equities.csv should be excluded
            assert "equities" not in symbols

    def test_rebuild_consolidated(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"nse": base / "nse"},
                storage_format="csv",
            )
            # Save two years of data
            df1 = pd.DataFrame(
                {
                    "Symbol": ["RELIANCE"],
                    "Date": ["2025-01-02"],
                    "Close": [2000.0],
                }
            )
            df2 = pd.DataFrame(
                {
                    "Symbol": ["TCS"],
                    "Date": ["2026-01-02"],
                    "Close": [3800.0],
                }
            )
            storage.save_equities(df1, "nse")
            storage.save_equities(df2, "nse")
            consolidated = storage.load_equities("nse")
            assert len(consolidated) == 2
