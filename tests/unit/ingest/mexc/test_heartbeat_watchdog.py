"""Unit tests for heartbeat watchdog (D-49 point 3).

Tests cover:
  - When all stream freshness values are recent (lag < 60s): no exception raised
  - When any stream freshness value exceeds HEARTBEAT_TIMEOUT_S (60s): RuntimeError raised
  - Hypothesis property: threshold boundary exact

TDD cycle: RED phase — tests written before implementation.

Decisions honored:
  D-49 point 3: heartbeat watchdog pings freshness gauge every 30s;
                raises RuntimeError when lag > 60s for any stream
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


async def test_heartbeat_watchdog_does_not_raise_when_fresh() -> None:
    """Watchdog should not raise when all gauge values are recent (lag < 60s)."""
    from shortfire.ingest.mexc.streams import _heartbeat_watchdog

    raw_mock = MagicMock()
    client_mock = MagicMock()
    client_mock.ws_client = raw_mock

    # Simulate gauge samples with recent timestamps (10s lag)
    now_unix = time.time()
    gauge_value = now_unix - 10.0  # 10 seconds ago — fresh

    mock_sample = MagicMock()
    mock_sample.labels = {"source": "mexc_native", "dataset": "candles_1m", "symbol": "BTC/USDT:USDT"}
    mock_sample.value = gauge_value

    mock_gauge_family = MagicMock()
    mock_gauge_family.samples = [mock_sample]

    mock_metrics = MagicMock()
    mock_metrics.source_freshness_seconds.collect.return_value = [mock_gauge_family]

    shutdown_event = asyncio.Event()
    # Signal shutdown after first sleep so the loop exits
    shutdown_calls = {"n": 0}

    def fake_is_set() -> bool:
        shutdown_calls["n"] += 1
        return shutdown_calls["n"] > 1  # exit after second check

    shutdown_event.is_set = fake_is_set  # type: ignore[method-assign]

    with (
        patch("shortfire.ingest.mexc.streams.build_data_platform_metrics", return_value=mock_metrics),
        patch("shortfire.ingest.mexc.streams.asyncio.sleep", new_callable=AsyncMock),
        patch("shortfire.ingest.mexc.streams.time") as mock_time,
    ):
        mock_time.monotonic.return_value = 0.0
        mock_time.time.return_value = now_unix

        # Should not raise — all gauges are fresh
        await _heartbeat_watchdog(client_mock, ("candles_1m",), shutdown_event)


async def test_heartbeat_watchdog_raises_on_stale_stream() -> None:
    """Watchdog raises RuntimeError when a stream gauge lag exceeds HEARTBEAT_TIMEOUT_S."""
    from shortfire.ingest.mexc.streams import HEARTBEAT_TIMEOUT_S, _heartbeat_watchdog

    client_mock = MagicMock()

    now_unix = time.time()
    # Gauge value is 90 seconds ago → stale (> 60s threshold)
    stale_value = now_unix - (HEARTBEAT_TIMEOUT_S + 30.0)

    mock_sample = MagicMock()
    mock_sample.labels = {"source": "mexc_native", "dataset": "candles_1m", "symbol": "BTC/USDT:USDT"}
    mock_sample.value = stale_value

    mock_gauge_family = MagicMock()
    mock_gauge_family.samples = [mock_sample]

    mock_metrics = MagicMock()
    mock_metrics.source_freshness_seconds.collect.return_value = [mock_gauge_family]

    shutdown_event = asyncio.Event()
    shutdown_event.is_set = MagicMock(return_value=False)  # type: ignore[method-assign]

    with (
        patch("shortfire.ingest.mexc.streams.build_data_platform_metrics", return_value=mock_metrics),
        patch("shortfire.ingest.mexc.streams.asyncio.sleep", new_callable=AsyncMock),
        patch("shortfire.ingest.mexc.streams.time") as mock_time,
    ):
        mock_time.monotonic.return_value = 0.0
        mock_time.time.return_value = now_unix

        with pytest.raises(RuntimeError, match="stale"):
            await _heartbeat_watchdog(client_mock, ("candles_1m",), shutdown_event)


@settings(max_examples=50, deadline=None)
@given(lag_seconds=st.floats(min_value=0.0, max_value=200.0))
@pytest.mark.asyncio
async def test_heartbeat_watchdog_invariant(lag_seconds: float) -> None:
    """Property: lag > 60s → RuntimeError; lag <= 60s → no raise."""
    from shortfire.ingest.mexc.streams import HEARTBEAT_TIMEOUT_S, _heartbeat_watchdog

    client_mock = MagicMock()
    now_unix = time.time()
    gauge_value = now_unix - lag_seconds

    mock_sample = MagicMock()
    mock_sample.labels = {"source": "mexc_native", "dataset": "candles_1m"}
    mock_sample.value = gauge_value

    mock_gauge_family = MagicMock()
    mock_gauge_family.samples = [mock_sample]

    mock_metrics = MagicMock()
    mock_metrics.source_freshness_seconds.collect.return_value = [mock_gauge_family]

    shutdown_event = asyncio.Event()
    # is_set: False on first check (enter loop), True on second check (exit loop)
    is_set_calls = {"n": 0}

    def fake_is_set() -> bool:
        is_set_calls["n"] += 1
        return is_set_calls["n"] > 1  # exit after one iteration

    shutdown_event.is_set = fake_is_set  # type: ignore[method-assign]

    raised = False
    with (
        patch("shortfire.ingest.mexc.streams.build_data_platform_metrics", return_value=mock_metrics),
        patch("shortfire.ingest.mexc.streams.asyncio.sleep", new_callable=AsyncMock),
        patch("shortfire.ingest.mexc.streams.time") as mock_time,
    ):
        mock_time.monotonic.return_value = 0.0
        mock_time.time.return_value = now_unix

        try:
            await _heartbeat_watchdog(client_mock, ("candles_1m",), shutdown_event)
        except RuntimeError:
            raised = True

    if lag_seconds > HEARTBEAT_TIMEOUT_S:
        assert raised, f"Expected RuntimeError for lag={lag_seconds}s (>{HEARTBEAT_TIMEOUT_S}s)"
    else:
        assert not raised, f"Expected no exception for lag={lag_seconds}s (<={HEARTBEAT_TIMEOUT_S}s)"
