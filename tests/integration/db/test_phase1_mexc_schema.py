"""Integration tests for Phase 1 MEXC hypertable migrations 0003–0008.

Validates that `alembic upgrade head` against a fresh `timescale/timescaledb:2.18.0-pg16`
container results in 7 new MEXC hypertables with correct chunk intervals and compression
policies — on top of the service_event hypertable from Phase 0.

Security (T-1-DDL-04): All queries are read-only against timescaledb_information system views.
No DDL or user-controlled input crosses into these tests.

VALIDATION.md Wave-0 keystone: test_migrations_through_0008_apply,
test_compression_policy_attached_per_table, test_chunk_intervals_match_locked_values.
"""

from datetime import timedelta

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Helper: asyncpg URL (copy from test_alembic_and_hypertables.py precedent)
# ---------------------------------------------------------------------------


def _to_asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy dialect suffix for asyncpg.connect()."""
    if "postgresql+" in url:
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url


# ---------------------------------------------------------------------------
# D-58 table inventory — locked values for assertions
# ---------------------------------------------------------------------------

# All 7 MEXC hypertables that must exist after `alembic upgrade head`
_MEXC_HYPERTABLES = [
    "raw_mexc_candles_1m",
    "raw_mexc_candles_1d",
    "raw_mexc_funding",
    "raw_mexc_oi",
    "raw_mexc_trades",
    "raw_mexc_l2_top20",
    "raw_mexc_liquidations",
]

# Chunk intervals locked per D-58 inventory.
# timescaledb_information.dimensions.time_interval returns a Python timedelta (Timescale 2.18).
_EXPECTED_CHUNK_INTERVALS: dict[str, timedelta] = {
    "raw_mexc_candles_1m": timedelta(days=1),
    "raw_mexc_candles_1d": timedelta(days=90),
    "raw_mexc_funding": timedelta(days=30),
    "raw_mexc_oi": timedelta(days=7),
    "raw_mexc_trades": timedelta(days=1),
    "raw_mexc_l2_top20": timedelta(days=1),
    "raw_mexc_liquidations": timedelta(days=7),
}


# ---------------------------------------------------------------------------
# Test 1: All 7 MEXC hypertables exist after alembic upgrade head
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migrations_through_0008_apply(migrated_db: str) -> None:
    """Assert all 7 MEXC hypertables + service_event are registered in TimescaleDB.

    Probes `timescaledb_information.hypertables` for the full expected set of 8
    hypertables (1 from Phase 0 + 7 from Phase 1 migrations 0003–0008).
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        rows: list[asyncpg.Record] = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT hypertable_name FROM timescaledb_information.hypertables ORDER BY hypertable_name"
        )
    finally:
        await conn.close()  # type: ignore[attr-defined]

    found_tables = {row["hypertable_name"] for row in rows}  # type: ignore[index]
    expected_tables = set(_MEXC_HYPERTABLES) | {"service_event"}

    missing = expected_tables - found_tables
    assert not missing, (
        f"Missing hypertables after alembic upgrade head: {sorted(missing)}.\nFound: {sorted(found_tables)}"
    )


# ---------------------------------------------------------------------------
# Test 2 (split): Verify migrations 0003–0005 apply (subset probe)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migrations_0003_through_0005_apply(migrated_db: str) -> None:
    """Assert the 4 Phase-1-batch-1 hypertables exist after alembic upgrade head.

    Covers raw_mexc_candles_1m, raw_mexc_candles_1d, raw_mexc_funding, raw_mexc_oi.
    Called by Task 1 acceptance criteria verify step.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        _tables_0003_0005 = "'raw_mexc_candles_1m','raw_mexc_candles_1d','raw_mexc_funding','raw_mexc_oi'"
        rows: list[asyncpg.Record] = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            f"WHERE hypertable_name IN ({_tables_0003_0005})"
        )
    finally:
        await conn.close()  # type: ignore[attr-defined]

    found = {row["hypertable_name"] for row in rows}  # type: ignore[index]
    expected = {"raw_mexc_candles_1m", "raw_mexc_candles_1d", "raw_mexc_funding", "raw_mexc_oi"}
    missing = expected - found
    assert not missing, f"Migrations 0003–0005 did not create: {sorted(missing)}. Found: {sorted(found)}"


# ---------------------------------------------------------------------------
# Test 3: Compression policy attached per table
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("table", _MEXC_HYPERTABLES)
async def test_compression_policy_attached_per_table(migrated_db: str, table: str) -> None:
    """Assert each MEXC hypertable has a compression policy job registered.

    Queries timescaledb_information.jobs for proc_name='policy_compression'.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        rows: list[asyncpg.Record] = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT COUNT(*) AS cnt "
            "FROM timescaledb_information.jobs "
            "WHERE proc_name = 'policy_compression' "
            "  AND hypertable_name = $1",
            table,
        )
    finally:
        await conn.close()  # type: ignore[attr-defined]

    count = rows[0]["cnt"]  # type: ignore[index]
    assert count >= 1, (
        f"No compression policy found for table '{table}'. "
        "Check add_compression_policy() call in the migration."
    )


# ---------------------------------------------------------------------------
# Test 4: Chunk intervals match locked D-58 values
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("table,expected_td", list(_EXPECTED_CHUNK_INTERVALS.items()))
async def test_chunk_intervals_match_locked_values(
    migrated_db: str, table: str, expected_td: timedelta
) -> None:
    """Assert each hypertable's chunk interval matches the D-58 table inventory.

    Queries timescaledb_information.dimensions for the time dimension interval.
    In Timescale 2.18 the 'time_interval' column returns a Python timedelta
    (PostgreSQL INTERVAL type); 'interval_length' (microseconds INTEGER) does NOT
    exist in this version.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        rows: list[asyncpg.Record] = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT time_interval "
            "FROM timescaledb_information.dimensions "
            "WHERE hypertable_name = $1 "
            "  AND dimension_type = 'Time'",
            table,
        )
    finally:
        await conn.close()  # type: ignore[attr-defined]

    assert len(rows) >= 1, (
        f"No time dimension found for hypertable '{table}' in timescaledb_information.dimensions."
    )
    actual_td: timedelta = rows[0]["time_interval"]  # type: ignore[index]
    assert actual_td == expected_td, (
        f"Chunk interval for '{table}': expected {expected_td}, got {actual_td}. "
        "Check D-58 table inventory and create_hypertable() call in the migration."
    )
