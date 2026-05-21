"""SQLAlchemy ORM models for relational/admin lookup tables.

These models are used for admin-only writes and reads to relational (non-hypertable)
and low-volume operational tables: symbols, ingest_runs, dead_letter.

HOT-PATH INGEST NOTE (D-69, D-70):
Hypertable INSERT hot-path goes through copy_into_hypertable (asyncpg COPY),
NOT through these ORM models. ORM is admin-write / read-only for lookup data.
"""

from shortfire.db.models.dead_letter import DeadLetter
from shortfire.db.models.ingest_runs import IngestRun
from shortfire.db.models.symbols import Symbol

__all__ = ["DeadLetter", "IngestRun", "Symbol"]
