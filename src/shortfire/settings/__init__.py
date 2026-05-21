"""Settings layer — pydantic-settings per-service subclasses with anti-leak boundaries.

Public API:
    BaseAppSettings       — shared base class; all subclasses inherit from this
    DataPlatformSettings  — data-platform service; NO mexc_trade field (D-16)
    StrategyEngineSettings — strategy-engine service; has mexc_trade for Phase 5
    DashboardSettings     — dashboard service; has telegram for Phase 5
    RiskGuardSettings     — risk-guard service (Phase 5); no external API keys
    assert_no_trade_env_leaked — startup guardrail for data-platform (D-16)
"""

from shortfire.settings.base import BaseAppSettings
from shortfire.settings.dashboard import DashboardSettings
from shortfire.settings.data_platform import DataPlatformSettings, assert_no_trade_env_leaked
from shortfire.settings.risk_guard import RiskGuardSettings
from shortfire.settings.strategy_engine import StrategyEngineSettings

__all__ = [
    "BaseAppSettings",
    "DataPlatformSettings",
    "StrategyEngineSettings",
    "DashboardSettings",
    "RiskGuardSettings",
    "assert_no_trade_env_leaked",
]
