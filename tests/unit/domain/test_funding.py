"""Property tests for Funding domain type.

Tests:
  1. published_ts > settlement_ts raises ValidationError
  2. Naive datetime raises ValidationError
  3. Round-trip preserves all fields
  4. Negative rate allowed (funding can be negative)
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from pydantic import ValidationError

from shortfire.domain.market import Funding
from tests.conftest import utc_dt


def test_funding_published_gt_settlement_raises() -> None:
    """Funding with published_ts > settlement_ts raises ValidationError."""
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
    later = now + timedelta(hours=8)
    with pytest.raises(ValidationError, match=r"published_ts.*<=.*settlement_ts|published"):
        Funding(
            symbol="BTCUSDT",
            source="mexc",
            published_ts=later,  # published AFTER settlement — wrong
            settlement_ts=now,
            rate=Decimal("0.0001"),
        )


def test_funding_naive_published_ts_raises() -> None:
    """Funding with naive published_ts raises ValidationError."""
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        Funding(
            symbol="BTCUSDT",
            source="mexc",
            published_ts=datetime(2026, 5, 21, 12, 0, 0),  # naive
            settlement_ts=now,
            rate=Decimal("0.0001"),
        )


def test_funding_naive_settlement_ts_raises() -> None:
    """Funding with naive settlement_ts raises ValidationError."""
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match=r"timezone-aware|tzinfo"):
        Funding(
            symbol="BTCUSDT",
            source="mexc",
            published_ts=now,
            settlement_ts=datetime(2026, 5, 21, 20, 0, 0),  # naive
            rate=Decimal("0.0001"),
        )


def test_funding_happy_path() -> None:
    """Valid Funding constructs and round-trips."""
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
    settlement = now + timedelta(hours=8)
    f = Funding(
        symbol="BTCUSDT",
        source="mexc",
        published_ts=now,
        settlement_ts=settlement,
        rate=Decimal("0.0001"),
    )
    assert f.published_ts <= f.settlement_ts
    assert Funding.model_validate(f.model_dump()) == f


def test_funding_negative_rate_allowed() -> None:
    """Funding rate can be negative (bear market funding)."""
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
    settlement = now + timedelta(hours=8)
    f = Funding(
        symbol="BTCUSDT",
        source="mexc",
        published_ts=now,
        settlement_ts=settlement,
        rate=Decimal("-0.0003"),
    )
    assert f.rate < Decimal("0")


def test_funding_equal_timestamps_allowed() -> None:
    """Funding published_ts == settlement_ts is allowed (le is inclusive)."""
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
    f = Funding(
        symbol="BTCUSDT",
        source="mexc",
        published_ts=now,
        settlement_ts=now,
        rate=Decimal("0.0001"),
    )
    assert f.published_ts == f.settlement_ts


def test_funding_optional_next_funding_ts() -> None:
    """next_funding_ts is optional and defaults to None."""
    now = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
    settlement = now + timedelta(hours=8)
    f = Funding(
        symbol="BTCUSDT",
        source="mexc",
        published_ts=now,
        settlement_ts=settlement,
        rate=Decimal("0.0001"),
    )
    assert f.next_funding_ts is None


@given(ts=utc_dt)
@settings(max_examples=50)
def test_funding_round_trip_hypothesis(ts: datetime) -> None:
    """Round-trip model_dump / model_validate preserves all fields."""
    from datetime import timedelta

    settlement = ts + timedelta(hours=8)
    # Clamp settlement to max_value used in utc_dt
    from datetime import datetime as dt

    if settlement > dt(2030, 1, 1, tzinfo=UTC):
        settlement = ts  # equal timestamps are valid
    f = Funding(
        symbol="ETHUSDT",
        source="coinglass",
        published_ts=ts,
        settlement_ts=settlement,
        rate=Decimal("-0.0001"),
    )
    assert Funding.model_validate(f.model_dump()) == f
