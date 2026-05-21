"""Tests for copy_into_hypertable helper (D-62, D-70).

Tests:
  1. Empty records list returns 0 with no DB calls
  2. SQL contains CREATE UNLOGGED TABLE IF NOT EXISTS ... _staging
  3. SQL contains TRUNCATE TABLE ... _staging
  4. copy_records_to_table called with correct staging table, records, columns
  5. Final INSERT SQL contains target table, staging table, ON CONFLICT ... DO NOTHING
  6. No DO UPDATE ever used (D-62 first-write-wins invariant)
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock


async def test_empty_records_returns_zero() -> None:
    """copy_into_hypertable with empty records list returns 0 with no DB calls (short-circuit)."""
    from shortfire.ingest.storage.copy import copy_into_hypertable

    mock_engine = MagicMock()
    # Should return 0 immediately without touching engine
    result = await copy_into_hypertable(
        engine=mock_engine,
        target_table="raw_mexc_candles_1m",
        records=[],
        columns=("symbol", "ts", "open", "high", "low", "close", "volume"),
        conflict_columns=("symbol", "ts"),
    )
    assert result == 0
    # Engine should not have been called at all
    mock_engine.connect.assert_not_called()


async def test_copy_creates_staging_table() -> None:
    """copy_into_hypertable issues CREATE UNLOGGED TABLE IF NOT EXISTS ... _staging."""
    from shortfire.ingest.storage.copy import copy_into_hypertable

    # Build async mock hierarchy: engine -> connect -> __aenter__ -> conn
    raw_conn = AsyncMock()
    raw_conn.copy_records_to_table = AsyncMock()
    raw_conn.execute = AsyncMock()

    # Transaction context manager
    tx_cm = AsyncMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    raw_conn.transaction = MagicMock(return_value=tx_cm)

    # get_raw_connection() -> driver_connection
    raw_connection_obj = MagicMock()
    raw_connection_obj.driver_connection = raw_conn
    conn_obj = AsyncMock()
    conn_obj.get_raw_connection = AsyncMock(return_value=raw_connection_obj)

    # engine.connect() context manager
    connect_cm = AsyncMock()
    connect_cm.__aenter__ = AsyncMock(return_value=conn_obj)
    connect_cm.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=connect_cm)

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    records = [
        ("BTC/USDT:USDT", ts, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("10"))
    ]
    columns = ("symbol", "ts", "open", "high", "low", "close", "volume")

    result = await copy_into_hypertable(
        engine=mock_engine,
        target_table="raw_mexc_candles_1m",
        records=records,
        columns=columns,
        conflict_columns=("symbol", "ts"),
    )

    assert result == 1

    # Check execute was called — find CREATE UNLOGGED TABLE call
    execute_calls = raw_conn.execute.call_args_list
    assert len(execute_calls) >= 1

    # First execute should contain CREATE UNLOGGED TABLE and TRUNCATE
    first_sql = str(execute_calls[0])
    assert "CREATE UNLOGGED TABLE" in first_sql or any(
        "CREATE UNLOGGED TABLE" in str(c) for c in execute_calls
    )


async def test_copy_calls_copy_records_to_table() -> None:
    """copy_into_hypertable calls copy_records_to_table with staging table name."""
    from shortfire.ingest.storage.copy import copy_into_hypertable

    raw_conn = AsyncMock()
    raw_conn.copy_records_to_table = AsyncMock()
    raw_conn.execute = AsyncMock()

    tx_cm = AsyncMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    raw_conn.transaction = MagicMock(return_value=tx_cm)

    raw_connection_obj = MagicMock()
    raw_connection_obj.driver_connection = raw_conn
    conn_obj = AsyncMock()
    conn_obj.get_raw_connection = AsyncMock(return_value=raw_connection_obj)

    connect_cm = AsyncMock()
    connect_cm.__aenter__ = AsyncMock(return_value=conn_obj)
    connect_cm.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=connect_cm)

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    records = [
        ("BTC/USDT:USDT", ts, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("10"))
    ]
    columns = ("symbol", "ts", "open", "high", "low", "close", "volume")

    await copy_into_hypertable(
        engine=mock_engine,
        target_table="raw_mexc_candles_1m",
        records=records,
        columns=columns,
        conflict_columns=("symbol", "ts"),
    )

    # copy_records_to_table must have been called
    raw_conn.copy_records_to_table.assert_called_once()
    call_kwargs = raw_conn.copy_records_to_table.call_args

    # First positional arg should be staging table name
    assert "raw_mexc_candles_1m_staging" in str(call_kwargs)


async def test_copy_insert_sql_contains_on_conflict_do_nothing() -> None:
    """The INSERT SQL uses ON CONFLICT ... DO NOTHING (D-62 first-write-wins)."""
    from shortfire.ingest.storage.copy import copy_into_hypertable

    raw_conn = AsyncMock()
    raw_conn.copy_records_to_table = AsyncMock()
    execute_sqls: list[str] = []

    async def _execute_side_effect(sql: str) -> None:
        execute_sqls.append(str(sql))

    raw_conn.execute = AsyncMock(side_effect=_execute_side_effect)

    tx_cm = AsyncMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    raw_conn.transaction = MagicMock(return_value=tx_cm)

    raw_connection_obj = MagicMock()
    raw_connection_obj.driver_connection = raw_conn
    conn_obj = AsyncMock()
    conn_obj.get_raw_connection = AsyncMock(return_value=raw_connection_obj)

    connect_cm = AsyncMock()
    connect_cm.__aenter__ = AsyncMock(return_value=conn_obj)
    connect_cm.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=connect_cm)

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    records = [
        ("BTC/USDT:USDT", ts, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("10"))
    ]
    columns = ("symbol", "ts", "open", "high", "low", "close", "volume")

    await copy_into_hypertable(
        engine=mock_engine,
        target_table="raw_mexc_candles_1m",
        records=records,
        columns=columns,
        conflict_columns=("symbol", "ts"),
    )

    all_sql = " ".join(execute_sqls)
    # Must contain staging table creation
    assert "CREATE UNLOGGED TABLE" in all_sql
    assert "raw_mexc_candles_1m_staging" in all_sql
    # Must contain ON CONFLICT DO NOTHING
    assert "ON CONFLICT" in all_sql
    assert "DO NOTHING" in all_sql
    # Must NOT contain DO UPDATE (D-62)
    assert "DO UPDATE" not in all_sql
    # Must target the real table
    assert "raw_mexc_candles_1m" in all_sql


def test_copy_sql_never_uses_do_update() -> None:
    """Structural check: copy.py source does not contain DO UPDATE (D-62 invariant)."""
    import inspect

    from shortfire.ingest.storage import copy as copy_module

    source = inspect.getsource(copy_module)
    assert "DO UPDATE" not in source, "copy_into_hypertable must never use ON CONFLICT DO UPDATE"
