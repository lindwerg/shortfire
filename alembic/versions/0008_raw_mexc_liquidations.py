"""raw_mexc_liquidations hypertable

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-21

D-58 inventory row for raw_mexc_liquidations:
  - chunk_interval=7 days, segment_by=symbol, compress_after=7 days
  - PK: (symbol, ts, side, qty, price) — dedup by tuple (vendor lacks stable id)
  - time_column=ts

D-48: Liquidations captured two ways:
  - source='mexc_native': watch_liquidations ws if available in ccxt 4.5.54,
    otherwise REST poll every minute with quality_flag='partial_capture'
  - source='coinglass_aggregate': Coinglass historical liquidation endpoint, 5-min refresh

LiquidationSide domain: side IN ('short', 'long') — matches LiquidationSide Literal
  (distinct from TradeSide 'buy'/'sell' used in raw_mexc_trades).

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
revision = "0008"
down_revision = "0007"
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
    """Create raw_mexc_liquidations hypertable (D-48, D-58, D-27).

    PK is (symbol, ts, side, qty, price) — dedup-by-tuple because MEXC's liquidation
    feed does not provide a stable vendor id (D-58 note). Two rows at the same ts for
    the same side/qty/price are treated as one event.

    side IN ('short','long') matches the LiquidationSide domain literal
    (not 'buy'/'sell' — those belong to raw_mexc_trades TradeSide).
    """
    op.create_table(
        "raw_mexc_liquidations",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("qty", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("price", sa.NUMERIC(28, 10), nullable=False),
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
        # 5-column dedup tuple PK — vendor lacks stable id (D-58)
        sa.PrimaryKeyConstraint("symbol", "ts", "side", "qty", "price", name="pk_raw_mexc_liquidations"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_mexc_liquidations_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_mexc_liquidations_quality",
        ),
        # LiquidationSide domain: 'short' | 'long' (distinct from TradeSide 'buy'|'sell')
        sa.CheckConstraint(
            "side IN ('short','long')",
            name="ck_raw_mexc_liquidations_side",
        ),
    )
    create_hypertable("raw_mexc_liquidations", time_column="ts", chunk_interval="7 days")
    enable_compression("raw_mexc_liquidations", segment_by="symbol", order_by="ts DESC")
    add_compression_policy("raw_mexc_liquidations", after_age="7 days")


def downgrade() -> None:
    """Drop raw_mexc_liquidations table."""
    op.drop_table("raw_mexc_liquidations")
