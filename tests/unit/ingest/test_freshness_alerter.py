"""Unit tests for src/shortfire/ingest/freshness/alerter.py (D-85, D-87, ORCH-04)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import SecretStr

from shortfire.observability.metrics_data_platform import build_data_platform_metrics
from shortfire.settings.data_platform import DataPlatformSettings, TelegramSettings


def _make_settings_with_telegram() -> DataPlatformSettings:
    """Build DataPlatformSettings with a dummy TelegramSettings configured."""
    return DataPlatformSettings.model_construct(
        telegram=TelegramSettings(
            bot_token=SecretStr("fake_token_123"),
            operator_chat_id="42",
        )
    )


def _set_gauge(source: str, dataset: str, symbol: str, value: float) -> None:
    """Helper: set a freshness gauge sample to a specific value."""
    metrics = build_data_platform_metrics()
    metrics.source_freshness_seconds.labels(source=source, dataset=dataset, symbol=symbol).set(value)


class TestFreshnessCheckJob:
    """Tests for freshness_check_job (D-85, D-87, RESEARCH.md §12)."""

    def setup_method(self) -> None:
        """Reset _degraded_set before each test."""
        from shortfire.ingest.freshness import alerter

        alerter._degraded_set.clear()

    def test_freshness_check_job_fires_alert_on_stale(self) -> None:
        """Test 2: Gauge set to stale time fires warn Telegram alert."""
        from shortfire.ingest.freshness.alerter import freshness_check_job

        # candles_1m expected lag = 90s; stale = time.time() - 1000 (>> 2*90=180s)
        stale_ts = time.time() - 1000.0
        _set_gauge("mexc_native", "candles_1m", "BTC/USDT:USDT", stale_ts)

        settings = _make_settings_with_telegram()
        mock_send = AsyncMock()

        import asyncio

        with patch("shortfire.ingest.freshness.alerter.send_telegram_alert", mock_send):
            asyncio.run(freshness_check_job(settings=settings))

        # Gauge REGISTRY is shared across tests; other tests may have set stale gauges too.
        # Assert that at least one call was made with warn severity for our specific key.
        assert mock_send.await_count >= 1, "Expected at least one Telegram alert for stale gauge"
        # Find the call for our specific source/dataset/symbol
        matching_calls = [
            c
            for c in mock_send.call_args_list
            if len(c[0]) >= 3
            and c[0][1] == "warn"
            and "stale: mexc_native/candles_1m/BTC/USDT:USDT" in c[0][2]
        ]
        assert len(matching_calls) >= 1, (
            f"Expected at least one warn alert for mexc_native/candles_1m/BTC/USDT:USDT. "
            f"Got calls: {[(c[0][1], c[0][2][:80]) for c in mock_send.call_args_list]}"
        )

    def test_freshness_check_job_does_not_alert_when_fresh(self) -> None:
        """Test: Fresh gauge for coingecko/market (25h expected) → no alert for that symbol.

        Note: The shared REGISTRY may have stale gauges from test_freshness_gauges.py tests
        (e.g. mexc_native/trades set to 1700111111 which is very old). We test a source/dataset
        that no other test touches (coingecko/market) so we can isolate the assertion.
        """
        from shortfire.ingest.freshness.alerter import freshness_check_job

        # coingecko/market expected = 25 * 3600 = 90000s; set to only 10s old → definitely fresh
        fresh_ts = time.time() - 10.0
        _set_gauge("coingecko", "market", "CG_FRESH_TEST", fresh_ts)

        settings = _make_settings_with_telegram()
        mock_send = AsyncMock()

        import asyncio

        with patch("shortfire.ingest.freshness.alerter.send_telegram_alert", mock_send):
            asyncio.run(freshness_check_job(settings=settings))

        # The freshly-set coingecko/market/CG_FRESH_TEST gauge should NOT trigger an alert
        fresh_calls = [
            c for c in mock_send.call_args_list if c[0] and "coingecko/market/CG_FRESH_TEST" in str(c[0][2])
        ]
        assert len(fresh_calls) == 0, (
            f"Expected no alert for fresh coingecko/market/CG_FRESH_TEST gauge, got: {fresh_calls}"
        )

    def test_freshness_check_job_emits_recovered_event(self) -> None:
        """Test 3: Degrade then recover → freshness.recovered structlog event fires."""
        from shortfire.ingest.freshness import alerter
        from shortfire.ingest.freshness.alerter import freshness_check_job

        settings = _make_settings_with_telegram()
        # Step 1: Set gauge as stale to put it in _degraded_set
        stale_ts = time.time() - 2000.0
        _set_gauge("mexc_native", "oi", "SOL/USDT:USDT", stale_ts)

        import asyncio

        with patch("shortfire.ingest.freshness.alerter.send_telegram_alert", AsyncMock()):
            asyncio.run(freshness_check_job(settings=settings))

        # SOL OI should now be in _degraded_set
        assert ("mexc_native", "oi", "SOL/USDT:USDT") in alerter._degraded_set

        # Step 2: Set gauge fresh → should transition to recovered
        fresh_ts = time.time() - 5.0
        _set_gauge("mexc_native", "oi", "SOL/USDT:USDT", fresh_ts)

        recovered_events: list[str] = []

        def _capture_info(event: str, **kwargs: object) -> None:
            if event == "freshness.recovered":
                recovered_events.append(event)

        with (
            patch("shortfire.ingest.freshness.alerter.send_telegram_alert", AsyncMock()),
            patch("shortfire.ingest.freshness.alerter.log") as mock_log,
        ):
            mock_log.info = _capture_info
            mock_log.warning = MagicMock()
            asyncio.run(freshness_check_job(settings=settings))

        assert len(recovered_events) >= 1, f"Expected freshness.recovered event, got: {recovered_events}"
