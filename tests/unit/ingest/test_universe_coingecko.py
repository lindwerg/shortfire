"""Unit tests for fetch_and_write_daily (TDD RED → GREEN).

Tests verify:
  - Returns 0 when FakeCoinGeckoClient returns None (API failure)
  - Returns correct count when rows are written
  - Passes correct columns and conflict_columns to copy_into_hypertable
  - ts defaults to datetime.now(UTC) if not supplied
  - to_record() called with ts for each row
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from shortfire.ingest.coingecko.universe import fetch_and_write_daily

from tests.fakes.coingecko import CANNED_MARKETS_ROWS, FakeCoinGeckoClient

_FROZEN_TS = datetime(2026, 5, 21, 0, 30, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_returns_zero_when_client_returns_none() -> None:
    """fetch_and_write_daily returns 0 when FakeCoinGeckoClient.fetch_coins_markets → None."""
    engine = AsyncMock()
    client = FakeCoinGeckoClient(canned_markets=None)

    result = await fetch_and_write_daily(engine=engine, client=client, ts=_FROZEN_TS)

    assert result == 0


@pytest.mark.asyncio
async def test_returns_zero_when_no_rows() -> None:
    """fetch_and_write_daily returns 0 when client returns empty tuple."""
    engine = AsyncMock()
    client = FakeCoinGeckoClient(canned_markets=())

    result = await fetch_and_write_daily(engine=engine, client=client, ts=_FROZEN_TS)

    assert result == 0


@pytest.mark.asyncio
async def test_returns_correct_row_count() -> None:
    """Returns number of rows written (len of canned_markets)."""
    engine = AsyncMock()
    client = FakeCoinGeckoClient(canned_markets=CANNED_MARKETS_ROWS)

    with patch(
        "shortfire.ingest.coingecko.universe.copy_into_hypertable",
        new_callable=AsyncMock,
        return_value=len(CANNED_MARKETS_ROWS),
    ) as mock_copy:
        result = await fetch_and_write_daily(engine=engine, client=client, ts=_FROZEN_TS)

    assert result == len(CANNED_MARKETS_ROWS)
    mock_copy.assert_called_once()


@pytest.mark.asyncio
async def test_copy_called_with_correct_table_and_columns() -> None:
    """copy_into_hypertable called with target='raw_coingecko_market' and correct columns."""
    engine = AsyncMock()
    client = FakeCoinGeckoClient(canned_markets=CANNED_MARKETS_ROWS)

    with patch(
        "shortfire.ingest.coingecko.universe.copy_into_hypertable",
        new_callable=AsyncMock,
        return_value=len(CANNED_MARKETS_ROWS),
    ) as mock_copy:
        await fetch_and_write_daily(engine=engine, client=client, ts=_FROZEN_TS)

    assert mock_copy.call_count == 1
    call_args = mock_copy.call_args
    # target_table positional or keyword
    positional = call_args[0]
    kwargs = call_args[1]

    # table name
    target = positional[1] if len(positional) > 1 else kwargs["target_table"]
    assert target == "raw_coingecko_market"

    # columns: 10-tuple matching migration 0010 column order
    columns = positional[3] if len(positional) > 3 else kwargs["columns"]
    assert columns == (
        "symbol",
        "ts",
        "price_usd",
        "volume_24h_usd",
        "market_cap_usd",
        "category",
        "listing_date",
        "raw_payload",
        "source",
        "quality_flag",
    )

    # conflict_columns matches PK from migration 0010
    conflict = positional[4] if len(positional) > 4 else kwargs["conflict_columns"]
    assert conflict == ("symbol", "ts", "source")


@pytest.mark.asyncio
async def test_ts_defaults_to_utc_now_when_not_supplied() -> None:
    """When ts=None, fetch_and_write_daily uses datetime.now(UTC)."""
    engine = AsyncMock()
    client = FakeCoinGeckoClient(canned_markets=CANNED_MARKETS_ROWS)

    with (
        freeze_time(_FROZEN_TS),
        patch(
            "shortfire.ingest.coingecko.universe.copy_into_hypertable",
            new_callable=AsyncMock,
            return_value=len(CANNED_MARKETS_ROWS),
        ) as mock_copy,
    ):
        await fetch_and_write_daily(engine=engine, client=client)  # no ts arg

    call_args = mock_copy.call_args
    records_arg = call_args[0][2] if len(call_args[0]) > 2 else call_args[1]["records"]
    records = list(records_arg)
    # Every record's ts field (index 1) should equal frozen UTC now
    for rec in records:
        assert rec[1] == _FROZEN_TS


@pytest.mark.asyncio
async def test_records_have_source_coingecko() -> None:
    """Every record emitted has source='coingecko' (T-1-CG-04 — never from wire)."""
    engine = AsyncMock()
    client = FakeCoinGeckoClient(canned_markets=CANNED_MARKETS_ROWS)

    with patch(
        "shortfire.ingest.coingecko.universe.copy_into_hypertable",
        new_callable=AsyncMock,
        return_value=len(CANNED_MARKETS_ROWS),
    ) as mock_copy:
        await fetch_and_write_daily(engine=engine, client=client, ts=_FROZEN_TS)

    call_args = mock_copy.call_args
    records_arg = call_args[0][2] if len(call_args[0]) > 2 else call_args[1]["records"]
    records = list(records_arg)
    # source is index 8 in the 10-tuple
    for rec in records:
        assert rec[8] == "coingecko"


@pytest.mark.asyncio
async def test_records_price_usd_is_decimal_or_none() -> None:
    """price_usd field in each record is Decimal or None — never float (D-52 type safety)."""
    engine = AsyncMock()
    client = FakeCoinGeckoClient(canned_markets=CANNED_MARKETS_ROWS)

    with patch(
        "shortfire.ingest.coingecko.universe.copy_into_hypertable",
        new_callable=AsyncMock,
        return_value=len(CANNED_MARKETS_ROWS),
    ) as mock_copy:
        await fetch_and_write_daily(engine=engine, client=client, ts=_FROZEN_TS)

    call_args = mock_copy.call_args
    records_arg = call_args[0][2] if len(call_args[0]) > 2 else call_args[1]["records"]
    records = list(records_arg)
    # price_usd is index 2 in the 10-tuple
    for rec in records:
        assert rec[2] is None or isinstance(rec[2], Decimal)
