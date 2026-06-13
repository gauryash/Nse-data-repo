"""
Serialisation abstraction for Parquet and CSV storage formats.
"""

from __future__ import annotations

from os import PathLike

import pandas as pd


class FormatHandler:
    """Read/write :class:`pandas.DataFrame` in Parquet or CSV format.

    Args:
        storage_format: ``'parquet'`` (default) or ``'csv'``.
    """

    def __init__(self, storage_format: str = "parquet") -> None:
        self._fmt = storage_format

    @property
    def ext(self) -> str:
        return ".parquet" if self._fmt != "csv" else ".csv"

    def read(self, path: str | PathLike) -> pd.DataFrame:
        if self._fmt == "csv":
            return pd.read_csv(
                path,
                parse_dates=(["Date"] if "Date" in pd.read_csv(path, nrows=0).columns else False),
            )
        return pd.read_parquet(path, engine="fastparquet")

    def write(self, df: pd.DataFrame, path: str | PathLike) -> None:
        if self._fmt == "csv":
            df.to_csv(path, index=False)
        else:
            df.to_parquet(path, index=False, compression="gzip", engine="fastparquet")
