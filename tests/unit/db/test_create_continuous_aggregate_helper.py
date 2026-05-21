"""Unit tests for create_continuous_aggregate helper in shortfire.db.timescale.

Tests SQL shape via mock — no real database required.
All tests patch alembic.op so no real database is required.

The helper issues two op.execute calls:
  1. CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)
  2. SELECT add_continuous_aggregate_policy(...)
Tests combine both call SQL strings for assertions.

Requirements: D-27 (helper preserves the "never raw op.execute for TimescaleDB DDL" discipline),
D-95 (D-27 carve-out via helper), RESEARCH.md §3.5.
"""

from unittest.mock import patch

from shortfire.db.timescale import create_continuous_aggregate


def _combined_sql(mock_op) -> str:  # type: ignore[no-untyped-def]
    """Combine SQL from all op.execute calls for assertion coverage."""
    return " ".join(str(c[0][0]) for c in mock_op.execute.call_args_list)


def test_create_continuous_aggregate_5m_sql_shape() -> None:
    """create_continuous_aggregate must issue SQL with all required TimescaleDB CA elements."""
    with patch("shortfire.db.timescale.op") as mock_op:
        create_continuous_aggregate(
            view_name="raw_mexc_candles_5m",
            source_table="raw_mexc_candles_1m",
            bucket="5 minutes",
            select_columns=("symbol, time_bucket('5 minutes', ts) AS ts, sum(volume) AS volume"),
            start_offset="2 hours",
            end_offset="5 minutes",
            schedule_interval="5 minutes",
        )
        # Two calls: CREATE MATERIALIZED VIEW + add_continuous_aggregate_policy
        assert mock_op.execute.call_count == 2
        sql = _combined_sql(mock_op)
        assert "CREATE MATERIALIZED VIEW raw_mexc_candles_5m" in sql
        assert "WITH (timescaledb.continuous)" in sql
        assert "FROM raw_mexc_candles_1m" in sql
        assert "WITH NO DATA" in sql
        assert "add_continuous_aggregate_policy" in sql
        assert "INTERVAL '2 hours'" in sql
        assert "INTERVAL '5 minutes'" in sql


def test_create_continuous_aggregate_default_group_by() -> None:
    """Default group_by uses symbol + time_bucket when group_by is not supplied."""
    with patch("shortfire.db.timescale.op") as mock_op:
        create_continuous_aggregate(
            view_name="raw_mexc_candles_5m",
            source_table="raw_mexc_candles_1m",
            bucket="5 minutes",
            select_columns=("symbol, time_bucket('5 minutes', ts) AS ts, sum(volume) AS volume"),
        )
        sql = _combined_sql(mock_op)
        assert "GROUP BY symbol, time_bucket('5 minutes', ts)" in sql


def test_create_continuous_aggregate_custom_group_by() -> None:
    """Custom group_by overrides the default when supplied."""
    custom_group = "symbol, time_bucket('15 minutes', ts), source"
    with patch("shortfire.db.timescale.op") as mock_op:
        create_continuous_aggregate(
            view_name="raw_mexc_candles_15m",
            source_table="raw_mexc_candles_1m",
            bucket="15 minutes",
            select_columns="symbol, time_bucket('15 minutes', ts) AS ts",
            group_by=custom_group,
        )
        sql = _combined_sql(mock_op)
        assert f"GROUP BY {custom_group}" in sql


def test_create_continuous_aggregate_schedule_interval_in_sql() -> None:
    """schedule_interval must appear in the add_continuous_aggregate_policy call."""
    with patch("shortfire.db.timescale.op") as mock_op:
        create_continuous_aggregate(
            view_name="raw_mexc_candles_1h",
            source_table="raw_mexc_candles_1m",
            bucket="1 hour",
            select_columns="symbol, time_bucket('1 hour', ts) AS ts",
            start_offset="12 hours",
            end_offset="1 hour",
            schedule_interval="1 hour",
        )
        sql = _combined_sql(mock_op)
        assert "INTERVAL '12 hours'" in sql
        assert "INTERVAL '1 hour'" in sql
        assert "schedule_interval" in sql


def test_create_continuous_aggregate_4h_parameters() -> None:
    """4h aggregate: start_offset=2 days, end_offset=4 hours (D-67 locked values)."""
    with patch("shortfire.db.timescale.op") as mock_op:
        create_continuous_aggregate(
            view_name="raw_mexc_candles_4h",
            source_table="raw_mexc_candles_1m",
            bucket="4 hours",
            select_columns="symbol, time_bucket('4 hours', ts) AS ts",
            start_offset="2 days",
            end_offset="4 hours",
            schedule_interval="4 hours",
        )
        sql = _combined_sql(mock_op)
        assert "INTERVAL '2 days'" in sql
        assert "INTERVAL '4 hours'" in sql
