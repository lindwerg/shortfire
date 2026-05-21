"""Continuous aggregates 5m / 15m / 1h / 4h over raw_mexc_candles_1m

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-21

D-67: Continuous aggregates for 5m / 15m / 1h / 4h sourced from raw_mexc_candles_1m.
D-95 + RESEARCH.md §3.5: continuous aggregate DDL goes through `create_continuous_aggregate`
helper, NOT raw op.execute — preserves D-27 discipline. The helper is the lone TimescaleDB DDL
whose Alembic story did not exist before Phase 1.

Per-aggregate locked (start_offset, end_offset, schedule_interval, bucket) from D-67:
  5m:  (2 hours, 5 minutes,  5 minutes)
  15m: (4 hours, 15 minutes, 15 minutes)
  1h:  (12 hours, 1 hour,    1 hour)
  4h:  (2 days,  4 hours,    4 hours)

All start_offset values are inside the 7-day compression-after window on raw_mexc_candles_1m
so refreshes never touch compressed chunks (T-1-CA-02 mitigation).

SELECT shape (D-67):
  symbol,
  time_bucket('<bucket>', ts) AS ts,
  first(open, ts)  AS open,
  max(high)        AS high,
  min(low)         AS low,
  last(close, ts)  AS close,
  sum(volume)      AS volume,
  max(quality_flag) AS quality_flag,   -- propagate worst flag in bucket (T-1-CA-01)
  'mexc_native'::TEXT AS source

T-1-CA-01: max(quality_flag) propagation relies on alphabetical ordering coincidentally
mapping to severity for the current enum. Phase 2 adds quality_severity SMALLINT if
this assumption breaks down.
"""

from alembic import op
from shortfire.db.timescale import create_continuous_aggregate

# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _select_columns(bucket: str) -> str:
    """Return the standard SELECT clause for a continuous aggregate at the given bucket width."""
    return (
        f"symbol,\n"
        f"        time_bucket('{bucket}', ts) AS ts,\n"
        f"        first(open, ts)   AS open,\n"
        f"        max(high)         AS high,\n"
        f"        min(low)          AS low,\n"
        f"        last(close, ts)   AS close,\n"
        f"        sum(volume)       AS volume,\n"
        f"        max(quality_flag) AS quality_flag,\n"
        f"        'mexc_native'::TEXT AS source"
    )


# D-95 + RESEARCH.md §3.5: continuous aggregate DDL goes through `create_continuous_aggregate`
# helper, NOT raw op.execute — preserves D-27 discipline.
def upgrade() -> None:
    """Create 4 continuous aggregates over raw_mexc_candles_1m (D-67, D-95, D-27 carve-out)."""
    # 5m aggregate (start_offset=2 hours, end_offset=5 minutes, schedule=5 minutes)
    create_continuous_aggregate(
        view_name="raw_mexc_candles_5m",
        source_table="raw_mexc_candles_1m",
        bucket="5 minutes",
        select_columns=_select_columns("5 minutes"),
        start_offset="2 hours",
        end_offset="5 minutes",
        schedule_interval="5 minutes",
    )

    # 15m aggregate (start_offset=4 hours, end_offset=15 minutes, schedule=15 minutes)
    create_continuous_aggregate(
        view_name="raw_mexc_candles_15m",
        source_table="raw_mexc_candles_1m",
        bucket="15 minutes",
        select_columns=_select_columns("15 minutes"),
        start_offset="4 hours",
        end_offset="15 minutes",
        schedule_interval="15 minutes",
    )

    # 1h aggregate (start_offset=12 hours, end_offset=1 hour, schedule=1 hour)
    create_continuous_aggregate(
        view_name="raw_mexc_candles_1h",
        source_table="raw_mexc_candles_1m",
        bucket="1 hour",
        select_columns=_select_columns("1 hour"),
        start_offset="12 hours",
        end_offset="1 hour",
        schedule_interval="1 hour",
    )

    # 4h aggregate (start_offset=2 days, end_offset=4 hours, schedule=4 hours)
    create_continuous_aggregate(
        view_name="raw_mexc_candles_4h",
        source_table="raw_mexc_candles_1m",
        bucket="4 hours",
        select_columns=_select_columns("4 hours"),
        start_offset="2 days",
        end_offset="4 hours",
        schedule_interval="4 hours",
    )


def downgrade() -> None:
    """Drop all 4 continuous aggregates (reverse order).

    Note: CASCADE here is on DROP MATERIALIZED VIEW — it drops dependent objects
    (e.g. refresh policies). This is a DIFFERENT SQL construct from the cascade-on-delete
    FK syntax; the Phase 0 grep guard correctly does NOT flag DROP MATERIALIZED VIEW ... CASCADE.
    """
    op.execute("DROP MATERIALIZED VIEW IF EXISTS raw_mexc_candles_4h CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS raw_mexc_candles_1h CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS raw_mexc_candles_15m CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS raw_mexc_candles_5m CASCADE")
