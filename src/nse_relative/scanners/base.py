"""
Abstract base class for all scanners.

Scanners are standalone: they call external REST APIs (Chartink, Screener.in,
Trendlyne, etc.) and send results to Telegram. They do **not** depend on the
data pipeline or analytics layers.
"""

from abc import ABC, abstractmethod


class BaseScanner(ABC):
    """Interface every scanner must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. ``'chartink'``, ``'composite'``, ``'sector'``."""
        ...

    @abstractmethod
    def run(self) -> None:
        """Execute the scanner and send results via Telegram."""
        ...
