"""raw_mexc_oi hypertable

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-21

D-58 inventory row for raw_mexc_oi:
  - chunk_interval=7 days, segment_by=symbol, compress_after=7 days
  - PK: (symbol, ts)
  - time_column=ts

D-45: OI ingest is REST-only (fetch_open_interest_history hourly,
  fetch_open_interest for current snapshot every 5 min).

D-59: source CHECK constraint (DATA-12)
D-60: quality_flag CHECK enum
D-61: ingested_at TIMESTAMP(timezone=True) NOT NULL DEFAULT now()
D-65: every time column is TIMESTAMP(timezone=True)
D-66: compression DDL goes through shortfire.db.timescale helpers
"""

import sqlalchemy as sa

from alembic import op
from shortfire.db.timescale import add_compression_policy, create_hypertable, enable_compression

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
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
    """Create raw_mexc_oi hypertable (D-45, D-58, D-27)."""
    op.create_table(
        "raw_mexc_oi",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("open_interest", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("symbol", "ts", name="pk_raw_mexc_oi"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_mexc_oi_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_mexc_oi_quality",
        ),
    )
    create_hypertable("raw_mexc_oi", time_column="ts", chunk_interval="7 days")
    enable_compression("raw_mexc_oi", segment_by="symbol", order_by="ts DESC")
    add_compression_policy("raw_mexc_oi", after_age="7 days")


def downgrade() -> None:
    """Drop raw_mexc_oi table."""
    op.drop_table("raw_mexc_oi")
