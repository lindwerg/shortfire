"""Test D-16: DataPlatformSettings anti-leak boundary.

Verifies the structural absence of mexc_trade field on DataPlatformSettings
and the runtime assert_no_trade_env_leaked() guardrail.
"""

import pytest
from shortfire.settings.data_platform import (
    DataPlatformSettings,
    assert_no_trade_env_leaked,
)
from shortfire.settings.strategy_engine import StrategyEngineSettings


def test_data_platform_has_no_mexc_trade_field() -> None:
    """D-16: DataPlatformSettings must NOT have a mexc_trade field.

    This is the structural anti-leak guarantee: even if MEXC_TRADE__* env vars
    are present in the environment, pydantic-settings won't load them because
    there is no field to populate.
    """
    assert "mexc_trade" not in DataPlatformSettings.model_fields, (
        "D-16 violated: DataPlatformSettings must NOT have a mexc_trade field. "
        "MEXC_TRADE__* env vars must only be visible to StrategyEngineSettings."
    )


def test_strategy_engine_has_mexc_trade_field() -> None:
    """D-16 Phase 5 pre-wire: StrategyEngineSettings declares mexc_trade field.

    This confirms that the MEXC_TRADE__* env var routing is ALLOWED on strategy-engine
    and FORBIDDEN (structurally absent) on data-platform.
    """
    assert "mexc_trade" in StrategyEngineSettings.model_fields, (
        "StrategyEngineSettings should declare mexc_trade field for Phase 5 routing. "
        "This ensures MEXC_TRADE__TRADE_KEY env var routes to strategy-engine, not data-platform."
    )


def test_assert_no_trade_env_leaked_raises_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-16: assert_no_trade_env_leaked() raises RuntimeError when MEXC_TRADE__* is in env."""
    monkeypatch.setenv("MEXC_TRADE__TRADE_KEY", "dummy_trade_key")

    with pytest.raises(RuntimeError, match="MEXC_TRADE__"):
        assert_no_trade_env_leaked()


def test_assert_no_trade_env_leaked_passes_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-16: assert_no_trade_env_leaked() returns None without raising when env is clean."""
    monkeypatch.delenv("MEXC_TRADE__TRADE_KEY", raising=False)
    monkeypatch.delenv("MEXC_TRADE__TRADE_SECRET", raising=False)

    result = assert_no_trade_env_leaked()
    assert result is None, "assert_no_trade_env_leaked() must return None when env is clean"
