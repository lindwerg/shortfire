"""raw_mexc_trades hypertable

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-21

D-58 inventory row for raw_mexc_trades:
  - chunk_interval=1 day, segment_by=symbol, compress_after=2 days (aggressive — high-volume table)
  - PK: (symbol, ts, exchange_trade_id)
  - time_column=ts

D-47: Signed trades captured via watch_trades(symbol) with 1-minute batching.
  Primary dedup key is exchange_trade_id — MEXC ws returns a stable id via ccxt 4.5
  unified trades response. Fallback tuple (symbol, ts, side, price, qty) preserved
  as a comment; the PK uses (symbol, ts, exchange_trade_id).

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
revision = "0006"
down_revision = "0005"
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
    """Create raw_mexc_trades hypertable (D-47, D-58, D-27).

    PK is (symbol, ts, exchange_trade_id) — exchange_trade_id is stable per
    ccxt 4.5 MEXC unified trades. Fallback dedup tuple (symbol, ts, side, price, qty)
    is informational only (D-47 note).

    compress_after=2 days is aggressive because trades data grows fast; older trades
    are used only for backtesting and can tolerate decompression cost.
    """
    op.create_table(
        "raw_mexc_trades",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        # exchange_trade_id: stable unique ID from MEXC via ccxt 4.5 unified trades (D-47)
        sa.Column("exchange_trade_id", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("price", sa.NUMERIC(28, 10), nullable=False),
        sa.Column("qty", sa.NUMERIC(28, 10), nullable=False),
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
        # 3-column PK: symbol + ts + exchange_trade_id (D-58 dedup key)
        sa.PrimaryKeyConstraint("symbol", "ts", "exchange_trade_id", name="pk_raw_mexc_trades"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_mexc_trades_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_mexc_trades_quality",
        ),
        sa.CheckConstraint(
            "side IN ('buy','sell')",
            name="ck_raw_mexc_trades_side",
        ),
    )
    create_hypertable("raw_mexc_trades", time_column="ts", chunk_interval="1 day")
    enable_compression("raw_mexc_trades", segment_by="symbol", order_by="ts DESC")
    # 2-day compress_after — aggressive; trades volume requires short compression window (D-58)
    add_compression_policy("raw_mexc_trades", after_age="2 days")


def downgrade() -> None:
    """Drop raw_mexc_trades table."""
    op.drop_table("raw_mexc_trades")
