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
