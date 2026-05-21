"""raw_mexc_funding hypertable

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-21

D-58 inventory row for raw_mexc_funding:
  - chunk_interval=30 days, segment_by=symbol, compress_after=7 days
  - PK: (symbol, settlement_ts)
  - time_column=settlement_ts (not ts — Pitfall 2 / D-44)

D-44: Funding ingest captures BOTH settlement_ts AND published_ts.
  settlement_ts = time the funding rate was settled / applied to positions.
  published_ts  = time MEXC published the rate (may differ by seconds/minutes).
  Both are REQUIRED for Pitfall 2 mitigation (funding rate attribution errors).

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
revision = "0004"
down_revision = "0003"
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
    """Create raw_mexc_funding hypertable (D-44, D-58, D-27).

    NOTE: Hypertable time dimension is settlement_ts (not ts) — the canonical
    event time for funding rate application. published_ts is preserved alongside
    it for audit and latency analysis.
    """
    op.create_table(
        "raw_mexc_funding",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("settlement_ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("published_ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("funding_rate", sa.NUMERIC(28, 18), nullable=False),
        sa.Column("next_funding_ts", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("symbol", "settlement_ts", name="pk_raw_mexc_funding"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_mexc_funding_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_mexc_funding_quality",
        ),
    )
    # time_column=settlement_ts — the partitioning column is settlement time (D-44, D-58)
    create_hypertable("raw_mexc_funding", time_column="settlement_ts", chunk_interval="30 days")
    enable_compression("raw_mexc_funding", segment_by="symbol", order_by="settlement_ts DESC")
    add_compression_policy("raw_mexc_funding", after_age="7 days")


def downgrade() -> None:
    """Drop raw_mexc_funding table."""
    op.drop_table("raw_mexc_funding")
