"""
Upstox F&O (Options & Futures) historical data provider.

Fetches historical candle data for NSE F&O contracts (stock options,
index options, stock futures, index futures) via the Upstox API.

Uses the same V2 API endpoint as the equity ``UpstoxProvider`` so no
additional authentication is required.

Key features:
  - **Unified discovery**: discovers both OPTSTK (stock options, filtered
    by NSE index ISIN) and OPTIDX (index options, auto-discovered from
    the instrument master).
  - **Expiry-aware filtering**: by default only fetches contracts for the
    next 2 expiry cycles per underlying. Pass ``n_expiries=0`` to fetch all.
  - **Contract manifest**: maintains a ``_contracts.parquet`` catalog enabling
    O(1) expiry-based queries without loading individual files.
  - **Checkpoint**: incremental fetch with per-contract date tracking.

Storage:
  Each contract is saved as a separate parquet file at::

      data/upstox_options/{tradingsymbol}.parquet

  Metadata columns (``instrument_type``, ``option_type``, ``expiry``,
  ``strike``, ``lot_size``, ``underlying_name``) are included alongside
  the standard candle columns so analytics can load everything needed
  from a single file.
"""

from __future__ import annotations

import urllib.parse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import pytz
import requests

from nse_relative.pipeline.base import DataProvider
from nse_relative.pipeline import storage as store
from nse_relative.pipeline import checkpoint as cp
from nse_relative.pipeline.symbol_manager import (
    DEFAULT_NSE_INDEX,
    discover_option_contracts,
    filter_by_expiry,
)
from nse_relative.config.settings import (
    UPSTOX_BASE_URL,
    UPSTOX_OPTIONS_MAX_WORKERS,
    UPSTOX_OPTIONS_CHUNK_YEARS,
    UPSTOX_OPTIONS_INTERVAL,
    UPSTOX_OPTIONS_FETCH_START,
    UPSTOX_OPTIONS_TYPES,
    UPSTOX_OPTIONS_N_EXPIRIES,
)
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

TIME_ZONE = pytz.timezone("Asia/Kolkata")
CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "vol", "oi"]
_DATE_FMT = "%d-%m-%Y"
_PROVIDER = "upstox_options"


def _parse_date(dd_mm_yy: str) -> datetime:
    """Convert ``DD-MM-YYYY`` → timezone-aware datetime."""
    naive = datetime.strptime(dd_mm_yy, _DATE_FMT)
    return TIME_ZONE.localize(naive)


def _fmt_url_date(dt: datetime) -> str:
    """Format a datetime as ``YYYY-MM-DD`` (Upstox API format)."""
    return dt.strftime("%Y-%m-%d")


def _parse_instrument_types(raw: str) -> list[str]:
    """Parse comma/space-separated instrument types from env config.

    Example: ``"OPTSTK,OPTIDX"`` → ``["OPTSTK", "OPTIDX"]``
    """
    return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]


