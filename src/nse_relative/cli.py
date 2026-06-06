"""
Unified command-line interface for the NSE Relative Strength Analyzer.

Commands::

    nse-relative fetch     --provider nse|upstox  (fetch data from either source)
    nse-relative rs                              (relative strength on NSE data)
    nse-relative vwap                            (anchored VWAP on Upstox data)
    nse-relative scan       [scanner ...]         (run one or all scanners)
    nse-relative alpha run    --index nifty50     (12-step alpha pipeline)
    nse-relative alpha backtest --index nifty50   (rolling monthly backtest)
    nse-relative list-providers
    nse-relative list-analytics
    nse-relative list-scanners
"""

import argparse
import sys
from pathlib import Path
from typing import Sequence

import pandas as pd

from nse_relative import __version__
from nse_relative.config.settings import (
    VALID_PROVIDERS,
    VALID_ANALYTICS,
    VALID_SCANNERS,
    ensure_dirs,
    BOT_TOKEN,
    ALPHA_LOOKBACK,
    ALPHA_ESTIMATION_PERIODS,
    ALPHA_ETA,
)
from nse_relative.pipeline.symbol_manager import NSE_INDEX_NAMES, DEFAULT_NSE_INDEX

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nse-relative",
        description="NSE / Upstox data pipeline + RS / VWAP analytics + Telegram scanners.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ---- fetch ----
    fetch_parser = sub.add_parser("fetch", help="Fetch data from a provider")
    fetch_parser.add_argument(
        "--provider", "-p",
        choices=VALID_PROVIDERS,
        default="nse",
        help="Data provider (default: nse)",
    )
    fetch_parser.add_argument(
        "--index", "-x",
        choices=NSE_INDEX_NAMES,
        default=DEFAULT_NSE_INDEX,
        help=f"NSE index to source symbols from (default: {DEFAULT_NSE_INDEX})",
    )
    fetch_parser.add_argument(
        "--symbols", "-s", nargs="*",
        help="Specific symbols (NSE: symbols; Upstox: tradingsymbols)",
    )
    fetch_parser.add_argument(
        "--start", "--from",
        dest="start_date",
        default=None,
        help="Fetch start date DD-MM-YYYY (default: from env, e.g. NSE_FETCH_START)",
    )
    fetch_parser.add_argument(
        "--end", "--to",
        dest="end_date",
        default=None,
        help="Fetch end date DD-MM-YYYY (default: from env or today)",
    )
    fetch_parser.add_argument(
        "--interval", "-i",
        choices=["day", "week", "month"],
        default=None,
        help="Candle interval for Upstox / UpstoxOptions (default: from env)",
    )
    fetch_parser.add_argument(
        "--instrument-types", "-t",
        default=None,
        help="F&O instrument types for UpstoxOptions, comma-separated "
             "(default: from env UPSTOX_OPTIONS_TYPES or 'OPTSTK'); "
             "e.g. 'OPTSTK,OPTIDX'",
    )
    fetch_parser.add_argument(
        "--include-futures", action="store_true",
        help="Include FUTSTK (stock futures) in UpstoxOptions fetch",
    )
    fetch_parser.add_argument(
        "--n-expiries", type=int, default=None,
        help="Number of upcoming expiry cycles to fetch per underlying "
             "(default: from env UPSTOX_OPTIONS_N_EXPIRIES or 2; 0 = all)",
    )
    fetch_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Ignore checkpoint and re-fetch all symbols from scratch",
    )
    fetch_parser.add_argument(
        "--skip-index", action="store_true",
        help="Skip fetching index data (only applies to NSE)",
    )

    # ---- rs ----
    rs_parser = sub.add_parser("rs", help="Compute weekly Relative Strength (NSE data)")
    rs_parser.add_argument(
        "--output", "-o", default="rs_weekly.csv",
        help="Output CSV path (default: rs_weekly.csv)",
    )
    rs_parser.add_argument(
        "--lookback", "-l", type=int, default=None,
        help="RS lookback in weeks (default: from env or 50)",
    )

    # ---- vwap ----
    vwap_parser = sub.add_parser("vwap", help="Anchored VWAP proximity screener (Upstox data)")
    vwap_parser.add_argument(
        "--output", "-o", default=None,
        help="Output Excel path (default: data/ScreenerList_VWAP_Proximity.xlsx)",
    )
    vwap_parser.add_argument(
        "--threshold", "-t", type=float, default=None,
        help="Proximity threshold as decimal, e.g. 0.03 = 3%% (default: 0.03)",
    )

    # ---- scan ----
    scan_parser = sub.add_parser("scan", help="Run one or more Telegram scanners")
    scan_parser.add_argument(
        "scanners", nargs="*",
        choices=VALID_SCANNERS + ("all",),
        default=("all",),
        help="Scanner(s) to run (default: all)",
    )

    # ---- alpha (12-step signal pipeline) ----
    alpha_parser = sub.add_parser("alpha", help="Run the 12-step alpha extraction pipeline")
    alpha_sub = alpha_parser.add_subparsers(dest="alpha_command", required=True)

    alpha_run = alpha_sub.add_parser("run", help="Run alpha pipeline on NSE data")
    alpha_run.add_argument(
        "--index", "-x",
        choices=NSE_INDEX_NAMES,
        default=DEFAULT_NSE_INDEX,
        help=f"Index universe (default: {DEFAULT_NSE_INDEX})",
    )
    alpha_run.add_argument(
        "--lookback", "-M", type=int, default=None,
        help=f"Lookback periods M (default: {ALPHA_LOOKBACK})",
    )
    alpha_run.add_argument(
        "--estimation", "-d", type=int, default=None,
        help=f"Estimation periods d (default: {ALPHA_ESTIMATION_PERIODS})",
    )
    alpha_run.add_argument(
        "--eta", type=float, default=None,
        help=f"Weighting scale eta (default: {ALPHA_ETA})",
    )
    alpha_run.add_argument(
        "--output", "-o", default="alpha_ranking.csv",
        help="Output CSV path (default: alpha_ranking.csv)",
    )
    alpha_run.add_argument(
        "--send", action="store_true",
        help="Send results to Telegram after computation",
    )
    alpha_run.add_argument(
        "--top", type=int, default=10,
        help="Show top N stocks (default: 10)",
    )
    alpha_run.add_argument(
        "--start", "--from",
        default=None,
        help="Start date DD-MM-YYYY (default: earliest available)",
    )
    alpha_run.add_argument(
        "--end", "--to",
        default=None,
        help="End date DD-MM-YYYY (default: latest available)",
    )

    alpha_send = alpha_sub.add_parser("send", help="Send latest alpha results to Telegram")
    alpha_send.add_argument(
        "--input", "-i", default="alpha_ranking.csv",
        help="Input CSV path (default: alpha_ranking.csv)",
    )
    alpha_send.add_argument(
        "--top", type=int, default=10,
        help="Show top N stocks (default: 10)",
    )

    alpha_backtest = alpha_sub.add_parser(
        "backtest",
        help="Rolling monthly backtest: long-only, top 10%%, monthly rebalance",
    )
    alpha_backtest.add_argument(
        "--index", "-x",
        choices=NSE_INDEX_NAMES,
        default=DEFAULT_NSE_INDEX,
        help=f"Index universe (default: {DEFAULT_NSE_INDEX})",
    )
    alpha_backtest.add_argument(
        "--lookback", "-M", type=int, default=None,
        help=f"Lookback periods M (default: {ALPHA_LOOKBACK})",
    )
    alpha_backtest.add_argument(
        "--estimation", "-d", type=int, default=None,
        help=f"Estimation periods d (default: {ALPHA_ESTIMATION_PERIODS})",
    )
    alpha_backtest.add_argument(
        "--eta", type=float, default=None,
        help=f"Weighting scale eta (default: {ALPHA_ETA})",
    )
    alpha_backtest.add_argument(
        "--top-pct", type=float, default=0.10,
        help="Top percentile of stocks to keep (default: 0.10 = top 10%%)",
    )
    alpha_backtest.add_argument(
        "--min-stocks", type=int, default=5,
        help="Minimum number of stocks to keep per month (default: 5)",
    )
    alpha_backtest.add_argument(
        "--start", "--from",
        default=None,
        help="Start date DD-MM-YYYY (default: earliest available)",
    )
    alpha_backtest.add_argument(
        "--end", "--to",
        default=None,
        help="End date DD-MM-YYYY (default: latest available)",
    )

    # ---- list commands ----
    sub.add_parser("list-providers", help="List available data providers")
    sub.add_parser("list-analytics", help="List available analytics modules")
    sub.add_parser("list-scanners", help="List available scanners")
    sub.add_parser("list-indices", help="List available NSE index constituent lists")

    return parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _cmd_fetch(args: argparse.Namespace) -> None:
    ensure_dirs()

    provider_name = args.provider

    if provider_name == "nse":
        from nse_relative.pipeline.nse_provider import NSEProvider

        provider = NSEProvider(
            index=args.index,
            start_date=args.start_date,
            end_date=args.end_date,
            force=args.force,
        )
        provider.fetch_equities(symbols=args.symbols)
        if not args.skip_index:
            provider.fetch_index()

    elif provider_name == "upstox":
        from nse_relative.pipeline.upstox_provider import UpstoxProvider

        interval = args.interval or "month"
        provider = UpstoxProvider(
            interval=interval,
            index=args.index,
            start_date=args.start_date,
            end_date=args.end_date,
            force=args.force,
        )
        provider.fetch_equities(symbols=args.symbols)
        # Upstox has no index fetching currently

    elif provider_name == "upstox_options":
        from nse_relative.pipeline.upstox_options_provider import UpstoxOptionsProvider

        interval = args.interval or "day"
        n_expiries = args.n_expiries if args.n_expiries is not None else 2
        provider = UpstoxOptionsProvider(
            interval=interval,
            index=args.index,
            instrument_types=args.instrument_types,
            include_futures=args.include_futures,
            n_expiries=n_expiries,
            start_date=args.start_date,
            end_date=args.end_date,
            force=args.force,
        )
        provider.fetch_options(symbols=args.symbols)


