"""Hot-path hypertable write helper — asyncpg COPY → UNLOGGED staging → INSERT ON CONFLICT.

SECURITY (T-1-IDEM-01): conflict policy is DO NOTHING (first-write-wins) per D-62.
NEVER use DO UPDATE — this guarantees idempotency (DATA-09).

D-62 / D-70: All hot-path writes route through this single helper.
  Staging tables are UNLOGGED per-session (speed); conflict policy DO NOTHING (correctness).

Usage:
    rows = await copy_into_hypertable(
        engine,
        "raw_mexc_candles_1m",
        records,
        columns=("symbol", "ts", "open", "high", "low", "close", "volume", "source", "quality_flag"),
        conflict_columns=("symbol", "ts"),
    )
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

# Per-session UNLOGGED staging table DDL (D-62, D-70)
# LIKE INCLUDING DEFAULTS copies server_default values so staging accepts the same records.
_STAGING_DDL = """
CREATE UNLOGGED TABLE IF NOT EXISTS {staging} (LIKE {target} INCLUDING DEFAULTS);
TRUNCATE TABLE {staging};
"""


async def copy_into_hypertable(
    engine: AsyncEngine,
    target_table: str,
    records: Iterable[tuple[Any, ...]],
    columns: tuple[str, ...],
    conflict_columns: tuple[str, ...],
) -> int:
    """COPY → UNLOGGED staging → INSERT … ON CONFLICT DO NOTHING. Returns record count.

    D-62/D-70: staging is per-session UNLOGGED for speed; conflict policy is DO NOTHING
    (first-write-wins). NEVER DO UPDATE — idempotency is structural, not behavioral
    (DATA-09 invariant, proved by test_idempotency.py Hypothesis property test).

    Implementation uses SQLAlchemy 2.x AsyncEngine to obtain the raw asyncpg connection
    via the driver_connection attribute (SQLA 2.0.49 escape hatch).

    Args:
        engine: SQLAlchemy 2.x async engine connected to TimescaleDB.
        target_table: Target hypertable name — must be a compile-time constant.
        records: Iterable of tuples in the same order as columns.
        columns: Column names matching the target table schema.
        conflict_columns: Columns forming the ON CONFLICT target (dedup key).

    Returns:
        Number of records in the input batch (not the inserted count — ON CONFLICT
        suppresses the PostgreSQL row count; refined in Phase 2 if needed).
    """
    records_list = list(records)
    if not records_list:
        return 0

    staging = f"{target_table}_staging"
    conflict_cols = ", ".join(conflict_columns)
    col_list = ", ".join(columns)

    async with engine.connect() as conn:
        # Obtain the raw asyncpg connection for copy_records_to_table access.
        # SQLAlchemy 2.0.49 pattern: get_raw_connection() returns AsyncAdaptedQueueConnection;
        # .driver_connection gives the underlying asyncpg.Connection.
        raw_driver = await conn.get_raw_connection()
        asyncpg_conn = raw_driver.driver_connection

        async with asyncpg_conn.transaction():
            await asyncpg_conn.execute(_STAGING_DDL.format(staging=staging, target=target_table))
            await asyncpg_conn.copy_records_to_table(staging, records=records_list, columns=list(columns))
            await asyncpg_conn.execute(
                f"""
                INSERT INTO {target_table} ({col_list})
                SELECT {col_list} FROM {staging}
                ON CONFLICT ({conflict_cols}) DO NOTHING
                """
            )

    return len(records_list)
