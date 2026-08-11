"""
LiveMarketHub — a single Upstox Market Data Feed V3 connection for all watchers.

The hub is the deep module of the live-monitor backend.  It hides:

  - Upstox authentication (analytics token)
  - the WebSocket lifecycle (connect, reconnect, resubscribe)
  - reference-counted subscriptions across all option-chain cards
  - the LTPC subscription budget (5000 keys per connection)
  - the latest-quote store and % change calculation
  - thread → asyncio event bridging (via a drainable queue)

Threading: the official SDK streamer runs in its own thread; its callbacks
update the quote store under a lock and push events into a thread-safe
queue that the FastAPI layer drains on an asyncio loop.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime, timezone
from typing import Any

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.config.settings import settings
from nse_data_pipeline.domain.live_models import ChainDefinition, LiveQuote
from nse_data_pipeline.infrastructure.symbol_source.upstox_live_catalog import (
    UpstoxLiveCatalog,
)
from nse_data_pipeline.shared.exceptions import SubscriptionLimitExceeded

logger = get_logger(__name__)

STREAMER_MODE = "ltpc"
_RECONNECT_INTERVAL = 2
_RECONNECT_RETRIES = 10


def build_upstox_streamer(token: str, mode: str = STREAMER_MODE) -> Any:
    """Construct the official SDK ``MarketDataStreamerV3`` (lazy import)."""
    import upstox_client  # type: ignore[import-untyped]

    configuration = upstox_client.Configuration()
    configuration.access_token = token
    return upstox_client.MarketDataStreamerV3(
        upstox_client.ApiClient(configuration),
        instrumentKeys=[],
        mode=mode,
    )


class LiveMarketHub:
    """Central connection manager and quote store for live option chains."""

    def __init__(
        self,
        catalog: UpstoxLiveCatalog,
        token: str,
        streamer: Any | None = None,
        token_index: dict[str, str] | None = None,
        max_keys: int = 0,
    ) -> None:
        self._catalog = catalog
        self._token = token
        self._max_keys = max_keys or settings.upstox_live_max_keys
        self._streamer = streamer
        self._token_index = (
            token_index if token_index is not None else catalog.token_to_instrument_key()
        )
        self._lock = threading.RLock()
        self._refcounts: dict[str, int] = {}
        self._chains: dict[str, ChainDefinition] = {}
        self._quotes: dict[str, LiveQuote] = {}
        self._events: queue.Queue[LiveQuote] = queue.Queue()
        self._connected = False
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Authorize and connect the feed, wiring all SDK events."""
        if self._started:
            return
        self._started = True
        if self._streamer is None:
            self._streamer = build_upstox_streamer(self._token)
        self._streamer.on("open", self._on_open)
        self._streamer.on("close", self._on_close)
        self._streamer.on("error", self._on_error)
        self._streamer.on("message", self._on_message)
        self._streamer.auto_reconnect(True, _RECONNECT_INTERVAL, _RECONNECT_RETRIES)  # type: ignore[attr-defined]
        self._streamer.connect()  # type: ignore[attr-defined]
        logger.info("LiveMarketHub started (limit=%d LTPC keys)", self._max_keys)

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._connected = False
        if self._streamer is not None:
            try:
                self._streamer.disconnect()  # type: ignore[attr-defined]
            except Exception as e:
                logger.warning("Streamer disconnect failed: %s", e)
        logger.info("LiveMarketHub stopped")

    # ------------------------------------------------------------------
    # Watch API
    # ------------------------------------------------------------------

    def watch_chain(self, owner_id: str, underlying_symbol: str, expiry: Any) -> ChainDefinition:
        """Start watching an option chain, subscribing any new keys.

        If *owner_id* already has a chain, it is atomically replaced
        (old keys released, new keys subscribed).

        Raises:
            SubscriptionLimitExceeded: If the projected subscription set
                exceeds the connection budget.
        """
        contracts = self._catalog.chain(underlying_symbol, expiry)
        keys = tuple(c.instrument_key for c in contracts)
        with self._lock:
            if self._projected_size(owner_id, keys) > self._max_keys:
                raise SubscriptionLimitExceeded(
                    f"Can't subscribe to {underlying_symbol} @ {expiry.isoformat()}: "
                    f"requires {len(set(keys) - set(self._refcounts))} new keys, "
                    f"budget is {self._max_keys}",
                    required=len(set(keys) - set(self._refcounts)),
                    current=len(self._refcounts),
                    limit=self._max_keys,
                )
            subscribe, unsubscribe = self._apply_watch(owner_id, underlying_symbol, expiry, keys)
        if unsubscribe:
            self._safe_unsubscribe(unsubscribe)
        if subscribe:
            self._safe_subscribe(subscribe)
        return self._chains[owner_id]

    def unwatch(self, owner_id: str) -> None:
        """Stop watching *owner_id*'s chain, unsubscribing orphaned keys."""
        with self._lock:
            chain = self._chains.pop(owner_id, None)
            if chain is None:
                return
            zeroed: list[str] = []
            for key in chain.instrument_keys:
                self._refcounts[key] -= 1
                if self._refcounts[key] == 0:
                    del self._refcounts[key]
                    zeroed.append(key)
        if zeroed:
            self._safe_unsubscribe(zeroed)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def snapshot(self, instrument_keys: set[str]) -> dict[str, dict]:
        """Latest quotes for the requested keys (tick dicts)."""
        with self._lock:
            return {
                key: self._quotes[key].to_tick() for key in instrument_keys if key in self._quotes
            }

    def drain_events(self) -> list[LiveQuote]:
        """Non-blocking drain of queued quote updates (asyncio bridge)."""
        out: list[LiveQuote] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def status(self) -> dict:
        with self._lock:
            return {
                "connected": self._connected,
                "subscribed": len(self._refcounts),
                "limit": self._max_keys,
                "chains": {owner: c.key for owner, c in self._chains.items()},
            }

    # ------------------------------------------------------------------
    # SDK callbacks (streamer thread)
    # ------------------------------------------------------------------

    def _on_open(self, *_args: Any) -> None:
        self._connected = True
        with self._lock:
            active = list(self._refcounts.keys())
        if active:
            self._safe_subscribe(active)
        logger.info("Upstox feed connected; %d keys active", len(active))

    def _on_close(self, *_args: Any) -> None:
        self._connected = False
        logger.info("Upstox feed closed")

    def _on_error(self, error: Any, *_args: Any) -> None:
        self._connected = False
        logger.warning("Upstox feed error: %s", error)

    def _on_message(self, payload: Any, *_args: Any) -> None:
        if not isinstance(payload, dict):
            return
        feeds = payload.get("feeds") or {}
        if not feeds:
            return
        current_ts = payload.get("currentTs")
        ts = self._ts(current_ts)
        for token, feed in feeds.items():
            if not isinstance(feed, dict):
                continue
            ltpc = feed.get("ltpc") or {}
            key = self._token_index.get(str(token))
            if key is None:
                continue
            quote = LiveQuote(
                instrument_key=key,
                ltp=_opt_float(ltpc.get("ltp")),
                cp=_opt_float(ltpc.get("cp")),
                volume=_opt_int(ltpc.get("ltq")),
                timestamp=ts,
            )
            with self._lock:
                self._quotes[key] = quote
            self._events.put(quote)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _projected_size(self, owner_id: str, keys: tuple[str, ...]) -> int:
        """Size of the refcount set after (re)watching *owner_id* with *keys*."""
        base = set(self._refcounts)
        existing = self._chains.get(owner_id)
        if existing is not None:
            released = {k for k in existing.instrument_keys if self._refcounts.get(k, 1) == 1}
            base -= released
        return len(base | set(keys))

    def _apply_watch(
        self,
        owner_id: str,
        underlying_symbol: str,
        expiry: Any,
        keys: tuple[str, ...],
    ) -> tuple[list[str], list[str]]:
        """Apply a watch under the lock; returns (subscribe_now, unsubscribe_now)."""
        unsubscribe: list[str] = []
        existing = self._chains.pop(owner_id, None)
        if existing is not None:
            for key in existing.instrument_keys:
                self._refcounts[key] -= 1
                if self._refcounts[key] == 0:
                    del self._refcounts[key]
                    unsubscribe.append(key)
        subscribe = [key for key in keys if key not in self._refcounts]
        for key in keys:
            self._refcounts[key] = self._refcounts.get(key, 0) + 1
        self._chains[owner_id] = ChainDefinition(owner_id, underlying_symbol, expiry, keys)
        return subscribe, unsubscribe

    def _safe_subscribe(self, keys: list[str]) -> None:
        if not self._streamer or not self._connected:
            logger.info("Feed not connected; %d keys queued", len(keys))
            return
        try:
            self._streamer.subscribe(keys, STREAMER_MODE)  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning("subscribe failed (%d keys): %s", len(keys), e)

    def _safe_unsubscribe(self, keys: list[str]) -> None:
        if not self._streamer or not self._connected:
            return
        try:
            self._streamer.unsubscribe(keys)  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning("unsubscribe failed (%d keys): %s", len(keys), e)

    @staticmethod
    def _ts(epoch_ms: Any) -> datetime | None:
        if epoch_ms is None:
            return None
        try:
            return datetime.fromtimestamp(float(epoch_ms) / 1000.0, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
