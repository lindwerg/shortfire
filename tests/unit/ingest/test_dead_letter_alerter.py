"""Unit tests for src/shortfire/ingest/dead_letter/alerter.py (D-74, D-87)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import SecretStr

from shortfire.settings.data_platform import DataPlatformSettings, TelegramSettings


def _make_settings() -> DataPlatformSettings:
    return DataPlatformSettings.model_construct(
        telegram=TelegramSettings(
            bot_token=SecretStr("test_token"),
            operator_chat_id="99",
        )
    )


class TestDeadLetterAlerterJob:
    """Tests for dead_letter_alerter_job (D-74, threshold > 10 per hour)."""

    def test_fires_alert_when_offenders_exceed_threshold(self) -> None:
        """Test 4: When dead_letter groups exceed threshold, fires warn Telegram alert."""
        from shortfire.ingest.dead_letter.alerter import dead_letter_alerter_job

        # Simulate 2 groups that exceed threshold (>10)
        offender_rows = [
            ("mexc_native", "ValidationError", 25),
            ("coinglass_aggregate", "TimeoutError", 15),
        ]

        mock_conn = MagicMock()

        async def mock_execute(stmt: object, params: object = None) -> MagicMock:
            result = MagicMock()
            result.__iter__ = lambda self: iter(offender_rows)
            return result

        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = mock_execute

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        settings = _make_settings()
        mock_send = AsyncMock()

        # get_engine is imported inside dead_letter_alerter_job from shortfire.ingest.context
        with (
            patch("shortfire.ingest.context.get_engine", return_value=mock_engine),
            patch("shortfire.ingest.dead_letter.alerter.send_telegram_alert", mock_send),
        ):
            asyncio.run(dead_letter_alerter_job(settings=settings))

        mock_send.assert_awaited_once()
        call_args = mock_send.call_args
        assert call_args[0][1] == "warn"
        body = call_args[0][2]
        assert "mexc_native" in body
        assert "coinglass_aggregate" in body

    def test_no_alert_when_no_offenders(self) -> None:
        """No alert when dead_letter query returns empty rows."""
        from shortfire.ingest.dead_letter.alerter import dead_letter_alerter_job

        mock_conn = MagicMock()

        async def mock_execute_empty(stmt: object, params: object = None) -> MagicMock:
            result = MagicMock()
            result.__iter__ = lambda self: iter([])
            return result

        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = mock_execute_empty

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        settings = _make_settings()
        mock_send = AsyncMock()

        with (
            patch("shortfire.ingest.context.get_engine", return_value=mock_engine),
            patch("shortfire.ingest.dead_letter.alerter.send_telegram_alert", mock_send),
        ):
            asyncio.run(dead_letter_alerter_job(settings=settings))

        mock_send.assert_not_awaited()
