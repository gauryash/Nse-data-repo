"""
Application configuration.

All settings are loaded once from environment variables (with optional
``.env`` file) and exposed via the ``settings`` singleton.

Use ``Settings.from_env()`` in tests to create isolated configs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Project root helper (defined before Settings so default_factory lambdas work)
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    """Locate the project root directory.

    Resolution order:
      1. Environment variable ``NSE_PROJECT_ROOT``
      2. Walk up from this file looking for ``pyproject.toml`` (development install)
      3. Fall back to current working directory
    """
    env = os.getenv("NSE_PROJECT_ROOT")
    if env:
        return Path(env).resolve()

    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        if (parent / "pyproject.toml").is_file():
            return parent

    return Path.cwd().resolve()


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------


@dataclass
class Settings:
    """All application configuration as a single dataclass.

    Defaults match the old module-level constants so existing ``.env``
    files continue to work unchanged.
    """

    # --- Project paths ---
    project_root: Path = field(default_factory=lambda: _find_project_root())
    data_dir: Path = field(default_factory=lambda: _find_project_root() / "data")

    # --- NSE API ---
    nse_base_url: str = "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
    nse_index_url: str = "https://www.nseindia.com/api/NextApi/apiClient/historicalGraph"
    nse_benchmark: str = "NIFTY 500"
    nse_fetch_start: str = "01-01-2021"
    nse_fetch_end: str = ""  # empty = today at runtime
    nse_fetch_chunk_days: int = 110
    nse_fetch_max_retries: int = 5
    nse_fetch_sleep: float = 0.1
    nse_storage_format: StorageFormat = StorageFormat.PARQUET
    nse_rate_max_workers: int = 5

    # --- Upstox API (equities) ---
    upstox_base_url: str = "https://api.upstox.com/v2/historical-candle"
    upstox_instruments_url: str = (
        "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    )
    upstox_interval: CandleInterval = CandleInterval.MONTH
    upstox_max_workers: int = 10
    upstox_chunk_years: int = 5
    upstox_fetch_start: str = "01-01-2000"

    # --- Upstox Options (F&O) ---
    upstox_options_interval: CandleInterval = CandleInterval.DAY
    upstox_options_max_workers: int = 5
    upstox_options_chunk_years: int = 2
    upstox_options_fetch_start: str = "01-01-2024"
    upstox_options_types: str = "OPTSTK"
    upstox_options_n_expiries: int = 2
    upstox_options_index_names: str = ""

    # --- Rate limiter ---
    rate_initial_delay: float = 0.5
    rate_max_delay: float = 30.0
    rate_backoff_factor: float = 2.0

    # --- Logging ---
    log_level: str = "INFO"

    # --- Derived paths ---
    nse_storage_dir: Path = field(init=False)
    upstox_storage_dir: Path = field(init=False)
    upstox_options_storage_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.nse_storage_dir = self.data_dir / "nse"
        self.upstox_storage_dir = self.data_dir / "upstox"
        self.upstox_options_storage_dir = self.data_dir / "upstox_options"
        self.nse_storage_dir.mkdir(parents=True, exist_ok=True)
        self.upstox_storage_dir.mkdir(parents=True, exist_ok=True)
        self.upstox_options_storage_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> Settings:
        """Build Settings from environment variables.

        All env vars are optional — missing vars fall back to defaults.
        """
        return cls(
            nse_fetch_start=os.getenv("NSE_FETCH_START", "01-01-2021"),
            nse_fetch_end=os.getenv("NSE_FETCH_END", ""),
            nse_fetch_chunk_days=int(os.getenv("NSE_FETCH_CHUNK_DAYS", "110")),
            nse_fetch_max_retries=int(os.getenv("NSE_FETCH_MAX_RETRIES", "5")),
            nse_fetch_sleep=float(os.getenv("NSE_FETCH_SLEEP", "0.1")),
            nse_storage_format=StorageFormat(os.getenv("NSE_STORAGE_FORMAT", "parquet")),
            nse_rate_max_workers=int(os.getenv("NSE_RATE_MAX_WORKERS", "5")),
            upstox_interval=CandleInterval(os.getenv("UPSTOX_INTERVAL", "month")),
            upstox_max_workers=int(os.getenv("UPSTOX_MAX_WORKERS", "10")),
            upstox_chunk_years=int(os.getenv("UPSTOX_CHUNK_YEARS", "5")),
            upstox_fetch_start=os.getenv("UPSTOX_FETCH_START", "01-01-2000"),
            upstox_options_interval=CandleInterval(os.getenv("UPSTOX_OPTIONS_INTERVAL", "day")),
            upstox_options_max_workers=int(os.getenv("UPSTOX_OPTIONS_MAX_WORKERS", "5")),
            upstox_options_chunk_years=int(os.getenv("UPSTOX_OPTIONS_CHUNK_YEARS", "2")),
            upstox_options_fetch_start=os.getenv("UPSTOX_OPTIONS_FETCH_START", "01-01-2024"),
            upstox_options_types=os.getenv("UPSTOX_OPTIONS_TYPES", "OPTSTK"),
            upstox_options_n_expiries=int(os.getenv("UPSTOX_OPTIONS_N_EXPIRIES", "2")),
            upstox_options_index_names=os.getenv("UPSTOX_OPTIONS_INDEX_NAMES", ""),
            rate_initial_delay=float(os.getenv("NSE_RATE_INITIAL_DELAY", "0.5")),
            rate_max_delay=float(os.getenv("NSE_RATE_MAX_DELAY", "30.0")),
            rate_backoff_factor=float(os.getenv("NSE_RATE_BACKOFF_FACTOR", "2.0")),
            log_level=os.getenv("NSE_LOG_LEVEL", "INFO"),
        )


# ---------------------------------------------------------------------------
# Singleton (backward-compatible with existing code that imports settings.*)
# ---------------------------------------------------------------------------

settings = Settings.from_env()


# --- Keep backward-compatible aliases for smooth migration ---
def _sync_legacy_aliases() -> None:
    """Patch module-level names so old ``from settings import X`` still works.

    This allows incremental migration: old code can import ``settings.BASE_URL``
    while new code uses ``settings.nse_base_url``.
    """
    import sys

    this = sys.modules[__name__]
    mapping = {
        "BASE_URL": settings.nse_base_url,
        "INDEX_HISTORICAL_URL": settings.nse_index_url,
        "NIFTY_BENCHMARK": settings.nse_benchmark,
        "NSE_STORAGE_DIR": settings.nse_storage_dir,
        "DATA_DIR": settings.data_dir,
        "UPSTOX_BASE_URL": settings.upstox_base_url,
        "UPSTOX_INSTRUMENTS_URL": settings.upstox_instruments_url,
        "UPSTOX_STORAGE_DIR": settings.upstox_storage_dir,
        "UPSTOX_OPTIONS_STORAGE_DIR": settings.upstox_options_storage_dir,
        "RATE_MAX_WORKERS": settings.nse_rate_max_workers,
        "RATE_INITIAL_DELAY": settings.rate_initial_delay,
        "RATE_MAX_DELAY": settings.rate_max_delay,
        "RATE_BACKOFF_FACTOR": settings.rate_backoff_factor,
        "FETCH_START_DATE": settings.nse_fetch_start,
        "FETCH_END_DATE": settings.nse_fetch_end,
        "FETCH_CHUNK_DAYS": settings.nse_fetch_chunk_days,
        "FETCH_MAX_RETRIES": settings.nse_fetch_max_retries,
        "FETCH_SLEEP_INTERVAL": settings.nse_fetch_sleep,
        "FETCH_STORAGE_FORMAT": settings.nse_storage_format.value,
        "UPSTOX_INTERVAL": settings.upstox_interval.value,
        "UPSTOX_MAX_WORKERS": settings.upstox_max_workers,
        "UPSTOX_CHUNK_YEARS": settings.upstox_chunk_years,
        "UPSTOX_FETCH_START": settings.upstox_fetch_start,
        "UPSTOX_OPTIONS_INTERVAL": settings.upstox_options_interval.value,
        "UPSTOX_OPTIONS_MAX_WORKERS": settings.upstox_options_max_workers,
        "UPSTOX_OPTIONS_CHUNK_YEARS": settings.upstox_options_chunk_years,
        "UPSTOX_OPTIONS_FETCH_START": settings.upstox_options_fetch_start,
        "UPSTOX_OPTIONS_TYPES": settings.upstox_options_types,
        "UPSTOX_OPTIONS_N_EXPIRIES": settings.upstox_options_n_expiries,
        "UPSTOX_OPTIONS_INDEX_NAMES": settings.upstox_options_index_names,
        "LOG_LEVEL": settings.log_level,
        "VALID_PROVIDERS": ("nse", "upstox", "upstox_options"),
    }
    for name, value in mapping.items():
        setattr(this, name, value)


_sync_legacy_aliases()


def ensure_dirs() -> None:
    """Create all data directories if they don't exist."""
    for d in (settings.nse_storage_dir, settings.upstox_storage_dir, settings.upstox_options_storage_dir):
        d.mkdir(parents=True, exist_ok=True)
