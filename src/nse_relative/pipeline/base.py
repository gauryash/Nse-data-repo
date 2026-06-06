"""
Abstract base class for all data providers.

Each provider implements its own fetch logic (API endpoints, auth, rate limiting),
but all save data through the same ``storage`` module so analytics code can load
it uniformly.
"""

from abc import ABC, abstractmethod
from typing import Optional

from nse_relative.config.logger import get_logger

logger = get_logger(__name__)


class DataProvider(ABC):
    """Interface that every provider (NSE, Upstox, …) must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. ``'nse'`` or ``'upstox'``."""
        ...

    # ------------------------------------------------------------------
    # Fetch methods
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_equities(self, symbols: Optional[list[str]] = None) -> None:
        """Fetch daily / periodic equity data and persist to storage."""
        ...

    @abstractmethod
    def fetch_index(self) -> None:
        """Fetch index / benchmark data (if available) and persist."""
        ...

    def fetch_options(self, symbols: Optional[list[str]] = None) -> None:
        """Fetch historical options / F&O data and persist to storage.

        Base implementation logs a skip message. Providers that support
        options override this method.
        """
        logger.info("%s: options fetching not implemented — skip.", self.name)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @abstractmethod
    def list_symbols(self) -> list[str]:
        """Return all symbols this provider knows about."""
        ...

    def __str__(self) -> str:
        return f"DataProvider({self.name})"
