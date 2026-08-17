"""
Abstract storage repository interface.

Defines the protocol that all storage backends must implement.
The current codebase has a single implementation (``FileStorageRepository``)
writing Parquet/CSV to the local filesystem, but the interface makes it
easy to add S3, GCS, or in-memory variants for testing.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class StorageRepository(Protocol):
    """Interface for persisting and loading financial data."""

    # ------------------------------------------------------------------
    # Equities (NSE-style: yearly partitioned + consolidated)
    # ------------------------------------------------------------------

    def save_equities(self, df: pd.DataFrame, provider: str) -> None:
        """Save equity data, partitioned by year.

        Args:
            df: DataFrame with at least ``Symbol`` and ``Date`` columns.
            provider: Provider name (e.g. ``'nse'``).
        """
        ...

    def load_equities(self, provider: str) -> pd.DataFrame:
        """Load the consolidated equities file for *provider*.

        Returns empty DataFrame if no data exists.
        """
        ...

    def rebuild_consolidated(self, provider: str) -> None:
        """Merge all yearly partitions into a single file."""
        ...

    def load_equities_yearly(self, provider: str) -> pd.DataFrame:
        """Load all yearly partitions as a single DataFrame."""
        ...

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def save_index(self, df: pd.DataFrame, provider: str) -> None:
        """Save index/benchmark data."""
        ...

    def load_index(self, provider: str) -> pd.DataFrame:
        """Load index/benchmark data."""
        ...

    # ------------------------------------------------------------------
    # Per-symbol (Upstox equity style)
    # ------------------------------------------------------------------

    def save_symbol(self, df: pd.DataFrame, provider: str, symbol: str) -> None:
        """Save data for a single symbol."""
        ...

    def load_symbol(self, provider: str, symbol: str) -> pd.DataFrame:
        """Load data for a single symbol."""
        ...

    def list_symbols(self, provider: str) -> list[str]:
        """List all symbols with stored data for *provider*."""
        ...

    # ------------------------------------------------------------------
    # Per-contract (Upstox F&O style)
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
        ...

    def load_option(
        self,
        provider: str,
        symbol: str,
        underlying: str | None = None,
        expiry_date: str | None = None,
    ) -> pd.DataFrame:
        """Load candle data for a single contract."""
        ...

    def list_option_symbols(self, provider: str) -> list[str]:
        """List all contract tradingsymbols with stored data."""
        ...

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @property
    def storage_format(self) -> str:
        """Return the file extension format (``'parquet'`` or ``'csv'``)."""
        ...
