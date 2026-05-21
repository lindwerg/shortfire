"""Unit tests for src/shortfire/ingest/freshness/gauges.py (D-84, RESEARCH.md Open Q1 option B)."""

from __future__ import annotations

import contextlib
from unittest.mock import patch

from shortfire.observability.metrics_data_platform import build_data_platform_metrics


def _clear_freshness_gauge(source: str, dataset: str, symbol: str) -> None:
    """Helper: reset a gauge label so tests don't leak state."""
    metrics = build_data_platform_metrics()
    with contextlib.suppress(KeyError):
        metrics.source_freshness_seconds.remove(source, dataset, symbol)


class TestUpdateFreshnessGauge:
    """Tests for update_freshness_gauge helper (RESEARCH.md §12, option B)."""

    def test_update_freshness_gauge_sets_unix_timestamp(self) -> None:
        """Test 1: Sets gauge to current unix timestamp (NOT 0.0) — option B."""
        from shortfire.ingest.freshness.gauges import update_freshness_gauge

        _clear_freshness_gauge("mexc_native", "candles_1m", "BTC/USDT:USDT")

        fixed_ts = 1700000000.0
        with patch("shortfire.ingest.freshness.gauges.time") as mock_time:
            mock_time.time.return_value = fixed_ts
            update_freshness_gauge("mexc_native", "candles_1m", [("BTC/USDT:USDT",)])

        metrics = build_data_platform_metrics()
        samples = list(metrics.source_freshness_seconds.collect()[0].samples)
        matching = [
            s
            for s in samples
            if s.labels.get("source") == "mexc_native"
            and s.labels.get("dataset") == "candles_1m"
            and s.labels.get("symbol") == "BTC/USDT:USDT"
        ]
        assert len(matching) == 1, f"Expected 1 gauge sample, got {len(matching)}"
        assert matching[0].value == fixed_ts, (
            f"Gauge value should be unix timestamp {fixed_ts}, got {matching[0].value}"
        )

    def test_update_freshness_gauge_handles_empty_records(self) -> None:
        """Test 2: Empty records list → no gauge update, no exception."""
        from shortfire.ingest.freshness.gauges import update_freshness_gauge

        metrics = build_data_platform_metrics()
        # Count current samples before
        before = len(list(metrics.source_freshness_seconds.collect()[0].samples))

        update_freshness_gauge("mexc_native", "candles_1m", [])

        after = len(list(metrics.source_freshness_seconds.collect()[0].samples))
        # No new samples added
        assert after == before

    def test_update_freshness_gauge_handles_multiple_symbols(self) -> None:
        """Test 3: 3 records for 3 symbols → 3 separate gauge labels updated."""
        from shortfire.ingest.freshness.gauges import update_freshness_gauge

        symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
        for sym in symbols:
            _clear_freshness_gauge("mexc_native", "trades", sym)

        fixed_ts = 1700111111.0
        with patch("shortfire.ingest.freshness.gauges.time") as mock_time:
            mock_time.time.return_value = fixed_ts
            records = [(sym, 100, 0.0, 0.0, 0.0, 0.0) for sym in symbols]
            update_freshness_gauge("mexc_native", "trades", records)

        metrics = build_data_platform_metrics()
        samples = list(metrics.source_freshness_seconds.collect()[0].samples)
        matched_symbols = {
            s.labels.get("symbol")
            for s in samples
            if s.labels.get("source") == "mexc_native"
            and s.labels.get("dataset") == "trades"
            and s.value == fixed_ts
        }
        for sym in symbols:
            assert sym in matched_symbols, f"Expected symbol {sym!r} in gauge samples"