def _cmd_rs(args: argparse.Namespace) -> None:
    from nse_relative.analytics.relative_strength import RelativeStrength

    lookback = args.lookback
    kwargs = {}
    if lookback is not None:
        kwargs["lookback"] = lookback

    analyzer = RelativeStrength(**kwargs)
    analyzer.run(output_path=args.output)


def _cmd_vwap(args: argparse.Namespace) -> None:
    from nse_relative.analytics.anchored_vwap import AnchoredVWAP

    kwargs = {}
    if args.threshold is not None:
        kwargs["threshold"] = args.threshold

    analyzer = AnchoredVWAP(**kwargs)
    analyzer.run(output_path=args.output)


def _cmd_scan(args: argparse.Namespace) -> None:
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set. Configure .env and try again.", file=sys.stderr)
        sys.exit(1)

    scanners_to_run: list[str]
    if "all" in args.scanners:
        scanners_to_run = list(VALID_SCANNERS)
    else:
        scanners_to_run = args.scanners

    for name in scanners_to_run:
        print(f"\n--- Running scanner: {name} ---")
        if name == "chartink":
            from nse_relative.scanners.chartink_scanner import ChartinkScanner
            ChartinkScanner().run()
        elif name == "composite":
            from nse_relative.scanners.composite_scorer import CompositeScorer
            CompositeScorer().run()
        elif name == "sector":
            from nse_relative.scanners.sector_scanner import SectorScanner
            SectorScanner().run()
        print(f"--- {name} done ---")


