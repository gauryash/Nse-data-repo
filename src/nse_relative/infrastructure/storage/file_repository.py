"""
Local filesystem storage repository.

Writes provider-partitioned data to ``data/{provider}/`` in either
Parquet (gzip) or CSV format.

Storage layout::

    data/nse/
        equities_{year}.parquet   (yearly partitions)
        equities.parquet          (consolidated)
        indices.parquet           (index data)
        _checkpoint.json

    data/upstox/
        {symbol}.parquet          (per-symbol)
        _checkpoint.json

    data/upstox_options/
        {tradingsymbol}.parquet   (per-contract)
        _contracts.parquet        (contract manifest)
        _checkpoint.json
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Optional

import pandas as pd

from nse_relative.config.settings import settings
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)

_FORMAT_EXT = {"parquet": ".parquet", "csv": ".csv"}


class FileStorageRepository:
    """Filesystem-backed storage for provider data.

    Args:
        base_dirs: Optional dict mapping provider name to base Path.
            Defaults to ``settings.nse_storage_dir`` etc.
        storage_format: ``'parquet'`` or ``'csv'``.
    """

    def __init__(
        self,
        base_dirs: dict[str, Path] | None = None,
        storage_format: str = "",
    ) -> None:
        self._base_dirs = base_dirs or {
            "nse": settings.nse_storage_dir,
            "upstox": settings.upstox_storage_dir,
            "upstox_options": settings.upstox_options_storage_dir,
        }
        self._storage_format = storage_format or settings.nse_storage_format.value

        # Ensure directories exist
        for d in self._base_dirs.values():
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Format helpers
    # ------------------------------------------------------------------

    def _ext(self) -> str:
        return _FORMAT_EXT.get(self._storage_format, ".parquet")

    def _read_func(self):
        if self._storage_format == "csv":
            return lambda p: pd.read_csv(
                p,
                parse_dates=["Date"]
                if "Date" in pd.read_csv(p, nrows=0).columns
                else False,
            )
        return lambda p: pd.read_parquet(p, engine="fastparquet")

    def _write_func(self):
        if self._storage_format == "csv":
            return lambda df, p: df.to_csv(p, index=False)
        return lambda df, p: df.to_parquet(
            p, index=False, compression="gzip", engine="fastparquet"
        )

    # ------------------------------------------------------------------
    # Base path resolver
    # ------------------------------------------------------------------

    def base_dir(self, provider: str) -> Path:
        """Return the storage directory for a provider."""
        d = self._base_dirs.get(provider)
        if d is None:
            raise ValueError(f"Unknown provider: {provider}")
        return d

    # ------------------------------------------------------------------
    # Path builders
    # ------------------------------------------------------------------

    def equities_path(self, provider: str, year: Optional[int] = None) -> Path:
        """Path to an equities file."""
        base = self.base_dir(provider)
        ext = self._ext()
        if year is not None:
            return base / f"equities_{year}{ext}"
        return base / f"equities{ext}"

    def indices_path(self, provider: str) -> Path:
        """Path to the index data file."""
        return self.base_dir(provider) / f"indices{self._ext()}"

    def symbol_path(self, provider: str, symbol: str) -> Path:
        """Path to an individual symbol file."""
        return self.base_dir(provider) / f"{symbol}{self._ext()}"

    def options_path(self, provider: str, symbol: str) -> Path:
        """Path to an individual option contract file."""
        return self.base_dir(provider) / f"{symbol}{self._ext()}"

    def checkpoint_path(self, provider: str) -> Path:
        """Path to the checkpoint JSON file."""
        return self.base_dir(provider) / "_checkpoint.json"

    def manifest_path(self, provider: str) -> Path:
        """Path to the contract manifest file."""
        return self.base_dir(provider) / "_contracts.parquet"

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
            path = self.equities_path(provider, int(year))
            if path.exists():
                existing = self._read_func()(path)
                group = pd.concat([existing, group], ignore_index=True)
                group = group.drop_duplicates(
                    subset=["Symbol", "Date"], keep="last"
                ).sort_values("Date")
            group.drop(columns=["Year"], inplace=True)
            self._write_func()(group, path)

        self.rebuild_consolidated(provider)

    def rebuild_consolidated(self, provider: str) -> None:
        """Merge all yearly equity partitions into a single file."""
        base = self.base_dir(provider)
        ext = self._ext()
        files = sorted(glob.glob(os.path.join(base, f"equities_*{ext}")))
        if not files:
            return
        dfs = [self._read_func()(f) for f in files]
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.drop_duplicates(subset=["Symbol", "Date"]).sort_values("Date")
        path = self.equities_path(provider)
        self._write_func()(combined, path)

    def load_equities(self, provider: str) -> pd.DataFrame:
        """Load the consolidated equities file.

        Returns empty DataFrame if no data exists.
        """
        path = self.equities_path(provider)
        if not path.exists():
            return pd.DataFrame()
        df = self._read_func()(path)
        if "Date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["Date"]):
            df["Date"] = pd.to_datetime(df["Date"])
        return df

    def load_equities_yearly(self, provider: str) -> pd.DataFrame:
        """Load all yearly partitions as a single DataFrame."""
        files = sorted(
            glob.glob(os.path.join(self.base_dir(provider), f"equities_*{self._ext()}"))
        )
        if not files:
            return pd.DataFrame()
        dfs = [self._read_func()(f) for f in files]
        return pd.concat(dfs, ignore_index=True)

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def save_index(self, df: pd.DataFrame, provider: str) -> None:
        """Save index data."""
        path = self.indices_path(provider)
        self._write_func()(df, path)

    def load_index(self, provider: str) -> pd.DataFrame:
        """Load index data."""
        path = self.indices_path(provider)
        if not path.exists():
            return pd.DataFrame()
        df = self._read_func()(path)
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
        path = self.symbol_path(provider, symbol)
        self._write_func()(df, path)

    def load_symbol(self, provider: str, symbol: str) -> pd.DataFrame:
        """Load data for a single symbol."""
        path = self.symbol_path(provider, symbol)
        if not path.exists():
            return pd.DataFrame()
        return self._read_func()(path)

    def list_symbols(self, provider: str) -> list[str]:
        """List all symbols with stored data (excludes meta files)."""
        base = self.base_dir(provider)
        files = glob.glob(os.path.join(base, f"*{self._ext()}"))
        names = []
        for f in files:
            stem = Path(f).stem
            if stem.startswith("equities") or stem.startswith("indices"):
                continue
            names.append(stem)
        return sorted(names)

    # ------------------------------------------------------------------
    # Per-contract (options/futures)
    # ------------------------------------------------------------------

    def save_option(self, df: pd.DataFrame, provider: str, symbol: str) -> None:
        """Save candle data for a single option/future contract."""
        if df.empty:
            return
        path = self.options_path(provider, symbol)
        self._write_func()(df, path)

    def load_option(self, provider: str, symbol: str) -> pd.DataFrame:
        """Load candle data for a single contract."""
        path = self.options_path(provider, symbol)
        if not path.exists():
            return pd.DataFrame()
        return self._read_func()(path)

    def list_option_symbols(self, provider: str) -> list[str]:
        """List all contract tradingsymbols with stored data."""
        return self.list_symbols(provider)
