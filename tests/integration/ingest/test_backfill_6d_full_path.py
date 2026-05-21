"""STOR-08 CI sanity slice — 6-day universe backfill full-path integration test.

D-94: 50 synthetic symbols × 1m × 6 days = 50 × 8640 = 432 000 candles through the
      complete pipeline (FakeMexcClient → backfill_universe → copy_into_hypertable →
      raw_mexc_candles_1m hypertable). Target CI budget: 5 minutes.

Invariants verified:
  - Total row count ≥ 432 000 × 0.99 (within 1% of perfect coverage)
  - source='mexc_native' on every row (D-59, DATA-12)
  - OHLCV domain invariant: low <= open AND low <= close AND open <= high AND close <= high
  - Idempotency: re-running the same backfill inserts 0 new rows (DATA-09)

Requires Docker for TimescaleDB testcontainer. Skipped automatically if Docker unavailable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from shortfire.ingest.mexc.backfill import backfill_universe
from tests.fakes.mexc import FakeMexcClient

# ---------------------------------------------------------------------------
# URL helpers (mirrored from test_mexc_ohlcv.py)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Test-scoped fixture: truncate before + after
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_candles(migrated_db: str):  # type: ignore[no-untyped-def]
    """TRUNCATE raw_mexc_candles_1m before and after each test for isolation."""
    asyncpg_url = _to_asyncpg_url(migrated_db)

    async def _truncate() -> None:
        conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
        try:
            await conn.execute("TRUNCATE raw_mexc_candles_1m")  # type: ignore[attr-defined]
        finally:
            await conn.close()  # type: ignore[attr-defined]

    asyncio.run(_truncate())
    yield migrated_db
    asyncio.run(_truncate())


# ---------------------------------------------------------------------------
# STOR-08 sanity slice (D-94)
# ---------------------------------------------------------------------------

# 50 symbols × 8640 1m candles per 6 days = 432 000 expected rows
_N_SYMBOLS = 50
_DAYS = 6
_CANDLES_PER_SYMBOL = _DAYS * 24 * 60  # 8 640


@pytest.mark.integration
@pytest.mark.timeout(600)  # 10-minute hard cap; D-94 target is 5 min
async def test_six_day_universe_backfill_completes_under_ci_budget(clean_candles: str) -> None:
    """STOR-08 sanity slice (D-94): 50 symbols × 1m × 6 days through the full pipeline.

    Asserts:
      - backfill_universe completes within the timeout budget
      - Final row count in raw_mexc_candles_1m is ≥ 432 000 × 0.99
      - source='mexc_native' on every row (DATA-12 / D-59)
      - Re-running produces zero new rows (idempotency, DATA-09)
    """
    migrated_db = clean_candles
    engine = create_async_engine(
        _to_asyncalchemy_url(migrated_db),
        pool_size=10,
        pool_pre_ping=True,
    )

    symbols = tuple(f"SYM{i:02d}/USDT:USDT" for i in range(_N_SYMBOLS))
    until = datetime(2024, 1, 8, 0, 0, 0, tzinfo=UTC)  # deterministic, not now()
    since = until - timedelta(days=_DAYS)

    fake = FakeMexcClient.with_synthetic_candles(
        symbols=symbols,
        timeframe="1m",
        since=since,
        until=until,
    )

    # --- Run backfill ---
    results = await backfill_universe(
        engine,
        fake,
        list(symbols),
        timeframes=["1m"],
        since=since,
        until=until,
        max_concurrency=8,
    )
    total_inserted = sum(results.values())
    assert total_inserted > 0, "backfill_universe returned zero rows_written"

    # --- Verify row count ---
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        count: int = await conn.fetchval("SELECT count(*) FROM raw_mexc_candles_1m")  # type: ignore[assignment]
        expected_minimum = int(_N_SYMBOLS * _CANDLES_PER_SYMBOL * 0.99)
        assert count >= expected_minimum, (
            f"Expected ≥{expected_minimum} rows "
            f"({_N_SYMBOLS} symbols × {_CANDLES_PER_SYMBOL} candles × 99%), got {count}"
        )

        # --- Verify source attribution (DATA-12) ---
        bad_sources: int = await conn.fetchval(  # type: ignore[assignment]
            "SELECT count(*) FROM raw_mexc_candles_1m WHERE source != 'mexc_native'"
        )
        assert bad_sources == 0, f"Found {bad_sources} rows with source != 'mexc_native'"

        # --- OHLCV domain invariants ---
        bad_ohlcv: int = await conn.fetchval(  # type: ignore[assignment]
            """
            SELECT count(*) FROM raw_mexc_candles_1m
            WHERE NOT (low <= open AND low <= close AND open <= high AND close <= high)
            """
        )
        assert bad_ohlcv == 0, f"Found {bad_ohlcv} rows violating OHLCV invariants"

    finally:
        await conn.close()  # type: ignore[attr-defined]

    # --- Verify idempotency (DATA-09): re-run, assert count unchanged ---
    # Reset page cursors so FakeMexcClient can serve pages again
    fake2 = FakeMexcClient.with_synthetic_candles(
        symbols=symbols,
        timeframe="1m",
        since=since,
        until=until,
    )
    await backfill_universe(
        engine,
        fake2,
        list(symbols),
        timeframes=["1m"],
        since=since,
        until=until,
        max_concurrency=8,
    )

    conn2: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        count2: int = await conn2.fetchval("SELECT count(*) FROM raw_mexc_candles_1m")  # type: ignore[assignment]
        assert count2 == count, f"Re-ingest produced duplicates: count was {count}, now {count2}"
    finally:
        await conn2.close()  # type: ignore[attr-defined]

    await engine.dispose()
