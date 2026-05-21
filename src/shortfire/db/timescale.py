"""Phase 0 TimescaleDB DDL helpers — idempotent wrappers for Alembic migrations (D-27).

SECURITY (T-00-03): Helpers accept hardcoded constants from migration files only.
NEVER call from request-handling code or with user-controlled input.
D-27 forbids raw op.execute("SELECT create_hypertable(...)") in migrations —
all TimescaleDB DDL must go through these helpers.

Usage in migrations:
    from shortfire.db.timescale import create_hypertable, enable_compression, add_compression_policy

    create_hypertable("my_table", time_column="ts", chunk_interval="7 days")
    enable_compression("my_table", segment_by="symbol")
    add_compression_policy("my_table", after_age="7 days")
"""

from sqlalchemy import text

from alembic import op


def create_hypertable(
    table: str,
    time_column: str = "ts",
    chunk_interval: str = "7 days",
    if_not_exists: bool = True,
) -> None:
    """Idempotent create_hypertable wrapper (D-27).

    Timescale 2.18 ships the legacy create_hypertable() function which accepts
    if_not_exists => TRUE. The newer CREATE TABLE ... WITH (timescaledb.hypertable)
    syntax is preferred for fresh tables but is not as Alembic-autogenerate-friendly,
    so we use the function form here.

    Args:
        table: Table name — must be a hardcoded constant from the migration file.
        time_column: Name of the time partitioning column.
        chunk_interval: TimescaleDB chunk interval (e.g. '7 days', '1 day').
        if_not_exists: Skip silently if already a hypertable.
    """
    op.execute(
        text(f"""
        SELECT create_hypertable(
            '{table}',
            '{time_column}',
            chunk_time_interval => INTERVAL '{chunk_interval}',
            if_not_exists => {str(if_not_exists).upper()}
        );
    """)
    )


def enable_compression(
    table: str,
    segment_by: str,
    order_by: str = "ts DESC",
) -> None:
    """Idempotent ALTER TABLE ... SET (timescaledb.compress, ...) wrapper (D-27).

    Args:
        table: Table name — must be a hardcoded constant from the migration file.
        segment_by: Column name for compression segmentation.
        order_by: ORDER BY expression for compression (default: 'ts DESC').
    """
    op.execute(
        text(f"""
        ALTER TABLE {table} SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = '{segment_by}',
            timescaledb.compress_orderby = '{order_by}'
        );
    """)
    )


def add_compression_policy(
    table: str,
    after_age: str = "7 days",
    if_not_exists: bool = True,
) -> None:
    """Idempotent add_compression_policy wrapper (D-27).

    Skips silently if a policy already exists — Timescale's add_compression_policy
    supports if_not_exists since 2.4.

    Args:
        table: Table name — must be a hardcoded constant from the migration file.
        after_age: Compress chunks older than this interval.
        if_not_exists: Skip if policy already exists.
    """
    op.execute(
        text(f"""
        SELECT add_compression_policy(
            '{table}',
            INTERVAL '{after_age}',
            if_not_exists => {str(if_not_exists).upper()}
        );
    """)
    )


def create_continuous_aggregate(
    view_name: str,
    source_table: str,
    bucket: str,
    select_columns: str,
    group_by: str | None = None,
    start_offset: str = "2 hours",
    end_offset: str = "5 minutes",
    schedule_interval: str = "5 minutes",
) -> None:
    """Create a TimescaleDB continuous aggregate + refresh policy (D-95 carve-out, D-27).

    D-27 discipline: TimescaleDB DDL goes through helpers. Continuous aggregates have no
    Alembic helper equivalent, so this helper is the ONE place where raw `op.execute` for
    CA DDL is permitted — the carve-out is justified by D-95 + RESEARCH.md §3.5.
    Migration 0014 calls this helper four times; no raw `op.execute` appears in that file.

    SECURITY (T-00-03): Arguments must be hardcoded constants from migration files only.
    NEVER call from request-handling code or with user-controlled input.

    T-1-CA-02: All start_offset values used in production are < 7 days (the compression-after
    window on raw_mexc_candles_1m), so refresh never touches compressed chunks.

    Args:
        view_name: Name of the continuous aggregate view to create.
        source_table: Source hypertable to aggregate from.
        bucket: Time bucket width (e.g. '5 minutes', '1 hour', '4 hours').
        select_columns: Full SELECT clause (symbol, time_bucket(…) AS ts, agg_columns…).
        group_by: GROUP BY clause. Defaults to "symbol, time_bucket('<bucket>', ts)".
        start_offset: CA refresh policy start_offset INTERVAL (D-67 locked values).
        end_offset: CA refresh policy end_offset INTERVAL (D-67 locked values).
        schedule_interval: CA refresh policy schedule_interval INTERVAL (D-67 locked values).
    """
    if group_by is None:
        group_by = f"symbol, time_bucket('{bucket}', ts)"

    # Two separate op.execute calls:
    # 1. CREATE MATERIALIZED VIEW ... WITH NO DATA runs inside the migration transaction.
    #    WITH NO DATA avoids immediate materialization which would fail inside a transaction.
    #    TimescaleDB supports WITH NO DATA for continuous aggregates since 2.x.
    # 2. add_continuous_aggregate_policy is a plain SELECT that runs fine in a transaction.
    op.execute(
        text(f"""
        CREATE MATERIALIZED VIEW {view_name}
        WITH (timescaledb.continuous) AS
        SELECT {select_columns}
        FROM {source_table}
        GROUP BY {group_by}
        WITH NO DATA
    """)
    )
    op.execute(
        text(f"""
        SELECT add_continuous_aggregate_policy(
            '{view_name}',
            start_offset   => INTERVAL '{start_offset}',
            end_offset     => INTERVAL '{end_offset}',
            schedule_interval => INTERVAL '{schedule_interval}'
        )
    """)
    )


def add_retention_policy(
    table: str,
    drop_after: str,
    if_not_exists: bool = True,
) -> None:
    """Idempotent add_retention_policy wrapper (D-27).

    Args:
        table: Table name — must be a hardcoded constant from the migration file.
        drop_after: Drop chunks older than this interval (e.g. '365 days').
        if_not_exists: Skip if policy already exists.
    """
    op.execute(
        text(f"""
        SELECT add_retention_policy(
            '{table}',
            INTERVAL '{drop_after}',
            if_not_exists => {str(if_not_exists).upper()}
        );
    """)
    )
