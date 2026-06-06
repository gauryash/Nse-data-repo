"""
Abstract base class for analytics modules.

Every analyzer reads data from a storage backend, processes it,
and writes results (CSV / Excel / etc.).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BaseAnalyzer(ABC):
    """Interface that every analytics module must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. ``'rs'`` or ``'vwap'``."""
        ...

    @abstractmethod
    def run(self, output_path: Optional[str | Path] = None, **kwargs) -> None:
        """Load data, compute, persist results."""
        ...
