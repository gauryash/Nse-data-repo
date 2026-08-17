"""Unit tests for rate limiter."""

import time

from nse_data_pipeline.shared.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_initial_delay(self):
        limiter = RateLimiter(initial_delay=0.01, max_delay=1.0, backoff_factor=2.0)
        start = time.time()
        limiter.wait("test")
        elapsed = time.time() - start
        assert elapsed >= 0.01

    def test_backoff_increases_delay(self):
        limiter = RateLimiter(initial_delay=0.01, max_delay=1.0, backoff_factor=2.0)
        limiter.backoff("test")
        start = time.time()
        limiter.wait("test")
        elapsed = time.time() - start
        assert elapsed >= 0.02  # initial * 2

    def test_success_resets_delay(self):
        limiter = RateLimiter(initial_delay=0.01, max_delay=1.0, backoff_factor=2.0)
        limiter.backoff("test")
        limiter.backoff("test")
        limiter.success("test")
        start = time.time()
        limiter.wait("test")
        elapsed = time.time() - start
        assert elapsed < 0.02  # should be back to initial

    def test_max_delay_cap(self):
        limiter = RateLimiter(initial_delay=0.01, max_delay=0.05, backoff_factor=10.0)
        for _ in range(5):
            limiter.backoff("test")
        start = time.time()
        limiter.wait("test")
        elapsed = time.time() - start
        assert elapsed <= 0.06  # should be capped at max_delay

    def test_per_key_isolation(self):
        limiter = RateLimiter(initial_delay=0.01, max_delay=1.0, backoff_factor=2.0)
        limiter.backoff("key_a")
        start_b = time.time()
        limiter.wait("key_b")  # should not be affected by key_a's backoff
        elapsed_b = time.time() - start_b
        assert elapsed_b < 0.02  # should still be initial delay
