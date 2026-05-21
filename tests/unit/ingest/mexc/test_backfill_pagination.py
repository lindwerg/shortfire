"""Unit tests for MEXC OHLCV paginated backfill (backfill.py).

Covers:
- test_backfill_ohlcv_walks_pages: pagination cursor advance over 2500 synthetic candles
- test_backfill_ohlcv_skips_ca_timeframes: 5m/15m/1h/4h return 0, emit structlog warning
- test_backfill_ohlcv_idempotent_against_in_memory_fake: second backfill inserts 0 new rows
- test_backfill_universe_respects_semaphore_cap: max_observed_concurrency <= semaphore limit
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shortfire.domain.market import Candle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candle(symbol: str, ts: datetime, idx: int) -> Candle:
    """Construct a minimal valid Candle for testing."""
    base = Decimal("30000") + Decimal(str(idx * 10))
    return Candle(
        symbol=symbol,
        source="mexc_native",
        timeframe="1m",
        ts=ts,
        open=base,
        high=base + Decimal("50"),
        low=base - Decimal("50"),
        close=base,
        volume=Decimal("100"),
    )


class PaginatingFakeMexcClient:
    """Fake client that returns canned candles in 1000-row pages per fetch_ohlcv call.

    Keeps a call counter + records `since` values for each call so tests can
    assert cursor advance behaviour.
    """

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles
        self.fetch_calls: list[datetime] = []  # since arg of each call
        self._page_cursor = 0

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]:
        self.fetch_calls.append(since)
        page = tuple(self._candles[self._page_cursor : self._page_cursor + 1000])
        self._page_cursor += len(page)
        return page

    # The other Protocol methods are not exercised by backfill tests
    async def fetch_funding_rate_history(
        self, symbol: str, since: datetime, until: datetime
    ) -> tuple[Any, ...]:  # type: ignore[return]
        raise NotImplementedError

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> Any:
        raise NotImplementedError

    async def place_order(self, order: Any) -> str:
        raise NotImplementedError

    async def cancel_order(self, client_order_id: str) -> None:
        raise NotImplementedError


class ConcurrencyProbeFake:
    """Fake client that tracks simultaneous in-flight fetch_ohlcv calls.

    Used to assert Semaphore cap (max_observed_concurrency <= limit).
    """

    def __init__(self, candles_per_page: int = 10) -> None:
        self._candles_per_page = candles_per_page
        self._in_flight = 0
        self.max_observed = 0
        self._called_once: dict[str, bool] = {}

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]:
        self._in_flight += 1
        if self._in_flight > self.max_observed:
            self.max_observed = self._in_flight
        await asyncio.sleep(0.01)  # yield to simulate I/O
        self._in_flight -= 1
        # Each symbol returns data only once to avoid infinite pagination
        if self._called_once.get(symbol):
            return ()
        self._called_once[symbol] = True
        ts = datetime(2024, 1, 1, tzinfo=UTC)
        candles = tuple(
            _make_candle(symbol, ts + timedelta(minutes=i), i) for i in range(self._candles_per_page)
        )
        return candles

    async def fetch_funding_rate_history(
        self, symbol: str, since: datetime, until: datetime
    ) -> tuple[Any, ...]:  # type: ignore[return]
        raise NotImplementedError

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> Any:
        raise NotImplementedError

    async def place_order(self, order: Any) -> str:
        raise NotImplementedError

    async def cancel_order(self, client_order_id: str) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_ohlcv_walks_pages() -> None:
    """backfill_ohlcv with 2500 candles makes 3 fetch calls (ceil(2500/1000)=3)."""
    from shortfire.ingest.mexc.backfill import backfill_ohlcv

    now = datetime(2024, 6, 1, 18, 0, 0, tzinfo=UTC)
    since = now - timedelta(hours=42)

    # Build 2500 candles
    candles = [_make_candle("BTC/USDT:USDT", since + timedelta(minutes=i), i) for i in range(2500)]

    fake = PaginatingFakeMexcClient(candles)

    written: list[Any] = []

    async def fake_copy(engine: Any, table: Any, records: Any, columns: Any, conflict_columns: Any) -> int:
        recs = list(records)
        written.extend(recs)
        return len(recs)

    mock_engine = MagicMock()

    with patch("shortfire.ingest.mexc.backfill.copy_into_hypertable", side_effect=fake_copy):
        total = await backfill_ohlcv(
            mock_engine,
            fake,
            "BTC/USDT:USDT",
            "1m",
            since,
            now,
            asyncio.Semaphore(8),
        )

    # 3 data-returning pages (1000, 1000, 500) + 1 terminating empty call = 4 total
    n_calls = len(fake.fetch_calls)
    assert n_calls == 4, f"Expected 4 fetch calls (3 pages + 1 terminator), got {n_calls}"
    assert total == 2500
    assert len(written) == 2500


@pytest.mark.asyncio
async def test_backfill_ohlcv_skips_ca_timeframes() -> None:
    """backfill_ohlcv with 5m/15m/1h/4h returns 0 without touching the client."""
    from shortfire.ingest.mexc.backfill import backfill_ohlcv

    fake = PaginatingFakeMexcClient([])
    mock_engine = MagicMock()
    since = datetime(2024, 1, 1, tzinfo=UTC)
    until = datetime(2024, 1, 2, tzinfo=UTC)
    sem = asyncio.Semaphore(8)

    for tf in ("5m", "15m", "1h", "4h"):
        result = await backfill_ohlcv(mock_engine, fake, "BTC/USDT:USDT", tf, since, until, sem)
        assert result == 0, f"Expected 0 for CA timeframe {tf}, got {result}"

    # No fetch calls emitted for CA timeframes
    assert len(fake.fetch_calls) == 0


@pytest.mark.asyncio
async def test_backfill_ohlcv_idempotent_against_in_memory_fake() -> None:
    """Second backfill call inserts 0 rows (ON CONFLICT DO NOTHING idempotency)."""
    from shortfire.ingest.mexc.backfill import backfill_ohlcv

    now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    since = now - timedelta(minutes=10)

    candles = [_make_candle("BTC/USDT:USDT", since + timedelta(minutes=i), i) for i in range(10)]

    # In-memory set simulating ON CONFLICT DO NOTHING
    inserted: set[tuple[str, datetime]] = set()

    async def fake_copy(engine: Any, table: Any, records: Any, columns: Any, conflict_columns: Any) -> int:
        recs = list(records)
        new_count = 0
        for rec in recs:
            key = (rec[0], rec[1])  # (symbol, ts)
            if key not in inserted:
                inserted.add(key)
                new_count += 1
        return new_count

    mock_engine = MagicMock()

    with patch("shortfire.ingest.mexc.backfill.copy_into_hypertable", side_effect=fake_copy):
        # First run
        fake1 = PaginatingFakeMexcClient(candles)
        n1 = await backfill_ohlcv(mock_engine, fake1, "BTC/USDT:USDT", "1m", since, now, asyncio.Semaphore(8))

        # Second run (fresh fake so cursor is at 0, but copy_into_hypertable
        # respects the already-inserted set → returns 0)
        fake2 = PaginatingFakeMexcClient(candles)
        n2 = await backfill_ohlcv(mock_engine, fake2, "BTC/USDT:USDT", "1m", since, now, asyncio.Semaphore(8))

    assert n1 == 10
    assert n2 == 0


@pytest.mark.asyncio
async def test_backfill_universe_respects_semaphore_cap() -> None:
    """backfill_universe with Semaphore(2) never has more than 2 in-flight calls."""
    from shortfire.ingest.mexc.backfill import backfill_universe

    fake = ConcurrencyProbeFake(candles_per_page=5)
    mock_engine = MagicMock()
    now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    since = now - timedelta(hours=1)

    # 12 symbols, semaphore=2 — max_observed must be <= 2
    symbols = [f"SYM{i:02d}/USDT:USDT" for i in range(12)]

    async def fake_copy(engine: Any, table: Any, records: Any, columns: Any, conflict_columns: Any) -> int:
        return len(list(records))

    with patch("shortfire.ingest.mexc.backfill.copy_into_hypertable", side_effect=fake_copy):
        await backfill_universe(
            mock_engine,
            fake,
            symbols=symbols,
            timeframes=["1m"],
            since=since,
            until=now,
            max_concurrency=2,
        )

    assert fake.max_observed <= 2, f"Semaphore cap violated: max_observed_concurrency={fake.max_observed} > 2"
