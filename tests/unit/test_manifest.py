"""Unit tests for contract manifest."""

import tempfile
from pathlib import Path

import pandas as pd

from nse_relative.infrastructure.storage.file_repository import FileStorageRepository
from nse_relative.infrastructure.storage.manifest import ContractManifest


class TestContractManifest:
    def test_empty_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"upstox_options": base / "upstox_options"},
            )
            manifest = ContractManifest(storage, "upstox_options")
            df = manifest.load()
            assert df.empty

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"upstox_options": base / "upstox_options"},
            )
            manifest = ContractManifest(storage, "upstox_options")
            df = pd.DataFrame(
                {
                    "instrument_key": ["NSE_FO|12345"],
                    "tradingsymbol": ["NIFTY26JUN23600CE"],
                    "name": ["NIFTY"],
                    "underlying_type": ["INDEX"],
                    "instrument_type": ["OPTIDX"],
                    "option_type": ["CE"],
                    "expiry": ["2026-06-09"],
                    "strike": [23600.0],
                    "lot_size": [65],
                    "tick_size": [0.05],
                }
            )
            manifest.save(df)
            loaded = manifest.load()
            assert len(loaded) == 1
            assert loaded["tradingsymbol"].iloc[0] == "NIFTY26JUN23600CE"

    def test_save_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"upstox_options": base / "upstox_options"},
            )
            manifest = ContractManifest(storage, "upstox_options")
            df1 = pd.DataFrame(
                {
                    "instrument_key": ["NSE_FO|12345"],
                    "tradingsymbol": ["NIFTY26JUN23600CE"],
                    "name": ["NIFTY"],
                    "underlying_type": ["INDEX"],
                    "instrument_type": ["OPTIDX"],
                    "option_type": ["CE"],
                    "expiry": ["2026-06-09"],
                    "strike": [23600.0],
                    "lot_size": [65],
                    "tick_size": [0.05],
                }
            )
            manifest.save(df1)
            manifest.save(df1)  # same data again
            loaded = manifest.load()
            assert len(loaded) == 1  # deduplicated

    def test_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = FileStorageRepository(
                base_dirs={"upstox_options": base / "upstox_options"},
            )
            manifest = ContractManifest(storage, "upstox_options")
            df = pd.DataFrame(
                {
                    "instrument_key": ["NSE_FO|1", "NSE_FO|2"],
                    "tradingsymbol": ["NIFTY26JUN23600CE", "NIFTY26JUN23600PE"],
                    "name": ["NIFTY", "NIFTY"],
                    "underlying_type": ["INDEX", "INDEX"],
                    "instrument_type": ["OPTIDX", "OPTIDX"],
                    "option_type": ["CE", "PE"],
                    "expiry": ["2026-06-09", "2026-06-09"],
                    "strike": [23600.0, 23600.0],
                    "lot_size": [65, 65],
                    "tick_size": [0.05, 0.05],
                }
            )
            manifest.save(df)
            result = manifest.query(option_type="CE")
            assert len(result) == 1
            assert result["tradingsymbol"].iloc[0] == "NIFTY26JUN23600CE"

    def test_build_checkpoint_entry(self):
        row = pd.Series(
            {
                "instrument_type": "OPTIDX",
                "option_type": "CE",
                "expiry": "2026-06-09",
                "strike": 23600.0,
                "lot_size": 65,
                "name": "NIFTY",
            }
        )
        entry = ContractManifest.build_checkpoint_entry(row)
        assert entry["instrument_type"] == "OPTIDX"
        assert entry["expiry"] == "2026-06-09"