class UpstoxOptionsProvider(DataProvider):
    """Fetch historical candle data for NSE F&O contracts from the Upstox API.

    Supports both **stock options** (OPTSTK, filtered by NSE index) and
    **index options** (OPTIDX, auto-discovered from the instrument master).

    By default only contracts for the next ``n_expiries`` upcoming expiry
    cycles are fetched. Pass ``n_expiries=0`` to fetch all discovered contracts.
    """

    def __init__(
        self,
        interval: str = UPSTOX_OPTIONS_INTERVAL,
        max_workers: int = UPSTOX_OPTIONS_MAX_WORKERS,
        chunk_years: int = UPSTOX_OPTIONS_CHUNK_YEARS,
        index: str = DEFAULT_NSE_INDEX,
        instrument_types: str | list[str] | None = None,
        include_futures: bool = False,
        n_expiries: int = UPSTOX_OPTIONS_N_EXPIRIES,
        start_date: str | None = None,
        end_date: str | None = None,
        force: bool = False,
    ) -> None:
        if interval not in ("day", "week", "month", "1minute", "30minute"):
            raise ValueError(f"Unsupported interval: {interval}")
        self._interval = interval
        self._max_workers = max_workers
        self._chunk_years = chunk_years
        self._index = index
        self._force = force
        self._include_futures = include_futures
        self._n_expiries = n_expiries

        # Parse instrument types
        if instrument_types is None:
            self._instrument_types = _parse_instrument_types(UPSTOX_OPTIONS_TYPES)
        elif isinstance(instrument_types, str):
            self._instrument_types = _parse_instrument_types(instrument_types)
        else:
            self._instrument_types = list(instrument_types)

        # Date range
        self._start = (
            _parse_date(start_date)
            if start_date
            else _parse_date(UPSTOX_OPTIONS_FETCH_START)
        )
        self._end = (
            _parse_date(end_date)
            if end_date
            else datetime.now(TIME_ZONE)
        )
        if self._end < self._start:
            raise ValueError(f"end_date ({end_date}) < start_date ({start_date})")

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "upstox_options"

    @property
    def provider(self) -> str:
        return _PROVIDER

    # ------------------------------------------------------------------
    # Abstract method stubs (options provider does not do equities / index)
    # ------------------------------------------------------------------

    def fetch_equities(self, symbols: Optional[list[str]] = None) -> None:
        """Not applicable — use ``UpstoxProvider`` for equity data."""
        logger.info("UpstoxOptions: equity fetching not applicable — skip.")

    def fetch_index(self) -> None:
        """Not applicable — use ``NSEProvider`` for index data."""
        logger.info("UpstoxOptions: index fetching not applicable — skip.")

    # ------------------------------------------------------------------
    # Main fetch method
    # ------------------------------------------------------------------

    def fetch_options(
        self,
        symbols: Optional[list[str]] = None,
        n_expiries: int | None = None,
    ) -> None:
        """Fetch historical candle data for F&O contracts and persist.

        Args:
            symbols: Optional list of ``tradingsymbol`` to restrict fetching
                (e.g.  ``["HINDALCO26JUN1230CE", "RELIANCE26JUN1500PE"]``).
                When ``None``, all contracts are discovered via
                :func:`discover_option_contracts` and filtered by expiry.
            n_expiries: Override the instance default for number of upcoming
                expiry cycles to fetch per underlying. ``0`` = fetch all.
        """
        effective_n = self._n_expiries if n_expiries is None else n_expiries

        # ── Resolve symbol universe ────────────────────────────────
        if symbols is not None:
            symboldf = self._resolve_provided_symbols(symbols)
        else:
            # Unified discovery: OPTSTK (via ISIN) + OPTIDX (auto-discovered)
            symboldf = discover_option_contracts(
                instrument_types=self._instrument_types,
                index_name=self._index,
                include_futures=self._include_futures,
            )
            # Apply expiry filter
            if effective_n > 0:
                symboldf = filter_by_expiry(symboldf, n_expiries=effective_n)

        if symboldf.empty:
            logger.error(
                "UpstoxOptions: symbol list is empty. "
                "Check the instrument master CSV or your NSE index name."
            )
            return

        logger.info(
            "UpstoxOptions: %d contracts, interval=%s, types=%s, "
            "n_expiries=%s, range=[%s … %s], force=%s",
            len(symboldf), self._interval, self._instrument_types,
            effective_n if symbols is None else "ALL",
            self._start.strftime("%Y-%m-%d"), self._end.strftime("%Y-%m-%d"),
            self._force,
        )

        # ── Fetch each contract in parallel ────────────────────────
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            fut_map = {
                pool.submit(self._fetch_one_contract, symboldf.loc[i]): i
                for i in symboldf.index
            }
            for future in as_completed(fut_map):
                idx = fut_map[future]
                row = symboldf.loc[idx]
                symbol = row["tradingsymbol"]
                try:
                    df = future.result()
                    if df is not None:
                        # Attach contract metadata
                        df = self._attach_metadata(df, row)
                        store.save_option(df, self.provider)
                        # Update checkpoint
                        dmin = df["date"].min()
                        dmax = df["date"].max()
                        meta = store.build_options_checkpoint_entry(row)
                        cp.update_symbol_coverage(
                            self.provider, symbol,
                            dmin.strftime("%Y-%m-%d"),
                            dmax.strftime("%Y-%m-%d"),
                            rows=len(df),
                        )
                        self._update_contract_meta(symbol, meta)
                except Exception as e:
                    logger.error("%s fetch error: %s", symbol, e)

        # ── Save contract manifest for expiry-based queries ────────
        if not symboldf.empty:
            store.save_contract_manifest(self.provider, symboldf)
            logger.info("Contract manifest updated (%d contracts)", len(symboldf))

        logger.info("UpstoxOptions fetch complete.")

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_chunk(
        self,
        row: pd.Series,
        chunk_start: datetime,
        chunk_end: datetime,
    ) -> pd.DataFrame | None:
        """Fetch a single date chunk for one contract."""
        parse_key = urllib.parse.quote(row["instrument_key"])
        url = (
            f"{UPSTOX_BASE_URL}/{parse_key}/{self._interval}"
            f"/{_fmt_url_date(chunk_end)}/{_fmt_url_date(chunk_start)}"
        )
        try:
            r = requests.get(url, headers={"accept": "application/json"}, timeout=30)
            candles = r.json().get("data", {}).get("candles", [])
            if not candles:
                return None
            df = pd.DataFrame(candles, columns=CANDLE_COLUMNS)
            df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(TIME_ZONE)
            df["symbol"] = row["tradingsymbol"]
            return df
        except Exception as e:
            logger.warning(
                "%s | %s → %s | %s",
                row["tradingsymbol"], _fmt_url_date(chunk_start),
                _fmt_url_date(chunk_end), e,
            )
            return None

    def _fetch_one_contract(self, row: pd.Series) -> pd.DataFrame | None:
        """Fetch *missing* date chunks for a single contract.

        Skips contracts whose expiry date has passed **and** whose
        checkpoint already covers the full requested date range.

        In ``force`` mode the entire requested range is re-fetched.
        """
        symbol = row["tradingsymbol"]

        # ── Skip if contract expired before our start date ──────────
        contract_expiry = row.get("expiry")
        if contract_expiry is not None and isinstance(contract_expiry, date):
            if contract_expiry < self._start.date():
                logger.debug(
                    "%s: expired %s before fetch start %s — skip",
                    symbol, contract_expiry, self._start.strftime("%Y-%m-%d"),
                )
                return None

        # ── Checkpoint check ──────────────────────────────────────
        if not self._force:
            if not cp.coverage_needed(
                self.provider, symbol,
                self._start.replace(tzinfo=None),
                self._end.replace(tzinfo=None),
            ):
                logger.debug("%s: checkpoint covers range, skip", symbol)
                return None

        # ── Fetch in chunks ────────────────────────────────────────
        parts: list[pd.DataFrame] = []
        cur = self._start
        while cur < self._end:
            chunk_end = min(cur + timedelta(days=365 * self._chunk_years), self._end)
            df = self._fetch_chunk(row, cur, chunk_end)
            if df is not None:
                parts.append(df)
            cur = chunk_end + timedelta(days=1)
            time.sleep(0.05)

        if not parts:
            return None

        combined = pd.concat(parts, ignore_index=True).drop_duplicates(
            subset=["date", "symbol"],
        ).sort_values("date")

        logger.info(
            "%s: %d rows [%s … %s]", symbol, len(combined),
            combined["date"].min().strftime("%Y-%m-%d"),
            combined["date"].max().strftime("%Y-%m-%d"),
        )
        return combined

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _attach_metadata(df: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
        """Add contract metadata columns to the candle DataFrame."""
        df["instrument_type"] = row.get("instrument_type", "")
        df["option_type"] = row.get("option_type", "")
        df["expiry"] = pd.to_datetime(row["expiry"]).date() if pd.notna(row.get("expiry")) else None
        df["strike"] = float(row["strike"]) if pd.notna(row.get("strike")) else None
        df["lot_size"] = int(row["lot_size"]) if pd.notna(row.get("lot_size")) else None
        df["underlying_name"] = row.get("name", "")
        return df

    def _update_contract_meta(self, symbol: str, meta: dict) -> None:
        """Store contract metadata in the checkpoint's symbol entry."""
        cp_data = cp.read_checkpoint(self.provider)
        symbols = cp_data.setdefault("symbols", {})
        if symbol not in symbols:
            symbols[symbol] = {}
        symbols[symbol].setdefault("meta", {})
        symbols[symbol]["meta"].update(meta)
        cp.write_checkpoint(self.provider, cp_data)

    # ------------------------------------------------------------------
    # Symbol resolution (when user provides tradingsymbols)
    # ------------------------------------------------------------------

    def _resolve_provided_symbols(self, symbols: list[str]) -> pd.DataFrame:
        """Look up contract metadata for user-provided tradingsymbols.

        Falls back to scanning the instrument master CSV, then adds
        ``underlying_type`` column for consistency with the discovery path.
        """
        from nse_relative.pipeline.symbol_manager import (
            _derive_underlying_type,
            download_upstox_instruments,
        )

        df = download_upstox_instruments()
        df = df[df["exchange"] == "NSE_FO"]
        matched = df[df["tradingsymbol"].isin(symbols)].copy()
        found = len(matched)
        if found < len(symbols):
            missing = set(symbols) - set(matched["tradingsymbol"])
            logger.warning(
                "%d tradingsymbol(s) not found in NSE_FO master: %s",
                len(missing), sorted(missing),
            )
        # Add underlying_type derived from instrument_type
        matched["underlying_type"] = matched["instrument_type"].apply(_derive_underlying_type)
        return matched[
            ["instrument_key", "tradingsymbol", "name", "underlying_type",
             "instrument_type", "option_type", "expiry", "strike",
             "lot_size", "tick_size"]
        ]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_symbols(self) -> list[str]:
        return store.list_option_symbols(self.provider)
