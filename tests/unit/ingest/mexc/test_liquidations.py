"""Unit tests for dual-source liquidations (D-48).

Tests cover:
  - ws path: watch_liquidations present → records written via COPY
  - degraded path: watch_liquidations absent → liquidations.degraded event emitted;
    freshness gauge set to 0 sentinel; no COPY called

TDD cycle: RED phase — tests written before implementation.

Decisions honored:
  D-48: ws-only in Phase 1; REST fallback deferred (W3 reconciliation)
"""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch


async def test_liquidations_ws_path_writes_records() -> None:
    """When watch_liquidations is present, records are written via copy_into_hypertable."""
    import asyncio

    from shortfire.ingest.mexc.liquidations import liquidations_dual_source_loop

    liq_event = {
        "symbol": "BTC/USDT:USDT",
        "timestamp": 1716307200000,
        "side": "sell",
        "amount": "0.1",
        "price": "48000.0",
    }

    copied_records = []

    async def capture_copy(engine, table, records, columns, conflict_columns):  # type: ignore[no-untyped-def]
        copied_records.extend(records)
        return len(list(records))

    call_count = {"n": 0}

    async def patched_watch_liq(sym_or_none):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()
        return [liq_event]

    raw_mock = MagicMock()
    raw_mock.watch_liquidations = patched_watch_liq  # method present → ws path

    client_mock = MagicMock()
    client_mock.ws_client = raw_mock

    with (
        patch("shortfire.ingest.mexc.liquidations.copy_into_hypertable", side_effect=capture_copy),
        contextlib.suppress(asyncio.CancelledError),
    ):
        await liquidations_dual_source_loop(None, client_mock, ["BTC/USDT:USDT"])  # type: ignore[arg-type]

    assert len(copied_records) == 1, f"Expected 1 liquidation record, got {len(copied_records)}"
    sym, ts, side, qty, price, source, qf = copied_records[0]
    assert sym == "BTC/USDT:USDT"
    assert side == "sell"
    assert source == "mexc_native"
    assert qf == "ok"


async def test_liquidations_degraded_path_emits_event_and_sentinel() -> None:
    """When watch_liquidations is absent, degraded event logged; gauge set to 0; no COPY."""
    from shortfire.ingest.mexc.liquidations import liquidations_dual_source_loop

    raw_mock = MagicMock()
    # Explicitly remove watch_liquidations to trigger degraded path
    del raw_mock.watch_liquidations  # hasattr(raw, 'watch_liquidations') → False

    client_mock = MagicMock()
    client_mock.ws_client = raw_mock

    gauge_sets: dict[str, float] = {}
    mock_gauge = MagicMock()
    mock_gauge.labels.return_value.set.side_effect = lambda v: gauge_sets.update({"value": v})

    copy_called = {"n": 0}

    async def fail_copy(*a, **kw):  # type: ignore[no-untyped-def]
        copy_called["n"] += 1
        return 0

    with (
        patch("shortfire.ingest.mexc.liquidations.copy_into_hypertable", side_effect=fail_copy),
        patch("shortfire.ingest.mexc.liquidations.build_data_platform_metrics") as mock_metrics,
    ):
        metrics_mock = MagicMock()
        metrics_mock.source_freshness_seconds = mock_gauge
        mock_metrics.return_value = metrics_mock

        # Should return cleanly (not raise) — degraded path exits immediately
        await liquidations_dual_source_loop(None, client_mock, ["BTC/USDT:USDT"])  # type: ignore[arg-type]

    assert copy_called["n"] == 0, "No COPY should be called in degraded path"
    # Gauge should have been set to 0 (sentinel per D-48 revision)
    assert gauge_sets.get("value") == 0, (
        f"Freshness gauge should be set to 0 sentinel in degraded path, got {gauge_sets.get('value')}"
    )


async def test_liquidations_degraded_path_uses_partial_capture_flag() -> None:
    """Degraded-path emits reason='ws_unavailable_phase1_ships_no_fallback' in structlog."""
    from shortfire.ingest.mexc.liquidations import liquidations_dual_source_loop

    raw_mock = MagicMock()
    del raw_mock.watch_liquidations

    client_mock = MagicMock()
    client_mock.ws_client = raw_mock

    logged_events: list[dict] = []

    def fake_log_warning(event: str, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
        logged_events.append({"event": event, **kwargs})

    with (
        patch("shortfire.ingest.mexc.liquidations.log") as mock_log,
    ):
        mock_log.warning.side_effect = fake_log_warning

        await liquidations_dual_source_loop(None, client_mock, ["BTC/USDT:USDT"])  # type: ignore[arg-type]

    assert any(e["event"] == "liquidations.degraded" for e in logged_events), (
        f"Expected liquidations.degraded event, got: {logged_events}"
    )
    degraded_event = next(e for e in logged_events if e["event"] == "liquidations.degraded")
    assert degraded_event.get("reason") == "ws_unavailable_phase1_ships_no_fallback"
