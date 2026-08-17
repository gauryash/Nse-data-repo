"""
Local filesystem storage repository.

Writes provider-partitioned data to ``data/{provider}/`` in either
Parquet (gzip) or CSV format.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import cast

import pandas as pd

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.config.settings import settings
from nse_data_pipeline.infrastructure.storage.format_handler import FormatHandler
from nse_data_pipeline.infrastructure.storage.layout import ProviderLayout

logger = get_logger(__name__)


class FileStorageRepository:
    """Filesystem-backed storage for provider data.

    Delegates path generation to :class:`ProviderLayout` and
    serialisation to :class:`FormatHandler`.
    """

    def __init__(
        self,
        base_dirs: dict[str, Path] | None = None,
        storage_format: str = "",
    ) -> None:
        self._layout = ProviderLayout(base_dirs, storage_format)
        fmt = storage_format or settings.nse_storage_format.value
        self._format = FormatHandler(fmt)

    # ------------------------------------------------------------------
    # Equities (yearly partitioned + consolidated)
    # ------------------------------------------------------------------

    def save_equities(self, df: pd.DataFrame, provider: str) -> None:
        """Save/append equity data partitioned by year."""
        df = df.copy()
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")

        df["Year"] = pd.to_datetime(df["Date"]).dt.year
        for year, group in df.groupby("Year"):
            path = self._layout.equities(provider, cast(int, year))
            if path.exists():
                existing = self._format.read(path)
                group = pd.concat([existing, group], ignore_index=True)
                group = group.drop_duplicates(subset=["Symbol", "Date"], keep="last").sort_values(
                    "Date"
                )
            group.drop(columns=["Year"], inplace=True)
            self._format.write(group, path)

        self.rebuild_consolidated(provider)

    def rebuild_consolidated(self, provider: str) -> None:
        """Merge all yearly equity partitions into a single file."""
        ext = self._layout.ext
        base = self._layout.for_provider(provider)
        files = sorted(glob.glob(os.path.join(base, f"equities_*{ext}")))
        if not files:
            return
        dfs = [self._format.read(f) for f in files]
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.drop_duplicates(subset=["Symbol", "Date"]).sort_values("Date")
        path = self._layout.equities(provider)
        self._format.write(combined, path)

    def load_equities(self, provider: str) -> pd.DataFrame:
        """Load the consolidated equities file."""
        path = self._layout.equities(provider)
        if not path.exists():
            return pd.DataFrame()
        df = self._format.read(path)
        if "Date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["Date"]):
            df["Date"] = pd.to_datetime(df["Date"])
        return df

    def load_equities_yearly(self, provider: str) -> pd.DataFrame:
        """Load all yearly partitions as a single DataFrame."""
        ext = self._layout.ext
        base = self._layout.for_provider(provider)
        files = sorted(glob.glob(os.path.join(base, f"equities_*{ext}")))
        if not files:
            return pd.DataFrame()
        dfs = [self._format.read(f) for f in files]
        return pd.concat(dfs, ignore_index=True)

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def save_index(self, df: pd.DataFrame, provider: str) -> None:
        """Save index data."""
        self._format.write(df, self._layout.indices(provider))

    def load_index(self, provider: str) -> pd.DataFrame:
        """Load index data."""
        path = self._layout.indices(provider)
        if not path.exists():
            return pd.DataFrame()
        df = self._format.read(path)
        if "Date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["Date"]):
            df["Date"] = pd.to_datetime(df["Date"])
        return df

    # ------------------------------------------------------------------
    # Per-symbol
    # ------------------------------------------------------------------

    def save_symbol(self, df: pd.DataFrame, provider: str, symbol: str) -> None:
        """Save data for a single symbol."""
        if df.empty:
            return
        self._format.write(df, self._layout.symbol(provider, symbol))

    def load_symbol(self, provider: str, symbol: str) -> pd.DataFrame:
        """Load data for a single symbol."""
        path = self._layout.symbol(provider, symbol)
        if not path.exists():
            return pd.DataFrame()
        return self._format.read(path)

    def list_symbols(self, provider: str) -> list[str]:
        """List all symbols with stored data (excludes meta files)."""
        base = self._layout.for_provider(provider)
        files = glob.glob(os.path.join(base, f"*{self._layout.ext}"))
        names: list[str] = []
        for f in files:
            stem = Path(f).stem
            if stem.startswith("equities") or stem.startswith("indices"):
                continue
            names.append(stem)
        return sorted(names)

    # ------------------------------------------------------------------
    # Per-contract (options/futures)
    # ------------------------------------------------------------------

    def save_option(
        self,
        df: pd.DataFrame,
        provider: str,
        symbol: str,
        underlying: str | None = None,
        expiry_date: str | None = None,
    ) -> None:
        """Save candle data for a single option/future contract."""
        if df.empty:
            return
        path = self._layout.option_contract(
            provider,
            symbol,
            underlying=underlying,
            expiry_date=expiry_date,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        self._format.write(df, path)

    def load_option(
        self,
        provider: str,
        symbol: str,
        underlying: str | None = None,
        expiry_date: str | None = None,
    ) -> pd.DataFrame:
        """Load candle data for a single contract."""
        path = self._layout.option_contract(
            provider,
            symbol,
            underlying=underlying,
            expiry_date=expiry_date,
        )
        if not path.exists():
            return pd.DataFrame()
        return self._format.read(path)

    def list_option_symbols(self, provider: str) -> list[str]:
        """List all contract tradingsymbols with stored data.

        Recursively walks ``{underlying}/{expiry_short}/`` subdirectories.
        """
        base = self._layout.for_provider(provider)
        ext = self._layout.ext
        symbols: list[str] = []
        # Walk flat files at base level (legacy)
        for f in sorted(glob.glob(os.path.join(base, f"*{ext}"))):
            stem = Path(f).stem
            if not stem.startswith("_") and stem != "indices":
                symbols.append(stem)
        # Walk subdirectory structure
        for f in sorted(glob.glob(os.path.join(base, "*", "*", f"*{ext}"))):
            stem = Path(f).stem
            if not stem.startswith("_"):
                symbols.append(stem)
        return sorted(set(symbols))

    # ------------------------------------------------------------------
    # Path / checkpoint / manifest  (delegated to layout)
    # ------------------------------------------------------------------

    def base_dir(self, provider: str) -> Path:
        return self._layout.for_provider(provider)

    def equities_path(self, provider: str, year: int | None = None) -> Path:
        return self._layout.equities(provider, year)

    def indices_path(self, provider: str) -> Path:
        return self._layout.indices(provider)

    def symbol_path(self, provider: str, symbol: str) -> Path:
        return self._layout.symbol(provider, symbol)

    def checkpoint_path(self, provider: str) -> Path:
        return self._layout.checkpoint(provider)

    def manifest_path(self, provider: str) -> Path:
        return self._layout.manifest(provider)

    def options_path(
        self,
        provider: str,
        symbol: str,
        underlying: str | None = None,
        expiry_date: str | None = None,
    ) -> Path:
        return self._layout.option_contract(
            provider, symbol, underlying=underlying, expiry_date=expiry_date
        )