# ===================================================================
# Alpha pipeline commands
# ===================================================================


def _cmd_alpha_backtest(args: argparse.Namespace) -> None:
    """Run rolling monthly backtest (long-only, top 10%%)."""
    import sys
    from nse_relative.pipeline import storage as store
    from nse_relative.pipeline.symbol_manager import get_nse_symbols
    from nse_relative.alphaextraction import AlphaBacktest
    from nse_relative.config.logger import get_logger

    logger = get_logger(__name__)

    # ── Load data ──────────────────────────────────────────────
    logger.info("Loading NSE equities for index '%s' ...", args.index)
    df = store.load_equities("nse")
    if df.empty:
        print("ERROR: No NSE data found. Run 'nse-relative fetch --provider nse' first.",
              file=sys.stderr)
        sys.exit(1)

    universe = get_nse_symbols(args.index)
    df = df[df["Symbol"].isin(universe)].copy()
    if df.empty:
        print(f"ERROR: No data for index '{args.index}' symbols.", file=sys.stderr)
        sys.exit(1)

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values(["Symbol", "Date"])

    # ── Slice by date range if provided ─────────────────────────
    if args.start:
        start_dt = pd.to_datetime(args.start, format="%d-%m-%Y")
        df = df[df["Date"] >= start_dt].copy()
        logger.info("Sliced from %s", start_dt.strftime("%Y-%m-%d"))
    if args.end:
        end_dt = pd.to_datetime(args.end, format="%d-%m-%Y")
        df = df[df["Date"] <= end_dt].copy()
        logger.info("Sliced to   %s", end_dt.strftime("%Y-%m-%d"))

    if df.empty:
        print("ERROR: No data after date filter.", file=sys.stderr)
        sys.exit(1)

    prices = df.pivot_table(index="Date", columns="Symbol", values="Close")
    prices = prices.sort_index()
    returns = prices.pct_change().dropna(how="all")

    # Clean unadjusted corporate actions (stock splits, bonus issues)
    from nse_relative.analytics.utils import clean_corporate_actions
    returns = clean_corporate_actions(returns)

    n_stocks = returns.shape[1]
    n_days = len(returns)
    logger.info(
        "Loaded %d stocks x %d daily return periods  [%s .. %s]",
        n_stocks, n_days,
        returns.index[0].strftime("%Y-%m-%d"),
        returns.index[-1].strftime("%Y-%m-%d"),
    )

    lookback = args.lookback or ALPHA_LOOKBACK
    estimation = args.estimation or ALPHA_ESTIMATION_PERIODS
    eta = args.eta or ALPHA_ETA

    if n_days < lookback:
        print(
            f"ERROR: Need at least {lookback} daily return periods, have {n_days}.",
            file=sys.stderr,
        )
        sys.exit(1)

    bt = AlphaBacktest(
        lookback=lookback,
        estimation_periods=estimation,
        eta=eta,
        top_pct=args.top_pct,
        min_stocks=args.min_stocks,
    )

    print()
    print(f"Starting backtest: M={lookback} d={estimation} "
          f"top={args.top_pct:.0%} min_stocks={args.min_stocks}")
    if args.start:
        print(f"  Date range: {args.start} to {args.end or returns.index[-1].strftime('%d-%m-%Y')}")
    print(f"Results will be saved to: {bt.output_dir}")
    print()

    result = bt.run(returns)

    print()
    print("Backtest complete!")
    print(f"  Portfolio weights: {bt.output_dir / 'portfolio_weights.csv'}")
    print(f"  Monthly rankings: {bt.output_dir / 'rankings/'}")
    print(f"  Summary:          {bt.output_dir / 'backtest_summary.csv'}")
    print(f"  Equity curve:     {bt.output_dir / 'equity_curve.csv'}")
    print(f"  Performance:      {bt.output_dir / 'performance_metrics.csv'}")
    print(f"  Log:              {bt.output_dir / 'backtest_log.txt'}")

    # Print VectorBT metrics
    metrics = result.get("metrics", {})
    if metrics:
        print()
        print("  " + "=" * 50)
        print("  PERFORMANCE METRICS  (VectorBT)")
        print("  " + "=" * 50)
        print(f"    Total Return:        {metrics.get('total_return', 0)*100:>8.2f} %")
        print(f"    Annualized Return:   {metrics.get('annualized_return', 0)*100:>8.2f} %")
        print(f"    Annualized Vol:      {metrics.get('annualized_volatility', 0)*100:>8.2f} %")
        print(f"    Sharpe Ratio:        {metrics.get('sharpe_ratio', 0):>8.4f}")
        print(f"    Max Drawdown:        {metrics.get('max_drawdown', 0)*100:>8.2f} %")
        print(f"    Calmar Ratio:        {metrics.get('calmar_ratio', 0):>8.4f}")
        print(f"    Sortino Ratio:       {metrics.get('sortino_ratio', 0):>8.4f}")
        print(f"    Avg Daily Turnover:  {metrics.get('avg_daily_turnover', 0):>8.4f}")
        print()

    summary_path = bt.output_dir / "backtest_summary.csv"
    if summary_path.exists():
        summary = pd.read_csv(summary_path)
        print(summary.to_string(index=False))

    logger.info("Alpha backtest complete.")


