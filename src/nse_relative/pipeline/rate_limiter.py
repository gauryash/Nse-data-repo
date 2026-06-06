"""
Generic rate limiter with per-key exponential backoff (thread-safe).

Preserves the same interface the original ``fetcher.py`` used, but
decoupled so both NSE and Upstox providers can share it.
"""

import time
import threading

from nse_relative.config.settings import (
    RATE_MAX_WORKERS,
    RATE_INITIAL_DELAY,
    RATE_MAX_DELAY,
    RATE_BACKOFF_FACTOR,
)


class RateLimiter:
    """Per-key rate limiter with exponential backoff for HTTP 429 / throttling."""

    def __init__(
        self,
        max_workers: int = RATE_MAX_WORKERS,
        initial_delay: float = RATE_INITIAL_DELAY,
        max_delay: float = RATE_MAX_DELAY,
        backoff_factor: float = RATE_BACKOFF_FACTOR,
    ) -> None:
        self.max_workers = max_workers
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self._lock = threading.Lock()
        self._delays: dict[str, float] = {}

    def wait(self, key: str) -> None:
        """Sleep for the current delay associated with *key*."""
        with self._lock:
            delay = self._delays.get(key, self.initial_delay)
        time.sleep(delay)

    def backoff(self, key: str) -> None:
        """Increase the delay for *key* (multiplicative backoff)."""
        with self._lock:
            d = self._delays.get(key, self.initial_delay)
            self._delays[key] = min(d * self.backoff_factor, self.max_delay)

    def success(self, key: str) -> None:
        """Reset the delay for *key* after a successful request."""
        with self._lock:
            self._delays[key] = self.initial_delay
