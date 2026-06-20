"""
Contract manifest — an expiry-queryable catalog of all fetched F&O contracts.

The manifest is stored as ``_contracts.parquet`` in the provider's storage
directory.  It enables O(1) queries like "all CE contracts for NIFTY expiring
on 2026-06-09" without loading individual parquet files.

The manifest is always stored in Parquet format regardless of
``NSE_STORAGE_FORMAT`` because it is an internal index, not user-facing data.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.infrastructure.storage.file_repository import FileStorageRepository

logger = get_logger(__name__)

# Mirrors OptionContract._CONTRACT_COLUMNS with "underlying_name" instead of "name".
MANIFEST_COLUMNS = [
    "instrument_key",
    "tradingsymbol",
    "underlying_name",
    "underlying_type",
    "instrument_type",
    "option_type",
    "expiry",
    "strike",
    "lot_size",
    "tick_size",
]


class ContractManifest:
    """Manages the contract manifest for a provider.

    The manifest is a deduplicated parquet file cataloguing all F&O
    contracts that have been discovered and/or fetched.

    Args:
        storage: FileStorageRepository instance for path resolution.
        provider: Provider name (e.g. ``'upstox_options'``).
    """

    def __init__(
        self,
        storage: FileStorageRepository,
        provider: str,
    ) -> None:
        self._storage = storage
        self._provider = provider

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> pd.DataFrame:
        """Load the contract manifest.

        Returns:
            DataFrame with manifest columns, or empty if no manifest exists.
        """
        path = self._storage.manifest_path(self._provider)
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path, engine=self._parquet_engine())
        if "expiry" in df.columns:
            df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
        return df

    def save(self, contracts_df: pd.DataFrame) -> None:
        """Save/update the contract manifest.

        Deduplicates by ``tradingsymbol`` so each contract appears only once.

        Args:
            contracts_df: DataFrame with columns matching ``MANIFEST_COLUMNS``.
                The column ``name`` is accepted as an alias for ``underlying_name``.
        """
        if contracts_df.empty:
            return

        path = self._storage.manifest_path(self._provider)
        df = contracts_df.copy()

        # Normalise column names
        if "name" in df.columns and "underlying_name" not in df.columns:
            df.rename(columns={"name": "underlying_name"}, inplace=True)
        elif "name" in df.columns and "underlying_name" in df.columns:
            df.drop(columns=["name"], inplace=True)

        cols = [c for c in MANIFEST_COLUMNS if c in df.columns]
        engine = self._parquet_engine()

        if path.exists():
            existing = pd.read_parquet(path, engine=engine)
            combined = pd.concat([existing, df[cols]], ignore_index=True)
            combined = combined.drop_duplicates(subset=["tradingsymbol"], keep="last")
        else:
            combined = df[cols].copy()

        # Normalise expiry to string for consistent storage
        if "expiry" in combined.columns:
            combined["expiry"] = combined["expiry"].astype(str)

        combined.to_parquet(path, index=False, compression="gzip", engine=engine)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        underlying_name: str | None = None,
        expiry: str | date | None = None,
        option_type: str | None = None,
        instrument_type: str | None = None,
    ) -> pd.DataFrame:
        """Query the contract manifest with optional filters.

        Args:
            underlying_name: Filter by underlying name.
            expiry: Filter by expiry date (string ``'YYYY-MM-DD'`` or ``date``).
            option_type: Filter by ``'CE'`` or ``'PE'``.
            instrument_type: Filter by ``'OPTSTK'``, ``'OPTIDX'``, etc.

        Returns:
            Filtered DataFrame, or empty if no matches.
        """
        df = self.load()
        if df.empty:
            return df
        if underlying_name is not None:
            df = df[df["underlying_name"] == underlying_name]
        if expiry is not None:
            expiry_str = str(expiry)
            df = df[df["expiry"].astype(str) == expiry_str]
        if option_type is not None:
            df = df[df["option_type"] == option_type]
        if instrument_type is not None:
            df = df[df["instrument_type"] == instrument_type]
        return df

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parquet_engine() -> str:
        """Return 'pyarrow' if available, else 'fastparquet'."""
        try:
            import pyarrow  # noqa: F401

            return "pyarrow"
        except ImportError:
            return "fastparquet"

    @staticmethod
    def build_checkpoint_entry(row: pd.Series) -> dict:
        """Build a metadata dict for an option contract from a CSV row.

        Returns a dict suitable for storing in the checkpoint.
        """
        return {
            "instrument_type": row.get("instrument_type", ""),
            "option_type": row.get("option_type", ""),
            "expiry": str(row.get("expiry", "")),
            "strike": float(row["strike"]) if pd.notna(row.get("strike")) else None,
            "lot_size": int(row["lot_size"]) if pd.notna(row.get("lot_size")) else None,
            "underlying_name": row.get("name", ""),
        }
