"""Tests for per-source tenacity retry decorators (D-72).

Tests:
  1. All three decorators are importable and callable
  2. Per-source stop_after_attempt values: mexc=6, coinglass=5, coingecko=4
  3. mexc_retry catches TimeoutError; coinglass_retry and coingecko_retry do NOT
  4. coinglass_retry uses wait_exponential_jitter with initial=1.0, max=60.0
  5. mexc_retry uses wait_exponential_jitter with initial=2.0, max=120.0
  6. All decorators have reraise=True
"""

from typing import Any

import httpx
import pytest
from tenacity import RetryError


def test_retry_decorators_are_importable() -> None:
    """All three retry decorators import without error (D-72)."""
    from shortfire.ingest.retry import coingecko_retry, coinglass_retry, mexc_retry

    assert callable(mexc_retry)
    assert callable(coinglass_retry)
    assert callable(coingecko_retry)


def _get_retrying(decorator: Any) -> Any:
    """Apply decorator to a stub function and return the Retrying config object."""

    @decorator
    def stub() -> None:
        pass

    return stub.retry  # type: ignore[attr-defined]


def test_retry_stop_attempts_mexc() -> None:
    """mexc_retry stops after 6 attempts (D-72)."""
    from shortfire.ingest.retry import mexc_retry

    retrying = _get_retrying(mexc_retry)
    assert retrying.stop.max_attempt_number == 6


def test_retry_stop_attempts_coinglass() -> None:
    """coinglass_retry stops after 5 attempts (D-72)."""
    from shortfire.ingest.retry import coinglass_retry

    retrying = _get_retrying(coinglass_retry)
    assert retrying.stop.max_attempt_number == 5


def test_retry_stop_attempts_coingecko() -> None:
    """coingecko_retry stops after 4 attempts (D-72)."""
    from shortfire.ingest.retry import coingecko_retry

    retrying = _get_retrying(coingecko_retry)
    assert retrying.stop.max_attempt_number == 4


def test_mexc_wait_initial_and_max() -> None:
    """mexc_retry uses wait_exponential_jitter(initial=2.0, max=120.0) (D-72)."""
    from shortfire.ingest.retry import mexc_retry

    retrying = _get_retrying(mexc_retry)
    assert retrying.wait.initial == 2.0
    assert retrying.wait.max == 120.0


def test_coinglass_wait_initial_and_max() -> None:
    """coinglass_retry uses wait_exponential_jitter(initial=1.0, max=60.0) (D-72)."""
    from shortfire.ingest.retry import coinglass_retry

    retrying = _get_retrying(coinglass_retry)
    assert retrying.wait.initial == 1.0
    assert retrying.wait.max == 60.0


def test_coingecko_wait_initial_and_max() -> None:
    """coingecko_retry uses wait_exponential_jitter(initial=1.0, max=60.0) (D-72)."""
    from shortfire.ingest.retry import coingecko_retry

    retrying = _get_retrying(coingecko_retry)
    assert retrying.wait.initial == 1.0
    assert retrying.wait.max == 60.0


def test_mexc_retry_catches_timeout_error() -> None:
    """mexc_retry retries on TimeoutError (D-72 — MEXC also retries on TimeoutError)."""
    from shortfire.ingest.retry import mexc_retry

    call_count = 0

    @mexc_retry
    async def _raises_timeout() -> None:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("simulated timeout")

    with pytest.raises((TimeoutError, RetryError)):
        import asyncio

        asyncio.get_event_loop().run_until_complete(_raises_timeout())

    # Should have retried 6 times before giving up
    assert call_count == 6


def test_coinglass_retry_does_not_catch_timeout_error() -> None:
    """coinglass_retry does NOT retry on TimeoutError (D-72 — only MEXC does)."""
    from shortfire.ingest.retry import coinglass_retry

    call_count = 0

    @coinglass_retry
    async def _raises_timeout() -> None:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("simulated timeout")

    # TimeoutError should propagate immediately (no retries) for coinglass
    with pytest.raises(TimeoutError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(_raises_timeout())

    # Should NOT have retried — first call then immediate re-raise
    assert call_count == 1


def test_coingecko_retry_does_not_catch_timeout_error() -> None:
    """coingecko_retry does NOT retry on TimeoutError (D-72 — only MEXC does)."""
    from shortfire.ingest.retry import coingecko_retry

    call_count = 0

    @coingecko_retry
    async def _raises_timeout() -> None:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("simulated timeout")

    with pytest.raises(TimeoutError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(_raises_timeout())

    assert call_count == 1


def test_coinglass_retry_catches_transport_error() -> None:
    """coinglass_retry retries on httpx.TransportError (D-72)."""
    from shortfire.ingest.retry import coinglass_retry

    call_count = 0

    @coinglass_retry
    async def _raises_transport() -> None:
        nonlocal call_count
        call_count += 1
        raise httpx.TransportError("network error")

    with pytest.raises((httpx.TransportError, RetryError)):
        import asyncio

        asyncio.get_event_loop().run_until_complete(_raises_transport())

    # Should have attempted 5 times (coinglass stop_after_attempt=5)
    assert call_count == 5


def test_mexc_retry_reraise_true() -> None:
    """mexc_retry re-raises the original exception after exhausting retries (reraise=True)."""
    from shortfire.ingest.retry import mexc_retry

    @mexc_retry
    async def _raises_http() -> None:
        # Create a real httpx.HTTPStatusError
        request = httpx.Request("GET", "https://example.com")
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(_raises_http())
