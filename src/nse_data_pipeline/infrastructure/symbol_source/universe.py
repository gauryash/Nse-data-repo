"""
Universe loaders for the live monitor.

Upstox has no endpoint for NSE index constituent membership, so the
universe lists (NIFTY 50 / 100 / 200) are stored as static JSON snapshots
in ``config/universes/``.  At runtime the lists are intersected with the
underlyings that actually have F&O contracts in the Upstox catalog, so
stocks without listed options simply do not appear.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.config.settings import settings

logger = get_logger(__name__)

UNIVERSES_DIR = settings.project_root / "config" / "universes"

_KNOWN_UNIVERSES = ("nifty50", "nifty100", "nifty200")


def _load_universe(name: str, base_dir: Path = UNIVERSES_DIR) -> dict[str, Any]:
    path = base_dir / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Universe file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_symbols(name: str, base_dir: Path = UNIVERSES_DIR) -> list[str]:
    """Return the constituent symbols for a static universe (lowercased)."""
    data = _load_universe(name, base_dir)
    return [s.strip().upper() for s in data.get("symbols", []) if s.strip()]


def list_universes(base_dir: Path = UNIVERSES_DIR) -> list[str]:
    """Names of all known universe files present on disk."""
    return [n for n in _KNOWN_UNIVERSES if (base_dir / f"{n}.json").exists()]
