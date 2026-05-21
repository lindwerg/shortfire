"""Test D-21: safe_summary() must never return SecretStr instances or leaked secret values.

Every Settings class must expose a safe_summary() method returning a sanitized dict
suitable for structured log output. No credentials, no database passwords.
"""

import json

import pytest
from pydantic import SecretStr

from shortfire.settings.data_platform import DataPlatformSettings


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate the minimum required env vars for DataPlatformSettings construction."""
    monkeypatch.setenv("ENV", "ci")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:5432/testdb")
    monkeypatch.setenv("MEXC__READ_KEY", "dummy_key_xyz")
    monkeypatch.setenv("MEXC__READ_SECRET", "dummy_secret_uvw")
    monkeypatch.setenv("COINGLASS__API_KEY", "dummy_coinglass_abc")
    monkeypatch.setenv("COINGECKO__API_KEY", "dummy_coingecko_def")


def test_safe_summary_returns_no_secretstr_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-21: no value in safe_summary() output is a SecretStr instance."""
    _set_required_env(monkeypatch)
    settings = DataPlatformSettings()  # type: ignore[call-arg]
    summary = settings.safe_summary()

    for key, value in summary.items():
        assert not isinstance(value, SecretStr), (
            f"safe_summary() must not return SecretStr; key '{key}' has value type {type(value)}"
        )
        # Also check nested dicts
        if isinstance(value, dict):
            from typing import cast as _cast

            nested = _cast(dict[str, object], value)
            for sub_key, sub_val in nested.items():
                assert not isinstance(sub_val, SecretStr), (
                    f"safe_summary() nested key '{key}.{sub_key}' must not be SecretStr"
                )


def test_safe_summary_json_contains_no_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-21: JSON-serialized safe_summary must not contain any of the dummy secret strings."""
    _set_required_env(monkeypatch)
    settings = DataPlatformSettings()  # type: ignore[call-arg]
    summary = settings.safe_summary()

    serialized = json.dumps(summary, default=str)

    assert "dummy_key_xyz" not in serialized, "safe_summary must not leak MEXC read_key"
    assert "dummy_secret_uvw" not in serialized, "safe_summary must not leak MEXC read_secret"
    assert "dummy_coinglass_abc" not in serialized, "safe_summary must not leak Coinglass api_key"
    assert "dummy_coingecko_def" not in serialized, "safe_summary must not leak CoinGecko api_key"


def test_safe_summary_db_host_does_not_contain_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-21: safe_summary() must strip the password from db_host.

    The db URL is postgresql://user:password@localhost:5432/testdb.
    safe_summary() must log db_host as 'localhost:5432', NOT the full URL.
    """
    _set_required_env(monkeypatch)
    settings = DataPlatformSettings()  # type: ignore[call-arg]
    summary = settings.safe_summary()

    serialized = json.dumps(summary, default=str)
    assert "password" not in serialized, "safe_summary must not include the DB password in db_host"


def test_safe_summary_shows_configured_booleans(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-21: safe_summary() shows boolean flags for configured credentials."""
    _set_required_env(monkeypatch)
    settings = DataPlatformSettings()  # type: ignore[call-arg]
    summary = settings.safe_summary()

    assert summary.get("mexc_read_configured") is True, "mexc_read_configured should be True"
    assert summary.get("coinglass_configured") is True, "coinglass_configured should be True"
    assert summary.get("coingecko_configured") is True, "coingecko_configured should be True"


def test_safe_summary_shows_not_configured_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-21: safe_summary() shows False for unconfigured credentials."""
    monkeypatch.setenv("ENV", "ci")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    # No MEXC, Coinglass, or CoinGecko env vars set

    settings = DataPlatformSettings()  # type: ignore[call-arg]
    summary = settings.safe_summary()

    assert summary.get("mexc_read_configured") is False, "mexc_read_configured should be False"
    assert summary.get("coinglass_configured") is False, "coinglass_configured should be False"
    assert summary.get("coingecko_configured") is False, "coingecko_configured should be False"
