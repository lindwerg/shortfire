"""DATA-09 idempotency property test (VALIDATION.md keystone).

Proves that copy_into_hypertable is structurally idempotent:
re-running the SAME records (in any order) against a target hypertable
produces the same row count — no duplicates, no data loss.

Architecture: ON CONFLICT (symbol, ts) DO NOTHING in copy_into_hypertable
makes idempotency structural (D-62), not behavioral. This test validates
the invariant holds under Hypothesis-generated record sets.

D-09 (DATA-09) requirement: Idempotent on (symbol, ts, source).
VALIDATION.md Wave-0 keystone.
"""

import random
from datetime import datetime
from decimal import Decimal

import asyncpg
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from shortfire.ingest.storage.copy import copy_into_hypertable
from tests.conftest import money, utc_dt

# ---------------------------------------------------------------------------
# Helper: asyncpg URL (copy-paste precedent from test_alembic_and_hypertables.py)
# ---------------------------------------------------------------------------


def _to_asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy dialect suffix for asyncpg.connect()."""
    if "postgresql+" in url:
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url


def _to_asyncpg_sqla_url(url: str) -> str:
    """Convert plain postgresql:// to postgresql+asyncpg:// for SQLAlchemy AsyncEngine."""
    plain = _to_asyncpg_url(url)
    return plain.replace("postgresql://", "postgresql+asyncpg://", 1)


# ---------------------------------------------------------------------------
# Hypothesis composite strategy: single candle record tuple
# ---------------------------------------------------------------------------

_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "XYZ/USDT:USDT"]

_CANDLE_COLUMNS = (
    "symbol",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "quality_flag",
)


@composite
def candle_record(draw: st.DrawFn) -> tuple:  # type: ignore[type-arg]
    """Composite strategy generating a valid raw_mexc_candles_1m tuple.

    Uses 4 independent money samples and sorts them to produce valid OHLCV
    without risking InvalidArgument from bounded st.decimals with tiny ranges.
    Returns a 9-tuple matching _CANDLE_COLUMNS order.
    """
    symbol: str = draw(st.sampled_from(_SYMBOLS))
    ts: datetime = draw(utc_dt)
    # Sample 4 prices and sort to derive low/high/open/close safely
    prices = sorted([draw(money) for _ in range(4)])
    low, close_, open_, high = prices[0], prices[1], prices[2], prices[3]
    volume: Decimal = draw(money)
    return (symbol, ts, open_, high, low, close_, volume, "mexc_native", "ok")


# ---------------------------------------------------------------------------
# Idempotency property test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@settings(
    max_examples=20,
    deadline=10_000,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(records=st.lists(candle_record(), min_size=0, max_size=50))
async def test_reingest_is_idempotent(migrated_db: str, records: list[tuple]) -> None:  # type: ignore[type-arg]
    """Re-ingesting the same records (shuffled) must not produce duplicates.

    Protocol:
    1. TRUNCATE raw_mexc_candles_1m (isolation).
    2. Deduplicate records by (symbol, ts) to remove any intra-batch dupes.
    3. copy_into_hypertable → read count (count_after_1).
    4. Shuffle deduplicated records with a deterministic seed.
    5. copy_into_hypertable again with same records.
    6. Read count again (count_after_2).
    7. Assert count_after_1 == count_after_2.

    DATA-09 invariant: "Re-ingest produced duplicates" assertion message is
    intentionally unambiguous for CI debugging.
    """
    sqla_url = _to_asyncpg_sqla_url(migrated_db)
    asyncpg_url = _to_asyncpg_url(migrated_db)

    engine: AsyncEngine = create_async_engine(sqla_url)
    try:
        # Step 1: Isolation — truncate at the start of each example
        conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
        try:
            await conn.execute("TRUNCATE raw_mexc_candles_1m")  # type: ignore[attr-defined]
        finally:
            await conn.close()  # type: ignore[attr-defined]

        # Step 2: Deduplicate records by (symbol, ts) — the conflict columns.
        # Intra-batch dupes would cause count_after_1 to differ from count_after_2
        # even with a correct implementation if we test with the wrong invariant.
        seen: set[tuple] = set()
        deduped: list[tuple] = []  # type: ignore[type-arg]
        for rec in records:
            key = (rec[0], rec[1])  # (symbol, ts)
            if key not in seen:
                seen.add(key)
                deduped.append(rec)

        # Step 3: First ingest pass
        await copy_into_hypertable(
            engine,
            "raw_mexc_candles_1m",
            deduped,
            columns=_CANDLE_COLUMNS,
            conflict_columns=("symbol", "ts"),
        )

        conn2: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
        try:
            row = await conn2.fetchrow("SELECT count(*) AS cnt FROM raw_mexc_candles_1m")  # type: ignore[attr-defined]
            count_after_1: int = row["cnt"]  # type: ignore[index]
        finally:
            await conn2.close()  # type: ignore[attr-defined]

        # Step 4: Shuffle with deterministic seed for reproducible Hypothesis shrinking
        seed_key = tuple(str(r[0]) + r[1].isoformat() for r in deduped[:5])
        rng = random.Random(hash(seed_key))
        shuffled = list(deduped)
        rng.shuffle(shuffled)

        # Step 5: Second ingest pass with shuffled records
        await copy_into_hypertable(
            engine,
            "raw_mexc_candles_1m",
            shuffled,
            columns=_CANDLE_COLUMNS,
            conflict_columns=("symbol", "ts"),
        )

        # Step 6: Read count after second pass
        conn3: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
        try:
            row2 = await conn3.fetchrow("SELECT count(*) AS cnt FROM raw_mexc_candles_1m")  # type: ignore[attr-defined]
            count_after_2: int = row2["cnt"]  # type: ignore[index]
        finally:
            await conn3.close()  # type: ignore[attr-defined]

        # Step 7: Assert idempotency
        assert count_after_1 == count_after_2, (
            f"Re-ingest produced duplicates (DATA-09 invariant violated): "
            f"first pass count={count_after_1}, second pass count={count_after_2}. "
            f"Records: {len(deduped)}"
        )
    finally:
        await engine.dispose()
