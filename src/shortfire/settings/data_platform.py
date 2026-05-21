"""DataPlatformSettings — settings for the data-platform service.

Anti-leak boundary (D-16):
- DataPlatformSettings has NO `mexc_trade` field.
- Phase 5 MEXC_TRADE__* env vars are structurally inert on data-platform because
  pydantic-settings won't load env vars that don't appear as declared fields.
- assert_no_trade_env_leaked() provides a RUNTIME guardrail at startup (defense in depth).

Decisions honored:
  D-16: No mexc_trade field; assert_no_trade_env_leaked() startup guardrail
  D-18: MEXC__READ_KEY, MEXC__READ_SECRET, COINGLASS__API_KEY, COINGECKO__API_KEY
  D-19: All credentials are SecretStr
  D-21: safe_summary() returns bool flags only — never SecretStr values
"""

import os

from pydantic import BaseModel, SecretStr

from shortfire.settings.base import BaseAppSettings


class MexcReadSettings(BaseModel):
    """Read-only MEXC API credentials for data ingestion.

    Phase 1 wires MEXC__READ_KEY and MEXC__READ_SECRET env vars.
    These are READ-ONLY keys — never trade keys (those belong to strategy-engine).
    """

    read_key: SecretStr
    read_secret: SecretStr


class CoinglassSettings(BaseModel):
    """Coinglass API credentials for derivatives data (OI, funding, liquidations)."""

    api_key: SecretStr


class CoingeckoSettings(BaseModel):
    """CoinGecko API credentials for market metadata and universe filtering."""

    api_key: SecretStr


class DataPlatformSettings(BaseAppSettings):
    """Settings for the data-platform Railway service.

    IMPORTANT: This class intentionally has NO `mexc_trade` field.
    See D-16 and CONTEXT.md §Anti-leak architecture.
    MEXC_TRADE__* env vars must never appear in data-platform's Railway service config.
    Even if they do appear (misconfiguration), pydantic-settings ignores them (no field),
    AND assert_no_trade_env_leaked() will crash the service at startup.

    Phase 1+ wires: mexc, coinglass, coingecko
    """

    service_name: str = "data-platform"

    # Optional — None until Phase 1 wires the real keys.
    # Declared now so the env-var-routing boundary is structurally correct.
    mexc: MexcReadSettings | None = None
    coinglass: CoinglassSettings | None = None
    coingecko: CoingeckoSettings | None = None

    # D-16 structural absence: NO mexc_trade field here.
    # StrategyEngineSettings declares mexc_trade for Phase 5.

    def safe_summary(self) -> dict[str, object]:
        """Extend base summary with boolean flags for optional credential blocks (D-21)."""
        base = super().safe_summary()
        base.update(
            {
                "mexc_read_configured": self.mexc is not None,
                "coinglass_configured": self.coinglass is not None,
                "coingecko_configured": self.coingecko is not None,
            }
        )
        return base


def assert_no_trade_env_leaked() -> None:
    """Startup guardrail: raise if any MEXC_TRADE__* env var is present (D-16).

    This is defense-in-depth. The structural absence of `mexc_trade` on
    DataPlatformSettings means pydantic-settings won't load trade keys even if
    they're present. But if they ARE present, it means Railway service-scoping
    is misconfigured — fail loudly rather than silently continuing.

    Call this in the data-platform entrypoint immediately after constructing
    DataPlatformSettings().

    Usage:
        settings = DataPlatformSettings()  # fails fast on missing required vars
        assert_no_trade_env_leaked()        # fails fast on misrouted trade vars
    """
    leaked = [k for k in os.environ if k.startswith("MEXC_TRADE__")]
    if leaked:
        raise RuntimeError(
            f"FATAL: trade-only env vars visible to data-platform: {leaked}. "
            f"Check Railway service-scoping; MEXC_TRADE__* must only exist on strategy-engine."
        )
