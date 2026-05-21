"""SQLAlchemy ORM model for the dead_letter hypertable.

D-74: dead_letter captures Pydantic ValidationErrors and exhausted-retry exceptions.
DATA-11: every validation failure lands here rather than crashing the ingest loop.

raw_payload is TEXT (not JSONB) — a malformed API response may not be valid JSON;
storing as TEXT preserves forensics. See migration 0013 for the rationale.

HOT-PATH INGEST NOTE (D-69, D-70): This model is for admin reads and alerter queries.
The dead_letter writer (src/shortfire/ingest/dead_letter/writer.py) uses asyncpg direct
inserts for the write hot path.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shortfire.db.base import Base


class DeadLetter(Base):
    """dead_letter hypertable — forensic capture for ingest failures (D-74)."""

    __tablename__ = "dead_letter"
    __table_args__ = (
        CheckConstraint(
            "source IN ('mexc_native','coinglass_aggregate','coinglass_mexc_only','coingecko')",
            name="ck_dead_letter_source",
        ),
        CheckConstraint(
            "quality_flag IN ('ok','gap_detected','partial_candle','late_arrival',"
            "'ws_rest_divergence','schema_warn','partial_capture')",
            name="ck_dead_letter_quality",
        ),
    )

    # UUID PK — part of composite PK with ts (TimescaleDB requires partition col in PK)
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    # Partition column (hypertable time dimension) — also in PK (TimescaleDB requirement)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)
    # Source that produced the failure
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # API endpoint that produced the failure (e.g. 'fetch_ohlcv')
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    # Symbol context (nullable — not every error is per-symbol)
    symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Raw API response as TEXT (not JSONB — malformed JSON must still be stored)
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    # Exception class name (e.g. 'ValidationError', 'HTTPStatusError')
    error_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Truncated error message (truncate to 2KB at write time)
    error_msg: Mapped[str] = mapped_column(Text, nullable=False)
    # Number of retry attempts before this row was written
    retries_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Quality flag — default 'schema_warn' for dead-letter rows
    quality_flag: Mapped[str] = mapped_column(Text, nullable=False, default="schema_warn")
