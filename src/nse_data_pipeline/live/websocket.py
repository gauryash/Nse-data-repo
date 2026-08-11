"""WebSocket protocol for the live market monitor.

Client → server messages::

    {"op": "watch",   "id": "<owner-id>", "underlying_symbol": "NIFTY",
     "expiry": "2026-08-25"}
    {"op": "unwatch", "id": "<owner-id>"}
    {"op": "ping"}

Server → client messages::

    {"type": "status",   "connected": true, "subscribed": 5, "limit": 5000}
    {"type": "watched",  "id": ..., "chain": "NIFTY:2026-08-25", "keys": 226,
     "snapshot": {<instrument_key>: {ltp, cp, pct_change, timestamp}}}
    {"type": "unwatched", "id": ...}
    {"type": "ticks",    "ticks": [{instrument_key, ltp, cp, pct_change, timestamp}]}
    {"type": "error",    "message": "..."}

Ticks are batched (~150 ms) by the app's broadcast loop; the Upstox
token never leaves the server.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from nse_data_pipeline.application.live_market_hub import LiveMarketHub
from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.shared.exceptions import (
    SubscriptionLimitExceeded,
    UnknownUnderlyingError,
)

logger = get_logger(__name__)

router = APIRouter()


class ConnectionManager:
    """Tracks live WebSocket clients and fans out messages."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        logger.info("WS client connected (%d active)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.info("WS client disconnected (%d active)", len(self._clients))

    async def broadcast(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self._clients:
            if ws.client_state is not WebSocketState.CONNECTED:
                dead.append(ws)
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    hub: LiveMarketHub = ws.app.state.hub
    manager: ConnectionManager = ws.app.state.manager
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "status", **hub.status()})
        while True:
            raw = await ws.receive_json()
            op = raw.get("op")
            if op == "watch":
                await _handle_watch(ws, hub, raw)
            elif op == "unwatch":
                hub.unwatch(str(raw.get("id") or ""))
                await ws.send_json({"type": "unwatched", "id": raw.get("id")})
            elif op == "ping":
                await ws.send_json({"type": "pong"})
            else:
                await ws.send_json({"type": "error", "message": f"unknown op: {op}"})
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        logger.warning("WS error: %s", e)
        manager.disconnect(ws)


async def _handle_watch(ws: WebSocket, hub: LiveMarketHub, raw: dict) -> None:
    owner_id = str(raw.get("id") or uuid4())
    symbol = str(raw.get("underlying_symbol") or "").strip()
    try:
        expiry = date.fromisoformat(str(raw.get("expiry") or ""))
    except ValueError:
        await ws.send_json({"type": "error", "message": "expiry must be YYYY-MM-DD"})
        return
    try:
        chain = hub.watch_chain(owner_id, symbol, expiry)
    except UnknownUnderlyingError as e:
        await ws.send_json({"type": "error", "message": str(e)})
        return
    except SubscriptionLimitExceeded as e:
        await ws.send_json(
            {
                "type": "error",
                "message": str(e),
                "limit": e.limit,
                "current": e.current,
                "required": e.required,
            }
        )
        return
    keys = set(chain.instrument_keys)
    await ws.send_json(
        {
            "type": "watched",
            "id": owner_id,
            "chain": chain.key,
            "keys": len(keys),
            "snapshot": hub.snapshot(keys),
        }
    )
