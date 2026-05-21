"""init timescaledb extension

Revision ID: 0001
Revises: None
Create Date: 2026-05-21

D-28: This migration must run BEFORE 0002 — create_hypertable() does not
exist until the timescaledb extension is loaded (Pitfall 3).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the timescaledb extension (idempotent)."""
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")


def downgrade() -> None:
    """Drop the timescaledb extension."""
    op.execute("DROP EXTENSION IF EXISTS timescaledb")
