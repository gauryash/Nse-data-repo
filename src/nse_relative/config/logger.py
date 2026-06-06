"""Logging setup for the package."""
import logging
import sys

from nse_relative.config.settings import LOG_LEVEL


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured with a standard format."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(LOG_LEVEL)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(LOG_LEVEL)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)

    return logger
