"""
Live option-chain catalog built from the Upstox BOD instrument master.

The catalog is built once from the instrument master JSON and provides
fast lookups for the live monitor:

  - ``underlying -> contracts``  (per asset group)
  - ``underlying -> expiries``
  - ``instrument_key -> contract``

Asset groups:
  - **Indices** — index options (``NSE_FO`` + ``underlying_type=INDEX``),
    e.g. NIFTY, BANKNIFTY, FINNIFTY.
  - **NSE F&O stocks** — equity options (``NSE_FO`` + ``EQUITY``), keyed
    by the short ticker (``underlying_symbol``).
  - **Commodities** — MCX options (``MCX_FO`` + ``COM``) built locally
    from the catalog, since Upstox's option-chain REST endpoint does not
    cover MCX.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.domain.live_models import AssetGroup, LiveOptionContract
from nse_data_pipeline.infrastructure.symbol_source.upstox_instruments import (
    InstrumentMaster,
)
from nse_data_pipeline.shared.exceptions import UnknownUnderlyingError

logger = get_logger(__name__)


class UpstoxLiveCatalog:
    """Indexes the instrument master for live option-chain lookups."""

    def __init__(self, master: InstrumentMaster | None = None) -> None:
        self._master = master or InstrumentMaster()
        self._contracts: list[LiveOptionContract] | None = None
        self._by_key: dict[str, LiveOptionContract] | None = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def contracts(self) -> list[LiveOptionContract]:
        """All CE/PE contracts in the master (NSE F&O + MCX)."""
        if self._contracts is not None:
            return self._contracts
        df = self._master.download()
        options = df[df["option_type"].isin(("CE", "PE"))]
        contracts = [self._to_contract(row) for _, row in options.iterrows()]
        self._contracts = contracts
        logger.info("Live catalog built: %d option contracts", len(contracts))
        return contracts

    def by_instrument_key(self) -> dict[str, LiveOptionContract]:
        if self._by_key is None:
            self._by_key = {c.instrument_key: c for c in self.contracts()}
        return self._by_key

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def list_underlyings(self, group: AssetGroup) -> list[str]:
        """Sorted unique underlying symbols with options in *group*."""
        symbols = {c.underlying_symbol for c in self.contracts() if c.asset_group is group}
        return sorted(symbols)

    def expiries(self, underlying_symbol: str) -> list[date]:
        """Sorted ascending unique expiry dates for an underlying."""
        expiries = {
            c.expiry
            for c in self.contracts()
            if c.underlying_symbol.upper() == underlying_symbol.upper() and c.expiry is not None
        }
        return sorted(expiries)

    def chain(self, underlying_symbol: str, expiry: date) -> list[LiveOptionContract]:
        """All CE/PE contracts for an underlying on one expiry, strike-sorted.

        Raises:
            UnknownUnderlyingError: If the underlying has no contracts.
        """
        matches = [
            c
            for c in self.contracts()
            if c.underlying_symbol.upper() == underlying_symbol.upper() and c.expiry == expiry
        ]
        if not matches:
            raise UnknownUnderlyingError(
                f"No contracts for {underlying_symbol} @ {expiry.isoformat()}"
            )
        matches.sort(key=lambda c: ((c.strike or 0.0), 0 if c.is_call else 1))
        return matches

    def contract(self, instrument_key: str) -> LiveOptionContract | None:
        return self.by_instrument_key().get(instrument_key)

    def token_to_instrument_key(self) -> dict[str, str]:
        """Map feed exchange-tokens → instrument keys.

        Upstox WS messages key feeds by the numeric exchange token; this
        index reverses that to full instrument keys.
        """
        df = self._master.download()
        tokens = df["exchange_token"].astype(str).str.strip()
        keys = df["instrument_key"].astype(str)
        return {t: k for t, k in zip(tokens, keys, strict=False) if t}

    def eligible_from_universe(self, symbols: set[str]) -> set[str]:
        """Intersect a universe list with underlyings that actually have F&O."""
        available = set(self.list_underlyings(AssetGroup.NSE_FNO_STOCKS))
        return {s.upper() for s in symbols if s.upper() in available}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_contract(self, row: pd.Series) -> LiveOptionContract:
        segment = str(row.get("exchange") or "")
        underlying_type = str(row.get("underlying_type") or "")
        if segment == "MCX_FO" or underlying_type == "COM":
            group = AssetGroup.COMMODITIES
        elif underlying_type == "INDEX":
            group = AssetGroup.INDICES
        else:
            group = AssetGroup.NSE_FNO_STOCKS
        expiry = row["expiry"] if pd.notna(row.get("expiry")) else None
        return LiveOptionContract(
            instrument_key=str(row.get("instrument_key") or ""),
            tradingsymbol=str(row.get("tradingsymbol") or ""),
            underlying_symbol=str(row.get("underlying_symbol") or "") or str(row.get("name") or ""),
            underlying_name=str(row.get("name") or ""),
            underlying_type=underlying_type,
            option_type=str(row.get("option_type") or ""),
            expiry=expiry,
            strike=_as_float(row.get("strike")),
            lot_size=_as_int(row.get("lot_size"), 0),
            tick_size=_as_float(row.get("tick_size"), 0.05),
            asset_group=group,
        )


def _as_int(value: Any, default: int) -> int:
    if value is None or pd.isna(value):
        return default
    return int(value)


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    return float(value)
