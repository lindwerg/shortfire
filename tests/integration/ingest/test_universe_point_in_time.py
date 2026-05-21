"""Integration test: UNIV-03 keystone — point-in-time universe invariance.

Verifies that universe_at(date) returns exactly the symbols that were in the
snapshot for that date, regardless of what subsequent snapshots contain.
This is the survivorship-bias defence: append-only snapshots make historical
universe queries invariant under future writes (Pitfall 1).

Uses Hypothesis property-based testing with a testcontainer DB.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from shortfire.ingest.universe.snapshot import universe_at

pytestmark = pytest.mark.integration

_ALL_SYMBOLS = ["A/USDT:USDT", "B/USDT:USDT", "C/USDT:USDT", "D/USDT:USDT"]


async def _seed_snapshot(engine: AsyncEngine, snapshot_date: date, symbols: set[str]) -> None:
    """Insert qualifying snapshot rows for the given date and symbol set."""
    if not symbols:
        return
    records = [
        (snapshot_date, sym, Decimal("600000"), Decimal("1.0"), True, "mexc_native", "ok") for sym in symbols
    ]
    async with engine.begin() as conn:
        for snapshot_date_val, symbol, vol, price, is_qual, source, qflag in records:
            await conn.execute(
                text("""
                    INSERT INTO universe_snapshots
                        (snapshot_date, symbol, volume_24h_usd, price_usd,
                         is_qualifying, source, quality_flag)
                    VALUES (:d, :s, :v, :p, :q, :src, :qf)
                    ON CONFLICT (snapshot_date, symbol) DO NOTHING
                """),
                {
                    "d": snapshot_date_val,
                    "s": symbol,
                    "v": float(vol),
                    "p": float(price),
                    "q": is_qual,
                    "src": source,
                    "qf": qflag,
                },
            )


@given(
    early_symbols=st.frozensets(st.sampled_from(_ALL_SYMBOLS), min_size=1, max_size=4).map(set),
    late_symbols=st.frozensets(st.sampled_from(_ALL_SYMBOLS), min_size=1, max_size=4).map(set),
)
@settings(max_examples=15, deadline=15_000, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_universe_point_in_time_correctness(
    migrated_db: str,
    early_symbols: set[str],
    late_symbols: set[str],
) -> None:
    """Point-in-time universe is invariant under future writes (UNIV-03).

    Seeds snapshots at two separate dates; adds a third snapshot at an even
    later date. Asserts that universe_at(D1) still returns exactly the D1 set
    regardless of what happened at D2 and D3.
    """
    engine = create_async_engine(migrated_db.replace("postgresql://", "postgresql+asyncpg://"))

    try:
        # Cleanup any leftover rows from previous examples
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE universe_snapshots"))

        d1 = date(2026, 3, 1)
        d2 = date(2026, 4, 1)
        d3 = date(2026, 5, 1)

        await _seed_snapshot(engine, d1, early_symbols)
        await _seed_snapshot(engine, d2, late_symbols)
        # Third snapshot with different content that must not affect D1 or D2 queries
        await _seed_snapshot(engine, d3, {"X/USDT:USDT", "Y/USDT:USDT"})

        # Point-in-time queries must return the exact seeded sets
        u_d1 = await universe_at(engine, d1)
        u_d2 = await universe_at(engine, d2)

        assert u_d1 == early_symbols, (
            f"universe_at({d1}) returned {u_d1!r} but expected {early_symbols!r}. "
            "Future writes must NOT affect historical snapshots (UNIV-03)."
        )
        assert u_d2 == late_symbols, f"universe_at({d2}) returned {u_d2!r} but expected {late_symbols!r}."

    finally:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE universe_snapshots"))
        await engine.dispose()
