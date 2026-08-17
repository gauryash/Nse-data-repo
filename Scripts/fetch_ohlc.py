"""
Standalone Upstox OHLC fetcher by ticker name.

Self-contained script (requests + pandas + pytz only). Downloads the Upstox
instrument master to resolve a ticker name (e.g. ``RELIANCE``, ``NIFTY 50``)
to its instrument key, then fetches historical OHLC candles from the public
Upstox V2 historical-candle API (no authentication required).

Usage::

    python Scripts/fetch_ohlc.py RELIANCE --interval day --start 01-01-2024
    python Scripts/fetch_ohlc.py "NIFTY 50" --interval month --out nifty.csv

Output columns: date, open, high, low, close, vol, oi, symbol
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytz
import requests

INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
)
HISTORICAL_URL = "https://api.upstox.com/v2/historical-candle"
TIME_ZONE = pytz.timezone("Asia/Kolkata")
CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "vol", "oi"]
DATE_FMT = "%d-%m-%Y"
CACHE_TTL_HOURS = 12.0
CACHE_PATH = Path(tempfile.gettempdir()) / "upstox_instruments.json.gz"

INTERVALS = ("day", "week", "month", "1minute", "30minute")


# ---------------------------------------------------------------------------
# Instrument master (ticker name -> instrument key)
# ---------------------------------------------------------------------------


def _cache_fresh(path: Path) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) / 3600.0 < CACHE_TTL_HOURS


def load_instruments(force_refresh: bool = False) -> list[dict]:
    """Return instrument master rows (cached in temp dir for 12h)."""
    if not force_refresh and _cache_fresh(CACHE_PATH):
        try:
            return json.loads(gzip.decompress(CACHE_PATH.read_bytes()))
        except Exception:
            pass
    print(f"Downloading instrument master from {INSTRUMENTS_URL}")
    r = requests.get(INSTRUMENTS_URL, timeout=120)
    r.raise_for_status()
    rows = json.loads(gzip.decompress(r.content))
    CACHE_PATH.write_bytes(gzip.compress(json.dumps(rows).encode()))
    return rows


def resolve_instrument(ticker: str, rows: list[dict]) -> dict | None:
    """Match a ticker name against NSE_EQ (equities) and NSE_INDEX (indices).

    Case-insensitive exact match on ``trading_symbol`` first, then on ``name``.
    Returns the matched row or ``None``.
    """
    ticker = ticker.strip()
    segments = {"NSE_EQ", "NSE_INDEX"}
    candidates = [r for r in rows if r.get("segment") in segments]
    for key in ("trading_symbol", "name"):
        for r in candidates:
            if str(r.get(key) or "").strip().lower() == ticker.lower():
                return r
    return None


def suggest_candidates(ticker: str, rows: list[dict]) -> list[str]:
    """Return up to 10 similar trading symbols for a failed lookup."""
    needle = ticker.strip().lower()
    segments = {"NSE_EQ", "NSE_INDEX"}
    seen: set[str] = set()
    out: list[str] = []
    for r in rows:
        if r.get("segment") not in segments:
            continue
        symbol = str(r.get("trading_symbol") or "").strip()
        if symbol and symbol.lower() not in seen and needle in symbol.lower():
            seen.add(symbol.lower())
            out.append(symbol)
        if len(out) >= 10:
            break
    return out


# ---------------------------------------------------------------------------
# OHLC fetch
# ---------------------------------------------------------------------------


def fetch_candles(
    instrument_key: str,
    interval: str,
    start: datetime,
    end: datetime,
    chunk_years: int = 5,
) -> pd.DataFrame | None:
    """Fetch candles over a date range, auto-chunking long ranges."""
    parts: list[pd.DataFrame] = []
    cur = start
    while cur < end:
        chunk_end = min(cur + timedelta(days=365 * chunk_years), end)
        df = _fetch_chunk(instrument_key, interval, cur, chunk_end)
        if df is not None:
            parts.append(df)
        cur = chunk_end + timedelta(days=1)
        time.sleep(0.05)
    if not parts:
        return None
    return (
        pd.concat(parts, ignore_index=True)
        .drop_duplicates(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def _fetch_chunk(
    instrument_key: str,
    interval: str,
    chunk_start: datetime,
    chunk_end: datetime,
) -> pd.DataFrame | None:
    """Fetch a single chunk from the Upstox historical-candle API."""
    parse_key = urllib.parse.quote(instrument_key)
    url = (
        f"{HISTORICAL_URL}/{parse_key}/{interval}"
        f"/{chunk_end.strftime('%Y-%m-%d')}/{chunk_start.strftime('%Y-%m-%d')}"
    )
    try:
        r = requests.get(url, headers={"accept": "application/json"}, timeout=30)
        r.raise_for_status()
        candles = r.json().get("data", {}).get("candles", [])
        if not candles:
            return None
        df = pd.DataFrame(candles, columns=CANDLE_COLUMNS)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(TIME_ZONE)
        return df
    except Exception as e:
        print(f"WARNING: {instrument_key} | {url} | {e}", file=sys.stderr)
        return None


def parse_date(dd_mm_yy: str) -> datetime:
    """Parse ``DD-MM-YYYY`` as a timezone-aware datetime (IST)."""
    return TIME_ZONE.localize(datetime.strptime(dd_mm_yy, DATE_FMT))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_ohlc.py",
        description="Fetch Upstox OHLC candles for a ticker name (equities or indices).",
    )
    parser.add_argument("ticker", help="Ticker name, e.g. RELIANCE, TCS, NIFTY 50")
    parser.add_argument(
        "--interval",
        "-i",
        choices=INTERVALS,
        default="day",
        help="Candle interval (default: day)",
    )
    parser.add_argument(
        "--start", default="01-01-2020", help="Fetch start date DD-MM-YYYY (default: 01-01-2020)"
    )
    parser.add_argument(
        "--end",
        default="",
        help="Fetch end date DD-MM-YYYY (default: today)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Output CSV path (default: ohlc_<TICKER>_<interval>.csv in current dir)",
    )
    parser.add_argument(
        "--refresh-master",
        action="store_true",
        help="Force re-download of the instrument master cache",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    rows = load_instruments(force_refresh=args.refresh_master)
    inst = resolve_instrument(args.ticker, rows)
    if inst is None:
        print(f"ERROR: no instrument found for ticker {args.ticker!r}", file=sys.stderr)
        similar = suggest_candidates(args.ticker, rows)
        if similar:
            print(f"Did you mean: {', '.join(similar)}", file=sys.stderr)
        return 1

    start = parse_date(args.start)
    end = parse_date(args.end) if args.end else datetime.now(TIME_ZONE)
    if end < start:
        print("ERROR: --end is before --start", file=sys.stderr)
        return 1

    symbol = str(inst.get("trading_symbol") or inst.get("name") or args.ticker)
    instrument_key = str(inst.get("instrument_key") or "")
    print(
        f"Fetching {symbol} ({inst.get('segment')}) "
        f"[{start.strftime('%Y-%m-%d')} .. {end.strftime('%Y-%m-%d')}] interval={args.interval}"
    )

    df = fetch_candles(instrument_key, args.interval, start, end)
    if df is None or df.empty:
        print(f"WARNING: no candles returned for {symbol}", file=sys.stderr)
        return 1

    df["symbol"] = symbol
    out = Path(args.out) if args.out else Path.cwd() / f"ohlc_{symbol}_{args.interval}.csv"
    df.to_csv(out, index=False)

    print(f"\nSaved {len(df)} rows to {out}")
    print(f"Range: {df['date'].min().strftime('%Y-%m-%d')} .. {df['date'].max().strftime('%Y-%m-%d')}")
    print(f"First close: {df.iloc[0]['close']} | Last close: {df.iloc[-1]['close']}")
    print("\nLast 5 rows:")
    print(df.tail(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
