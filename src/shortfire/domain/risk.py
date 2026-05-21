"""Risk management domain types — RiskLimits.

RiskLimits encodes the RISK-02 hard caps as structural Field constraints:
  - max_per_trade_pct <= 0.05 (5% per trade cap)
  - max_gross_exposure_pct <= 0.15 (15% gross exposure cap)
  - kelly_fraction <= 0.25 (quarter-Kelly maximum)

Cannot construct RiskLimits with any cap exceeded — constraint is structural (D-13).
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RiskLimits(BaseModel):
    """Hard caps for the risk management system (RISK-02 structural constraints).

    All caps are enforced via Field(le=...) — construction fails if any cap is exceeded.
    Fields are frozen+strict (D-08) — no runtime mutation of risk caps.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    # RISK-02: per-trade cap <= 5% of account
    max_per_trade_pct: Decimal = Field(gt=Decimal("0"), le=Decimal("0.05"))

    # RISK-02: gross exposure cap <= 15% of account
    max_gross_exposure_pct: Decimal = Field(gt=Decimal("0"), le=Decimal("0.15"))

    # RISK-02: Kelly fraction cap <= 0.25 (quarter-Kelly)
    kelly_fraction: Decimal = Field(gt=Decimal("0"), le=Decimal("0.25"))

    # Maximum concurrent open positions
    max_concurrent_positions: int = Field(ge=1, le=20)

    # Daily loss limit before trading is halted
    daily_loss_limit_pct: Decimal = Field(gt=Decimal("0"), le=Decimal("0.10"))
