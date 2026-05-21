"""Property tests for RiskLimits domain type — RISK-02 hard caps.

Tests:
  1. max_per_trade_pct > 0.05 raises ValidationError (RISK-02)
  2. max_gross_exposure_pct > 0.15 raises (RISK-02)
  3. kelly_fraction > 0.25 raises (RISK-02)
  4. At boundary (0.05 / 0.15 / 0.25) succeeds (le is inclusive)
  5. Round-trip preserves all fields
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from shortfire.domain.risk import RiskLimits


def _valid_kwargs(**overrides: Decimal) -> dict:  # type: ignore[type-arg]
    """Return a valid RiskLimits kwargs dict, with optional field overrides."""
    defaults = {
        "max_per_trade_pct": Decimal("0.02"),
        "max_gross_exposure_pct": Decimal("0.10"),
        "kelly_fraction": Decimal("0.20"),
        "max_concurrent_positions": 5,
        "daily_loss_limit_pct": Decimal("0.05"),
    }
    defaults.update(overrides)
    return defaults


def test_max_per_trade_pct_above_cap_raises() -> None:
    """max_per_trade_pct=0.06 raises ValidationError (cap is 0.05)."""
    with pytest.raises(ValidationError):
        RiskLimits(**_valid_kwargs(max_per_trade_pct=Decimal("0.06")))


def test_max_gross_exposure_pct_above_cap_raises() -> None:
    """max_gross_exposure_pct=0.16 raises ValidationError (cap is 0.15)."""
    with pytest.raises(ValidationError):
        RiskLimits(**_valid_kwargs(max_gross_exposure_pct=Decimal("0.16")))


def test_kelly_fraction_above_cap_raises() -> None:
    """kelly_fraction=0.26 raises ValidationError (cap is 0.25)."""
    with pytest.raises(ValidationError):
        RiskLimits(**_valid_kwargs(kelly_fraction=Decimal("0.26")))


def test_risk_limits_at_exact_caps_succeeds() -> None:
    """RiskLimits at the exact cap values (0.05/0.15/0.25) succeeds — le is inclusive."""
    r = RiskLimits(
        max_per_trade_pct=Decimal("0.05"),
        max_gross_exposure_pct=Decimal("0.15"),
        kelly_fraction=Decimal("0.25"),
        max_concurrent_positions=5,
        daily_loss_limit_pct=Decimal("0.05"),
    )
    assert r.max_per_trade_pct == Decimal("0.05")
    assert r.max_gross_exposure_pct == Decimal("0.15")
    assert r.kelly_fraction == Decimal("0.25")


def test_risk_limits_zero_max_per_trade_pct_raises() -> None:
    """max_per_trade_pct=0 raises (must be > 0)."""
    with pytest.raises(ValidationError):
        RiskLimits(**_valid_kwargs(max_per_trade_pct=Decimal("0")))


def test_risk_limits_max_concurrent_positions_bounds() -> None:
    """max_concurrent_positions must be in [1, 20]."""
    with pytest.raises(ValidationError):
        RiskLimits(**_valid_kwargs(max_concurrent_positions=0))  # < 1

    with pytest.raises(ValidationError):
        RiskLimits(**_valid_kwargs(max_concurrent_positions=21))  # > 20


def test_risk_limits_round_trip() -> None:
    """Round-trip model_dump / model_validate preserves all fields."""
    r = RiskLimits(**_valid_kwargs())
    assert RiskLimits.model_validate(r.model_dump()) == r


def test_risk_limits_frozen() -> None:
    """RiskLimits is frozen — mutating a field raises."""
    r = RiskLimits(**_valid_kwargs())
    with pytest.raises(ValidationError):  # Pydantic raises ValidationError for frozen model mutation
        r.max_per_trade_pct = Decimal("0.01")  # type: ignore[misc]
