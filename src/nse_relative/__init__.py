"""NSE Relative Strength Analyzer — revamped architecture.

Three layers:
  pipeline  – data fetching from NSE / Upstox APIs
  analytics – compute RS, anchored VWAP, etc.
  scanners  – external screener APIs → Telegram notifications
"""

__version__ = "0.2.0"
