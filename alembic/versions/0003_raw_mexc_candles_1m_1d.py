"""raw_mexc_candles_1m + raw_mexc_candles_1d hypertables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-21

D-58 inventory rows 1+5 (candles_1m and candles_1d share this migration as the OHLCV pair):
  - raw_mexc_candles_1m: 1-day chunk, 7-day compress, segment_by=symbol
  - raw_mexc_candles_1d: 90-day chunk, 30-day compress, segment_by=symbol

D-59: source CHECK(source IN ('mexc_native','coinglass_aggregate','coinglass_mexc_only','coingecko'))
D-60: quality_flag CHECK enum
D-61: ingested_at TIMESTAMP(timezone=True) NOT NULL DEFAULT now()
D-65: every time column is TIMESTAMP(timezone=True)
D-66: compression DDL goes through shortfire.db.timescale helpers (never raw op.execute)
D-67: raw_mexc_candles_1m is the source for continuous aggregates 5m/15m/1h/4h in migration 0014
D-96: migration filename convention 00NN_<short_snake_case_description>
"""

import sqlalchemy as sa

from alembic import op
from shortfire.db.timescale import add_compression_policy, create_hypertable, enable_compression

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
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
    """Create raw_mexc_candles_1m and raw_mexc_candles_1d hypertables (D-58, D-27)."""

    # ------------------------------------------------------------------
    # raw_mexc_candles_1m — 1-minute OHLCV bars from MEXC
    # Source of truth for continuous aggregates 5m/15m/1h/4h (D-67).
    # chunk_interval=1 day, compress_after=7 days, segment_by=symbol (D-58)
    # ------------------------------------------------------------------
    op.create_table(
        "raw_mexc_candles_1m",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("open", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("high", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("low", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("close", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("volume", sa.NUMERIC(28, 10), nullable=False),
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
        sa.PrimaryKeyConstraint("symbol", "ts", name="pk_raw_mexc_candles_1m"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_mexc_candles_1m_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_mexc_candles_1m_quality",
        ),
    )
    create_hypertable("raw_mexc_candles_1m", time_column="ts", chunk_interval="1 day")
    enable_compression("raw_mexc_candles_1m", segment_by="symbol", order_by="ts DESC")
    add_compression_policy("raw_mexc_candles_1m", after_age="7 days")

    # ------------------------------------------------------------------
    # raw_mexc_candles_1d — daily OHLCV bars from MEXC
    # Independent table (D-58 row 5); NOT a continuous aggregate.
    # chunk_interval=90 days, compress_after=30 days, segment_by=symbol (D-58)
    # ------------------------------------------------------------------
    op.create_table(
        "raw_mexc_candles_1d",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("open", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("high", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("low", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("close", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("volume", sa.NUMERIC(28, 10), nullable=False),
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
        sa.PrimaryKeyConstraint("symbol", "ts", name="pk_raw_mexc_candles_1d"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_mexc_candles_1d_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_mexc_candles_1d_quality",
        ),
    )
    create_hypertable("raw_mexc_candles_1d", time_column="ts", chunk_interval="90 days")
    enable_compression("raw_mexc_candles_1d", segment_by="symbol", order_by="ts DESC")
    add_compression_policy("raw_mexc_candles_1d", after_age="30 days")


def downgrade() -> None:
    """Drop raw_mexc_candles_1d and raw_mexc_candles_1m (reverse creation order)."""
    op.drop_table("raw_mexc_candles_1d")
    op.drop_table("raw_mexc_candles_1m")
