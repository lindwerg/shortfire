"""Single-helper hypertable write path via asyncpg COPY (D-62, D-70).

Pattern (RESEARCH.md §2 Pattern 1):
  1. Materialize records to list; short-circuit return 0 if empty.
  2. Create UNLOGGED staging table (IF NOT EXISTS) per session for speed.
  3. TRUNCATE staging table.
  4. Use asyncpg copy_records_to_table for bulk insert into staging.
  5. INSERT INTO target SELECT ... ON CONFLICT (conflict_cols) DO NOTHING.
  6. Return count of records inserted.

Security (T-1-INF-01):
  target_table is an f-string substitution. Callers MUST pass hardcoded table name
  literals from D-58 only — never a user-controlled string. Pyright strict mode
  catches dynamic string callers at type-check time.

Invariant (D-62):
  ON CONFLICT DO NOTHING (first-write-wins).
  Re-ingest cannot produce duplicates by construction.
  Upsert via the alternative conflict handler is FORBIDDEN in this module.

Pitfall P1-D (from RESEARCH.md §12):
  asyncpg raw connection is obtained via:
    raw_conn = (await conn.get_raw_connection()).driver_connection
  Not via conn.raw_connection (old SQLAlchemy 1.x API).
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine


async def copy_into_hypertable(
    engine: AsyncEngine,
    target_table: str,
    records: Iterable[tuple[Any, ...]],
    columns: tuple[str, ...],
    conflict_columns: tuple[str, ...],
) -> int:
    """COPY records into a TimescaleDB hypertable via asyncpg staging pattern.

    Implements the RESEARCH.md §2 Pattern 1 COPY → staging → INSERT … ON CONFLICT
    DO NOTHING write path. Returns the number of records processed.

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        target_table: Hardcoded table name (e.g. 'raw_mexc_candles_1m'). MUST be
            a literal constant from D-58 — never a user-controlled value.
        records: Iterable of row tuples matching the column order.
        columns: Column names in the same order as the record tuples.
        conflict_columns: Columns forming the uniqueness key for ON CONFLICT.

    Returns:
        Number of records in the batch (0 if empty, short-circuited without DB call).

    Note:
        ON CONFLICT DO NOTHING (first-write-wins per D-62).
        Upserting via the alternative conflict handler is forbidden — re-ingest
        must not overwrite existing rows.
    """
    records_list = list(records)
    if not records_list:
        return 0

    conflict_cols = ", ".join(conflict_columns)
    col_list = ", ".join(columns)

    async with engine.connect() as conn:
        raw_connection_obj = await conn.get_raw_connection()
        raw_conn = raw_connection_obj.driver_connection
        assert raw_conn is not None, "asyncpg driver_connection must not be None"

        # Use the backend PID to give each connection its own staging table,
        # preventing UniqueViolationError on pg_type when multiple coroutines
        # issue concurrent CREATE UNLOGGED TABLE IF NOT EXISTS for the same name.
        pid: int = await raw_conn.fetchval("SELECT pg_backend_pid()")
        staging = f"{target_table}_staging_{pid}"

        async with raw_conn.transaction():
            # Create UNLOGGED staging table scoped to this backend PID (fast, isolated)
            await raw_conn.execute(
                f"CREATE UNLOGGED TABLE IF NOT EXISTS {staging}"
                f" (LIKE {target_table} INCLUDING DEFAULTS);"
                f" TRUNCATE TABLE {staging};"
            )

            # Bulk copy via asyncpg native COPY protocol
            await raw_conn.copy_records_to_table(
                staging,
                records=records_list,
                columns=columns,
            )

            # Merge from staging into target — ON CONFLICT DO NOTHING (D-62)
            await raw_conn.execute(
                f"INSERT INTO {target_table} ({col_list})"
                f" SELECT {col_list} FROM {staging}"
                f" ON CONFLICT ({conflict_cols}) DO NOTHING"
            )

    return len(records_list)
