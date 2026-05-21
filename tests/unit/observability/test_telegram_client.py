"""Unit tests for the raw-httpx Telegram alert client (D-86).

Tests:
  1. send_telegram_alert with telegram=None skips silently (no POST, no exception).
  2. send_telegram_alert with telegram configured POSTs to api.telegram.org with correct body.
  3. Body is truncated to 4000 chars total (prefix + message).
  4. HTTP error does NOT propagate — Telegram failure must not crash the caller.
"""

import httpx
import pytest
import respx
from httpx import Response
from pydantic import SecretStr

from shortfire.observability.telegram import send_telegram_alert
from shortfire.settings.data_platform import DataPlatformSettings, TelegramSettings

_DB_URL = "postgresql://user:pass@localhost:5432/testdb"


@pytest.fixture()
def settings_with_telegram(monkeypatch: pytest.MonkeyPatch) -> DataPlatformSettings:
    """DataPlatformSettings with TelegramSettings configured."""
    monkeypatch.setenv("ENV", "ci")
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    return DataPlatformSettings(  # type: ignore[call-arg]
        telegram=TelegramSettings(
            bot_token=SecretStr("TESTTOK"),
            operator_chat_id="12345",
        )
    )


@pytest.fixture()
def settings_no_telegram(monkeypatch: pytest.MonkeyPatch) -> DataPlatformSettings:
    """DataPlatformSettings with telegram=None (default)."""
    monkeypatch.setenv("ENV", "ci")
    monkeypatch.setenv("DATABASE_URL", _DB_URL)
    return DataPlatformSettings()  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_send_alert_skips_when_telegram_none(
    settings_no_telegram: DataPlatformSettings,
) -> None:
    """When settings.telegram is None, send_telegram_alert returns without POSTing (graceful skip)."""
    with respx.mock(assert_all_mocked=True):
        # No routes registered — if a POST fires, respx raises an error.
        await send_telegram_alert(settings_no_telegram, "warn", "stale: mexc/candles_1m/BTC")
    # Reaching here means no POST was attempted — test passes.


@pytest.mark.asyncio
async def test_send_alert_posts_to_telegram_api(
    settings_with_telegram: DataPlatformSettings,
) -> None:
    """send_telegram_alert POSTs to api.telegram.org/bot{TOKEN}/sendMessage with correct JSON."""
    captured_json: dict[str, object] = {}

    def capture(request: httpx.Request) -> Response:
        import json

        captured_json.update(json.loads(request.content))
        return Response(200, json={"ok": True})

    with respx.mock() as mock:
        route = mock.post(url__regex=r"https://api\.telegram\.org/bot.+/sendMessage").mock(
            side_effect=capture
        )
        await send_telegram_alert(settings_with_telegram, "warn", "stale: mexc/candles_1m/BTC")

    assert route.called, "Expected exactly one POST to api.telegram.org"
    assert captured_json["chat_id"] == "12345"
    text = str(captured_json.get("text", ""))
    assert text.startswith("⚠️ WARN | stale:"), f"Expected warn prefix in text, got: {text!r}"


@pytest.mark.asyncio
async def test_send_alert_severity_crit(
    settings_with_telegram: DataPlatformSettings,
) -> None:
    """send_telegram_alert uses 🚨 CRIT prefix for severity='crit'."""
    captured_text: list[str] = []

    def capture(request: httpx.Request) -> Response:
        import json

        data = json.loads(request.content)
        captured_text.append(str(data.get("text", "")))
        return Response(200, json={"ok": True})

    with respx.mock() as mock:
        mock.post(url__regex=r"https://api\.telegram\.org/bot.+/sendMessage").mock(side_effect=capture)
        await send_telegram_alert(settings_with_telegram, "crit", "FATAL: db down")

    assert captured_text, "Expected one POST"
    assert captured_text[0].startswith("🚨 CRIT | "), f"Expected crit prefix, got: {captured_text[0]!r}"


@pytest.mark.asyncio
async def test_body_truncated_to_4000_chars(
    settings_with_telegram: DataPlatformSettings,
) -> None:
    """Body + prefix is truncated to 4000 chars total (D-86 Telegram message limit)."""
    long_body = "x" * 5000
    captured_text: list[str] = []

    def capture(request: httpx.Request) -> Response:
        import json

        data = json.loads(request.content)
        captured_text.append(str(data.get("text", "")))
        return Response(200, json={"ok": True})

    with respx.mock() as mock:
        mock.post(url__regex=r"https://api\.telegram\.org/bot.+/sendMessage").mock(side_effect=capture)
        await send_telegram_alert(settings_with_telegram, "info", long_body)

    assert captured_text, "Expected one POST"
    assert len(captured_text[0]) <= 4000, f"Message exceeds 4000 chars: {len(captured_text[0])}"


@pytest.mark.asyncio
async def test_http_error_does_not_propagate(
    settings_with_telegram: DataPlatformSettings,
) -> None:
    """HTTP 5xx from Telegram must NOT raise — caller must not crash (D-86 swallow rule)."""
    with respx.mock() as mock:
        mock.post(url__regex=r"https://api\.telegram\.org/bot.+/sendMessage").mock(
            return_value=Response(500, json={"ok": False})
        )
        # Should not raise even though the server returns 500
        await send_telegram_alert(settings_with_telegram, "warn", "test body")
