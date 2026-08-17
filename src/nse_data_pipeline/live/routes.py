"""REST endpoints for the live market monitor (catalog + status)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from nse_data_pipeline.domain.live_models import AssetGroup
from nse_data_pipeline.infrastructure.symbol_source import universe as universe_mod
from nse_data_pipeline.infrastructure.symbol_source.upstox_live_catalog import (
    UpstoxLiveCatalog,
)
from nse_data_pipeline.shared.exceptions import UnknownUnderlyingError

router = APIRouter(prefix="/api")


def _catalog(request: Request) -> UpstoxLiveCatalog:
    return request.app.state.catalog


def _hub(request: Request):
    return request.app.state.hub


@router.get("/status")
async def status(request: Request) -> dict:
    return _hub(request).status()


@router.get("/universes")
async def universes(request: Request) -> list[dict]:
    """Static universe lists with their live F&O eligibility counts."""
    catalog = _catalog(request)
    out: list[dict] = []
    for name in universe_mod.list_universes():
        symbols = set(universe_mod.load_symbols(name))
        eligible = catalog.eligible_from_universe(symbols)
        out.append(
            {
                "name": name,
                "total": len(symbols),
                "eligible": len(eligible),
                "symbols": sorted(eligible),
            }
        )
    return out


@router.get("/underlyings/{group}")
async def underlyings(request: Request, group: AssetGroup) -> list[dict]:
    """Underlyings in a group with display name + expiry count."""
    catalog = _catalog(request)
    return [
        {
            "symbol": symbol,
            "name": name,
            "expiries": len(catalog.expiries(symbol)),
        }
        for symbol, name in catalog.underlying_details(group)
    ]


@router.get("/expiries/{underlying_symbol}")
async def expiries(underlying_symbol: str, request: Request) -> list[str]:
    catalog = _catalog(request)
    try:
        return [d.isoformat() for d in catalog.expiries(underlying_symbol)]
    except UnknownUnderlyingError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/chain/{underlying_symbol}")
async def chain(
    underlying_symbol: str,
    request: Request,
    expiry: Annotated[date, Query(description="Expiry date (YYYY-MM-DD)")],
) -> dict:
    """Option chain contracts for one underlying + expiry (strike-sorted)."""
    catalog = _catalog(request)
    try:
        contracts = catalog.chain(underlying_symbol, expiry)
    except UnknownUnderlyingError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "underlying_symbol": underlying_symbol,
        "expiry": expiry.isoformat(),
        "contracts": [c.to_dict() for c in contracts],
    }
