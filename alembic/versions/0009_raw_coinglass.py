"""Four Coinglass hypertables: funding_agg, oi, liq, lsr

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-21

D-58 inventory rows 9–12: typed-per-source Coinglass aggregate tables.
D-07 (DATA-07): Coinglass derivatives data for funding/OI/liquidation/long-short ratio.
D-52: Pydantic v2 schemas per endpoint; source='coinglass_aggregate' always in Phase 1.
D-59: source TEXT NOT NULL + CHECK enum (DATA-12)
D-60: quality_flag TEXT NOT NULL DEFAULT 'ok' + CHECK enum
D-61: ingested_at TIMESTAMP(timezone=True) NOT NULL DEFAULT now()
D-65: every time column is TIMESTAMP(timezone=True)
D-66: compression DDL goes through shortfire.db.timescale helpers (D-27)

All four tables share the same source/quality_flag CHECK enums and compression policy (7 days).
PK includes source so rows from different aggregate sources don't collide.
raw_coinglass_liq has side in its PK because two liquidations at the same ts would otherwise collide.
"""

import sqlalchemy as sa

from alembic import op
from shortfire.db.timescale import add_compression_policy, create_hypertable, enable_compression

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
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
    """Create four Coinglass aggregate hypertables (D-58, D-27).

    All four tables share:
    - source TEXT NOT NULL with CHECK enum (D-59)
    - quality_flag TEXT NOT NULL DEFAULT 'ok' with CHECK enum (D-60)
    - ingested_at TIMESTAMP(timezone=True) DEFAULT now() (D-61)
    - 30-day chunk intervals (D-58) — except raw_coinglass_liq (7 days)
    - compression segmented by symbol, after 7 days (D-66)
    """
    # --- raw_coinglass_funding_agg (D-58 row 9) ---
    op.create_table(
        "raw_coinglass_funding_agg",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("funding_rate", sa.NUMERIC(28, 18), nullable=False),
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
        sa.PrimaryKeyConstraint("symbol", "ts", "source", name="pk_raw_coinglass_funding_agg"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_coinglass_funding_agg_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_coinglass_funding_agg_quality",
        ),
    )
    create_hypertable("raw_coinglass_funding_agg", time_column="ts", chunk_interval="30 days")
    enable_compression("raw_coinglass_funding_agg", segment_by="symbol", order_by="ts DESC")
    add_compression_policy("raw_coinglass_funding_agg", after_age="7 days")

    # --- raw_coinglass_oi (D-58 row 10) ---
    op.create_table(
        "raw_coinglass_oi",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("open_interest", sa.NUMERIC(28, 10), nullable=False),
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
        sa.PrimaryKeyConstraint("symbol", "ts", "source", name="pk_raw_coinglass_oi"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_coinglass_oi_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_coinglass_oi_quality",
        ),
    )
    create_hypertable("raw_coinglass_oi", time_column="ts", chunk_interval="30 days")
    enable_compression("raw_coinglass_oi", segment_by="symbol", order_by="ts DESC")
    add_compression_policy("raw_coinglass_oi", after_age="7 days")

    # --- raw_coinglass_liq (D-58 row 11) ---
    # side must be in the PK: two liquidations at the same ts for different sides would collide
    op.create_table(
        "raw_coinglass_liq",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("liquidation_usd", sa.NUMERIC(28, 10), nullable=False),
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
        # side in PK to prevent same-ts collision between 'short' and 'long'
        sa.PrimaryKeyConstraint("symbol", "ts", "source", "side", name="pk_raw_coinglass_liq"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_coinglass_liq_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_coinglass_liq_quality",
        ),
        sa.CheckConstraint(
            "side IN ('short','long')",
            name="ck_raw_coinglass_liq_side",
        ),
    )
    create_hypertable("raw_coinglass_liq", time_column="ts", chunk_interval="7 days")
    enable_compression("raw_coinglass_liq", segment_by="symbol", order_by="ts DESC")
    add_compression_policy("raw_coinglass_liq", after_age="7 days")

    # --- raw_coinglass_lsr (D-58 row 12 — long/short ratio) ---
    op.create_table(
        "raw_coinglass_lsr",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("long_short_ratio", sa.NUMERIC(28, 10), nullable=False),
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
        sa.PrimaryKeyConstraint("symbol", "ts", "source", name="pk_raw_coinglass_lsr"),
        sa.CheckConstraint(
            f"source IN {_SOURCE_ENUM}",
            name="ck_raw_coinglass_lsr_source",
        ),
        sa.CheckConstraint(
            f"quality_flag IN {_QUALITY_FLAG_ENUM}",
            name="ck_raw_coinglass_lsr_quality",
        ),
    )
    create_hypertable("raw_coinglass_lsr", time_column="ts", chunk_interval="30 days")
    enable_compression("raw_coinglass_lsr", segment_by="symbol", order_by="ts DESC")
    add_compression_policy("raw_coinglass_lsr", after_age="7 days")


def downgrade() -> None:
    """Drop all four Coinglass aggregate tables (reverse order)."""
    op.drop_table("raw_coinglass_lsr")
    op.drop_table("raw_coinglass_liq")
    op.drop_table("raw_coinglass_oi")
    op.drop_table("raw_coinglass_funding_agg")
