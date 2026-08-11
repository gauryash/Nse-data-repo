"""API + WebSocket tests for the live monitor (FastAPI TestClient)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from nse_data_pipeline.application.live_market_hub import LiveMarketHub
from nse_data_pipeline.infrastructure.symbol_source.upstox_instruments import InstrumentMaster
from nse_data_pipeline.infrastructure.symbol_source.upstox_live_catalog import UpstoxLiveCatalog
from nse_data_pipeline.live.app import create_app
from tests.unit.test_live_market_hub import FakeStreamer

_PATCH_GET = "nse_data_pipeline.infrastructure.symbol_source.upstox_instruments.requests.get"
_OCT = datetime.date(2026, 10, 27)


def _ms(day: datetime.date) -> int:
    dt = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)


def _rows() -> list[dict]:
    def _opt(key, sym, itype, strike, seg, utype, token=None, lot=100):
        return {
            "instrument_key": key,
            "exchange_token": token or key.split("|")[-1],
            "trading_symbol": f"{sym} {strike} {itype} 27 OCT 26",
            "name": sym,
            "asset_symbol": sym,
            "underlying_symbol": sym,
            "underlying_type": utype,
            "instrument_type": itype,
            "strike_price": strike,
            "expiry": _ms(_OCT),
            "lot_size": lot,
            "tick_size": 0.05,
            "segment": seg,
        }

    return [
        _opt("NSE_FO|111", "RELIANCE", "CE", 1200.0, "NSE_FO", "EQUITY"),
        _opt("NSE_FO|222", "RELIANCE", "PE", 1200.0, "NSE_FO", "EQUITY"),
        _opt("NSE_FO|333", "NIFTY", "CE", 23600.0, "NSE_FO", "INDEX", lot=0),
        _opt("NSE_FO|444", "NIFTY", "PE", 23600.0, "NSE_FO", "INDEX"),
        _opt("MCX_FO|555", "CRUDEOIL", "CE", 6500.0, "MCX_FO", "COM"),
    ]


def _gz(rows: list[dict]) -> bytes:
    import gzip

    return gzip.compress(json.dumps(rows).encode())


@pytest.fixture()
def client(tmp_path: Path):
    with patch(_PATCH_GET) as mock_get:
        mock_get.return_value.content = _gz(_rows())
        mock_get.return_value.raise_for_status = lambda: None
        master = InstrumentMaster(url="u", cache_path=tmp_path / "c.json.gz")
        master.download()
        catalog = UpstoxLiveCatalog(master)
    streamer = FakeStreamer()
    hub = LiveMarketHub(catalog, token="t", streamer=streamer, max_keys=100)
    app = create_app(hub=hub, catalog=catalog, broadcast_interval=0.05)
    with TestClient(app) as test_client:
        test_client.app.state._streamer = streamer  # type: ignore[attr-defined]
        yield test_client, streamer


class TestREST:
    def test_health(self, client):
        c, _ = client
        assert c.get("/api/health").json() == {"ok": True}

    def test_status(self, client):
        c, _ = client
        body = c.get("/api/status").json()
        assert body["connected"] is True
        assert body["limit"] == 100
        assert body["subscribed"] == 0

    def test_underlyings_groups(self, client):
        c, _ = client
        stocks = c.get("/api/underlyings/stocks").json()
        indices = c.get("/api/underlyings/indices").json()
        comms = c.get("/api/underlyings/commodities").json()
        assert [u["symbol"] for u in stocks] == ["RELIANCE"]
        assert indices[0]["symbol"] == "NIFTY"
        assert [u["symbol"] for u in comms] == ["CRUDEOIL"]

    def test_chain_endpoint(self, client):
        c, _ = client
        body = c.get("/api/chain/RELIANCE", params={"expiry": _OCT.isoformat()}).json()
        assert len(body["contracts"]) == 2
        assert body["contracts"][0]["option_type"] == "CE"

    def test_chain_unknown_underlying_404(self, client):
        c, _ = client
        r = c.get("/api/chain/WIPRO", params={"expiry": _OCT.isoformat()})
        assert r.status_code == 404

    def test_expiries_endpoint(self, client):
        c, _ = client
        assert c.get("/api/expiries/reliance").json() == [_OCT.isoformat()]

    def test_universes_endpoint(self, client):
        c, _ = client
        body = c.get("/api/universes").json()
        assert any(u["name"] == "nifty50" for u in body)


class TestWebSocket:
    def test_watch_receives_watched_and_ticks(self, client):
        c, streamer = client
        with c.websocket_connect("/ws") as ws:
            status = ws.receive_json()
            assert status["type"] == "status"

            ws.send_json(
                {
                    "op": "watch",
                    "id": "card-1",
                    "underlying_symbol": "RELIANCE",
                    "expiry": _OCT.isoformat(),
                }
            )
            watched = ws.receive_json()
            assert watched["type"] == "watched"
            assert watched["chain"] == f"RELIANCE:{_OCT.isoformat()}"
            assert watched["keys"] == 2

            # Push a live tick from the (fake) streamer thread.
            streamer.push_message(
                {
                    "type": "market_packet",
                    "currentTs": _ms(_OCT) + 5000,
                    "feeds": {"111": {"ltpc": {"ltp": 152.4, "cp": 131.2}}},
                }
            )
            ticks = ws.receive_json()
            assert ticks["type"] == "ticks"
            assert ticks["ticks"][0]["instrument_key"] == "NSE_FO|111"
            assert ticks["ticks"][0]["pct_change"] > 0

    def test_watch_sends_error_for_unknown_underlying(self, client):
        c, _ = client
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()  # status
            ws.send_json(
                {
                    "op": "watch",
                    "id": "card-x",
                    "underlying_symbol": "WIPRO",
                    "expiry": _OCT.isoformat(),
                }
            )
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_unwatch(self, client):
        c, _ = client
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json(
                {
                    "op": "watch",
                    "id": "card-1",
                    "underlying_symbol": "RELIANCE",
                    "expiry": _OCT.isoformat(),
                }
            )
            assert ws.receive_json()["type"] == "watched"
            ws.send_json({"op": "unwatch", "id": "card-1"})
            assert ws.receive_json()["type"] == "unwatched"
            assert c.get("/api/status").json()["subscribed"] == 0

    def test_ping_pong(self, client):
        c, _ = client
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"op": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_bad_expiry_rejected(self, client):
        c, _ = client
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json(
                {
                    "op": "watch",
                    "id": "card-1",
                    "underlying_symbol": "RELIANCE",
                    "expiry": "not-a-date",
                }
            )
            msg = ws.receive_json()
            assert msg["type"] == "error"
