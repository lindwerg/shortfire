"""Test D-17/D-18: env_nested_delimiter='__' routes nested env vars correctly.

Verifies that MEXC__READ_KEY routes to DataPlatformSettings.mexc.read_key,
and that _env_file() returns None only when ENV=production.
"""

import pytest

from shortfire.settings.base import env_file as _env_file
from shortfire.settings.data_platform import DataPlatformSettings


def _set_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set minimum required env vars."""
    monkeypatch.setenv("ENV", "ci")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")


def test_mexc_read_key_routes_via_nested_delimiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-17/D-18: MEXC__READ_KEY routes to mexc.read_key via env_nested_delimiter='__'."""
    _set_base_env(monkeypatch)
    monkeypatch.setenv("MEXC__READ_KEY", "key_value_abc")
    monkeypatch.setenv("MEXC__READ_SECRET", "secret_value_def")

    settings = DataPlatformSettings()  # type: ignore[call-arg]

    assert settings.mexc is not None, "mexc should be populated when MEXC__READ_KEY is set"
    assert settings.mexc.read_key.get_secret_value() == "key_value_abc", (
        "MEXC__READ_KEY must route to mexc.read_key via env_nested_delimiter='__'"
    )
    assert settings.mexc.read_secret.get_secret_value() == "secret_value_def", (
        "MEXC__READ_SECRET must route to mexc.read_secret via env_nested_delimiter='__'"
    )


def test_coinglass_api_key_routes_via_nested_delimiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-17/D-18: COINGLASS__API_KEY routes to coinglass.api_key via env_nested_delimiter='__'."""
    _set_base_env(monkeypatch)
    monkeypatch.setenv("COINGLASS__API_KEY", "cg_key_123")

    settings = DataPlatformSettings()  # type: ignore[call-arg]

    assert settings.coinglass is not None, "coinglass should be populated when COINGLASS__API_KEY is set"
    assert settings.coinglass.api_key.get_secret_value() == "cg_key_123"


def test_coingecko_api_key_routes_via_nested_delimiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-17/D-18: COINGECKO__API_KEY routes to coingecko.api_key via env_nested_delimiter='__'."""
    _set_base_env(monkeypatch)
    monkeypatch.setenv("COINGECKO__API_KEY", "gecko_key_456")

    settings = DataPlatformSettings()  # type: ignore[call-arg]

    assert settings.coingecko is not None, "coingecko should be populated when COINGECKO__API_KEY is set"
    assert settings.coingecko.api_key.get_secret_value() == "gecko_key_456"


@pytest.mark.parametrize(
    "env_value, expected",
    [
        ("local", ".env.local"),
        ("ci", ".env.local"),
        ("staging", ".env.local"),
        ("production", None),
    ],
)
def test_env_file_returns_none_only_for_production(
    monkeypatch: pytest.MonkeyPatch, env_value: str, expected: str | None
) -> None:
    """D-17/D-20: _env_file() returns '.env.local' for all envs except 'production'."""
    monkeypatch.setenv("ENV", env_value)

    result = _env_file()

    assert result == expected, (
        f"_env_file() with ENV={env_value!r} should return {expected!r}, got {result!r}"
    )


def test_env_file_defaults_to_env_local_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-17/D-20: _env_file() defaults to '.env.local' when ENV is not set."""
    monkeypatch.delenv("ENV", raising=False)

    result = _env_file()

    assert result == ".env.local", f"_env_file() with no ENV should default to '.env.local', got {result!r}"
