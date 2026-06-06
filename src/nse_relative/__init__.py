"""NSE / Upstox data pipeline — fetch equities, index, and F&O data.

Two data sources:
  - NSE India public website API (equities + index)
  - Upstox API (equities + F&O options/futures)

Storage is provider-partitioned under ``data/`` with per-symbol checkpoint
tracking for incremental fetching.
"""

__version__ = "0.3.0"
