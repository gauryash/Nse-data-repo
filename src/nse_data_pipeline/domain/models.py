"""
Domain models for the data pipeline.

Contains value objects and entities that represent the core concepts
of the financial data domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import ClassVar

import pandas as pd

# ======================================================================
# Enums
#
# StorageFormat, CandleInterval, and ProviderName are intentionally
# duplicated from config/settings.py.  Domain enums carry extra methods
# (from_str, from_instrument_type) not needed by the config layer.
# ======================================================================


class InstrumentType(str, Enum):
    """F&O instrument types supported by Upstox."""

    OPTSTK = "OPTSTK"  # Stock options
    OPTIDX = "OPTIDX"  # Index options
    FUTSTK = "FUTSTK"  # Stock futures
    FUTIDX = "FUTIDX"  # Index futures

    @classmethod
    def from_str(cls, value: str) -> list[InstrumentType]:
        """Parse comma/space-separated instrument types.

        Example: ``"OPTSTK,OPTIDX"`` → ``[InstrumentType.OPTSTK, InstrumentType.OPTIDX]``
        """
        return [cls(t.strip()) for t in value.replace(",", " ").split() if t.strip()]


class AssetType(str, Enum):
    """Underlying asset class for F&O contracts."""

    STOCK = "STOCK"
    INDEX = "INDEX"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_instrument_type(cls, instrument_type: str) -> AssetType:
        if instrument_type in ("OPTSTK", "FUTSTK"):
            return cls.STOCK
        if instrument_type in ("OPTIDX", "FUTIDX"):
            return cls.INDEX
        return cls.UNKNOWN


class OptionType(str, Enum):
    """Call/Put/Futures classification."""

    CE = "CE"
    PE = "PE"
    FF = "FF"  # Futures


class StorageFormat(str, Enum):
    PARQUET = "parquet"
    CSV = "csv"


class CandleInterval(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    MINUTE_1 = "1minute"
    MINUTE_30 = "30minute"


class ProviderName(str, Enum):
    NSE = "nse"
    UPSTOX = "upstox"
    UPSTOX_OPTIONS = "upstox_options"


# ======================================================================
# Value Objects
# ======================================================================


@dataclass(frozen=True)
class FetchRange:
    """A date range for fetching data."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) < start ({self.start})")

    @classmethod
    def from_strings(
        cls,
        start_str: str,
        end_str: str | None = None,
        fmt: str = "%d-%m-%Y",
    ) -> FetchRange:
        """Create from date strings.

        If *end_str* is ``None``, uses today's date.
        """
        start = datetime.strptime(start_str, fmt)
        if end_str:
            end = datetime.strptime(end_str, fmt)
        else:
            from datetime import datetime as dt_now

            end = dt_now.now()
        return cls(start=start, end=end)

    def contains(self, other: FetchRange) -> bool:
        """Check if this range fully contains *other*."""
        return self.start <= other.start and self.end >= other.end

    def split_chunks(self, chunk_days: int) -> list[FetchRange]:
        """Split into *chunk_days*-sized sub-ranges."""
        from datetime import timedelta

        chunks: list[FetchRange] = []
        cur = self.start
        while cur < self.end:
            chunk_end = min(cur + timedelta(days=chunk_days - 1), self.end)
            chunks.append(FetchRange(start=cur, end=chunk_end))
            cur = chunk_end + timedelta(days=1)
        return chunks


# ======================================================================
# Entities
# ======================================================================


@dataclass
class Symbol:
    """Represents a trading symbol / tradingsymbol."""

    name: str
    provider: ProviderName
    instrument_key: str | None = None
    isin: str | None = None
    underlying_name: str | None = None


@dataclass
class OptionContract:
    """Value object representing a single F&O contract.

    Composed from the Upstox instrument master CSV row.
    """

    instrument_key: str
    tradingsymbol: str
    underlying_name: str  # company name for OPTSTK, index name for OPTIDX
    underlying_type: str  # "STOCK" or "INDEX"
    instrument_type: str  # OPTSTK, OPTIDX, FUTSTK, FUTIDX
    option_type: str  # CE, PE, or FF for futures
    expiry: date | None  # contract expiry date
    strike: float | None  # strike price (None for futures)
    lot_size: int
    tick_size: float

    _CONTRACT_COLUMNS: ClassVar[list[str]] = [
        "instrument_key",
        "tradingsymbol",
        "name",
        "underlying_type",
        "instrument_type",
        "option_type",
        "expiry",
        "strike",
        "lot_size",
        "tick_size",
    ]

    @classmethod
    def from_dataframe_row(cls, row: pd.Series) -> OptionContract:
        """Build from a row of the Upstox instrument master CSV."""
        return cls(
            instrument_key=row["instrument_key"],
            tradingsymbol=row["tradingsymbol"],
            underlying_name=row.get("name", ""),
            underlying_type=AssetType.from_instrument_type(row.get("instrument_type", "")).value,
            instrument_type=row.get("instrument_type", ""),
            option_type=row.get("option_type", ""),
            expiry=row["expiry"] if pd.notna(row.get("expiry")) else None,
            strike=float(row["strike"]) if pd.notna(row.get("strike")) else None,
            lot_size=int(row["lot_size"]) if pd.notna(row.get("lot_size")) else 0,
            tick_size=float(row["tick_size"]) if pd.notna(row.get("tick_size")) else 0.05,
        )

    def to_dict(self) -> dict:
        """Serialize to dict for DataFrame construction / checkpoint storage."""
        return {
            "instrument_key": self.instrument_key,
            "tradingsymbol": self.tradingsymbol,
            "underlying_name": self.underlying_name,
            "underlying_type": self.underlying_type,
            "instrument_type": self.instrument_type,
            "option_type": self.option_type,
            "expiry": str(self.expiry) if self.expiry else None,
            "strike": self.strike,
            "lot_size": self.lot_size,
            "tick_size": self.tick_size,
        }
