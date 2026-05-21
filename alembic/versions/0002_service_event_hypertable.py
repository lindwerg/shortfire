"""service_event hypertable + compression policy

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-21

D-28: service_event is a REAL long-term observability table, not a throwaway
smoke object. Every service writes heartbeat/restart/task events here.
Survives into Phase 1+ to power ad-hoc operator queries:
  SELECT * FROM service_event WHERE event_type = 'startup' ORDER BY ts DESC LIMIT 20;
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op
from shortfire.db.timescale import add_compression_policy, create_hypertable, enable_compression

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create service_event hypertable with compression policy (D-28, D-27)."""
    op.create_table(
        "service_event",
        sa.Column(
            "ts",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
    )
    # Time-partition via hypertable; no app-level PK uniqueness needed
    # (time-series append pattern, queried by ts range + service_name).
    create_hypertable("service_event", time_column="ts", chunk_interval="7 days")
    enable_compression("service_event", segment_by="service_name", order_by="ts DESC")
    add_compression_policy("service_event", after_age="7 days")


def downgrade() -> None:
    """Drop service_event table (includes hypertable chunks + compression policy)."""
    op.drop_table("service_event")
