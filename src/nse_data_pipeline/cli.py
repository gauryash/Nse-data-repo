"""
Unified command-line interface for the NSE/Upstox data pipeline.

Commands::

    nse-data-pipeline fetch              Fetch data from NSE or Upstox
    nse-data-pipeline list-providers     List available data providers
    nse-data-pipeline list-indices       List available NSE index constituent lists
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from nse_data_pipeline import __version__
from nse_data_pipeline.application.fetch_service import PipelineOrchestrator
from nse_data_pipeline.config.settings import ensure_dirs
from nse_data_pipeline.infrastructure.symbol_source.nse_index_csv import (
    DEFAULT_NSE_INDEX,
    NSE_INDEX_NAMES,
)

VALID_PROVIDERS = ("nse", "upstox", "upstox_options")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nse-data-pipeline",
        description="NSE / Upstox data pipeline — fetch equities, index, and F&O data.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    # ---- fetch ----
    fetch_parser = sub.add_parser("fetch", help="Fetch data from a provider")
    fetch_parser.add_argument(
        "--provider",
        "-p",
        choices=VALID_PROVIDERS,
        default="nse",
        help="Data provider (default: nse)",
    )
    fetch_parser.add_argument(
        "--index",
        "-x",
        choices=NSE_INDEX_NAMES,
        default=DEFAULT_NSE_INDEX,
        help=f"NSE index to source symbols from (default: {DEFAULT_NSE_INDEX})",
    )
    fetch_parser.add_argument(
        "--underlying",
        default=None,
        help="Single underlying stock/index name for F&O fetch "
        "(e.g. WIPRO, NIFTY, RELIANCE); filters contract discovery",
    )
    fetch_parser.add_argument(
        "--underlyings",
        nargs="*",
        default=None,
        help="Multiple underlying names for F&O fetch "
        "(e.g. RELIANCE TCS HDFCBANK); filters contract discovery. "
        "Takes precedence over --underlying and is OPTSTK-only.",
    )
    fetch_parser.add_argument(
        "--symbols",
        "-s",
        nargs="*",
        help="Specific symbols (NSE: symbols; Upstox: tradingsymbols)",
    )
    fetch_parser.add_argument(
        "--start",
        "--from",
        dest="start_date",
        default=None,
        help="Fetch start date DD-MM-YYYY (default: from env)",
    )
    fetch_parser.add_argument(
        "--end",
        "--to",
        dest="end_date",
        default=None,
        help="Fetch end date DD-MM-YYYY (default: from env or today)",
    )
    fetch_parser.add_argument(
        "--interval",
        "-i",
        choices=["day", "week", "month"],
        default=None,
        help="Candle interval for Upstox / UpstoxOptions (default: from env)",
    )
    fetch_parser.add_argument(
        "--instrument-types",
        "-t",
        default=None,
        help="F&O instrument types for UpstoxOptions, comma-separated "
        "(default: from env UPSTOX_OPTIONS_TYPES or 'OPTSTK')",
    )
    fetch_parser.add_argument(
        "--include-futures",
        action="store_true",
        help="Include FUTSTK (stock futures) in UpstoxOptions fetch",
    )
    fetch_parser.add_argument(
        "--n-expiries",
        type=int,
        default=None,
        help="Number of upcoming expiry cycles to fetch per underlying "
        "(default: from env UPSTOX_OPTIONS_N_EXPIRIES or 2; 0 = all)",
    )
    fetch_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Ignore checkpoint and re-fetch all symbols from scratch",
    )
    fetch_parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Skip fetching index data (only applies to NSE)",
    )

    # ---- list commands ----
    sub.add_parser("list-providers", help="List available data providers")
    sub.add_parser("list-indices", help="List available NSE index constituent lists")

    # ---- live monitor ----
    live_parser = sub.add_parser(
        "live",
        help="Start the live market monitor (FastAPI + WebSocket)",
    )
    live_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    live_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind port (default: 8000)",
    )
    live_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (dev only)",
    )

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cmd_fetch(args: argparse.Namespace) -> None:
    """Dispatch fetch to the appropriate provider via PipelineOrchestrator."""

    service = PipelineOrchestrator()
    service.fetch(
        provider=args.provider,
        index=args.index,
        underlying=args.underlying,
        underlyings=args.underlyings,
        symbols=args.symbols,
        start_date=args.start_date,
        end_date=args.end_date,
        interval=args.interval,
        instrument_types=args.instrument_types,
        include_futures=args.include_futures,
        n_expiries=args.n_expiries or 2,
        force=args.force,
        skip_index=args.skip_index,
    )


def _cmd_list_providers() -> None:
    print("Available providers:")
    for p in VALID_PROVIDERS:
        print(f"  - {p}")


def _cmd_list_indices() -> None:
    from nse_data_pipeline.infrastructure.symbol_source.nse_index_csv import (
        NSE_INDEX_URLS,
    )

    print("Available NSE index constituent lists:")
    for name in sorted(NSE_INDEX_URLS):
        print(f"  - {name}")


def _cmd_live(args: argparse.Namespace) -> None:
    from nse_data_pipeline.live.app import run_server

    run_server(host=args.host, port=args.port, reload=args.reload)


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    ensure_dirs()

    if args.command == "fetch":
        _cmd_fetch(args)
    elif args.command == "list-providers":
        _cmd_list_providers()
    elif args.command == "list-indices":
        _cmd_list_indices()
    elif args.command == "live":
        _cmd_live(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
