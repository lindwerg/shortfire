"""raw_coingecko_market hypertable

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-21

D-57: raw_coingecko_market schema — daily-cadence CoinGecko market metadata.
D-58 row 13: chunk_interval=90 days, segment_by=source, compress_after=30 days.
D-55: CoinGecko is universe-metadata-only, daily cadence.
D-59: source TEXT NOT NULL + CHECK enum (DATA-12)
D-60: quality_flag TEXT NOT NULL DEFAULT 'ok' + CHECK enum
D-61: ingested_at TIMESTAMP(timezone=True) NOT NULL DEFAULT now()
D-65: every time column is TIMESTAMP(timezone=True)
D-66: compression DDL goes through shortfire.db.timescale helpers (D-27)

Nullable columns (price_usd, volume_24h_usd, market_cap_usd, category, listing_date,
raw_payload) because CoinGecko responses may omit fields for newly listed or delisted tokens.
segment_by=source per D-58 row 13 (unlike Coinglass tables which segment by symbol).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op
from shortfire.db.timescale import add_compression_policy, create_hypertable, enable_compression

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "0009"
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
    """Create raw_coingecko_market hypertable (D-57, D-58, D-27).

    Daily-cadence CoinGecko market metadata. PK is (symbol, ts, source).
    segment_by=source (D-58 row 13 explicit).
    Many metric columns are nullable — CoinGecko omits fields for low-data tokens.
    """
    op.create_table(
        "raw_coingecko_market",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("price_usd", sa.NUMERIC(28, 10), nullable=True),
        sa.Column("volume_24h_usd", sa.NUMERIC(28, 10), nullable=True),
        sa.Column("market_cap_usd", sa.NUMERIC(28, 10), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("listing_date", sa.Date(), nullable=True),
        sa.Column("raw_payload", JSONB(), nullable=True),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default="coingecko",
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
        sa.PrimaryKeyConstraint("symbol", "ts", "source", name="pk_raw_coingecko_market"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_coingecko_market_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_coingecko_market_quality",
        ),
    )
    create_hypertable("raw_coingecko_market", time_column="ts", chunk_interval="90 days")
    # D-58 row 13: segment_by=source (explicit) — differs from Coinglass tables
    enable_compression("raw_coingecko_market", segment_by="source", order_by="ts DESC")
    add_compression_policy("raw_coingecko_market", after_age="30 days")


def downgrade() -> None:
    """Drop raw_coingecko_market table."""
    op.drop_table("raw_coingecko_market")
