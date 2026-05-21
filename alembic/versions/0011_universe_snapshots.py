"""universe_snapshots hypertable

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-21

D-64: universe_snapshots hypertable for point-in-time universe — daily cadence.
D-58 row 16: PK (snapshot_date, symbol), chunk_interval=90 days, NO compression (tiny volume).
UNIV-01: is_qualifying flag — 24h volume > $500K USD threshold.
UNIV-03: point-in-time correctness — SELECT symbol WHERE snapshot_date = $T AND is_qualifying.

Key design decisions:
- snapshot_date is DATE (not TIMESTAMP(timezone=True)) — daily granularity is correct here;
  timescaledb supports DATE columns as the time dimension.
- NO compression policy — universe snapshot volume is tiny (O(200 symbols × 365 days/yr));
  D-58 row 15 explicitly says "NONE (tiny)".
- PK (snapshot_date, symbol) — one row per (day, symbol) for clean point-in-time lookups.

D-59: source TEXT NOT NULL + CHECK enum (DATA-12)
D-60: quality_flag TEXT NOT NULL DEFAULT 'ok' + CHECK enum
D-61: ingested_at TIMESTAMP(timezone=True) NOT NULL DEFAULT now()
D-65: every time column is TIMESTAMP(timezone=True) — snapshot_date is DATE (allowed exception)
D-66: create_hypertable via helper; NO compression on this table
"""

import sqlalchemy as sa

from alembic import op
from shortfire.db.timescale import create_hypertable

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
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
    """Create universe_snapshots hypertable (D-64, D-58, D-27).

    Partitioned on snapshot_date (DATE) with 90-day chunks.
    No compression policy — volume is tiny (D-58 row 15: "NONE (tiny)").
    """
    op.create_table(
        "universe_snapshots",
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("volume_24h_usd", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("price_usd", sa.NUMERIC(20, 10), nullable=True),
        sa.Column("is_qualifying", sa.Boolean(), nullable=False),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default="mexc_native",
        ),
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
        # PK is (snapshot_date, symbol) per D-64 for point-in-time queries
        sa.PrimaryKeyConstraint("snapshot_date", "symbol", name="pk_universe_snapshots"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_universe_snapshots_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_universe_snapshots_quality",
        ),
    )
    # Partition on snapshot_date (DATE column); 90-day chunks per D-64
    create_hypertable(
        "universe_snapshots",
        time_column="snapshot_date",
        chunk_interval="90 days",
    )
    # NO enable_compression or add_compression_policy — D-58 row 15: "NONE (tiny)"


def downgrade() -> None:
    """Drop universe_snapshots table."""
    op.drop_table("universe_snapshots")
