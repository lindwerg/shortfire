"""Tests for write_to_dead_letter (D-74).

Tests:
  1. Calls copy_into_hypertable with target_table="dead_letter" and conflict_columns=("id",)
  2. error_msg is truncated to 2000 characters
  3. Record index 0 is a UUID
  4. Record index 1 is a tz-aware datetime
  5. Record index 9 (quality_flag) is "schema_warn"
  6. source is set correctly in the record
  7. raw_payload bytes are decoded to str
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


async def test_dead_letter_calls_copy_with_correct_table() -> None:
    """write_to_dead_letter calls copy_into_hypertable with target_table='dead_letter'."""
    with (
        patch("shortfire.ingest.dead_letter.writer.copy_into_hypertable") as mock_copy,
        patch("shortfire.ingest.dead_letter.writer.get_engine") as mock_engine,
    ):
        mock_copy.__aenter__ = AsyncMock()
        mock_copy.return_value = 1
        mock_copy.side_effect = None
        mock_copy_async = AsyncMock(return_value=1)
        mock_engine.return_value = MagicMock()

        # Patch copy_into_hypertable as an awaitable
        with patch(
            "shortfire.ingest.dead_letter.writer.copy_into_hypertable",
            new=mock_copy_async,
        ):
            from shortfire.ingest.dead_letter.writer import write_to_dead_letter

            await write_to_dead_letter(
                source="coinglass_aggregate",
                endpoint="/api/futures/funding-rate-list",
                symbol=None,
                raw_payload='{"bad": 1}',
                error_type="ValidationError",
                error_msg="field required",
                retries_attempted=0,
            )

        call_kwargs = mock_copy_async.call_args
        assert call_kwargs is not None
        assert call_kwargs[1].get("target_table") == "dead_letter" or (
            len(call_kwargs[0]) > 1 and call_kwargs[0][1] == "dead_letter"
        )


async def test_dead_letter_conflict_columns_is_id() -> None:
    """write_to_dead_letter passes conflict_columns=('id',) to copy_into_hypertable."""
    mock_copy_async = AsyncMock(return_value=1)
    mock_engine = MagicMock()

    with (
        patch("shortfire.ingest.dead_letter.writer.copy_into_hypertable", new=mock_copy_async),
        patch("shortfire.ingest.dead_letter.writer.get_engine", return_value=mock_engine),
    ):
        from shortfire.ingest.dead_letter.writer import write_to_dead_letter

        await write_to_dead_letter(
            source="coinglass_aggregate",
            endpoint="/api/futures/funding-rate-list",
            symbol=None,
            raw_payload='{"bad": 1}',
            error_type="ValidationError",
            error_msg="field required",
            retries_attempted=0,
        )

    call_kwargs = mock_copy_async.call_args
    # conflict_columns should be ("id",) regardless of positional or keyword
    all_args = str(call_kwargs)
    assert "('id',)" in all_args or '("id",)' in all_args


async def test_dead_letter_error_msg_truncated_to_2000() -> None:
    """write_to_dead_letter truncates error_msg to 2000 chars (D-74)."""
    captured_records: list[tuple] = []

    async def _mock_copy(
        engine,
        target_table,
        records,
        columns,
        conflict_columns,
    ) -> int:
        captured_records.extend(records)
        return len(records)

    mock_engine = MagicMock()
    with (
        patch("shortfire.ingest.dead_letter.writer.copy_into_hypertable", side_effect=_mock_copy),
        patch("shortfire.ingest.dead_letter.writer.get_engine", return_value=mock_engine),
    ):
        from shortfire.ingest.dead_letter.writer import write_to_dead_letter

        long_msg = "x" * 3000  # > 2000 chars
        await write_to_dead_letter(
            source="coinglass_aggregate",
            endpoint="/api/futures/funding-rate-list",
            symbol=None,
            raw_payload='{"bad": 1}',
            error_type="ValidationError",
            error_msg=long_msg,
            retries_attempted=0,
        )

    assert len(captured_records) == 1
    record = captured_records[0]
    # index 7 = error_msg
    assert len(record[7]) == 2000


async def test_dead_letter_record_id_is_uuid() -> None:
    """First element of the dead_letter record is a UUID."""
    captured_records: list[tuple] = []

    async def _mock_copy(engine, target_table, records, columns, conflict_columns) -> int:
        captured_records.extend(records)
        return len(records)

    mock_engine = MagicMock()
    with (
        patch("shortfire.ingest.dead_letter.writer.copy_into_hypertable", side_effect=_mock_copy),
        patch("shortfire.ingest.dead_letter.writer.get_engine", return_value=mock_engine),
    ):
        from shortfire.ingest.dead_letter.writer import write_to_dead_letter

        await write_to_dead_letter(
            source="coinglass_aggregate",
            endpoint="/api/futures/funding-rate-list",
            symbol=None,
            raw_payload='{"bad": 1}',
            error_type="ValidationError",
            error_msg="field required",
            retries_attempted=0,
        )

    record = captured_records[0]
    assert isinstance(record[0], uuid.UUID)


async def test_dead_letter_record_ts_is_tz_aware() -> None:
    """Second element of the dead_letter record is a tz-aware datetime."""
    captured_records: list[tuple] = []

    async def _mock_copy(engine, target_table, records, columns, conflict_columns) -> int:
        captured_records.extend(records)
        return len(records)

    mock_engine = MagicMock()
    with (
        patch("shortfire.ingest.dead_letter.writer.copy_into_hypertable", side_effect=_mock_copy),
        patch("shortfire.ingest.dead_letter.writer.get_engine", return_value=mock_engine),
    ):
        from shortfire.ingest.dead_letter.writer import write_to_dead_letter

        await write_to_dead_letter(
            source="coinglass_aggregate",
            endpoint="/api/futures/funding-rate-list",
            symbol=None,
            raw_payload='{"bad": 1}',
            error_type="ValidationError",
            error_msg="field required",
            retries_attempted=0,
        )

    record = captured_records[0]
    assert isinstance(record[1], datetime)
    assert record[1].tzinfo is not None, "ts must be tz-aware"


async def test_dead_letter_record_quality_flag_is_schema_warn() -> None:
    """Last (index 9) element of the dead_letter record is 'schema_warn'."""
    captured_records: list[tuple] = []

    async def _mock_copy(engine, target_table, records, columns, conflict_columns) -> int:
        captured_records.extend(records)
        return len(records)

    mock_engine = MagicMock()
    with (
        patch("shortfire.ingest.dead_letter.writer.copy_into_hypertable", side_effect=_mock_copy),
        patch("shortfire.ingest.dead_letter.writer.get_engine", return_value=mock_engine),
    ):
        from shortfire.ingest.dead_letter.writer import write_to_dead_letter

        await write_to_dead_letter(
            source="coinglass_aggregate",
            endpoint="/api/futures/funding-rate-list",
            symbol=None,
            raw_payload='{"bad": 1}',
            error_type="ValidationError",
            error_msg="field required",
            retries_attempted=0,
        )

    record = captured_records[0]
    assert record[9] == "schema_warn"


async def test_dead_letter_bytes_payload_decoded() -> None:
    """raw_payload as bytes is decoded to str in the record."""
    captured_records: list[tuple] = []

    async def _mock_copy(engine, target_table, records, columns, conflict_columns) -> int:
        captured_records.extend(records)
        return len(records)

    mock_engine = MagicMock()
    with (
        patch("shortfire.ingest.dead_letter.writer.copy_into_hypertable", side_effect=_mock_copy),
        patch("shortfire.ingest.dead_letter.writer.get_engine", return_value=mock_engine),
    ):
        from shortfire.ingest.dead_letter.writer import write_to_dead_letter

        await write_to_dead_letter(
            source="mexc_native",
            endpoint="fetch_ohlcv",
            symbol="BTC/USDT:USDT",
            raw_payload=b'{"raw": "bytes"}',  # bytes payload
            error_type="ValidationError",
            error_msg="bad field",
            retries_attempted=2,
        )

    record = captured_records[0]
    # index 5 = raw_payload — must be str
    assert isinstance(record[5], str)
    assert '{"raw": "bytes"}' in record[5]
