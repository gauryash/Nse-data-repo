"""
Pipeline orchestrator — builds providers and dispatches fetch requests.
"""

from __future__ import annotations

from nse_data_pipeline.config.logger import get_logger
from nse_data_pipeline.config.settings import settings
from nse_data_pipeline.infrastructure.api.nse_client import NseClient
from nse_data_pipeline.infrastructure.api.upstox_client import UpstoxClient
from nse_data_pipeline.infrastructure.storage.file_repository import (
    FileStorageRepository,
)
from nse_data_pipeline.pipeline.base import DataProvider

logger = get_logger(__name__)


class PipelineOrchestrator:
    """Central fetch orchestrator.

    Builds the appropriate provider and dispatches the right fetch
    method based on provider type.
    """

    def __init__(self) -> None:
        self._storage = FileStorageRepository()
        self._nse_client = NseClient()
        self._upstox_client = UpstoxClient()

    # ------------------------------------------------------------------
    # Provider construction
    # ------------------------------------------------------------------

    def fetch(
        self,
        provider: str,
        index: str = "",
        underlying: str | None = None,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        interval: str | None = None,
        instrument_types: str | None = None,
        include_futures: bool = False,
        n_expiries: int = 2,
        force: bool = False,
        skip_index: bool = False,
    ) -> None:
        """Fetch data from the specified provider.

        Args:
            provider: One of ``'nse'``, ``'upstox'``, ``'upstox_options'``.
            index: NSE index name for symbol sourcing.
            underlying: Single underlying name to restrict F&O fetch.
            symbols: Optional list of specific symbols to fetch.
            start_date: Fetch start (DD-MM-YYYY).
            end_date: Fetch end (DD-MM-YYYY).
            interval: Candle interval (day/week/month).
            instrument_types: F&O instrument types (for upstox_options).
            include_futures: Include FUTSTK/FUTIDX.
            n_expiries: Number of upcoming expiry cycles.
            force: Ignore checkpoint and re-fetch.
            skip_index: Skip index data (NSE only).
        """
        providers = {
            "nse": self._build_nse_provider(
                index=index,
                start_date=start_date,
                end_date=end_date,
                force=force,
            ),
            "upstox": self._build_upstox_provider(
                interval=interval or "",
                index=index,
                start_date=start_date,
                end_date=end_date,
                force=force,
            ),
            "upstox_options": self._build_upstox_options_provider(
                interval=interval or "",
                index=index,
                instrument_types=instrument_types,
                include_futures=include_futures,
                n_expiries=n_expiries,
                start_date=start_date,
                end_date=end_date,
                force=force,
            ),
        }

        p = providers.get(provider)
        if p is None:
            msg = f"Unknown provider '{provider}'. Known: {list(providers)}"
            raise ValueError(msg)

        if provider == "nse":
            p.fetch_equities(symbols=symbols)
            if not skip_index:
                p.fetch_index()
        elif provider == "upstox":
            p.fetch_equities(symbols=symbols)
        elif provider == "upstox_options":
            p.fetch_options(symbols=symbols, underlying=underlying)

    def _build_nse_provider(
        self,
        index: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        force: bool = False,
    ) -> DataProvider:
        from nse_data_pipeline.pipeline.nse_provider import NSEProvider

        return NSEProvider(
            index=index or "nifty500",
            start_date=start_date,
            end_date=end_date,
            force=force,
            client=self._nse_client,
            storage=self._storage,
        )

    def _build_upstox_provider(
        self,
        interval: str = "",
        index: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        force: bool = False,
    ) -> DataProvider:
        from nse_data_pipeline.pipeline.upstox_provider import UpstoxProvider

        return UpstoxProvider(
            interval=interval or settings.upstox_interval.value,
            index=index or "nifty500",
            start_date=start_date,
            end_date=end_date,
            force=force,
            client=self._upstox_client,
            storage=self._storage,
        )

    def _build_upstox_options_provider(
        self,
        interval: str = "",
        index: str = "",
        instrument_types: str | None = None,
        include_futures: bool = False,
        n_expiries: int = 2,
        start_date: str | None = None,
        end_date: str | None = None,
        force: bool = False,
    ) -> DataProvider:
        from nse_data_pipeline.pipeline.upstox_options_provider import (
            UpstoxOptionsProvider,
        )

        return UpstoxOptionsProvider(
            interval=interval or settings.upstox_options_interval.value,
            index=index or "nifty500",
            instrument_types=instrument_types,
            include_futures=include_futures,
            n_expiries=n_expiries,
            start_date=start_date,
            end_date=end_date,
            force=force,
            client=self._upstox_client,
            storage=self._storage,
        )