def _cmd_list_providers() -> None:
    print("Available providers:")
    for p in VALID_PROVIDERS:
        print(f"  - {p}")


def _cmd_list_analytics() -> None:
    print("Available analytics:")
    for a in VALID_ANALYTICS:
        print(f"  - {a}")


def _cmd_list_scanners() -> None:
    print("Available scanners:")
    for s in VALID_SCANNERS:
        print(f"  - {s}")


def _cmd_alpha_run(args: argparse.Namespace) -> None:
    """Run the 12-step alpha pipeline on NSE data."""
    import sys
    from nse_relative.pipeline import storage as store
    from nse_relative.alphaextraction import AlphaPipeline, format_alpha_table, save_alpha_csv
    from nse_relative.config.logger import get_logger

    logger = get_logger(__name__)

    # ── Load data ────────────────────────────────────────────────
    logger.info("Loading NSE equities for index '%s' ...", args.index)
    df = store.load_equities("nse")
    if df.empty:
        print("ERROR: No NSE data found. Run 'nse-relative fetch --provider nse' first.",
              file=sys.stderr)
        sys.exit(1)

    # Filter to symbol set for this index
    from nse_relative.pipeline.symbol_manager import get_nse_symbols

    universe = get_nse_symbols(args.index)
    df = df[df["Symbol"].isin(universe)].copy()
    if df.empty:
        print(f"ERROR: No data for index '{args.index}' symbols.", file=sys.stderr)
        sys.exit(1)

    # ── Pivot to returns matrix ──────────────────────────────────
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values(["Symbol", "Date"])

    # Slice by date range if provided
    if args.start:
        start_dt = pd.to_datetime(args.start, format="%d-%m-%Y")
        df = df[df["Date"] >= start_dt].copy()
        logger.info("Sliced from %s", start_dt.strftime("%Y-%m-%d"))
    if args.end:
        end_dt = pd.to_datetime(args.end, format="%d-%m-%Y")
        df = df[df["Date"] <= end_dt].copy()
        logger.info("Sliced to   %s", end_dt.strftime("%Y-%m-%d"))

    if df.empty:
        print("ERROR: No data after date filter.", file=sys.stderr)
        sys.exit(1)

    # Pivot: rows = Date, columns = Symbol, values = Close
    prices = df.pivot_table(index="Date", columns="Symbol", values="Close")
    prices = prices.sort_index()

    # Calculate daily returns
    returns = prices.pct_change().dropna(how="all")

    # Clean unadjusted corporate actions (stock splits, bonus issues)
    from nse_relative.analytics.utils import clean_corporate_actions
    returns = clean_corporate_actions(returns)

    n_stocks = returns.shape[1]
    n_days = len(returns)
    logger.info(
        "Loaded %d stocks x %d daily return periods  [%s .. %s]",
        n_stocks, n_days,
        returns.index[0].strftime("%Y-%m-%d"),
        returns.index[-1].strftime("%Y-%m-%d"),
    )

    # ── Configure pipeline ───────────────────────────────────────
    lookback = args.lookback or ALPHA_LOOKBACK
    estimation = args.estimation or ALPHA_ESTIMATION_PERIODS
    eta = args.eta or ALPHA_ETA

    if n_days < lookback:
        print(
            f"ERROR: Need at least {lookback} daily return periods, have {n_days}. "
            f"Fetch more data (nse-relative fetch --start <earlier date>).",
            file=sys.stderr,
        )
        sys.exit(1)

    pipeline = AlphaPipeline(
        lookback=lookback,
        estimation_periods=estimation,
        eta=eta,
    )

    # ── Run ──────────────────────────────────────────────────────
    logger.info("Running alpha pipeline (M=%d, d=%d, eta=%.2f) ...",
                lookback, estimation, eta)

    result = pipeline.run(returns)

    # ── Output ────────────────────────────────────────────────────
    print()
    print(format_alpha_table(result, top_n=args.top))

    csv_path = save_alpha_csv(result, args.output)
    print(f"\nRanking saved to: {csv_path}")

    # ── Telegram (optional) ───────────────────────────────────────
    if args.send:
        if not BOT_TOKEN:
            print("ERROR: BOT_TOKEN not set. Cannot send to Telegram.", file=sys.stderr)
        else:
            from nse_relative.scanners.telegram_notifier import TelegramNotifier
            from nse_relative.alphaextraction import send_alpha_report

            notifier = TelegramNotifier()
            send_alpha_report(result, notifier, top_n=args.top)
            print("Results sent to Telegram.")

    logger.info("Alpha pipeline complete.")


