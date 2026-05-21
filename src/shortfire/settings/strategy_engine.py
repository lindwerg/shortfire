"""StrategyEngineSettings — settings for the strategy-engine Railway service.

Phase 5 routing: this class declares `mexc_trade: MexcTradeSettings | None = None`
so that MEXC_TRADE__TRADE_KEY env var is ALLOWED here and FORBIDDEN (structurally
absent) on DataPlatformSettings (D-16).

Phase 2+ adds mlflow_tracking_uri.
Phase 5+ populates mexc_trade with real keys via Railway env var config.

Decisions honored:
  D-16: mexc_trade field present here (Phase 5 pre-wire); absent from DataPlatformSettings
  D-18: MEXC_TRADE__TRADE_KEY, MEXC_TRADE__TRADE_SECRET (Phase 5)
  D-19: All credentials are SecretStr
  D-21: safe_summary() returns bool flags only — never SecretStr values
"""

from pydantic import BaseModel, SecretStr

from shortfire.settings.base import BaseAppSettings


class MexcTradeSettings(BaseModel):
    """Trade API credentials for MEXC futures execution.

    Phase 5 only. These keys have order-execution permissions.
    NEVER expose on data-platform (D-16 anti-leak boundary).
    """

    trade_key: SecretStr
    trade_secret: SecretStr


class StrategyEngineSettings(BaseAppSettings):
    """Settings for the strategy-engine Railway service.

    Phase 2+ uses mlflow_tracking_uri for experiment tracking.
    Phase 5+ uses mexc_trade for live futures execution.

    The mexc_trade field being declared here (and ABSENT from DataPlatformSettings)
    is the structural anti-leak guarantee from D-16.
    """

    service_name: str = "strategy-engine"

    # Phase 2+: MLflow experiment tracking URI
    mlflow_tracking_uri: str | None = None

    # Phase 5+: MEXC trade execution credentials (MEXC_TRADE__TRADE_KEY, MEXC_TRADE__TRADE_SECRET)
    # Declared now so env-var routing is pre-wired and testable from Phase 0.
    mexc_trade: MexcTradeSettings | None = None

    def safe_summary(self) -> dict[str, object]:
        """Extend base summary with boolean flags for optional credential blocks (D-21)."""
        base = super().safe_summary()
        base.update(
            {
                "mexc_trade_configured": self.mexc_trade is not None,
                "mlflow_configured": self.mlflow_tracking_uri is not None,
            }
        )
        return base
