"""Tests for per-source aiolimiter rate limiters (D-51, D-56, D-73).

Tests:
  1. All three limiters are importable and are AsyncLimiter instances
  2. MEXC_LIMITER: max_rate=18, time_period=1 (D-73)
  3. COINGLASS_LIMITER: max_rate=28, time_period=60 (D-51, 5% headroom under 30 req/min)
  4. COINGECKO_LIMITER: max_rate=28, time_period=60 (D-56, same headroom as Coinglass)
"""

from aiolimiter import AsyncLimiter


def test_rate_limiters_are_importable() -> None:
    """All three limiters import without error."""
    from shortfire.ingest.rate_limit import COINGECKO_LIMITER, COINGLASS_LIMITER, MEXC_LIMITER

    assert MEXC_LIMITER is not None
    assert COINGLASS_LIMITER is not None
    assert COINGECKO_LIMITER is not None


def test_rate_limiters_are_async_limiter_instances() -> None:
    """Each limiter is an aiolimiter.AsyncLimiter instance."""
    from shortfire.ingest.rate_limit import COINGECKO_LIMITER, COINGLASS_LIMITER, MEXC_LIMITER

    assert isinstance(MEXC_LIMITER, AsyncLimiter)
    assert isinstance(COINGLASS_LIMITER, AsyncLimiter)
    assert isinstance(COINGECKO_LIMITER, AsyncLimiter)


def test_mexc_limiter_rate() -> None:
    """MEXC_LIMITER has max_rate=18 (D-73 — defense-in-depth under 20 req/s public quota)."""
    from shortfire.ingest.rate_limit import MEXC_LIMITER

    assert MEXC_LIMITER.max_rate == 18


def test_mexc_limiter_period() -> None:
    """MEXC_LIMITER has time_period=1 second."""
    from shortfire.ingest.rate_limit import MEXC_LIMITER

    assert MEXC_LIMITER.time_period == 1


def test_coinglass_limiter_rate() -> None:
    """COINGLASS_LIMITER has max_rate=28 (D-51 — 5% headroom under 30 req/min Hobbyist)."""
    from shortfire.ingest.rate_limit import COINGLASS_LIMITER

    assert COINGLASS_LIMITER.max_rate == 28


def test_coinglass_limiter_period() -> None:
    """COINGLASS_LIMITER has time_period=60 seconds."""
    from shortfire.ingest.rate_limit import COINGLASS_LIMITER

    assert COINGLASS_LIMITER.time_period == 60


def test_coingecko_limiter_rate() -> None:
    """COINGECKO_LIMITER has max_rate=28 (D-56 — same headroom shape as Coinglass)."""
    from shortfire.ingest.rate_limit import COINGECKO_LIMITER

    assert COINGECKO_LIMITER.max_rate == 28


def test_coingecko_limiter_period() -> None:
    """COINGECKO_LIMITER has time_period=60 seconds."""
    from shortfire.ingest.rate_limit import COINGECKO_LIMITER

    assert COINGECKO_LIMITER.time_period == 60