def _cmd_alpha_send(args: argparse.Namespace) -> None:
    """Re-send the latest alpha ranking via Telegram."""
    import sys
    from pathlib import Path

    csv_path = Path(args.input)
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found. Run 'nse-relative alpha run' first.",
              file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(csv_path, index_col=0)
    # Build a minimal AlphaResult-like structure for the report
    from nse_relative.alphaextraction import AlphaResult, format_alpha_table
    from nse_relative.scanners.telegram_notifier import TelegramNotifier

    # Reconstruct a rough AlphaResult from CSV
    weights = df["weight"]
    alpha = df["alpha"]
    ranking = df

    result = AlphaResult(
        weights=weights,
        alpha=alpha,
        combined_signal=0.0,
        volatility=df.get("volatility", pd.Series(dtype=float)),
        expected_return=df.get("expected_return", pd.Series(dtype=float)),
        risk_adjusted_return=df.get("risk_adj_return", pd.Series(dtype=float)),
        normalised_signal=df.get("normalised_signal", pd.Series(dtype=float)),
        market_bias=pd.Series(dtype=float),
        ranking=ranking,
        n_stocks=len(ranking),
        n_periods=0,
        lookback=0,
        estimation_periods=0,
    )

    text = format_alpha_table(result, top_n=args.top)
    notifier = TelegramNotifier()
    notifier.send_message(text)
    print("Results sent to Telegram.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    ensure_dirs()

    if args.command == "fetch":
        _cmd_fetch(args)
    elif args.command == "rs":
        _cmd_rs(args)
    elif args.command == "vwap":
        _cmd_vwap(args)
    elif args.command == "scan":
        _cmd_scan(args)
    elif args.command == "list-providers":
        _cmd_list_providers()
    elif args.command == "list-analytics":
        _cmd_list_analytics()
    elif args.command == "list-scanners":
        _cmd_list_scanners()
    elif args.command == "alpha":
        if args.alpha_command == "run":
            _cmd_alpha_run(args)
        elif args.alpha_command == "send":
            _cmd_alpha_send(args)
        elif args.alpha_command == "backtest":
            _cmd_alpha_backtest(args)
    elif args.command == "list-indices":
        _cmd_list_indices()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
