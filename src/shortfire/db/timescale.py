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

from alembic import op
from sqlalchemy import text


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
