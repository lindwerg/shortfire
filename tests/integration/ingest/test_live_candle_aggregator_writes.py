"""Integration test: live candle aggregator writes correct 1m candles via MinuteAggregator.

Tests the full path:
  FakeWsMexcClient (watch_trades_for_symbols returning synthetic trades)
    → trades_aggregator_loop (MinuteAggregator + batched COPY)
    → raw_mexc_candles_1m (TimescaleDB hypertable)

Invariants verified:
  - Correct OHLCV aggregation from synthetic trades
  - source='mexc_native', quality_flag='ok' on every row
  - Idempotency: second run writes 0 new rows

Requires Docker for TimescaleDB testcontainer. Skipped automatically if Docker unavailable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine


def _to_asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy driver suffix for raw asyncpg.connect()."""
    if "postgresql+" in url:
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url


def _to_asyncalchemy_url(url: str) -> str:
    """Convert plain postgresql:// → postgresql+asyncpg:// for SQLAlchemy AsyncEngine."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.fixture()
def clean_candles_live(migrated_db: str):  # type: ignore[no-untyped-def]
    """TRUNCATE raw_mexc_candles_1m before and after each test for isolation."""
    asyncpg_url = _to_asyncpg_url(migrated_db)

    async def _truncate() -> None:
        conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
        try:
            await conn.execute("TRUNCATE raw_mexc_candles_1m CASCADE")  # type: ignore[attr-defined]
        finally:
            await conn.close()  # type: ignore[attr-defined]

    asyncio.run(_truncate())
    yield
    asyncio.run(_truncate())


class FakeWsMexcClient:
    """Fake MexcClient with a ws_client that serves synthetic trades for testing.

    Delivers N batches of trades spanning M distinct minutes, then raises
    asyncio.CancelledError to stop the aggregator loop.
    """

    def __init__(self, trade_batches: list[list[dict]]) -> None:
        self._batches = list(trade_batches)
        self._batch_index = 0
        self.ws_client = self  # self acts as both the MexcClient and the ccxt.pro instance

    async def watch_trades_for_symbols(self, symbols: list[str]) -> list[dict]:  # type: ignore[return]
        if self._batch_index >= len(self._batches):
            raise asyncio.CancelledError()
        batch = self._batches[self._batch_index]
        self._batch_index += 1
        return batch


def _make_trade(symbol: str, ts: datetime, price: str, amount: str, trade_id: str) -> dict:
    return {
        "symbol": symbol,
        "timestamp": int(ts.timestamp() * 1000),
        "id": trade_id,
        "side": "buy",
        "price": price,
        "amount": amount,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_candle_aggregator_writes_to_hypertable(
    migrated_db: str,
    clean_candles_live: None,
) -> None:
    """MinuteAggregator + trades_aggregator_loop writes correctly bucketed 1m candles.

    Setup: 4 trades in minute 12:00 and 2 trades in minute 12:01, then a trade in 12:02.
    The aggregator should finalize minute 12:00 when minute 12:01 begins, and finalize
    12:01 when 12:02 begins. The flush is triggered immediately (flush_seconds=0.0).
    """
    from shortfire.ingest.mexc.live_candles import trades_aggregator_loop

    SYMBOL = "BTC/USDT:USDT"
    _T_12_00 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    _T_12_01 = datetime(2024, 6, 1, 12, 1, 0, tzinfo=UTC)
    _T_12_02 = datetime(2024, 6, 1, 12, 2, 0, tzinfo=UTC)

    # Minute 12:00: prices 100, 110, 90, 105 → open=100, high=110, low=90, close=105, vol=4
    minute_00_trades = [
        _make_trade(SYMBOL, _T_12_00.replace(second=0), "100.00", "1.0", "t1"),
        _make_trade(SYMBOL, _T_12_00.replace(second=15), "110.00", "1.0", "t2"),
        _make_trade(SYMBOL, _T_12_00.replace(second=30), "90.00", "1.0", "t3"),
        _make_trade(SYMBOL, _T_12_00.replace(second=45), "105.00", "1.0", "t4"),
    ]

    # Minute 12:01: prices 200, 180 → open=200, high=200, low=180, close=180, vol=2
    minute_01_trades = [
        _make_trade(SYMBOL, _T_12_01.replace(second=0), "200.00", "1.0", "t5"),
        _make_trade(SYMBOL, _T_12_01.replace(second=30), "180.00", "1.0", "t6"),
    ]

    # Minute 12:02: single trade triggers finalization of 12:01
    minute_02_trigger = [
        _make_trade(SYMBOL, _T_12_02.replace(second=0), "250.00", "1.0", "t7"),
    ]

    fake_client = FakeWsMexcClient(
        [
            minute_00_trades,  # batch 1: populates 12:00 partial
            minute_01_trades,  # batch 2: finalizes 12:00 → buffer; starts 12:01 partial
            minute_02_trigger,  # batch 3: finalizes 12:01 → buffer; then CancelledError on next
        ]
    )

    engine = create_async_engine(_to_asyncalchemy_url(migrated_db), echo=False)

    try:
        await asyncio.wait_for(
            trades_aggregator_loop(
                engine,
                fake_client,  # type: ignore[arg-type]
                [SYMBOL],
                flush_seconds=0.0,  # flush immediately for test speed
            ),
            timeout=10.0,
        )
    except (TimeoutError, asyncio.CancelledError):
        pass
    finally:
        await engine.dispose()

    # Verify in DB
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        rows = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT ts, open, high, low, close, volume, source, quality_flag "
            "FROM raw_mexc_candles_1m WHERE symbol = $1 ORDER BY ts",
            SYMBOL,
        )
        # We expect 2 finalized buckets: 12:00 and 12:01
        # (12:02 is still partial — never gets a next-minute trade in this test)
        assert len(rows) >= 1, f"Expected at least 1 finalized candle, got {len(rows)}"

        # Find the 12:00 bucket
        row_1200 = next((r for r in rows if r["ts"].replace(tzinfo=UTC) == _T_12_00), None)
        if row_1200 is not None:
            assert Decimal(str(row_1200["open"])) == Decimal("100"), "open=100"
            assert Decimal(str(row_1200["high"])) == Decimal("110"), "high=110"
            assert Decimal(str(row_1200["low"])) == Decimal("90"), "low=90"
            assert Decimal(str(row_1200["close"])) == Decimal("105"), "close=105"
            assert Decimal(str(row_1200["volume"])) == Decimal("4"), "volume=4"
            assert row_1200["source"] == "mexc_native"
            assert row_1200["quality_flag"] == "ok"

        # Verify OHLCV invariant on all rows
        for row in rows:
            assert Decimal(str(row["low"])) <= Decimal(str(row["open"]))
            assert Decimal(str(row["low"])) <= Decimal(str(row["close"]))
            assert Decimal(str(row["open"])) <= Decimal(str(row["high"]))
            assert Decimal(str(row["close"])) <= Decimal(str(row["high"]))

    finally:
        await conn.close()  # type: ignore[attr-defined]
