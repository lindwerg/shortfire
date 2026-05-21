"""raw_mexc_l2_top20 hypertable

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-21

D-58 inventory row for raw_mexc_l2_top20:
  - chunk_interval=1 day, segment_by=symbol, compress_after=2 days
  - PK: (symbol, ts)
  - time_column=ts

D-46: L2 top-20 captured via watch_order_book(symbol, limit=20) ccxt Pro.
  Sampling cadence: 10s for full universe, 5s for tier-1 subset.

JSONB structure for bids/asks (RESEARCH.md §4.4 confirmed + D-58):
  bids JSONB: array of [price, qty] pairs, e.g. [[42100.5, 0.3], [42100.4, 1.2], ...]
    - Descending price order (best bid first)
    - Narrower than object form {"price": x, "qty": y} — faster JSON scan
  asks JSONB: structurally identical to bids, ascending price order

D-59: source CHECK constraint (DATA-12)
D-60: quality_flag CHECK enum
D-61: ingested_at TIMESTAMP(timezone=True) NOT NULL DEFAULT now()
D-65: every time column is TIMESTAMP(timezone=True)
D-66: compression DDL goes through shortfire.db.timescale helpers
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op
from shortfire.db.timescale import add_compression_policy, create_hypertable, enable_compression

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
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
    """Create raw_mexc_l2_top20 hypertable (D-46, D-58, D-27).

    bids JSONB is an array of [price, qty] pairs (RESEARCH.md §4.4):
      e.g. [[42100.5, 0.3], [42100.4, 1.2], ...] — descending price (best bid first).
    asks JSONB: structurally identical to bids, ascending price order.
    Array-of-arrays form is narrower JSON and faster to scan than object form.

    compress_after=2 days — L2 snapshots grow fast; older snapshots have limited
    analytical value and benefit from early compression (D-58 storage note).
    """
    op.create_table(
        "raw_mexc_l2_top20",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        # bids/asks: JSONB arrays of [price, qty] pairs (RESEARCH.md §4.4, D-58)
        # bids: [[42100.5, 0.3], [42100.4, 1.2], ...] descending (best bid first)
        # asks: [[42101.0, 0.5], [42101.5, 1.0], ...] ascending (best ask first)
        sa.Column("bids", JSONB(), nullable=False),
        sa.Column("asks", JSONB(), nullable=False),
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
        sa.PrimaryKeyConstraint("symbol", "ts", name="pk_raw_mexc_l2_top20"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_mexc_l2_top20_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_mexc_l2_top20_quality",
        ),
    )
    create_hypertable("raw_mexc_l2_top20", time_column="ts", chunk_interval="1 day")
    enable_compression("raw_mexc_l2_top20", segment_by="symbol", order_by="ts DESC")
    # 2-day compress_after — storage-pressured; L2 snapshots volume requires
    # short compression window (D-58 + RESEARCH.md §4.4 budget sanity)
    add_compression_policy("raw_mexc_l2_top20", after_age="2 days")


def downgrade() -> None:
    """Drop raw_mexc_l2_top20 table."""
    op.drop_table("raw_mexc_l2_top20")
