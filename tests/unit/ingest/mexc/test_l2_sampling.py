"""Unit tests for L2 orderbook sampler (D-46).

Tests cover:
  - Sampling cadence: only emit L2 records when sample_seconds has elapsed
  - JSONB-serializable bids/asks format via orjson
  - Per-symbol isolation

TDD cycle: RED phase — tests written before implementation.

Decisions honored:
  D-46: watch_order_book(symbol, limit=20); tier-1=5s, tier-2=10s cadences
"""

from __future__ import annotations

import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch


def _make_book(bids: list | None = None, asks: list | None = None) -> dict:
    """Build a minimal ccxt watch_order_book response dict."""
    ts_ms = int(time.time() * 1000)
    return {
        "timestamp": ts_ms,
        "bids": bids or [["100.0", "1.0"], ["99.0", "2.0"]],
        "asks": asks or [["101.0", "0.5"], ["102.0", "1.5"]],
    }


async def test_l2_sampler_respects_cadence() -> None:
    """l2_sample_loop only COPYs a record when sample_seconds has elapsed since last emit.

    Strategy: mock watch_order_book to return immediately; mock time.monotonic to
    advance time manually; assert copy_into_hypertable call count matches expected cadence.
    """
    from shortfire.ingest.mexc.orderbook import l2_sample_loop

    call_count = {"copy": 0}

    async def fake_copy(engine, table, records, columns, conflict_columns):  # type: ignore[no-untyped-def]
        call_count["copy"] += len(list(records))
        return call_count["copy"]

    book = _make_book()
    raw_mock = MagicMock()
    raw_mock.watch_order_book = AsyncMock(return_value=book)

    client_mock = MagicMock()
    client_mock.ws_client = raw_mock

    # Simulate 3 calls with time advancing: t=0, t=4 (< 5s, no emit), t=6 (> 5s, emit)
    monotonic_times = [0.0, 4.0, 6.0]
    mono_iter = iter(monotonic_times)
    last_call = [-1]

    def fake_monotonic() -> float:
        try:
            v = next(mono_iter)
            last_call[0] = v
            return v
        except StopIteration:
            return last_call[0] + 100.0  # far future → exits on cancel

    import asyncio

    call_count["iterations"] = 0

    async def patched_watch_order_book(sym, limit=20):  # type: ignore[no-untyped-def]
        call_count["iterations"] += 1
        if call_count["iterations"] > 3:
            raise asyncio.CancelledError()
        return book

    raw_mock.watch_order_book = patched_watch_order_book

    with (
        patch("shortfire.ingest.mexc.orderbook.copy_into_hypertable", side_effect=fake_copy),
        patch("shortfire.ingest.mexc.orderbook.time") as mock_time,
    ):
        mock_time.monotonic.side_effect = fake_monotonic
        mock_time.time.return_value = 1234567890.0

        with contextlib.suppress(asyncio.CancelledError):
            await l2_sample_loop(None, client_mock, "BTC/USDT:USDT", sample_seconds=5.0)  # type: ignore[arg-type]

    # At t=6 (>5s elapsed since last_emit=0), exactly 1 COPY should have fired
    assert call_count["copy"] == 1, f"Expected 1 L2 COPY at cadence 5s, got {call_count['copy']}"


async def test_l2_sampler_bids_asks_are_json_serializable() -> None:
    """bids/asks stored as orjson-serialized string lists (not raw floats)."""
    import orjson

    from shortfire.ingest.mexc.orderbook import l2_sample_loop

    copied_records = []

    async def capture_copy(engine, table, records, columns, conflict_columns):  # type: ignore[no-untyped-def]
        copied_records.extend(records)
        return len(list(records))

    book = _make_book(
        bids=[["48000.5", "0.01"], ["47999.0", "0.02"]],
        asks=[["48001.0", "0.005"], ["48002.0", "0.01"]],
    )

    raw_mock = MagicMock()
    call_count = {"n": 0}

    import asyncio

    async def patched_watch(*a, **kw):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()
        return book

    raw_mock.watch_order_book = patched_watch
    client_mock = MagicMock()
    client_mock.ws_client = raw_mock

    mono_calls = {"n": 0}

    def fake_mono() -> float:
        mono_calls["n"] += 1
        # Return large value so now - last_emit (0.0) > sample_seconds on first call
        return 999.0

    with (
        patch("shortfire.ingest.mexc.orderbook.copy_into_hypertable", side_effect=capture_copy),
        patch("shortfire.ingest.mexc.orderbook.time") as mock_time,
    ):
        mock_time.monotonic.side_effect = fake_mono
        mock_time.time.return_value = 1234567890.0

        with contextlib.suppress(asyncio.CancelledError):
            await l2_sample_loop(None, client_mock, "BTC/USDT:USDT", sample_seconds=5.0)  # type: ignore[arg-type]

    assert len(copied_records) == 1, "Should have captured exactly 1 record"
    _symbol, _ts, bids_str, asks_str, source, qf = copied_records[0]
    assert source == "mexc_native"
    assert qf == "ok"

    # Both bids and asks must be JSON-decodable lists-of-lists
    bids = orjson.loads(bids_str)
    asks = orjson.loads(asks_str)
    assert isinstance(bids, list), "bids must be a list"
    assert isinstance(bids[0], list), "each bid level must be a list [price, qty]"
    assert isinstance(asks[0], list), "each ask level must be a list [price, qty]"
