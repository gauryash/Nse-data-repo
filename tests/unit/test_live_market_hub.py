"""Unit tests for LiveMarketHub using a fake SDK streamer."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nse_data_pipeline.application.live_market_hub import LiveMarketHub
from nse_data_pipeline.infrastructure.symbol_source.upstox_instruments import InstrumentMaster
from nse_data_pipeline.infrastructure.symbol_source.upstox_live_catalog import UpstoxLiveCatalog
from nse_data_pipeline.shared.exceptions import SubscriptionLimitExceeded

_PATCH_GET = "nse_data_pipeline.infrastructure.symbol_source.upstox_instruments.requests.get"

_OCT = datetime.date(2026, 10, 27)


class FakeStreamer:
    """Records subscribe/unsubscribe calls; can emit SDK-style events."""

    def __init__(self) -> None:
        self.listeners: dict[str, list] = {}
        self.subscribed: list[list[str]] = []
        self.unsubscribed: list[list[str]] = []
        self.reconnect_args = None
        self.connected_calls = 0
        self.disconnect_calls = 0
        self.open = False

    def on(self, event: str, listener) -> None:
        self.listeners.setdefault(event, []).append(listener)

    def emit(self, event: str, *args) -> None:
        for listener in self.listeners.get(event, []):
            listener(*args)

    def auto_reconnect(self, enable, interval, retry_count) -> None:
        self.reconnect_args = (enable, interval, retry_count)

    def connect(self) -> None:
        self.connected_calls += 1
        self.open = True
        self.emit("open")

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.open = False
        self.emit("close", 1000, "bye")

    def subscribe(self, keys, _mode) -> None:
        assert self.open, "subscribe called while socket closed"
        self.subscribed.append(list(keys))

    def unsubscribe(self, keys) -> None:
        assert self.open, "unsubscribe called while socket closed"
        self.unsubscribed.append(list(keys))

    def push_message(self, payload: dict) -> None:
        self.emit("message", payload)


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
        _opt("NSE_FO|333", "NIFTY", "CE", 23600.0, "NSE_FO", "INDEX", lot=50),
        _opt("NSE_FO|444", "NIFTY", "PE", 23600.0, "NSE_FO", "INDEX", lot=50),
    ]


def _gz(rows: list[dict]) -> bytes:
    import gzip

    return gzip.compress(json.dumps(rows).encode())


@pytest.fixture()
def hub(tmp_path: Path) -> tuple[LiveMarketHub, FakeStreamer]:
    with patch(_PATCH_GET) as mock_get:
        mock_get.return_value.content = _gz(_rows())
        mock_get.return_value.raise_for_status = lambda: None
        master = InstrumentMaster(url="u", cache_path=tmp_path / "c.json.gz")
        master.download()
        catalog = UpstoxLiveCatalog(master)
    streamer = FakeStreamer()
    hub = LiveMarketHub(catalog, token="t", streamer=streamer, max_keys=3)
    hub.start()
    return hub, streamer


class TestWatchUnwatch:
    def test_watch_subscribes_new_keys(self, hub):
        h, streamer = hub
        chain = h.watch_chain("c1", "RELIANCE", _OCT)
        assert len(chain.instrument_keys) == 2
        assert streamer.subscribed == [["NSE_FO|111", "NSE_FO|222"]]
        assert h.status()["subscribed"] == 2

    def test_shared_chain_does_not_resubscribe(self, hub):
        h, streamer = hub
        h.watch_chain("c1", "RELIANCE", _OCT)
        h.watch_chain("c2", "RELIANCE", _OCT)
        assert len(streamer.subscribed) == 1  # second owner reuses keys
        assert h.status()["subscribed"] == 2

    def test_unwatch_releases_orphaned_keys_only(self, hub):
        h, streamer = hub
        h.watch_chain("c1", "RELIANCE", _OCT)
        h.watch_chain("c2", "RELIANCE", _OCT)
        h.unwatch("c1")
        assert streamer.unsubscribed == []  # still shared by c2
        h.unwatch("c2")
        assert streamer.unsubscribed == [["NSE_FO|111", "NSE_FO|222"]]
        assert h.status()["subscribed"] == 0

    def test_replace_owner_chain(self, hub):
        h, streamer = hub
        h.watch_chain("c1", "RELIANCE", _OCT)
        h.watch_chain("c1", "NIFTY", _OCT)
        assert streamer.unsubscribed == [["NSE_FO|111", "NSE_FO|222"]]
        assert streamer.subscribed[-1] == ["NSE_FO|333", "NSE_FO|444"]
        assert h.status()["subscribed"] == 2

    def test_budget_exceeded_raises(self, hub):
        h, _ = hub
        h.watch_chain("c1", "RELIANCE", _OCT)  # 2 keys
        with pytest.raises(SubscriptionLimitExceeded) as exc:
            h.watch_chain("c2", "NIFTY", _OCT)  # would make 4 > 3
        assert exc.value.limit == 3
        assert h.status()["subscribed"] == 2

    def test_unwatch_unknown_owner_is_noop(self, hub):
        h, _ = hub
        h.unwatch("ghost")
        assert h.status()["subscribed"] == 0

    def test_watch_before_connect_subscribes_on_open(self, tmp_path):
        with patch(_PATCH_GET) as mock_get:
            mock_get.return_value.content = _gz(_rows())
            mock_get.return_value.raise_for_status = lambda: None
            master = InstrumentMaster(url="u", cache_path=tmp_path / "c.json.gz")
            master.download()
            catalog = UpstoxLiveCatalog(master)
        streamer = FakeStreamer()
        h = LiveMarketHub(catalog, token="t", streamer=streamer, max_keys=3)
        h.watch_chain("c1", "RELIANCE", _OCT)  # before start: no subscribe call
        assert streamer.subscribed == []
        h.start()
        assert streamer.subscribed == [["NSE_FO|111", "NSE_FO|222"]]


class TestMessageHandling:
    def test_message_updates_quote_store(self, hub):
        h, streamer = hub
        h.watch_chain("c1", "RELIANCE", _OCT)
        streamer.push_message(
            {
                "type": "market_packet",
                "currentTs": _ms(datetime.date(2026, 8, 11)) + 1000,
                "feeds": {"111": {"ltpc": {"ltp": 152.4, "ltq": 10, "cp": 131.2}}},
            }
        )
        events = h.drain_events()
        assert len(events) == 1
        assert events[0].instrument_key == "NSE_FO|111"
        assert events[0].ltp == 152.4
        assert events[0].pct_change == pytest.approx(16.1585, abs=1e-4)
        snap = h.snapshot({"NSE_FO|111"})
        assert snap["NSE_FO|111"]["ltp"] == 152.4

    def test_unknown_token_ignored(self, hub):
        h, streamer = hub
        streamer.push_message({"feeds": {"99999": {"ltpc": {"ltp": 1.0}}}})
        assert h.drain_events() == []

    def test_snapshot_missing_keys_omitted(self, hub):
        h, _ = hub
        assert h.snapshot({"NSE_FO|111"}) == {}

    def test_reconnect_resubscribes_active_keys(self, hub):
        h, streamer = hub
        h.watch_chain("c1", "RELIANCE", _OCT)
        streamer.emit("close", 1006, "gone")
        streamer.emit("open")  # simulated reconnect
        assert streamer.subscribed[-1] == ["NSE_FO|111", "NSE_FO|222"]
        assert h.status()["connected"] is True


class TestLifecycle:
    def test_start_is_idempotent(self, hub):
        h, streamer = hub
        h.start()
        assert streamer.connected_calls == 1

    def test_stop_disconnects(self, hub):
        h, streamer = hub
        h.stop()
        assert streamer.disconnect_calls == 1
        assert h.status()["connected"] is False

    def test_auto_reconnect_configured(self, hub):
        _, streamer = hub
        assert streamer.reconnect_args == (True, 2, 10)
