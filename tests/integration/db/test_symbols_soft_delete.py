"""Integration tests for symbols table soft-delete behavior.

Validates that:
- symbols rows can be soft-deleted via delisted_at (not hard-deleted)
- ON DELETE CASCADE is absent from all Phase 1 migrations

Requirements: STOR-07, T-1-SOFT-01

Security: All queries are parametrized asyncpg calls; no user-controlled input.
"""

import pathlib

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
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_symbols_can_be_soft_deleted(migrated_db: str) -> None:
    """INSERT a symbol, UPDATE delisted_at, assert row still exists.

    D-63: soft delete via delisted_at — never physically DELETE rows.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        # INSERT a symbol row
        await conn.execute(
            """
            INSERT INTO symbols (
                symbol, exchange, market_type, mexc_native_symbol,
                first_seen_at, tier
            ) VALUES (
                'BTC/USDT:USDT', 'mexc', 'swap', 'BTC_USDT',
                now(), 1
            )
            ON CONFLICT (symbol) DO NOTHING
            """
        )

        # Soft-delete by setting delisted_at
        await conn.execute("UPDATE symbols SET delisted_at = now() WHERE symbol = 'BTC/USDT:USDT'")

        # Row must still exist
        row = await conn.fetchrow("SELECT symbol, delisted_at FROM symbols WHERE symbol = 'BTC/USDT:USDT'")
        assert row is not None, "Symbol row was physically deleted — soft-delete violated (D-63)"
        assert row["delisted_at"] is not None, "delisted_at is still NULL after soft-delete UPDATE"

    finally:
        # Cleanup: remove test row so we don't pollute other tests
        await conn.execute("DELETE FROM symbols WHERE symbol = 'BTC/USDT:USDT'")
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_on_delete_cascade_anywhere(migrated_db: str) -> None:
    """Assert zero ON DELETE CASCADE constraints across all Phase 1 tables.

    Two-pronged check:
    1. pg_constraint catalog query: confdeltype = 'c' means CASCADE delete.
    2. Grep of migration files 0009–0013 for the literal string 'ON DELETE CASCADE'.

    T-1-SOFT-01: Structural ban on ON DELETE CASCADE.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        # Scope to user-created tables only (exclude TimescaleDB internal catalog tables
        # which live in pg_catalog, _timescaledb_catalog, _timescaledb_internal schemas).
        cascade_count = await conn.fetchval(
            """
            SELECT count(*)
            FROM pg_constraint c
            JOIN pg_class cl ON cl.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = cl.relnamespace
            WHERE c.contype = 'f'
              AND c.confdeltype = 'c'
              AND n.nspname = 'public'
            """
        )
        assert cascade_count == 0, (
            f"Found {cascade_count} ON DELETE CASCADE foreign key constraint(s) in public schema — "
            "all CASCADE deletes are banned project-wide (D-63, T-1-SOFT-01)"
        )
    finally:
        await conn.close()

    # Grep Phase 1 migration files for literal 'ON DELETE CASCADE'
    versions_dir = pathlib.Path(__file__).parents[3] / "alembic" / "versions"
    phase1_migrations = sorted(versions_dir.glob("00[0-9][0-9]_*.py"))
    for mig_file in phase1_migrations:
        content = mig_file.read_text()
        assert "ON DELETE CASCADE" not in content, (
            f"Migration {mig_file.name} contains 'ON DELETE CASCADE' — banned (T-1-SOFT-01)"
        )
