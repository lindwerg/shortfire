"""Tests for shortfire.db.timescale — idempotent DDL helper SQL shapes (D-27).

All tests patch alembic.op so no real database is required.
"""

from unittest.mock import patch

from shortfire.db.timescale import (
    add_compression_policy,
    add_retention_policy,
    create_hypertable,
    enable_compression,
)


def test_create_hypertable_sql_shape() -> None:
    """create_hypertable must issue SQL containing all required TimescaleDB arguments."""
    with patch("shortfire.db.timescale.op") as mock_op:
        create_hypertable("service_event")
        mock_op.execute.assert_called_once()
        sql_arg = str(mock_op.execute.call_args[0][0])
        assert "create_hypertable" in sql_arg
        assert "'service_event'" in sql_arg
        assert "chunk_time_interval" in sql_arg
        assert "INTERVAL '7 days'" in sql_arg
        assert "if_not_exists => TRUE" in sql_arg


def test_create_hypertable_custom_args() -> None:
    """create_hypertable respects overridden time_column and chunk_interval."""
    with patch("shortfire.db.timescale.op") as mock_op:
        create_hypertable("candle", time_column="open_time", chunk_interval="1 day")
        sql_arg = str(mock_op.execute.call_args[0][0])
        assert "'open_time'" in sql_arg
        assert "INTERVAL '1 day'" in sql_arg


def test_enable_compression_sql_shape() -> None:
    """enable_compression must issue ALTER TABLE with compress settings."""
    with patch("shortfire.db.timescale.op") as mock_op:
        enable_compression("service_event", segment_by="service_name")
        mock_op.execute.assert_called_once()
        sql_arg = str(mock_op.execute.call_args[0][0])
        assert "timescaledb.compress" in sql_arg
        assert "compress_segmentby = 'service_name'" in sql_arg
        assert "compress_orderby = 'ts DESC'" in sql_arg


def test_enable_compression_custom_order_by() -> None:
    """enable_compression must respect a custom order_by argument."""
    with patch("shortfire.db.timescale.op") as mock_op:
        enable_compression("candle", segment_by="symbol", order_by="open_time DESC")
        sql_arg = str(mock_op.execute.call_args[0][0])
        assert "compress_orderby = 'open_time DESC'" in sql_arg


def test_add_compression_policy_sql_shape() -> None:
    """add_compression_policy must call add_compression_policy with INTERVAL and if_not_exists."""
    with patch("shortfire.db.timescale.op") as mock_op:
        add_compression_policy("service_event")
        mock_op.execute.assert_called_once()
        sql_arg = str(mock_op.execute.call_args[0][0])
        assert "add_compression_policy" in sql_arg
        assert "'service_event'" in sql_arg
        assert "INTERVAL '7 days'" in sql_arg
        assert "if_not_exists => TRUE" in sql_arg


def test_add_compression_policy_custom_age() -> None:
    """add_compression_policy respects a custom after_age."""
    with patch("shortfire.db.timescale.op") as mock_op:
        add_compression_policy("candle", after_age="30 days")
        sql_arg = str(mock_op.execute.call_args[0][0])
        assert "INTERVAL '30 days'" in sql_arg


def test_add_retention_policy_sql_shape() -> None:
    """add_retention_policy must call add_retention_policy with INTERVAL and if_not_exists."""
    with patch("shortfire.db.timescale.op") as mock_op:
        add_retention_policy("service_event", drop_after="365 days")
        mock_op.execute.assert_called_once()
        sql_arg = str(mock_op.execute.call_args[0][0])
        assert "add_retention_policy" in sql_arg
        assert "'service_event'" in sql_arg
        assert "INTERVAL '365 days'" in sql_arg
        assert "if_not_exists => TRUE" in sql_arg
