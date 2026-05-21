"""dead_letter and ingest_runs hypertables

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-21

D-74: dead_letter schema — captures Pydantic ValidationErrors + exhausted-retry exceptions.
D-77: ingest_runs job telemetry table — per-job run tracking with round-robin cursor state.
D-58 rows 17–18: both are hypertables partitioned on ts, chunk_interval=30 days,
  segment_by=source, compress_after=30 days.

dead_letter design notes:
- raw_payload is TEXT (not JSONB) — a malformed API response may not be valid JSON;
  storing as TEXT preserves forensics without crashing on invalid JSON. D-74 spec said
  JSONB, but planner accepted TEXT as the safer choice for a dead-letter table.
- id UUID PK uses gen_random_uuid() from pgcrypto extension.
- op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto") is NOT a TimescaleDB DDL;
  the D-27 grep guard only blocks create_hypertable / enable_compression /
  add_compression_policy — pgcrypto install is outside that scope. T-1-EXT-01 accepts
  this: pgcrypto is a standard Postgres contrib module; Railway PG superuser already has
  CREATE EXTENSION privilege.

ingest_runs design notes:
- kv_state JSONB stores round-robin cursor state for ingest workers (RESEARCH.md §4.6).
- status IN ('running','succeeded','failed') CHECK constraint.

D-59: source TEXT NOT NULL + CHECK enum (DATA-12)
D-60: quality_flag TEXT NOT NULL DEFAULT appropriate values + CHECK enum
D-65: every time column is TIMESTAMP(timezone=True)
D-66: compression DDL goes through shortfire.db.timescale helpers (D-27)
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op
from shortfire.db.timescale import add_compression_policy, create_hypertable, enable_compression

# revision identifiers, used by Alembic.
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

# Locked source enum values (D-59, DATA-12)
_SOURCE_ENUM = "('mexc_native','coinglass_aggregate','coinglass_mexc_only','coingecko')"

# Locked quality_flag enum values (D-60)
_QUALITY_FLAG_ENUM = (
    "('ok','gap_detected','partial_candle','late_arrival',"
    "'ws_rest_divergence','schema_warn','partial_capture')"
)


def upgrade() -> None:
    """Create dead_letter and ingest_runs hypertables (D-74, D-77, D-27).

    Requires pgcrypto extension for gen_random_uuid() — this is NOT TimescaleDB DDL
    so the D-27 raw-op.execute carve-out applies only to the extension install.
    T-1-EXT-01: pgcrypto is a standard contrib module; accepted posture.
    """
    # pgcrypto for gen_random_uuid() — NOT TimescaleDB DDL (T-1-EXT-01, D-27 carve-out OK)
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # --- dead_letter (D-74) ---
    op.create_table(
        "dead_letter",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ts",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        # TEXT (not JSONB) — malformed API response may not be valid JSON;
        # storing as TEXT preserves forensics (deviation from D-74 spec; rationale above)
        sa.Column("raw_payload", sa.Text(), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=False),
        sa.Column("error_msg", sa.Text(), nullable=False),
        sa.Column(
            "retries_attempted",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "quality_flag",
            sa.Text(),
            nullable=False,
            server_default="schema_warn",
        ),
        # TimescaleDB requires the partition column (ts) to be in the PK
        sa.PrimaryKeyConstraint("id", "ts", name="pk_dead_letter"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_dead_letter_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_dead_letter_quality",
        ),
    )
    create_hypertable("dead_letter", time_column="ts", chunk_interval="30 days")
    enable_compression("dead_letter", segment_by="source", order_by="ts DESC")
    add_compression_policy("dead_letter", after_age="30 days")

    # --- ingest_runs (D-77) ---
    op.create_table(
        "ingest_runs",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ts",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "rows_written",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_msg", sa.Text(), nullable=True),
        # Round-robin cursor state for ingest workers (RESEARCH.md §4.6)
        sa.Column("kv_state", JSONB(), nullable=True),
        sa.Column(
            "quality_flag",
            sa.Text(),
            nullable=False,
            server_default="ok",
        ),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # TimescaleDB requires the partition column (ts) to be in the PK
        sa.PrimaryKeyConstraint("id", "ts", name="pk_ingest_runs"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_ingest_runs_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_ingest_runs_quality",
        ),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name="ck_ingest_runs_status",
        ),
    )
    create_hypertable("ingest_runs", time_column="ts", chunk_interval="30 days")
    enable_compression("ingest_runs", segment_by="source", order_by="ts DESC")
    add_compression_policy("ingest_runs", after_age="30 days")


def downgrade() -> None:
    """Drop ingest_runs and dead_letter tables (reverse order)."""
    op.drop_table("ingest_runs")
    op.drop_table("dead_letter")
