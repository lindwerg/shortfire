"""Integration test: MEXC OHLCV backfill writes attributed rows into raw_mexc_candles_1m.

DATA-01 keystone test — validates the full path:
  FakeMexcClient (with_synthetic_candles)
    → backfill_ohlcv
    → copy_into_hypertable
    → raw_mexc_candles_1m (TimescaleDB hypertable)

Invariants verified:
  - Exact row count matches candle count
  - Every row has source='mexc_native' (D-59, T-1-MEXC-05)
  - quality_flag='ok' on every row
  - OHLCV domain invariant: low <= open AND low <= close AND open <= high AND close <= high
  - Idempotency: second backfill inserts 0 new rows (STOR-08)

Requires Docker for TimescaleDB testcontainer. Skipped automatically if Docker unavailable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from tests.fakes.mexc import FakeMexcClient


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


@pytest.fixture
def clean_mexc_candles(migrated_db: str):  # type: ignore[no-untyped-def]
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mexc_ohlcv_backfill_writes_attributed_rows(
    migrated_db: str,
    clean_mexc_candles: None,
) -> None:
    """DATA-01 keystone: backfill writes 100 correctly attributed rows; second run is idempotent."""
    from shortfire.ingest.mexc.backfill import backfill_ohlcv

    # -----------------------------------------------------------------------
    # Setup: 100 synthetic 1m candles for BTC/USDT:USDT
    # -----------------------------------------------------------------------
    now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    since = now - timedelta(minutes=100)
    symbol = "BTC/USDT:USDT"

    fake = FakeMexcClient.with_synthetic_candles(
        symbols=(symbol,),
        timeframe="1m",
        since=since,
        until=now,
        base_price=Decimal("30000"),
    )

    engine = create_async_engine(_to_asyncalchemy_url(migrated_db), echo=False)

    try:
        # -----------------------------------------------------------------------
        # First backfill
        # -----------------------------------------------------------------------
        n1 = await backfill_ohlcv(
            engine,
            fake,
            symbol,
            "1m",
            since,
            now,
            asyncio.Semaphore(8),
        )
        assert n1 == 100, f"Expected 100 rows written, got {n1}"

        # -----------------------------------------------------------------------
        # Query the DB and assert attributions
        # -----------------------------------------------------------------------
        asyncpg_url = _to_asyncpg_url(migrated_db)
        conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
        try:
            # Row count
            count = await conn.fetchval(  # type: ignore[attr-defined]
                "SELECT COUNT(*) FROM raw_mexc_candles_1m WHERE symbol = $1",
                symbol,
            )
            assert count == 100, f"Expected 100 rows in DB, got {count}"

            # All sources = 'mexc_native'
            sources = await conn.fetch(  # type: ignore[attr-defined]
                "SELECT DISTINCT source FROM raw_mexc_candles_1m WHERE symbol = $1",
                symbol,
            )
            assert len(sources) == 1 and sources[0]["source"] == "mexc_native"

            # quality_flag
            flags = await conn.fetch(  # type: ignore[attr-defined]
                "SELECT DISTINCT quality_flag FROM raw_mexc_candles_1m WHERE symbol = $1",
                symbol,
            )
            assert len(flags) == 1 and flags[0]["quality_flag"] == "ok"

            # OHLCV domain invariant: low <= open,close AND open,close <= high
            bad_rows = await conn.fetchval(  # type: ignore[attr-defined]
                """
                SELECT COUNT(*) FROM raw_mexc_candles_1m
                WHERE symbol = $1
                  AND NOT (low <= open AND low <= close AND open <= high AND close <= high)
                """,
                symbol,
            )
            assert bad_rows == 0, f"OHLCV invariant violated on {bad_rows} rows"

            # ts is tz-aware UTC (TimescaleDB stores TIMESTAMPTZ)
            sample_ts = await conn.fetchval(  # type: ignore[attr-defined]
                "SELECT ts FROM raw_mexc_candles_1m WHERE symbol = $1 LIMIT 1",
                symbol,
            )
            assert sample_ts is not None
            # asyncpg returns datetime with tzinfo for TIMESTAMPTZ columns
            assert sample_ts.tzinfo is not None, "ts must be tz-aware (TIMESTAMPTZ)"

        finally:
            await conn.close()  # type: ignore[attr-defined]

        # -----------------------------------------------------------------------
        # Idempotency: second backfill must not increase the row count in the DB.
        # copy_into_hypertable returns the batch input count (not the INSERT count)
        # because asyncpg COPY doesn't expose ON CONFLICT skips via rowcount.
        # The STOR-08 idempotency invariant is verified by querying the DB directly.
        # -----------------------------------------------------------------------
        fake2 = FakeMexcClient.with_synthetic_candles(
            symbols=(symbol,),
            timeframe="1m",
            since=since,
            until=now,
            base_price=Decimal("30000"),
        )
        await backfill_ohlcv(
            engine,
            fake2,
            symbol,
            "1m",
            since,
            now,
            asyncio.Semaphore(8),
        )

        # Final count must still be exactly 100 — no duplicates created
        conn2: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
        try:
            count2 = await conn2.fetchval(  # type: ignore[attr-defined]
                "SELECT COUNT(*) FROM raw_mexc_candles_1m WHERE symbol = $1",
                symbol,
            )
            assert count2 == 100, (
                f"Idempotency violated: second run changed row count to {count2} (expected 100)"
            )
        finally:
            await conn2.close()  # type: ignore[attr-defined]

    finally:
        await engine.dispose()
