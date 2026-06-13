"""
Filesystem layout and path generation for provider storage.

Defines the directory and file naming conventions used by
``FileStorageRepository``.
"""

from __future__ import annotations

from pathlib import Path

from nse_data_pipeline.config.settings import settings


class ProviderLayout:
    """Generates storage paths for a given provider.

    The layout follows::

        data/{provider}/
            equities_{year}.ext     (yearly partitions)
            equities.ext            (consolidated)
            indices.ext
            _checkpoint.json
            _contracts.parquet
            {symbol}.ext            (per-symbol)
            {underlying}/{expiry}/{symbol}.ext  (per-contract F&O)
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

    @property
    def ext(self) -> str:
        return ".parquet" if self._storage_format != "csv" else ".csv"

    def for_provider(self, provider: str) -> Path:
        """Return the base storage directory for a provider."""
        d = self._base_dirs.get(provider)
        if d is None:
            msg = f"Unknown provider: {provider}"
            raise ValueError(msg)
        return d

    def equities(self, provider: str, year: int | None = None) -> Path:
        base = self.for_provider(provider)
        if year is not None:
            return base / f"equities_{year}{self.ext}"
        return base / f"equities{self.ext}"

    def indices(self, provider: str) -> Path:
        return self.for_provider(provider) / f"indices{self.ext}"

    def symbol(self, provider: str, symbol: str) -> Path:
        return self.for_provider(provider) / f"{symbol}{self.ext}"

    def checkpoint(self, provider: str) -> Path:
        return self.for_provider(provider) / "_checkpoint.json"

    def manifest(self, provider: str) -> Path:
        return self.for_provider(provider) / "_contracts.parquet"

    def option_contract(
        self,
        provider: str,
        symbol: str,
        underlying: str | None = None,
        expiry_date: str | None = None,
    ) -> Path:
        """Path to an individual F&O contract file.

        Subdirectory layout: ``{underlying}/{expiry_folder}/{symbol}.ext``.
        Falls back to flat file when underlying cannot be determined.
        """
        base = self.for_provider(provider)
        name = underlying or ""
        if not name:
            from nse_data_pipeline.infrastructure.storage.symbol_parser import (
                FnoSymbolParser,
            )

            name = FnoSymbolParser.extract_underlying(symbol)
        if not name:
            return base / f"{symbol}{self.ext}"

        exp_folder = ""
        if expiry_date:
            import pandas as pd

            try:
                dt = pd.to_datetime(expiry_date)
                exp_folder = dt.strftime("%y%m%d")
            except Exception:
                from nse_data_pipeline.infrastructure.storage.symbol_parser import (
                    FnoSymbolParser,
                )

                _, exp_folder = FnoSymbolParser.parse(symbol)
        else:
            from nse_data_pipeline.infrastructure.storage.symbol_parser import (
                FnoSymbolParser,
            )

            _, exp_folder = FnoSymbolParser.parse(symbol)

        if not exp_folder:
            return base / f"{symbol}{self.ext}"
        return base / name / exp_folder / f"{symbol}{self.ext}"
