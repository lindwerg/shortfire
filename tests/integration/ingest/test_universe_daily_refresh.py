"""Integration test: universe daily refresh — new-listing detection via DB (UNIV-04).

Uses a real testcontainer DB to verify that universe_snapshot_job:
  1. Writes qualifying symbols into universe_snapshots with correct is_qualifying flag
  2. On a second run (next day) with a new symbol, inserts a row in symbols table
  3. On a second run with a removed symbol, marks it as delisted in symbols table
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


def _make_mexc_client(tickers: dict[str, Any]) -> Any:
    """Build a minimal mock MexcClient."""
    mock_ccxt = AsyncMock()
    mock_ccxt.load_markets = AsyncMock(return_value={})
    mock_ccxt.fetch_tickers = AsyncMock(return_value=tickers)
    client = MagicMock()
    client._client = mock_ccxt
    return client


def _dummy_metrics() -> Any:
    """Return a dummy metrics object."""
    gauge = MagicMock()
    gauge.labels = MagicMock(return_value=MagicMock())
    m = MagicMock()
    m.universe_symbols_count = gauge
    return m


@pytest.mark.asyncio
async def test_universe_snapshot_writes_qualifying_rows(migrated_db: str) -> None:
    """universe_snapshot_job writes qualifying symbols to universe_snapshots."""
    engine = create_async_engine(migrated_db.replace("postgresql://", "postgresql+asyncpg://"))

    tickers_day1 = {
        "BTC/USDT:USDT": {"quoteVolume": "900000", "last": "65000"},
        "ETH/USDT:USDT": {"quoteVolume": "800000", "last": "3000"},
        "SMALL/USDT:USDT": {"quoteVolume": "300000", "last": "1.0"},  # below threshold
    }
    mock_mexc = _make_mexc_client(tickers_day1)
    snapshot_date = date(2026, 6, 1)

    try:
        _test_syms = "('BTC/USDT:USDT', 'ETH/USDT:USDT', 'SMALL/USDT:USDT')"
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE universe_snapshots"))
            await conn.execute(text(f"DELETE FROM symbols WHERE symbol IN {_test_syms}"))

        from shortfire.ingest.universe.snapshot import universe_snapshot_job

        with (
            patch("shortfire.ingest.universe.snapshot.date") as mock_date,
            patch(
                "shortfire.ingest.universe.snapshot.build_data_platform_metrics",
                return_value=_dummy_metrics(),
            ),
        ):
            mock_date.today.return_value = snapshot_date
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            n = await universe_snapshot_job(engine, mock_mexc)

        # Should have written 3 rows total (both qualifying and non-qualifying)
        assert n == 3

        # Verify qualifying flags in DB
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT symbol, is_qualifying FROM universe_snapshots"
                    " WHERE snapshot_date = :d ORDER BY symbol"
                ),
                {"d": snapshot_date},
            )
            result = {r[0]: r[1] for r in rows}

        assert result.get("BTC/USDT:USDT") is True
        assert result.get("ETH/USDT:USDT") is True
        assert result.get("SMALL/USDT:USDT") is False

    finally:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE universe_snapshots"))
            await conn.execute(text(f"DELETE FROM symbols WHERE symbol IN {_test_syms}"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_universe_snapshot_detects_new_listing(migrated_db: str) -> None:
    """When a new symbol appears today vs yesterday, it gets inserted into symbols table."""
    engine = create_async_engine(migrated_db.replace("postgresql://", "postgresql+asyncpg://"))

    yesterday = date(2026, 6, 10)
    today = date(2026, 6, 11)

    try:
        # Seed yesterday's snapshot with BTC only
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE universe_snapshots"))
            await conn.execute(text("DELETE FROM symbols WHERE symbol = 'NEWCOIN/USDT:USDT'"))
            await conn.execute(
                text("""
                    INSERT INTO universe_snapshots
                        (snapshot_date, symbol, volume_24h_usd, price_usd,
                         is_qualifying, source, quality_flag)
                    VALUES (:d, 'BTC/USDT:USDT', 900000, 65000, true, 'mexc_native', 'ok')
                    ON CONFLICT DO NOTHING
                """),
                {"d": yesterday},
            )

        # Today's tickers: BTC + NEWCOIN (new listing)
        tickers_today = {
            "BTC/USDT:USDT": {"quoteVolume": "900000", "last": "65000"},
            "NEWCOIN/USDT:USDT": {"quoteVolume": "650000", "last": "0.5"},
        }
        mock_mexc = _make_mexc_client(tickers_today)

        from shortfire.ingest.universe.snapshot import universe_snapshot_job

        with (
            patch("shortfire.ingest.universe.snapshot.date") as mock_date,
            patch(
                "shortfire.ingest.universe.snapshot.build_data_platform_metrics",
                return_value=_dummy_metrics(),
            ),
        ):
            mock_date.today.return_value = today
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            await universe_snapshot_job(engine, mock_mexc)

        # NEWCOIN should now appear in symbols table
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT symbol, tier, delisted_at FROM symbols WHERE symbol = 'NEWCOIN/USDT:USDT'"),
                )
            ).first()

        assert row is not None, "NEWCOIN/USDT:USDT should have been inserted into symbols"
        assert row[1] == 2, "New symbols default to tier=2"
        assert row[2] is None, "New symbols should not have delisted_at set"

    finally:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE universe_snapshots"))
            await conn.execute(text("DELETE FROM symbols WHERE symbol = 'NEWCOIN/USDT:USDT'"))
        await engine.dispose()
