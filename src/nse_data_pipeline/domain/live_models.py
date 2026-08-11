"""
Domain models for the live-market layer.

Represents the objects the live monitor deals with: option contracts from
the Upstox BOD catalog, chain definitions (a watched underlying + expiry),
and latest quotes streamed from Upstox Market Data Feed V3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class AssetGroup(str, Enum):
    """UI-facing groups of underlyings with option chains."""

    INDICES = "indices"
    NSE_FNO_STOCKS = "stocks"
    COMMODITIES = "commodities"


@dataclass(frozen=True)
class LiveOptionContract:
    """A single CE/PE contract as exposed by the live catalog."""

    instrument_key: str
    tradingsymbol: str
    underlying_symbol: str
    underlying_name: str
    underlying_type: str  # EQUITY | INDEX | COM
    option_type: str  # CE | PE
    expiry: date | None
    strike: float | None
    lot_size: int
    tick_size: float
    asset_group: AssetGroup

    @property
    def is_call(self) -> bool:
        return self.option_type == "CE"

    def to_dict(self) -> dict:
        return {
            "instrument_key": self.instrument_key,
            "tradingsymbol": self.tradingsymbol,
            "underlying_symbol": self.underlying_symbol,
            "underlying_name": self.underlying_name,
            "underlying_type": self.underlying_type,
            "option_type": self.option_type,
            "expiry": self.expiry.isoformat() if self.expiry else None,
            "strike": self.strike,
            "lot_size": self.lot_size,
            "tick_size": self.tick_size,
        }


@dataclass(frozen=True)
class ChainDefinition:
    """A watched option chain (underlying + expiry) owned by a client."""

    owner_id: str
    underlying_symbol: str
    expiry: date
    instrument_keys: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.underlying_symbol}:{self.expiry.isoformat()}"


@dataclass
class LiveQuote:
    """Latest quote for one instrument (LTPC mode fields)."""

    instrument_key: str
    ltp: float | None = None
    cp: float | None = None
    volume: int | None = None
    timestamp: datetime | None = None

    @property
    def pct_change(self) -> float | None:
        """Percentage change vs previous close; ``None`` when incalculable."""
        if self.ltp is None or self.cp is None or self.cp == 0:
            return None
        return (self.ltp - self.cp) / self.cp * 100.0

    def to_tick(self) -> dict:
        return {
            "instrument_key": self.instrument_key,
            "ltp": self.ltp,
            "cp": self.cp,
            "pct_change": self.pct_change,
            "timestamp": (int(self.timestamp.timestamp() * 1000) if self.timestamp else None),
        }
