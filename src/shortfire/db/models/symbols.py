"""SQLAlchemy ORM model for the symbols relational lookup table.

D-63: symbols is a relational (non-hypertable) lookup with soft-delete via delisted_at.
STOR-07: soft-delete — delisted_at is DateTime(timezone=True) nullable; NULL = currently listed.
NAMING_CONVENTION: PK named pk_symbols; CHECK named ck_symbols_<constraint_name>.

HOT-PATH INGEST NOTE (D-69, D-70): Do NOT use this model for high-throughput writes.
Use copy_into_hypertable for hypertable hot-path; this model is for admin reads/writes.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from shortfire.db.base import Base


class Symbol(Base):
    """symbols lookup table — relational, soft-delete via delisted_at (D-63)."""

    __tablename__ = "symbols"
    __table_args__ = (CheckConstraint("tier IN (1, 2)", name="ck_symbols_tier"),)

    # ccxt unified symbol, e.g. 'BTC/USDT:USDT' — PK
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    # Exchange name — default 'mexc'
    exchange: Mapped[str] = mapped_column(Text, nullable=False, default="mexc")
    # 'swap' | 'spot' | 'future' — default 'swap' (perpetual futures)
    market_type: Mapped[str] = mapped_column(Text, nullable=False, default="swap")
    # MEXC native symbol, e.g. 'BTC_USDT' — used only at live-trade send time (Phase 5)
    mexc_native_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    # Cross-reference to Coinglass symbol (e.g. 'BTC') — nullable until enriched
    coinglass_symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cross-reference to CoinGecko coin ID (e.g. 'bitcoin') — nullable until enriched
    coingecko_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # tier 1 = top-50 by 7d volume; tier 2 = rest (D-46, RESEARCH.md §3.6)
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # Timestamp when this symbol was first observed in the universe
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Soft-delete: NULL = listed; non-NULL = delisted (STOR-07, D-63)
    # NEVER physically DELETE rows — UPDATE delisted_at = now() instead.
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Listing date from CoinGecko enrichment — nullable until enriched
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
