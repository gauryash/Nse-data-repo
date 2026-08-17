"""Unit tests for the Upstox instrument master JSON (BOD) normalisation."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

from nse_data_pipeline.infrastructure.symbol_source.upstox_instruments import (
    InstrumentMaster,
    normalize_json_rows,
)

_PATCH_GET = "nse_data_pipeline.infrastructure.symbol_source.upstox_instruments.requests.get"

_EPOCH = datetime.datetime.fromtimestamp


def _ms(day: datetime.date) -> int:
    dt = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)


def _fixture_rows() -> list[dict]:
    """Realistic subset of the Upstox BOD JSON schema."""
    return [
        {
            "instrument_key": "NSE_EQ|INE002A01018",
            "exchange_token": "12804",
            "trading_symbol": "RELIANCE",
            "name": "RELIANCE INDUSTRIES LTD",
            "instrument_type": "EQ",
            "segment": "NSE_EQ",
            "underlying_type": "",
            "expiry": None,
        },
        {
            "instrument_key": "NSE_EQ|INE467B01029",
            "exchange_token": "10666",
            "trading_symbol": "TCS",
            "name": "TATA CONSULTANCY SERV LT",
            "instrument_type": "EQ",
            "segment": "NSE_EQ",
            "underlying_type": "",
            "expiry": None,
        },
        {
            "instrument_key": "NSE_FO|98917",
            "exchange_token": "98917",
            "trading_symbol": "RELIANCE 1230 CE 27 OCT 26",
            "name": "RELIANCE INDUSTRIES LTD",
            "asset_symbol": "RELIANCE",
            "underlying_symbol": "RELIANCE",
            "underlying_type": "EQUITY",
            "instrument_type": "CE",
            "strike_price": 1230.0,
            "expiry": _ms(datetime.date(2026, 10, 27)),
            "lot_size": 100,
            "tick_size": 5.0,
            "segment": "NSE_FO",
        },
        {
            "instrument_key": "NSE_FO|98918",
            "exchange_token": "98918",
            "trading_symbol": "RELIANCE 1230 PE 27 OCT 26",
            "name": "RELIANCE INDUSTRIES LTD",
            "asset_symbol": "RELIANCE",
            "underlying_symbol": "RELIANCE",
            "underlying_type": "EQUITY",
            "instrument_type": "PE",
            "strike_price": 1230.0,
            "expiry": _ms(datetime.date(2026, 10, 27)),
            "lot_size": 100,
            "tick_size": 5.0,
            "segment": "NSE_FO",
        },
        {
            "instrument_key": "NSE_FO|50918",
            "exchange_token": "50918",
            "trading_symbol": "NIFTY 23600 CE 27 OCT 26",
            "name": "NIFTY",
            "asset_symbol": "NIFTY",
            "underlying_symbol": "NIFTY",
            "underlying_type": "INDEX",
            "instrument_type": "CE",
            "strike_price": 23600.0,
            "expiry": _ms(datetime.date(2026, 10, 27)),
            "lot_size": 50,
            "tick_size": 0.05,
            "segment": "NSE_FO",
        },
        {
            "instrument_key": "NSE_FO|30001",
            "exchange_token": "30001",
            "trading_symbol": "RELIANCE FUT 27 OCT 26",
            "name": "RELIANCE INDUSTRIES LTD",
            "asset_symbol": "RELIANCE",
            "underlying_symbol": "RELIANCE",
            "underlying_type": "EQUITY",
            "instrument_type": "FUT",
            "expiry": _ms(datetime.date(2026, 10, 27)),
            "lot_size": 100,
            "segment": "NSE_FO",
        },
        {
            "instrument_key": "NSE_FO|50001",
            "exchange_token": "50001",
            "trading_symbol": "NIFTY FUT 27 OCT 26",
            "name": "NIFTY",
            "asset_symbol": "NIFTY",
            "underlying_symbol": "NIFTY",
            "underlying_type": "INDEX",
            "instrument_type": "FUT",
            "expiry": _ms(datetime.date(2026, 10, 27)),
            "lot_size": 50,
            "segment": "NSE_FO",
        },
        {
            "instrument_key": "MCX_FO|579520",
            "exchange_token": "579520",
            "trading_symbol": "CRUDEOIL 6500 CE 26 AUG 26",
            "name": "CRUDEOIL",
            "asset_symbol": "CRUDEOIL",
            "underlying_symbol": "CRUDEOIL",
            "underlying_type": "COM",
            "instrument_type": "CE",
            "strike_price": 6500.0,
            "expiry": _ms(datetime.date(2026, 8, 26)),
            "lot_size": 100,
            "tick_size": 0.1,
            "segment": "MCX_FO",
        },
        {
            "instrument_key": "NCD_FO|14294",
            "exchange_token": "14294",
            "trading_symbol": "GBPINR 130.5 CE 14 AUG 26",
            "name": "GBPINR",
            "asset_symbol": "GBPINR",
            "underlying_symbol": "GBPINR",
            "underlying_type": "CUR",
            "instrument_type": "CE",
            "strike_price": 130.5,
            "expiry": _ms(datetime.date(2026, 8, 14)),
            "lot_size": 1,
            "tick_size": 0.25,
            "segment": "NCD_FO",
        },
        {
            "instrument_key": "NSE_INDEX|Nifty 50",
            "exchange_token": "5089",
            "trading_symbol": "Nifty 50",
            "name": "Nifty 50",
            "asset_symbol": None,
            "underlying_symbol": None,
            "underlying_type": None,
            "instrument_type": "INDEX",
            "expiry": None,
            "segment": "NSE_INDEX",
        },
        {
            "instrument_key": "NSE_FO|0",
            "exchange_token": "0",
            "trading_symbol": "",
            "name": "MALFORMED",
            "underlying_type": "EQUITY",
            "instrument_type": "CE",
            "expiry": None,
            "strike_price": None,
            "segment": "NSE_FO",
        },
    ]


class TestNormalizeJsonRows:
    def test_maps_instrument_types(self):
        df = normalize_json_rows(_fixture_rows())
        by_key = df.set_index("instrument_key")["instrument_type"].to_dict()
        assert by_key["NSE_FO|98917"] == "OPTSTK"
        assert by_key["NSE_FO|98918"] == "OPTSTK"
        assert by_key["NSE_FO|50918"] == "OPTIDX"
        assert by_key["NSE_FO|30001"] == "FUTSTK"
        assert by_key["NSE_FO|50001"] == "FUTIDX"
        assert by_key["MCX_FO|579520"] == "CE"
        assert by_key["NCD_FO|14294"] == "CE"
        assert by_key["NSE_EQ|INE002A01018"] == "EQ"

    def test_maps_option_type(self):
        df = normalize_json_rows(_fixture_rows())
        by_key = df.set_index("instrument_key")["option_type"].to_dict()
        assert by_key["NSE_FO|98917"] == "CE"
        assert by_key["NSE_FO|98918"] == "PE"
        assert by_key["NSE_FO|30001"] == "FF"
        assert by_key["NSE_FO|50001"] == "FF"

    def test_converts_expiry_epoch_ms_to_date(self):
        df = normalize_json_rows(_fixture_rows())
        expiry = df.set_index("instrument_key")["expiry"].to_dict()
        assert expiry["NSE_FO|98917"] == datetime.date(2026, 10, 27)
        assert expiry["MCX_FO|579520"] == datetime.date(2026, 8, 26)
        assert expiry["NSE_EQ|INE002A01018"] is None

    def test_maps_strike_and_tradingsymbol_and_exchange(self):
        df = normalize_json_rows(_fixture_rows())
        row = df[df["instrument_key"] == "NSE_FO|98917"].iloc[0]
        assert row["strike"] == 1230.0
        assert row["tradingsymbol"] == "RELIANCE 1230 CE 27 OCT 26"
        assert row["exchange"] == "NSE_FO"
        assert row["lot_size"] == 100
        assert row["tick_size"] == 5.0

    def test_derives_isin_number_in_download(self, tmp_path):
        rows = _fixture_rows()
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz(rows)
            mock_get.return_value.raise_for_status = lambda: None
            df = InstrumentMaster(
                url="https://example.invalid/x.json.gz",
                cache_path=tmp_path / "c.json.gz",
            ).download()
        isins = df.set_index("instrument_key")["ISIN_NUMBER"].to_dict()
        assert isins["NSE_EQ|INE002A01018"] == "INE002A01018"
        assert isins["NSE_FO|98917"] == "98917"


def _gz(rows: list[dict]) -> bytes:
    import gzip
    import json

    return gzip.compress(json.dumps(rows).encode())


class TestInstrumentMasterCache:
    def _master(self, tmp: Path, ttl: float = 12.0) -> InstrumentMaster:
        return InstrumentMaster(
            url="https://example.invalid/x.json.gz",
            cache_path=tmp / "complete.json.gz",
            ttl_hours=ttl,
        )

    def test_download_writes_cache_and_reuses_it(self, tmp_path):
        rows = _fixture_rows()
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz(rows)
            mock_get.return_value.raise_for_status = lambda: None
            master = self._master(tmp_path)
            df1 = master.download()
            assert len(df1) == len(rows)
            assert (tmp_path / "complete.json.gz").exists()

        # Second master: network fails, fresh cache is used instead.
        with patch(_PATCH_GET) as mock_get:
            mock_get.side_effect = OSError("offline")
            df2 = self._master(tmp_path).download()
        assert df2["instrument_key"].tolist() == df1["instrument_key"].tolist()

    def test_stale_cache_fallback_on_network_failure(self, tmp_path):
        rows = _fixture_rows()
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz(rows)
            mock_get.return_value.raise_for_status = lambda: None
            self._master(tmp_path, ttl=-1.0).download()  # writes stale cache

        with patch(_PATCH_GET) as mock_get:
            mock_get.side_effect = OSError("offline")
            df = self._master(tmp_path, ttl=-1.0).download()
        assert len(df) == len(rows)

    def test_stale_cache_refreshes_from_network(self, tmp_path):
        rows = _fixture_rows()
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz(rows)
            mock_get.return_value.raise_for_status = lambda: None
            self._master(tmp_path, ttl=-1.0).download()

        new_row = {"instrument_key": "NSE_FO|99999", "segment": "NSE_FO", "instrument_type": "CE"}
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz([*rows, new_row])
            mock_get.return_value.raise_for_status = lambda: None
            df = self._master(tmp_path, ttl=-1.0).download()
        assert "NSE_FO|99999" in df["instrument_key"].tolist()

    def test_invalidate_cache_removes_file(self, tmp_path):
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz(_fixture_rows())
            mock_get.return_value.raise_for_status = lambda: None
            master = self._master(tmp_path)
            master.download()
        assert (tmp_path / "complete.json.gz").exists()
        master.invalidate_cache()
        assert not (tmp_path / "complete.json.gz").exists()


class TestInstrumentMasterFilters:
    def test_get_equities_and_fno(self, tmp_path):
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz(_fixture_rows())
            mock_get.return_value.raise_for_status = lambda: None
            master = InstrumentMaster(url="u", cache_path=tmp_path / "c.json.gz")
            eq = master.get_equities()
            fno = master.get_fno()
        assert set(eq["exchange"]) == {"NSE_EQ"}
        assert len(eq) == 2
        assert set(fno["exchange"]) == {"NSE_FO"}
        assert len(fno) == 6

    def test_filter_by_isin(self, tmp_path):
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz(_fixture_rows())
            mock_get.return_value.raise_for_status = lambda: None
            master = InstrumentMaster(url="u", cache_path=tmp_path / "c.json.gz")
            out = master.filter_by_isin({"INE002A01018"})
        assert out["tradingsymbol"].tolist() == ["RELIANCE"]

    def test_filter_fno_by_types(self, tmp_path):
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz(_fixture_rows())
            mock_get.return_value.raise_for_status = lambda: None
            master = InstrumentMaster(url="u", cache_path=tmp_path / "c.json.gz")
            out = master.filter_fno_by_types(["OPTSTK", "OPTIDX"])
        assert len(out) == 4
        assert set(out["instrument_type"]) == {"OPTSTK", "OPTIDX"}


class TestOptionDiscovererOnJson:
    def test_discovers_stock_and_index_options(self, tmp_path):
        """OptionDiscoverer must still work against normalized JSON rows."""
        from unittest.mock import patch as _patch

        rows = _fixture_rows()

        class _FakeIndex:
            def get_isin_set(self, _index_name: str) -> set[str]:
                return {"INE002A01018", "INE467B01029"}

        with (
            _patch(
                "nse_data_pipeline.infrastructure.symbol_source.upstox_instruments.requests.get"
            ) as mock_get,
            _patch(
                "nse_data_pipeline.infrastructure.symbol_source.nse_index_csv.NseIndexConstituents",
                _FakeIndex,
            ),
        ):
            mock_get.return_value.content = _gz(rows)
            mock_get.return_value.raise_for_status = lambda: None
            from nse_data_pipeline.infrastructure.symbol_source.upstox_instruments import (
                OptionDiscoverer,
            )

            discoverer = OptionDiscoverer(
                master=InstrumentMaster(url="u", cache_path=tmp_path / "c.json.gz")
            )
            discovered = discoverer.discover(
                instrument_types=["OPTSTK", "OPTIDX"],
                index_name="nifty50",
            )

        assert set(discovered["instrument_type"]) == {"OPTSTK", "OPTIDX"}
        assert len(discovered) == 3  # 2 RELIANCE + 1 NIFTY
        assert discovered["name"].tolist().count("RELIANCE INDUSTRIES LTD") == 2
