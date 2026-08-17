"""Domain-specific exceptions for the data pipeline."""


class DataPipelineError(Exception):
    """Base exception for all pipeline errors."""


class ProviderError(DataPipelineError):
    """Raised when a data provider encounters an error."""


class StorageError(DataPipelineError):
    """Raised on storage read/write failures."""


class SymbolResolutionError(DataPipelineError):
    """Raised when symbol/contract resolution fails."""


class ConfigurationError(DataPipelineError):
    """Raised when required configuration is missing or invalid."""


class CheckpointError(DataPipelineError):
    """Raised on checkpoint read/write failures."""


class UnknownUnderlyingError(DataPipelineError):
    """Raised when a requested underlying/expiry is not in the catalog."""


class SubscriptionLimitExceeded(DataPipelineError):
    """Raised when subscribing would exceed the Upstox feed key budget.

    Attributes:
        required: Number of instrument keys the operation would need.
        current: Number of keys currently subscribed.
        limit: Maximum allowed keys (mode-dependent).
    """

    def __init__(
        self,
        message: str,
        *,
        required: int = 0,
        current: int = 0,
        limit: int = 0,
    ) -> None:
        super().__init__(message)
        self.required = required
        self.current = current
        self.limit = limit
