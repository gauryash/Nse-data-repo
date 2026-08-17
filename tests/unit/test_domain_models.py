"""Unit tests for domain models."""

from datetime import date

import pandas as pd

from nse_data_pipeline.domain.models import (
    AssetType,
    CandleInterval,
    InstrumentType,
    OptionContract,
    OptionType,
    ProviderName,
    StorageFormat,
)


class TestEnums:
    def test_instrument_type_from_str(self):
        result = InstrumentType.from_str("OPTSTK,OPTIDX")
        assert result == [InstrumentType.OPTSTK, InstrumentType.OPTIDX]

    def test_instrument_type_from_str_single(self):
        result = InstrumentType.from_str("OPTSTK")
        assert result == [InstrumentType.OPTSTK]

    def test_asset_type_from_instrument_type(self):
        assert AssetType.from_instrument_type("OPTSTK") == AssetType.STOCK
        assert AssetType.from_instrument_type("FUTSTK") == AssetType.STOCK
        assert AssetType.from_instrument_type("OPTIDX") == AssetType.INDEX
        assert AssetType.from_instrument_type("FUTIDX") == AssetType.INDEX
        assert AssetType.from_instrument_type("UNKNOWN") == AssetType.UNKNOWN

    def test_enums_values(self):
        assert StorageFormat.PARQUET.value == "parquet"
        assert CandleInterval.DAY.value == "day"
        assert OptionType.CE.value == "CE"
        assert ProviderName.NSE.value == "nse"


class TestOptionContract:
    def test_from_dataframe_row(self):
        row = pd.Series(
            {
                "instrument_key": "NSE_FO|12345",
                "tradingsymbol": "NIFTY26JUN23600CE",
                "name": "NIFTY",
                "instrument_type": "OPTIDX",
                "option_type": "CE",
                "expiry": date(2026, 6, 9),
                "strike": 23600.0,
                "lot_size": 65,
                "tick_size": 0.05,
            }
        )
        contract = OptionContract.from_dataframe_row(row)
        assert contract.instrument_key == "NSE_FO|12345"
        assert contract.tradingsymbol == "NIFTY26JUN23600CE"
        assert contract.underlying_name == "NIFTY"
        assert contract.underlying_type == "INDEX"
        assert contract.instrument_type == "OPTIDX"
        assert contract.option_type == "CE"
        assert contract.expiry == date(2026, 6, 9)
        assert contract.strike == 23600.0
        assert contract.lot_size == 65
        assert contract.tick_size == 0.05

    def test_from_dataframe_row_futures(self):
        row = pd.Series(
            {
                "instrument_key": "NSE_FO|67890",
                "tradingsymbol": "RELIANCE26JUNFUT",
                "name": "RELIANCE",
                "instrument_type": "FUTSTK",
                "option_type": "FF",
                "expiry": date(2026, 6, 25),
                "strike": None,
                "lot_size": 250,
                "tick_size": 0.05,
            }
        )
        contract = OptionContract.from_dataframe_row(row)
        assert contract.strike is None
        assert contract.option_type == "FF"
        assert contract.underlying_type == "STOCK"

    def test_to_dict(self):
        contract = OptionContract(
            instrument_key="NSE_FO|12345",
            tradingsymbol="NIFTY26JUN23600CE",
            underlying_name="NIFTY",
            underlying_type="INDEX",
            instrument_type="OPTIDX",
            option_type="CE",
            expiry=date(2026, 6, 9),
            strike=23600.0,
            lot_size=65,
            tick_size=0.05,
        )
        d = contract.to_dict()
        assert d["tradingsymbol"] == "NIFTY26JUN23600CE"
        assert d["expiry"] == "2026-06-09"
        assert d["strike"] == 23600.0

    def test_to_dict_none_expiry(self):
        contract = OptionContract(
            instrument_key="NSE_FO|12345",
            tradingsymbol="TEST",
            underlying_name="TEST",
            underlying_type="STOCK",
            instrument_type="OPTSTK",
            option_type="CE",
            expiry=None,
            strike=None,
            lot_size=0,
            tick_size=0.05,
        )
        d = contract.to_dict()
        assert d["expiry"] is None
