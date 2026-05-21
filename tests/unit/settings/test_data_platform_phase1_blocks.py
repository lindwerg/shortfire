"""Unit tests for Phase 1 settings blocks: TelegramSettings + R2BackupSettings (D-83, D-86).

Tests:
  1. safe_summary() returns telegram_configured=False and r2_backup_configured=False by default.
  2. safe_summary() returns telegram_configured=True when TelegramSettings is set.
  3. safe_summary() returns r2_backup_configured=True when R2BackupSettings is set.
  4. repr(settings) does NOT contain SecretStr values (D-19 masking invariant).
  5. D-16: mexc_trade field is structurally absent from DataPlatformSettings.
"""

import pytest
from pydantic import SecretStr

from shortfire.settings.data_platform import (
    DataPlatformSettings,
    R2BackupSettings,
    TelegramSettings,
)

_DB_URL = "postgresql://user:pass@localhost:5432/testdb"


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set minimum required env vars for DataPlatformSettings construction."""
    monkeypatch.setenv("ENV", "ci")
    monkeypatch.setenv("DATABASE_URL", _DB_URL)


def test_safe_summary_defaults_both_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no optional blocks, safe_summary returns both flags as False."""
    _base_env(monkeypatch)
    settings = DataPlatformSettings()  # type: ignore[call-arg]
    summary = settings.safe_summary()
    assert summary["telegram_configured"] is False, "Expected telegram_configured=False"
    assert summary["r2_backup_configured"] is False, "Expected r2_backup_configured=False"


def test_safe_summary_telegram_configured_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """safe_summary returns telegram_configured=True when TelegramSettings is provided."""
    _base_env(monkeypatch)
    settings = DataPlatformSettings(  # type: ignore[call-arg]
        telegram=TelegramSettings(
            bot_token=SecretStr("tok"),
            operator_chat_id="123",
        )
    )
    summary = settings.safe_summary()
    assert summary["telegram_configured"] is True, "Expected telegram_configured=True"
    assert summary["r2_backup_configured"] is False, "Expected r2_backup_configured=False"


def test_safe_summary_r2_configured_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """safe_summary returns r2_backup_configured=True when R2BackupSettings is provided."""
    _base_env(monkeypatch)
    settings = DataPlatformSettings(  # type: ignore[call-arg]
        r2_backup=R2BackupSettings(
            account_id="acc",
            access_key_id=SecretStr("ak"),
            secret_access_key=SecretStr("sk"),
            bucket_name="bkt",
        )
    )
    summary = settings.safe_summary()
    assert summary["r2_backup_configured"] is True, "Expected r2_backup_configured=True"
    assert summary["telegram_configured"] is False, "Expected telegram_configured=False"


def test_safe_summary_both_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """safe_summary returns both flags True when both blocks are set."""
    _base_env(monkeypatch)
    settings = DataPlatformSettings(  # type: ignore[call-arg]
        telegram=TelegramSettings(
            bot_token=SecretStr("tok"),
            operator_chat_id="123",
        ),
        r2_backup=R2BackupSettings(
            account_id="acc",
            access_key_id=SecretStr("ak"),
            secret_access_key=SecretStr("sk"),
            bucket_name="bkt",
        ),
    )
    summary = settings.safe_summary()
    assert summary["telegram_configured"] is True
    assert summary["r2_backup_configured"] is True


def test_safe_summary_values_are_booleans(monkeypatch: pytest.MonkeyPatch) -> None:
    """safe_summary telegram_configured and r2_backup_configured must be bool (D-21)."""
    _base_env(monkeypatch)
    settings = DataPlatformSettings()  # type: ignore[call-arg]
    summary = settings.safe_summary()
    assert isinstance(summary["telegram_configured"], bool), "telegram_configured must be bool"
    assert isinstance(summary["r2_backup_configured"], bool), "r2_backup_configured must be bool"


def test_repr_does_not_contain_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """repr(settings) must NOT contain raw SecretStr values (D-19 masking invariant)."""
    _base_env(monkeypatch)
    settings = DataPlatformSettings(  # type: ignore[call-arg]
        telegram=TelegramSettings(
            bot_token=SecretStr("VERY_SECRET_TOKEN"),
            operator_chat_id="99999",
        ),
        r2_backup=R2BackupSettings(
            account_id="acc123",
            access_key_id=SecretStr("AK_SECRET"),
            secret_access_key=SecretStr("SK_SECRET"),
            bucket_name="my-bucket",
        ),
    )
    r = repr(settings)
    assert "VERY_SECRET_TOKEN" not in r, "bot_token must be masked in repr"
    assert "AK_SECRET" not in r, "access_key_id must be masked in repr"
    assert "SK_SECRET" not in r, "secret_access_key must be masked in repr"


def test_d16_no_mexc_trade_field() -> None:
    """DataPlatformSettings must not have a mexc_trade field (D-16 anti-leak invariant)."""
    assert "mexc_trade" not in DataPlatformSettings.model_fields, (
        "D-16 violation: mexc_trade field found on DataPlatformSettings"
    )
