"""
Application configuration — all settings loaded from environment variables.

Prefixes:
  NSE_  – core pipeline & analytics settings
  (no prefix) – Telegram bot credentials (from .env)
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Project paths
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

    # Walk up from this file location
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        if (parent / "pyproject.toml").is_file():
            return parent

    return Path.cwd().resolve()


PROJECT_ROOT = _find_project_root()
DATA_DIR = PROJECT_ROOT / "data"

# ---------------------------------------------------------------------------
# Telegram credentials (keep in .env, never commit)
# ---------------------------------------------------------------------------
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
CHAT_ID_ALERT: str = os.getenv("CHAT_ID_ALERT", "")
CHAT_ID_BOT: str = os.getenv("CHAT_ID_BOT", "")

# ---------------------------------------------------------------------------
# Data provider: NSE website API
# ---------------------------------------------------------------------------
BASE_URL: str = "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
INDEX_HISTORICAL_URL: str = "https://www.nseindia.com/api/NextApi/apiClient/historicalGraph"
NIFTY_BENCHMARK: str = "NIFTY 500"

NSE_STORAGE_DIR: Path = DATA_DIR / "nse"
NSE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Data provider: Upstox
# ---------------------------------------------------------------------------
UPSTOX_BASE_URL: str = "https://api.upstox.com/v2/historical-candle"
UPSTOX_INSTRUMENTS_URL: str = (
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
)
UPSTOX_STORAGE_DIR: Path = DATA_DIR / "upstox"
UPSTOX_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Rate limiter (shared across providers)
# ---------------------------------------------------------------------------
RATE_MAX_WORKERS: int = int(os.getenv("NSE_RATE_MAX_WORKERS", "5"))
RATE_INITIAL_DELAY: float = float(os.getenv("NSE_RATE_INITIAL_DELAY", "0.5"))
RATE_MAX_DELAY: float = float(os.getenv("NSE_RATE_MAX_DELAY", "30.0"))
RATE_BACKOFF_FACTOR: float = float(os.getenv("NSE_RATE_BACKOFF_FACTOR", "2.0"))

# ---------------------------------------------------------------------------
# Fetch defaults  (NSE)
# ---------------------------------------------------------------------------
DEFAULT_NSE_INDEX: str = os.getenv("NSE_DEFAULT_INDEX", "nifty500")
FETCH_START_DATE: str = os.getenv("NSE_FETCH_START", "01-01-2021")
FETCH_END_DATE: str = os.getenv("NSE_FETCH_END", "23-05-2026")
FETCH_CHUNK_DAYS: int = int(os.getenv("NSE_FETCH_CHUNK_DAYS", "110"))  # NSE API returns max 70 records ~ 100 trading days
FETCH_MAX_RETRIES: int = int(os.getenv("NSE_FETCH_MAX_RETRIES", "5"))
FETCH_SLEEP_INTERVAL: float = float(os.getenv("NSE_FETCH_SLEEP", "0.1"))
FETCH_STORAGE_FORMAT: str = os.getenv("NSE_STORAGE_FORMAT", "parquet")  # parquet | csv

# ---------------------------------------------------------------------------
# Fetch defaults  (Upstox)
# ---------------------------------------------------------------------------
UPSTOX_INTERVAL: str = os.getenv("UPSTOX_INTERVAL", "month")  # day | week | month
UPSTOX_MAX_WORKERS: int = int(os.getenv("UPSTOX_MAX_WORKERS", "10"))
UPSTOX_CHUNK_YEARS: int = int(os.getenv("UPSTOX_CHUNK_YEARS", "5"))
UPSTOX_FETCH_START: str = os.getenv("UPSTOX_FETCH_START", "01-01-2000")

# ---------------------------------------------------------------------------
# Data provider: Upstox Options (F&O historical data)
# ---------------------------------------------------------------------------
UPSTOX_OPTIONS_STORAGE_DIR: Path = DATA_DIR / "upstox_options"
UPSTOX_OPTIONS_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
UPSTOX_OPTIONS_INTERVAL: str = os.getenv("UPSTOX_OPTIONS_INTERVAL", "day")  # day | week | month
UPSTOX_OPTIONS_MAX_WORKERS: int = int(os.getenv("UPSTOX_OPTIONS_MAX_WORKERS", "5"))
UPSTOX_OPTIONS_CHUNK_YEARS: int = int(os.getenv("UPSTOX_OPTIONS_CHUNK_YEARS", "2"))
UPSTOX_OPTIONS_FETCH_START: str = os.getenv("UPSTOX_OPTIONS_FETCH_START", "01-01-2024")
# Filter: which F&O instrument types to fetch (OPTSTK, OPTIDX, FUTSTK, FUTIDX)
UPSTOX_OPTIONS_TYPES: str = os.getenv("UPSTOX_OPTIONS_TYPES", "OPTSTK")
# Number of upcoming expiries to fetch per underlying (0 = fetch all)
UPSTOX_OPTIONS_N_EXPIRIES: int = int(os.getenv("UPSTOX_OPTIONS_N_EXPIRIES", "2"))
# Index names for OPTIDX discovery (comma-separated; empty = auto-discover from CSV)
UPSTOX_OPTIONS_INDEX_NAMES: str = os.getenv("UPSTOX_OPTIONS_INDEX_NAMES", "")

# ---------------------------------------------------------------------------
# Analytics defaults
# ---------------------------------------------------------------------------
RS_LOOKBACK: int = int(os.getenv("NSE_RS_LOOKBACK", "50"))

VWAP_LOOKBACK_YEARS: list[int] = [30, 20, 10]
VWAP_THRESHOLD: float = 0.03  # 3 %
VWAP_MIN_ANCHOR_AGE_MONTHS: int = 12

# ---------------------------------------------------------------------------
# Alpha pipeline defaults
# ---------------------------------------------------------------------------
ALPHA_LOOKBACK: int = int(os.getenv("NSE_ALPHA_LOOKBACK", "252"))
ALPHA_ESTIMATION_PERIODS: int = int(os.getenv("NSE_ALPHA_ESTIMATION", "20"))
ALPHA_ETA: float = float(os.getenv("NSE_ALPHA_ETA", "1.0"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = os.getenv("NSE_LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PROVIDERS = ("nse", "upstox", "upstox_options")
VALID_ANALYTICS = ("rs", "vwap", "alpha")
VALID_SCANNERS = ("chartink", "composite", "sector")


def ensure_dirs() -> None:
    """Create all data directories if they don't exist."""
    for d in (NSE_STORAGE_DIR, UPSTOX_STORAGE_DIR, UPSTOX_OPTIONS_STORAGE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def validate_env() -> None:
    """Check that required Telegram env vars are set."""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not CHAT_ID_ALERT:
        missing.append("CHAT_ID_ALERT")
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Copy .env.example to .env and fill in your values."
        )
