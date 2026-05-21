"""Integration tests for Phase 1 auxiliary schema migrations 0009–0013.

Validates that `alembic upgrade head` against a fresh `timescale/timescaledb:2.18.0-pg16`
container results in 8 new auxiliary hypertables (Coinglass × 4, CoinGecko, universe_snapshots,
dead_letter, ingest_runs) plus the relational `symbols` table — on top of the 7 MEXC hypertables
from plan 01-03 and the Phase 0 service_event hypertable.

Requirements: STOR-01..04, STOR-06, STOR-07, DATA-07, DATA-08, DATA-11, UNIV-01, UNIV-03

Security (T-1-DDL-01): All queries are read-only against timescaledb_information system views
and pg_catalog. No DDL or user-controlled input crosses into these tests.
"""

from datetime import timedelta

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Helper: asyncpg URL
# ---------------------------------------------------------------------------


def _to_asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy dialect suffix for asyncpg.connect()."""
    if "postgresql+" in url:
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url


# ---------------------------------------------------------------------------
# Expected aux hypertables (D-58 rows 9–14, 16, 17)
# ---------------------------------------------------------------------------

_AUX_HYPERTABLES = [
    "raw_coinglass_funding_agg",
    "raw_coinglass_oi",
    "raw_coinglass_liq",
    "raw_coinglass_lsr",
    "raw_coingecko_market",
    "universe_snapshots",
    "dead_letter",
    "ingest_runs",
]

# Chunk intervals locked per D-58 + plan 01-04 action spec
_EXPECTED_AUX_CHUNK_INTERVALS: dict[str, timedelta] = {
    "raw_coinglass_funding_agg": timedelta(days=30),
    "raw_coinglass_oi": timedelta(days=30),
    "raw_coinglass_liq": timedelta(days=7),
    "raw_coinglass_lsr": timedelta(days=30),
    "raw_coingecko_market": timedelta(days=90),
    "universe_snapshots": timedelta(days=90),
    "dead_letter": timedelta(days=30),
    "ingest_runs": timedelta(days=30),
}

# Total expected hypertables: 1 (service_event) + 7 (MEXC) + 8 (aux) = 16
_MIN_TOTAL_HYPERTABLES = 16


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migrations_through_0013_apply(migrated_db: str) -> None:
    """All 8 aux hypertables exist after alembic upgrade head through 0013.

    Counts at least 16 total hypertables (1 Phase-0 + 7 MEXC + 8 aux).
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        # Check all aux hypertables exist
        rows = await conn.fetch("SELECT hypertable_name FROM timescaledb_information.hypertables")
        hypertable_names = {r["hypertable_name"] for r in rows}
        for table in _AUX_HYPERTABLES:
            assert table in hypertable_names, (
                f"Expected hypertable '{table}' not found. Found: {sorted(hypertable_names)}"
            )
        # Count total
        assert len(hypertable_names) >= _MIN_TOTAL_HYPERTABLES, (
            f"Expected at least {_MIN_TOTAL_HYPERTABLES} hypertables, "
            f"got {len(hypertable_names)}: {sorted(hypertable_names)}"
        )
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_symbols_is_relational_not_hypertable(migrated_db: str) -> None:
    """symbols exists as a regular relational table, NOT a hypertable.

    D-63: symbols is a relational lookup table with soft-delete via delisted_at.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        # Must exist as a table
        row = await conn.fetchrow("SELECT 1 FROM pg_tables WHERE tablename = 'symbols'")
        assert row is not None, "symbols table does not exist in pg_tables"

        # Must NOT be a hypertable
        count = await conn.fetchval(
            "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name = 'symbols'"
        )
        assert count == 0, f"symbols unexpectedly registered as a hypertable (count={count})"
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_universe_snapshots_partition_column_is_date(migrated_db: str) -> None:
    """universe_snapshots.snapshot_date column type must be DATE (not TIMESTAMPTZ).

    D-64: universe_snapshots uses DATE for daily snapshot granularity.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        row = await conn.fetchrow(
            """
            SELECT t.typname
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_type t ON t.oid = a.atttypid
            WHERE c.relname = 'universe_snapshots'
              AND a.attname = 'snapshot_date'
              AND a.attnum > 0
            """
        )
        assert row is not None, "snapshot_date column not found on universe_snapshots table"
        assert row["typname"] == "date", f"Expected snapshot_date to be 'date' type, got '{row['typname']}'"
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_aux_hypertable_chunk_intervals(migrated_db: str) -> None:
    """Chunk intervals for aux hypertables match the D-58 locked values."""
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        rows = await conn.fetch(
            """
            SELECT hypertable_name, time_interval
            FROM timescaledb_information.dimensions
            WHERE hypertable_name = ANY($1::text[])
            """,
            list(_EXPECTED_AUX_CHUNK_INTERVALS.keys()),
        )
        found = {r["hypertable_name"]: r["time_interval"] for r in rows}
        for table, expected_interval in _EXPECTED_AUX_CHUNK_INTERVALS.items():
            assert table in found, f"No dimension row for '{table}'"
            actual = found[table]
            assert actual == expected_interval, (
                f"{table}: expected chunk interval {expected_interval}, got {actual}"
            )
    finally:
        await conn.close()
