"""Shared test fixtures and Hypothesis strategies for the entire test suite.

Strategies:
  money   -- positive Decimal suitable for price/quantity/pnl fields
  utc_dt  -- tz-aware UTC datetime bounded to plausible trading dates

Hypothesis profile 'ci':
  deadline=None (removes flakiness from slow CI machines)
  max_examples=200 (thorough property coverage without runaway shrinking)
  suppress_health_check=[HealthCheck.too_slow]

Usage:
    from tests.conftest import money, utc_dt
    from hypothesis import given

    @given(price=money, ts=utc_dt)
    def test_candle_invariant(price, ts): ...
"""

import os
from datetime import UTC, datetime
from decimal import Decimal

import hypothesis.strategies as st
from hypothesis import HealthCheck, settings

# ---------------------------------------------------------------------------
# Shared Hypothesis strategies (Common Operation 1 from RESEARCH.md)
# ---------------------------------------------------------------------------

money = st.decimals(
    min_value=Decimal("0.00000001"),
    max_value=Decimal("1000000000"),
    places=18,
    allow_nan=False,
    allow_infinity=False,
)
"""Strategy for positive Decimal money — bounded for fast shrinking.

Covers prices, quantities, PnL, and notional values. Bounded min/max prevent
Hypothesis shrinking from running away on Decimal. Pitfall 1: always pass
Decimal instances (not float literals) into domain type constructors when strict=True.
"""

utc_dt = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 1, 1),
    timezones=st.just(UTC),
)
"""Strategy for tz-aware UTC datetimes — bounded to plausible trading dates.

NEVER use st.datetimes() without timezones= — that yields naive datetimes which
domain validators reject with ValidationError (Pitfall 7). Always freeze with
freeze_time("...Z") — not a naive date string.
"""

# ---------------------------------------------------------------------------
# Hypothesis profiles
# ---------------------------------------------------------------------------

settings.register_profile(
    "ci",
    deadline=None,
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
