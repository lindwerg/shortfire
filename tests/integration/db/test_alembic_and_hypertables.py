"""Integration tests for Alembic migrations + TimescaleDB hypertable/compression (D-31).

These 3 tests are the RUNTIME GATE for FOUND-03.

Plan 00-04 verified static migration shape (SQL strings + env.py wiring) without a
real database. These tests run `alembic upgrade head` against a real
`timescale/timescaledb:2.18.0-pg16` container and assert:

1. test_alembic_upgrade_is_idempotent  — rerun-safety: second `upgrade head` exits 0
2. test_service_event_is_hypertable    — `service_event` registered in timescaledb_information.hypertables
3. test_service_event_has_compression_policy — compression job exists with locked segment_by/order_by

All tests require Docker and use the session-scoped fixtures from conftest.py
(Pitfall 5 mitigation: container starts once, alembic runs once).

Security (T-00-03): Queries read timescaledb_information system views only — no dynamic
DDL or user-controlled input crosses into these tests.
"""

import os
import subprocess

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Helper: asyncpg URL for direct DB queries
# ---------------------------------------------------------------------------


def _to_asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy dialect suffix for asyncpg.connect().

    asyncpg.connect() rejects `+asyncpg` / `+psycopg2` suffixes.
    """
    if "postgresql+" in url:
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url


# ---------------------------------------------------------------------------
# Test 1: Idempotent rerun (D-31)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_alembic_upgrade_is_idempotent(migrated_db: str) -> None:
    """Run `alembic upgrade head` a SECOND time on an already-migrated container.

    The session-scoped `migrated_db` fixture ran `upgrade head` once before this test.
    This test runs it again to verify rerun-safety (D-31):
    - 0001's `CREATE EXTENSION IF NOT EXISTS timescaledb` is idempotent.
    - 0002's create_hypertable(..., if_not_exists=True) and add_compression_policy(
      ..., if_not_exists=True) helpers are idempotent.

    Pitfall 3 failure modes caught here:
    - URL rewrite missing → `Could not parse SQLAlchemy URL`
    - Extension ordering broken → `function create_hypertable does not exist`
    - Naming convention not applied → `alembic revision mismatch`
    """
    env = {**os.environ, "DATABASE_URL": migrated_db}
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    # Exit 0 — no error on second run
    assert result.returncode == 0, (
        f"Second alembic upgrade head failed (returncode={result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    # No ERROR or FATAL in output (Alembic prints these on partial failures)
    combined = (result.stdout + result.stderr).upper()
    assert "ERROR" not in combined, (
        f"ERROR pattern found in second alembic upgrade head output:\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "FATAL" not in combined, (
        f"FATAL pattern found in second alembic upgrade head output:\n"
        f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test 2: Hypertable existence (D-31)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_service_event_is_hypertable(migrated_db: str) -> None:
    """Assert service_event is registered as a TimescaleDB hypertable.

    Queries `timescaledb_information.hypertables` for `service_event`.
    Exactly 1 row must exist — proves create_hypertable() helper from Plan 00-04
    actually ran and was accepted by Timescale 2.18.0-pg16.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        rows: list[asyncpg.Record] = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT hypertable_name "
            "FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'service_event'"
        )
    finally:
        await conn.close()  # type: ignore[attr-defined]

    assert len(rows) == 1, (  # type: ignore[arg-type]
        f"Expected 1 hypertable row for service_event, got {len(rows)!r}. "  # type: ignore[arg-type]
        "Possible cause: create_hypertable() helper in 0002 did not register the table."
    )
    assert rows[0]["hypertable_name"] == "service_event"


