"""Unit tests for the --underlyings filter on UpstoxOptionsProvider."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from nse_data_pipeline.infrastructure.storage.file_repository import FileStorageRepository
from nse_data_pipeline.pipeline.upstox_options_provider import UpstoxOptionsProvider


def _make_storage(tmp: Path) -> FileStorageRepository:
    return FileStorageRepository(
        base_dirs={"upstox_options": tmp / "upstox_options"},
    )


def _fake_contracts() -> pd.DataFrame:
    """3 OPTSTK names + 1 OPTIDX name. The index row must be kept when no
    underlyings filter is applied; it should be dropped when OPTIDX is not
    in the filter (because filter is on extracted underlying, and NIFTY is
    a valid underlying short name)."""
    return pd.DataFrame(
        [
            {
                "instrument_key": "NSE_FO|RELIANCE",
                "tradingsymbol": "RELIANCE26JUN1230CE",
                "name": "RELIANCE",
                "underlying_type": "STOCK",
                "instrument_type": "OPTSTK",
                "option_type": "CE",
                "expiry": pd.Timestamp("2026-06-26"),
                "strike": 1230.0,
                "lot_size": 100,
                "tick_size": 0.05,
            },
            {
                "instrument_key": "NSE_FO|TCS",
                "tradingsymbol": "TCS26JUN3000CE",
                "name": "TCS",
                "underlying_type": "STOCK",
                "instrument_type": "OPTSTK",
                "option_type": "CE",
                "expiry": pd.Timestamp("2026-06-26"),
                "strike": 3000.0,
                "lot_size": 100,
                "tick_size": 0.05,
            },
            {
                "instrument_key": "NSE_FO|INFY",
                "tradingsymbol": "INFY26JUN1500CE",
                "name": "INFY",
                "underlying_type": "STOCK",
                "instrument_type": "OPTSTK",
                "option_type": "CE",
                "expiry": pd.Timestamp("2026-06-26"),
                "strike": 1500.0,
                "lot_size": 100,
                "tick_size": 0.05,
            },
            {
                "instrument_key": "NSE_FO|NIFTY",
                "tradingsymbol": "NIFTY26JUN23600CE",
                "name": "NIFTY",
                "underlying_type": "INDEX",
                "instrument_type": "OPTIDX",
                "option_type": "CE",
                "expiry": pd.Timestamp("2026-06-26"),
                "strike": 23600.0,
                "lot_size": 50,
                "tick_size": 0.05,
            },
        ]
    )


def _build_provider(tmp: Path) -> UpstoxOptionsProvider:
    storage = _make_storage(tmp)
    client = MagicMock()
    client.parse_date.side_effect = lambda s: pd.Timestamp(s, tz="UTC") if s else None
    return UpstoxOptionsProvider(
        interval="day",
        index="nifty50",
        instrument_types="OPTSTK,OPTIDX",
        n_expiries=3,
        start_date="25-05-2026",
        end_date="24-06-2026",
        client=client,
        storage=storage,
    )


class TestUnderlyingsFilter:
    def test_underlyings_keeps_only_named_optstk_preserves_optidx(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = _build_provider(Path(tmp))
            contracts = _fake_contracts()

            with patch("nse_data_pipeline.pipeline.upstox_options_provider.upstox_src") as mock_src:
                mock_src.discover_option_contracts.return_value = contracts
                mock_src.filter_by_expiry.side_effect = lambda df, _n_expiries: df

                kept = provider._filter_by_underlyings(contracts.copy(), ["RELIANCE", "TCS"])

            kept_optstk = kept[kept["instrument_type"] == "OPTSTK"]
            kept_optidx = kept[kept["instrument_type"] == "OPTIDX"]
            assert sorted(kept_optstk["_underlying_short"].unique()) == ["RELIANCE", "TCS"]
            assert len(kept_optstk) == 2
            assert kept_optidx["tradingsymbol"].tolist() == ["NIFTY26JUN23600CE"]
            assert len(kept) == 3

    def test_underlyings_normalises_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = _build_provider(Path(tmp))
            contracts = _fake_contracts()

            with patch("nse_data_pipeline.pipeline.upstox_options_provider.upstox_src") as mock_src:
                mock_src.discover_option_contracts.return_value = contracts
                mock_src.filter_by_expiry.side_effect = lambda df, _n_expiries: df

                kept = provider._filter_by_underlyings(contracts.copy(), ["reliance"])

            kept_optstk = kept[kept["instrument_type"] == "OPTSTK"]
            assert kept_optstk["_underlying_short"].unique().tolist() == ["RELIANCE"]
            assert (kept["instrument_type"] == "OPTIDX").sum() == 1

    def test_underlyings_missing_underlying_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = _build_provider(Path(tmp))
            contracts = _fake_contracts()

            with patch("nse_data_pipeline.pipeline.upstox_options_provider.upstox_src") as mock_src:
                mock_src.discover_option_contracts.return_value = contracts
                mock_src.filter_by_expiry.side_effect = lambda df, _n_expiries: df

                kept = provider._filter_by_underlyings(contracts.copy(), ["RELIANCE", "WIPRO"])

            kept_optstk = kept[kept["instrument_type"] == "OPTSTK"]
            assert sorted(kept_optstk["_underlying_short"].unique()) == ["RELIANCE"]

    def test_underlyings_all_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = _build_provider(Path(tmp))
            contracts = _fake_contracts()

            with patch("nse_data_pipeline.pipeline.upstox_options_provider.upstox_src") as mock_src:
                mock_src.discover_option_contracts.return_value = contracts
                mock_src.filter_by_expiry.side_effect = lambda df, _n_expiries: df

                kept = provider._filter_by_underlyings(
                    contracts.copy(), ["RELIANCE", "TCS", "INFY"]
                )

            assert len(kept) == 4  # 3 OPTSTK + 1 OPTIDX (preserved)
            assert (kept["instrument_type"] == "OPTSTK").sum() == 3
            assert (kept["instrument_type"] == "OPTIDX").sum() == 1

    def test_underlyings_empty_list_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = _build_provider(Path(tmp))
            contracts = _fake_contracts()

            with patch("nse_data_pipeline.pipeline.upstox_options_provider.upstox_src") as mock_src:
                mock_src.discover_option_contracts.return_value = contracts
                mock_src.filter_by_expiry.side_effect = lambda df, _n_expiries: df

                kept = provider._filter_by_underlyings(contracts.copy(), [])

            assert kept.empty

    def test_underlyings_no_stock_match_preserves_all_optidx(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = _build_provider(Path(tmp))
            contracts = _fake_contracts()

            with patch("nse_data_pipeline.pipeline.upstox_options_provider.upstox_src") as mock_src:
                mock_src.discover_option_contracts.return_value = contracts
                mock_src.filter_by_expiry.side_effect = lambda df, _n_expiries: df

                kept = provider._filter_by_underlyings(contracts.copy(), ["ZZZ"])

            kept_optstk = kept[kept["instrument_type"] == "OPTSTK"]
            kept_optidx = kept[kept["instrument_type"] == "OPTIDX"]
            assert kept_optstk.empty
            assert len(kept_optidx) == 1

    def test_underlyings_preserves_optidx_even_when_no_optstk_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = _build_provider(Path(tmp))
            optidx_only = _fake_contracts()[_fake_contracts()["instrument_type"] == "OPTIDX"].copy()
            optidx_only = optidx_only.reset_index(drop=True)

            with patch("nse_data_pipeline.pipeline.upstox_options_provider.upstox_src") as mock_src:
                mock_src.discover_option_contracts.return_value = optidx_only
                mock_src.filter_by_expiry.side_effect = lambda df, _n_expiries: df

                kept = provider._filter_by_underlyings(optidx_only.copy(), ["RELIANCE"])

            assert len(kept) == 1
            assert kept["tradingsymbol"].iloc[0] == "NIFTY26JUN23600CE"

    def test_optidx_survives_with_multiple_index_names(self):
        """Reproduces the user-reported scenario: 10 stock names in --underlyings
        must NOT drop NIFTY/BANKNIFTY OPTIDX rows when instrument_types=OPTSTK,OPTIDX."""
        with tempfile.TemporaryDirectory() as tmp:
            provider = _build_provider(Path(tmp))
            contracts = _fake_contracts()
            banknifty_row = {
                "instrument_key": "NSE_FO|BANKNIFTY",
                "tradingsymbol": "BANKNIFTY26JUN52000CE",
                "name": "BANKNIFTY",
                "underlying_type": "INDEX",
                "instrument_type": "OPTIDX",
                "option_type": "CE",
                "expiry": pd.Timestamp("2026-06-26"),
                "strike": 52000.0,
                "lot_size": 15,
                "tick_size": 0.05,
            }
            contracts = pd.concat([contracts, pd.DataFrame([banknifty_row])], ignore_index=True)

            with patch("nse_data_pipeline.pipeline.upstox_options_provider.upstox_src") as mock_src:
                mock_src.discover_option_contracts.return_value = contracts
                mock_src.filter_by_expiry.side_effect = lambda df, _n_expiries: df

                kept = provider._filter_by_underlyings(
                    contracts.copy(),
                    [
                        "RELIANCE",
                        "TCS",
                        "HDFCBANK",
                        "INFY",
                        "ICICIBANK",
                        "SBIN",
                        "BHARTIARTL",
                        "LT",
                        "ITC",
                        "AXISBANK",
                    ],
                )

            assert (kept["instrument_type"] == "OPTIDX").sum() == 2
            optidx_names = sorted(
                kept[kept["instrument_type"] == "OPTIDX"]["tradingsymbol"].tolist()
            )
            assert optidx_names == ["BANKNIFTY26JUN52000CE", "NIFTY26JUN23600CE"]
