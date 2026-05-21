"""Unit tests for new-listing and delisting detection in universe_snapshot_job.

Uses in-memory mocking — no real DB, no real MEXC API.
Verifies that structlog events universe.symbol.new and universe.symbol.delisted
are emitted with correct symbols when the snapshot job diffs yesterday vs today.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers: capture structlog events
# ---------------------------------------------------------------------------


class _LogCapture:
    """Simple accumulator for structlog log.info / log.warning calls."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def info(self, event: str, **kw: Any) -> None:
        self.events.append({"level": "info", "event": event, **kw})

    def warning(self, event: str, **kw: Any) -> None:
        self.events.append({"level": "warning", "event": event, **kw})

    def error(self, event: str, **kw: Any) -> None:
        self.events.append({"level": "error", "event": event, **kw})

    def debug(self, event: str, **kw: Any) -> None:
        self.events.append({"level": "debug", "event": event, **kw})

    def emitted(self, event: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == event]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_listing_detected_on_new_symbol() -> None:
    """universe.symbol.new fires when a symbol appears today but was absent yesterday."""
    cap = _LogCapture()
    today = date(2026, 5, 1)

    # Yesterday had: BTC, ETH. Today has: BTC, ETH, SOL (SOL is new)
    yesterday_symbols = {"BTC/USDT:USDT", "ETH/USDT:USDT"}
    today_tickers = {
        "BTC/USDT:USDT": {"quoteVolume": "800000", "last": "65000"},
        "ETH/USDT:USDT": {"quoteVolume": "700000", "last": "3000"},
        "SOL/USDT:USDT": {"quoteVolume": "600000", "last": "120"},
    }

    # Build mock engine
    mock_engine = _make_engine(yesterday_symbols)
    mock_mexc = _make_mexc_client(today_tickers)

    with (
        patch("shortfire.ingest.universe.snapshot.log", cap),
        patch(
            "shortfire.ingest.universe.snapshot.copy_into_hypertable", new_callable=AsyncMock, return_value=3
        ),
        patch("shortfire.ingest.universe.snapshot.date") as mock_date,
        patch(
            "shortfire.ingest.universe.snapshot.build_data_platform_metrics", return_value=_dummy_metrics()
        ),
    ):
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        from shortfire.ingest.universe.snapshot import universe_snapshot_job

        await universe_snapshot_job(mock_engine, mock_mexc)

    new_events = cap.emitted("universe.symbol.new")
    assert len(new_events) >= 1
    new_symbols = {e["symbol"] for e in new_events}
    assert "SOL/USDT:USDT" in new_symbols


@pytest.mark.asyncio
async def test_delisting_detected_on_missing_symbol() -> None:
    """universe.symbol.delisted fires when a symbol present yesterday is absent today."""
    cap = _LogCapture()
    today = date(2026, 5, 2)

    # Yesterday had BTC, ETH, LUNA. Today only BTC and ETH (LUNA delisted)
    yesterday_symbols = {"BTC/USDT:USDT", "ETH/USDT:USDT", "LUNA/USDT:USDT"}
    today_tickers = {
        "BTC/USDT:USDT": {"quoteVolume": "800000", "last": "65000"},
        "ETH/USDT:USDT": {"quoteVolume": "700000", "last": "3000"},
    }

    mock_engine = _make_engine(yesterday_symbols)
    mock_mexc = _make_mexc_client(today_tickers)

    with (
        patch("shortfire.ingest.universe.snapshot.log", cap),
        patch(
            "shortfire.ingest.universe.snapshot.copy_into_hypertable", new_callable=AsyncMock, return_value=2
        ),
        patch("shortfire.ingest.universe.snapshot.date") as mock_date,
        patch(
            "shortfire.ingest.universe.snapshot.build_data_platform_metrics", return_value=_dummy_metrics()
        ),
    ):
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

        from shortfire.ingest.universe.snapshot import universe_snapshot_job

        await universe_snapshot_job(mock_engine, mock_mexc)

    delisted_events = cap.emitted("universe.symbol.delisted")
    assert len(delisted_events) >= 1
    delisted_symbols = {e["symbol"] for e in delisted_events}
    assert "LUNA/USDT:USDT" in delisted_symbols


# ---------------------------------------------------------------------------
# Helpers to build mocks
# ---------------------------------------------------------------------------


def _make_engine(yesterday_symbols: set[str]) -> Any:
    """Build a minimal mock AsyncEngine that returns yesterday_symbols from SELECT."""
    # We need to mock: engine.connect().__aenter__().execute() → rows
    # AND: AsyncSession(engine).__aenter__().execute() → no-op

    rows = [(sym,) for sym in yesterday_symbols]

    # Mock for engine.connect() context manager returning yesterday rows
    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter(rows)

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_result)

    mock_conn_ctx = AsyncMock()
    mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect = MagicMock(return_value=mock_conn_ctx)
    # AsyncSession(engine) is patched at the module level in snapshot.py

    # Patch AsyncSession in snapshot module
    import shortfire.ingest.universe.snapshot as snap_module

    snap_module._test_mock_session_ctx = mock_session_ctx  # type: ignore[attr-defined]

    return engine


def _make_mexc_client(tickers: dict[str, Any]) -> Any:
    """Build a minimal mock MexcClient wrapping a fake ccxt client."""
    mock_ccxt = AsyncMock()
    mock_ccxt.load_markets = AsyncMock(return_value={})
    mock_ccxt.fetch_tickers = AsyncMock(return_value=tickers)

    client = MagicMock()
    client._client = mock_ccxt
    return client


def _dummy_metrics() -> Any:
    """Return a dummy metrics object that silently accepts .set() calls."""
    gauge = MagicMock()
    gauge.labels = MagicMock(return_value=MagicMock())
    m = MagicMock()
    m.universe_symbols_count = gauge
    return m