# ---------------------------------------------------------------------------
# Test 3: Compression policy existence (D-31)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_service_event_has_compression_policy(migrated_db: str) -> None:
    """Assert compression policy exists for service_event with locked config.

    Two sub-checks:
    1. `timescaledb_information.jobs` has at least 1 'Compression' job for service_event.
    2. `timescaledb_information.compression_settings` has:
       - compress_segmentby = 'service_name' (locked in enable_compression call)
       - compress_orderby   = 'ts DESC'       (locked in enable_compression call)

    Pitfall 3 / T-00-03: both queries are read-only against system views; no DDL.
    """
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(asyncpg_url)  # type: ignore[type-arg]
    try:
        # ----------------------------------------------------------------
        # Sub-check 1: compression job registered in background scheduler
        # ----------------------------------------------------------------
        job_rows: list[asyncpg.Record] = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT job_id, hypertable_name, schedule_interval "
            "FROM timescaledb_information.jobs "
            "WHERE hypertable_name = 'service_event' "
            "  AND application_name LIKE 'Compression%'"
        )
        assert len(job_rows) >= 1, (  # type: ignore[arg-type]
            "No compression job found for service_event in timescaledb_information.jobs. "
            "Possible cause: add_compression_policy() helper in 0002 did not register the job."
        )

        # ----------------------------------------------------------------
        # Sub-check 2: compression settings match locked config (D-27, D-28)
        #
        # TimescaleDB 2.18.0 compression_settings view schema (verified against real image):
        #   attname TEXT                  — column name involved in compression
        #   segmentby_column_index INT    — non-NULL for segment-by columns
        #   orderby_column_index INT      — non-NULL for order-by columns
        #   orderby_asc BOOL              — TRUE = ASC, FALSE = DESC (i.e. FALSE = "ts DESC")
        #
        # Note: compress_segmentby / compress_orderby columns do NOT exist in 2.18.0;
        # those were added in a later version. We use attname + index columns instead.
        # ----------------------------------------------------------------
        settings_rows: list[asyncpg.Record] = await conn.fetch(  # type: ignore[attr-defined]
            "SELECT attname, segmentby_column_index, orderby_column_index, orderby_asc "
            "FROM timescaledb_information.compression_settings "
            "WHERE hypertable_name = 'service_event' "
            "ORDER BY coalesce(segmentby_column_index, 999), coalesce(orderby_column_index, 999)"
        )
        assert len(settings_rows) >= 1, (  # type: ignore[arg-type]
            "No compression_settings rows found for service_event. "
            "Possible cause: enable_compression() helper in 0002 did not apply settings."
        )

        # Verify segment-by column is service_name
        segmentby_rows: list[asyncpg.Record] = [  # type: ignore[misc]
            r
            for r in settings_rows  # type: ignore[union-attr]
            if r["segmentby_column_index"] is not None
        ]
        assert len(segmentby_rows) >= 1, (  # type: ignore[arg-type]
            "No segmentby column found in compression_settings for service_event. "
            "Check enable_compression(segment_by='service_name') in 0002 migration."
        )
        seg_col: str = segmentby_rows[0]["attname"]  # type: ignore[assignment]
        assert seg_col == "service_name", (
            f"segment_by column expected 'service_name', got '{seg_col}'. "
            "Check enable_compression() call in 0002 migration."
        )

        # Verify order-by column is ts with DESC direction (orderby_asc=False)
        orderby_rows: list[asyncpg.Record] = [  # type: ignore[misc]
            r
            for r in settings_rows  # type: ignore[union-attr]
            if r["orderby_column_index"] is not None
        ]
        assert len(orderby_rows) >= 1, (  # type: ignore[arg-type]
            "No orderby column found in compression_settings for service_event. "
            "Check enable_compression(order_by='ts DESC') in 0002 migration."
        )
        orderby_col: str = orderby_rows[0]["attname"]  # type: ignore[assignment]
        orderby_asc: bool = orderby_rows[0]["orderby_asc"]  # type: ignore[assignment]
        assert orderby_col == "ts", (
            f"order_by column expected 'ts', got '{orderby_col}'. "
            "Check enable_compression() call in 0002 migration."
        )
        assert orderby_asc is False, (
            f"order_by direction expected DESC (orderby_asc=False), got orderby_asc={orderby_asc}. "
            "Check enable_compression(order_by='ts DESC') in 0002 migration."
        )

    finally:
        await conn.close()  # type: ignore[attr-defined]
