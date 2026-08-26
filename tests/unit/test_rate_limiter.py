"""Tests for the sliding-window rate limiter."""

from __future__ import annotations

from app.application.services.rate_limiter import RateLimiter


def test_allows_requests_within_limit() -> None:
    limiter = RateLimiter(window_seconds=60.0)
    assert limiter.check("a", 3).allowed is True
    assert limiter.check("a", 3).allowed is True
    result = limiter.check("a", 3)
    assert result.allowed is True
    assert result.remaining == 0


def test_denies_requests_over_limit() -> None:
    limiter = RateLimiter(window_seconds=60.0)
    limiter.check("a", 2)
    limiter.check("a", 2)
    result = limiter.check("a", 2)
    assert result.allowed is False
    assert result.retry_after_ms >= 0


def test_keys_are_independent() -> None:
    limiter = RateLimiter(window_seconds=60.0)
    limiter.check("a", 1)
    assert limiter.check("b", 1).allowed is True


def test_zero_limit_denies_everything() -> None:
    limiter = RateLimiter()
    assert limiter.check("a", 0).allowed is False
