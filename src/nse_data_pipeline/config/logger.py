"""Logging setup for the package."""

import logging
import sys

_LOG_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured with a standard format.

    The first call sets the level from ``NSE_LOG_LEVEL`` (default ``INFO``).
    Subsequent calls reuse the same config.
    """
    global _LOG_CONFIGURED

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    if not _LOG_CONFIGURED:
        _LOG_CONFIGURED = True
        # Set level on the root once
        from nse_data_pipeline.config.settings import settings

        logging.getLogger().setLevel(settings.log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)

    return logger
