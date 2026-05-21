"""symbols relational lookup table

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-21

D-63: symbols is a relational lookup table — NOT a hypertable.
STOR-07: soft-delete via delisted_at (TIMESTAMP(timezone=True), nullable).

Key design decisions:
- This is a plain relational table (no create_hypertable call).
- symbol is the PK (ccxt unified symbol, e.g. 'BTC/USDT:USDT').
- delisted_at is nullable TIMESTAMP(timezone=True) — NULL means currently listed.
- Cascade deletes are structurally absent and banned project-wide (T-1-SOFT-01).
  No foreign keys are defined in this migration (other tables reference symbols.symbol
  via TEXT only, not FK constraints — this prevents any cascade chain).
- tier INTEGER: tier 1 = top-50 by 7d volume, tier 2 = rest (D-46, D-58 §3.6).
  CHECK (tier IN (1, 2)).

D-65: listed_at and delisted_at and first_seen_at are all TIMESTAMP(timezone=True).
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create symbols relational lookup table (D-63, D-27).

    Plain relational table — no create_hypertable call.
    Soft-delete via delisted_at; hard DELETE is never used.
    No foreign key constraints to prevent any accidental cascade deletes.
    """
    op.create_table(
        "symbols",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column(
            "exchange",
            sa.Text(),
            nullable=False,
            server_default="mexc",
        ),
        sa.Column(
            "market_type",
            sa.Text(),
            nullable=False,
            server_default="swap",
        ),
        sa.Column("mexc_native_symbol", sa.Text(), nullable=False),
        sa.Column("coinglass_symbol", sa.Text(), nullable=True),
        sa.Column("coingecko_id", sa.Text(), nullable=True),
        sa.Column(
            "tier",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column(
            "first_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # delisted_at is nullable TIMESTAMP(timezone=True) — NULL = currently listed (D-63)
        sa.Column("delisted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # listed_at from CoinGecko enrichment — nullable until enriched
        sa.Column("listed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # PK named per NAMING_CONVENTION
        sa.PrimaryKeyConstraint("symbol", name="pk_symbols"),
        # tier 1 = top-50 by 7d volume, tier 2 = rest (D-46, RESEARCH.md §3.6)
        sa.CheckConstraint("tier IN (1, 2)", name="ck_symbols_tier"),
        # NOTE: no foreign keys defined — other tables reference symbols.symbol
        # via TEXT match only to prevent any future cascade path.
        # Cascade deletes are banned project-wide (T-1-SOFT-01, Phase 0 grep guard).
    )
    # No create_hypertable — symbols is a relational table (D-63)
    # No enable_compression / add_compression_policy — relational, not hypertable


def downgrade() -> None:
    """Drop symbols table."""
    op.drop_table("symbols")
