"""
Abstract base class for all data providers.

Each provider implements its own fetch logic (API endpoints, auth, rate
limiting), but all save data through the same storage interface so
analytics code can load it uniformly.

Providers accept their dependencies via constructor injection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from nse_data_pipeline.config.logger import get_logger

# ruff: noqa: ARG002 -- interface methods; args exist for callers, unused here

logger = get_logger(__name__)


class DataProvider(ABC):
    """Interface that every provider must implement.

    Dependencies (client, storage, checkpoint) are constructor-injected
    rather than imported at module level.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. ``'nse'`` or ``'upstox'``."""

    # ------------------------------------------------------------------
    # Fetch methods
    # ------------------------------------------------------------------

    def fetch_equities(self, symbols: list[str] | None = None) -> None:
        """Fetch daily / periodic equity data and persist to storage.

        Base implementation logs a skip message. Providers that support
        equities override this method.

        Args:
            symbols: Optional list of symbols to restrict fetching.
        """
        logger.info("%s: equity fetching not applicable — skip.", self.name)

    def fetch_index(self) -> None:
        """Fetch index / benchmark data (if available) and persist.

        Base implementation logs a skip message. Providers that support
        index data override this method.
        """
        logger.info("%s: index fetching not applicable — skip.", self.name)

    def fetch_options(
        self,
        symbols: list[str] | None = None,
        n_expiries: int | None = None,
        underlying: str | None = None,
        underlyings: list[str] | None = None,
    ) -> None:
        """Fetch historical options / F&O data and persist to storage.

        Base implementation logs a skip message. Providers that support
        options override this method.

        Args:
            symbols: Optional list of tradingsymbols to restrict fetching.
            n_expiries: Override number of upcoming expiry cycles.
            underlying: Single underlying name to restrict to.
            underlyings: Multiple underlying names to restrict to.
        """
        logger.info("%s: options fetching not implemented — skip.", self.name)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @abstractmethod
    def list_symbols(self) -> list[str]:
        """Return all symbols this provider knows about."""

    def __str__(self) -> str:
        return f"DataProvider({self.name})"
