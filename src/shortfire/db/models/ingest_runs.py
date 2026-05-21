"""SQLAlchemy ORM model for the ingest_runs hypertable.

D-77: ingest_runs tracks per-job telemetry for every ingest run.
Used by APScheduler jobs to record job start/finish/status/rows_written.
kv_state JSONB stores round-robin cursor state (RESEARCH.md §4.6).

HOT-PATH INGEST NOTE (D-69, D-70): This model is for admin reads and low-volume
status writes. High-volume row inserts use copy_into_hypertable.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shortfire.db.base import Base


class IngestRun(Base):
    """ingest_runs hypertable — per-job run telemetry (D-77)."""

    __tablename__ = "ingest_runs"
    __table_args__ = (
        CheckConstraint(
            "source IN ('mexc_native','coinglass_aggregate','coinglass_mexc_only','coingecko')",
            name="ck_ingest_runs_source",
        ),
        CheckConstraint(
            "quality_flag IN ('ok','gap_detected','partial_candle','late_arrival',"
            "'ws_rest_divergence','schema_warn','partial_capture')",
            name="ck_ingest_runs_quality",
        ),
        CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name="ck_ingest_runs_status",
        ),
    )

    # UUID PK — part of composite PK with ts (TimescaleDB requires partition col in PK)
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    # Partition column (hypertable time dimension) — also in PK (TimescaleDB requirement)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)
    # Source identifier (e.g. 'mexc_native', 'coinglass_aggregate')
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # Dataset name (e.g. 'ohlcv_1m', 'funding')
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    # APScheduler job ID
    job_id: Mapped[str] = mapped_column(Text, nullable=False)
    # Job lifecycle timestamps
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Job status
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # Rows written in this run
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Error message if status='failed'
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Round-robin cursor state for ingest workers (RESEARCH.md §4.6)
    kv_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Quality flag
    quality_flag: Mapped[str] = mapped_column(Text, nullable=False, default="ok")
    # Insert timestamp
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
