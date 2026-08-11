"""FastAPI application for the live market monitor.

Run with ``nse-data-pipeline live`` or directly via uvicorn::

    uvicorn nse_data_pipeline.live.app:app --host 127.0.0.1 --port 8000

The app owns the singleton :class:`LiveMarketHub` (started in the lifespan)
and exposes:

  - REST catalog endpoints under ``/api`` (universes, underlyings, chains)
  - a WebSocket endpoint at ``/ws`` for the browser monitor
  - a background broadcaster that batches hub quote events (~150 ms)
    to all connected WebSocket clients
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nse_data_pipeline.application.live_market_hub import LiveMarketHub
from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.config.settings import settings
from nse_data_pipeline.infrastructure.symbol_source.upstox_live_catalog import (
    UpstoxLiveCatalog,
)
from nse_data_pipeline.live.routes import router as routes_router
from nse_data_pipeline.live.websocket import ConnectionManager
from nse_data_pipeline.live.websocket import router as ws_router

logger = get_logger(__name__)


def create_app(
    hub: LiveMarketHub | None = None,
    catalog: UpstoxLiveCatalog | None = None,
    *,
    broadcast_interval: float = 0.15,
) -> FastAPI:
    """Build the FastAPI app; injectable hub/catalog for tests."""
    catalog = catalog or UpstoxLiveCatalog()
    hub = hub or LiveMarketHub(catalog, settings.upstox_analytics_token)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.start()
        broadcaster = asyncio.create_task(_broadcast_loop(app, broadcast_interval))
        try:
            yield
        finally:
            broadcaster.cancel()
            hub.stop()

    app = FastAPI(title="NSE Data Pipeline — Live Market Monitor", lifespan=lifespan)
    app.state.hub = hub
    app.state.catalog = catalog
    app.state.manager = ConnectionManager()
    app.include_router(routes_router)
    app.include_router(ws_router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True}

    return app


async def _broadcast_loop(app: FastAPI, interval: float) -> None:
    """Drain hub quote events and fan them out to WS clients in batches."""
    hub: LiveMarketHub = app.state.hub
    manager: ConnectionManager = app.state.manager
    while True:
        await asyncio.sleep(interval)
        events = hub.drain_events()
        if not events:
            continue
        ticks = [quote.to_tick() for quote in events]
        await manager.broadcast({"type": "ticks", "ticks": ticks})


def run_server(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Launch uvicorn for the live monitor app."""
    import uvicorn

    logger.info("Starting live monitor on http://%s:%d (reload=%s)", host, port, reload)
    uvicorn.run(
        "nse_data_pipeline.live.app:app",
        host=host,
        port=port,
        reload=reload,
    )


app = create_app()
