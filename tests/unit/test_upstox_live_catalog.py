"""Unit tests for the live-market domain models and catalog."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nse_data_pipeline.domain.live_models import AssetGroup, LiveQuote
from nse_data_pipeline.infrastructure.symbol_source import universe
from nse_data_pipeline.infrastructure.symbol_source.upstox_instruments import InstrumentMaster
from nse_data_pipeline.infrastructure.symbol_source.upstox_live_catalog import UpstoxLiveCatalog
from nse_data_pipeline.shared.exceptions import UnknownUnderlyingError

_PATCH_GET = "nse_data_pipeline.infrastructure.symbol_source.upstox_instruments.requests.get"


def _ms(day: datetime.date) -> int:
    dt = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)


def _catalog_rows() -> list[dict]:
    _OCT = _ms(datetime.date(2026, 10, 27))
    _AUG = _ms(datetime.date(2026, 8, 26))

    def _opt(key, sym, itype, strike, day, seg, utype, lot=100):
        return {
            "instrument_key": key,
            "trading_symbol": f"{sym} {strike} {itype} 27 OCT 26",
            "name": sym,
            "asset_symbol": sym,
            "underlying_symbol": sym,
            "underlying_type": utype,
            "instrument_type": itype,
            "strike_price": strike,
            "expiry": _OCT if day == "oct" else _AUG,
            "lot_size": lot,
            "tick_size": 0.05,
            "segment": seg,
        }

    return [
        _opt("NSE_FO|1", "RELIANCE", "CE", 1200.0, "oct", "NSE_FO", "EQUITY"),
        _opt("NSE_FO|2", "RELIANCE", "PE", 1200.0, "oct", "NSE_FO", "EQUITY"),
        _opt("NSE_FO|3", "RELIANCE", "CE", 1300.0, "oct", "NSE_FO", "EQUITY"),
        _opt("NSE_FO|4", "RELIANCE", "CE", 1250.0, "aug", "NSE_FO", "EQUITY"),
        _opt("NSE_FO|5", "TCS", "CE", 3000.0, "oct", "NSE_FO", "EQUITY"),
        _opt("NSE_FO|6", "NIFTY", "CE", 23600.0, "oct", "NSE_FO", "INDEX", 50),
        _opt("NSE_FO|7", "NIFTY", "PE", 23600.0, "oct", "NSE_FO", "INDEX", 50),
        _opt("MCX_FO|8", "CRUDEOIL", "CE", 6500.0, "oct", "MCX_FO", "COM", 100),
        _opt("MCX_FO|9", "CRUDEOIL", "PE", 6500.0, "oct", "MCX_FO", "COM", 100),
        _opt("MCX_FO|10", "GOLD", "CE", 70000.0, "oct", "MCX_FO", "COM", 1),
    ]


def _gz(rows: list[dict]) -> bytes:
    import gzip

    return gzip.compress(json.dumps(rows).encode())


def _catalog(tmp_path: Path) -> UpstoxLiveCatalog:
    with patch(_PATCH_GET) as mock_get:
        mock_get.return_value.content = _gz(_catalog_rows())
        mock_get.return_value.raise_for_status = lambda: None
        master = InstrumentMaster(url="u", cache_path=tmp_path / "c.json.gz")
        master.download()  # prime the on-disk cache inside the patch context
        return UpstoxLiveCatalog(master)


class TestLiveQuote:
    def test_pct_change_normal(self):
        q = LiveQuote(instrument_key="k", ltp=116.0, cp=100.0)
        assert q.pct_change == pytest.approx(16.0)

    def test_pct_change_negative(self):
        q = LiveQuote(instrument_key="k", ltp=90.0, cp=100.0)
        assert q.pct_change == pytest.approx(-10.0)

    def test_pct_change_undefined(self):
        assert LiveQuote(instrument_key="k", ltp=None, cp=100.0).pct_change is None
        assert LiveQuote(instrument_key="k", ltp=90.0, cp=None).pct_change is None
        assert LiveQuote(instrument_key="k", ltp=90.0, cp=0.0).pct_change is None


class TestUpstoxLiveCatalog:
    def test_asset_groups_mapped(self, tmp_path):
        catalog = _catalog(tmp_path)
        groups = {c.underlying_symbol: c.asset_group for c in catalog.contracts()}
        assert groups["RELIANCE"] is AssetGroup.NSE_FNO_STOCKS
        assert groups["TCS"] is AssetGroup.NSE_FNO_STOCKS
        assert groups["NIFTY"] is AssetGroup.INDICES
        assert groups["CRUDEOIL"] is AssetGroup.COMMODITIES
        assert groups["GOLD"] is AssetGroup.COMMODITIES

    def test_list_underlyings(self, tmp_path):
        catalog = _catalog(tmp_path)
        assert catalog.list_underlyings(AssetGroup.NSE_FNO_STOCKS) == ["RELIANCE", "TCS"]
        assert catalog.list_underlyings(AssetGroup.INDICES) == ["NIFTY"]
        assert catalog.list_underlyings(AssetGroup.COMMODITIES) == ["CRUDEOIL", "GOLD"]

    def test_expiries_sorted(self, tmp_path):
        catalog = _catalog(tmp_path)
        assert catalog.expiries("reliance") == [
            datetime.date(2026, 8, 26),
            datetime.date(2026, 10, 27),
        ]

    def test_chain_strike_sorted_ce_before_pe(self, tmp_path):
        catalog = _catalog(tmp_path)
        chain = catalog.chain("RELIANCE", datetime.date(2026, 10, 27))
        assert [(c.strike, c.option_type) for c in chain] == [
            (1200.0, "CE"),
            (1200.0, "PE"),
            (1300.0, "CE"),
        ]

    def test_chain_unknown_underlying_raises(self, tmp_path):
        catalog = _catalog(tmp_path)
        with pytest.raises(UnknownUnderlyingError):
            catalog.chain("WIPRO", datetime.date(2026, 10, 27))

    def test_by_instrument_key(self, tmp_path):
        catalog = _catalog(tmp_path)
        assert catalog.contract("NSE_FO|6").underlying_symbol == "NIFTY"
        assert catalog.contract("NSE_FO|999") is None

    def test_eligible_from_universe_intersects_stocks_only(self, tmp_path):
        catalog = _catalog(tmp_path)
        eligible = catalog.eligible_from_universe({"RELIANCE", "TCS", "NIFTY", "WIPRO", "CRUDEOIL"})
        assert eligible == {"RELIANCE", "TCS"}


class TestUniverseLoader:
    def test_load_symbols_uppercases(self, tmp_path):
        uni_dir = tmp_path / "universes"
        uni_dir.mkdir()
        (uni_dir / "nifty50.json").write_text(
            json.dumps({"name": "NIFTY 50", "symbols": ["reliance", "TCS"]}),
            encoding="utf-8",
        )
        assert universe.load_symbols("nifty50", base_dir=uni_dir) == ["RELIANCE", "TCS"]

    def test_missing_universe_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            universe.load_symbols("nifty50", base_dir=tmp_path)

    def test_list_universes(self, tmp_path):
        uni_dir = tmp_path / "universes"
        uni_dir.mkdir()
        (uni_dir / "nifty50.json").write_text("{}", encoding="utf-8")
        (uni_dir / "nifty200.json").write_text("{}", encoding="utf-8")
        assert universe.list_universes(base_dir=uni_dir) == ["nifty50", "nifty200"]
