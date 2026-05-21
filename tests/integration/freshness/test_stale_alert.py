"""ORCH-04 integration keystone: Telegram alert fires on freshness lag (respx mock).

Plan 01-10, Task 1: integration test using respx to mock the Telegram Bot API endpoint.
Tests that freshness_check_job actually sends a POST to Telegram when a freshness gauge
is stale (lag > 2 × EXPECTED_LAG).
"""

from __future__ import annotations

import json
import re
import time

import httpx
import pytest
import respx
from pydantic import SecretStr

from shortfire.ingest.freshness import alerter
from shortfire.ingest.freshness.alerter import freshness_check_job
from shortfire.observability.metrics_data_platform import build_data_platform_metrics
from shortfire.settings.data_platform import DataPlatformSettings, TelegramSettings


def _make_settings_with_telegram() -> DataPlatformSettings:
    return DataPlatformSettings.model_construct(
        telegram=TelegramSettings(
            bot_token=SecretStr("test_bot_token_orch04"),
            operator_chat_id="42",
        )
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_freshness_check_fires_telegram_when_stale() -> None:
    """ORCH-04 keystone: stale gauge triggers a Telegram warn POST via respx mock."""
    # Reset degraded state from previous tests
    alerter._degraded_set.clear()

    metrics = build_data_platform_metrics()
    # Set the gauge to a long-ago time: >> 2 × 90s threshold for candles_1m
    old_ts = time.time() - 10_000.0
    metrics.source_freshness_seconds.labels(
        source="mexc_native",
        dataset="candles_1m",
        symbol="BTC/USDT:USDT",
    ).set(old_ts)

    settings = _make_settings_with_telegram()
    captured_posts: list[httpx.Request] = []

    with respx.mock() as mock:
        mock.post(re.compile(r"https://api\.telegram\.org/bot.+/sendMessage")).mock(
            side_effect=lambda req: (
                captured_posts.append(req),
                httpx.Response(200, json={"ok": True}),
            )[1]
        )
        await freshness_check_job(settings=settings)

    assert len(captured_posts) >= 1, (
        f"Expected at least 1 Telegram POST for stale gauge, got {len(captured_posts)}"
    )
    body = json.loads(captured_posts[0].content)
    assert "WARN" in body["text"], f"Expected 'WARN' in message text, got: {body['text']!r}"
    assert "mexc_native/candles_1m/BTC/USDT:USDT" in body["text"], (
        f"Expected source/dataset/symbol in message text, got: {body['text']!r}"
    )

    # Cleanup: reset the gauge so other tests aren't polluted
    metrics.source_freshness_seconds.labels(
        source="mexc_native",
        dataset="candles_1m",
        symbol="BTC/USDT:USDT",
    ).set(time.time())
    alerter._degraded_set.clear()
