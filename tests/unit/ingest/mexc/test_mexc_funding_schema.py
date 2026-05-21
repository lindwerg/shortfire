"""Unit tests for MexcFundingRow Pydantic v2 schema — dual-timestamp invariant (DATA-02).

Covers:
- Hypothesis property: t1 <= t2 → Funding.published_ts <= Funding.settlement_ts
- Negative property: t1 > t2 → ValidationError matching published_ts.*<=.*settlement_ts
- tz-awareness: Funding.published_ts.tzinfo is UTC
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st


@given(
    t1=st.integers(min_value=0, max_value=10**13 - 1),
    offset=st.integers(min_value=0, max_value=10**6),
)
def test_funding_hypothesis_published_le_settlement(t1: int, offset: int) -> None:
    """Property: t1 <= t2 produces Funding with published_ts <= settlement_ts (DATA-02 keystone)."""
    from shortfire.ingest.mexc.schemas import MexcFundingRow

    t2 = t1 + offset
    row = MexcFundingRow.model_validate(
        {
            "symbol": "BTC/USDT:USDT",
            "timestamp": t1,
            "fundingTimestamp": t2,
            "fundingRate": Decimal("0.0001"),
        }
    )
    funding = row.to_domain()
    assert funding.published_ts <= funding.settlement_ts


@given(
    t1=st.integers(min_value=1, max_value=10**13),
    offset=st.integers(min_value=1, max_value=10**6),
)
def test_funding_hypothesis_published_gt_settlement_raises(t1: int, offset: int) -> None:
    """Property: t1 > t2 raises ValidationError matching published_ts.*<=.*settlement_ts."""
    from pydantic import ValidationError

    from shortfire.ingest.mexc.schemas import MexcFundingRow

    t2 = t1 - offset  # t1 > t2 (impossible-by-spec case)
    row = MexcFundingRow.model_validate(
        {
            "symbol": "BTC/USDT:USDT",
            "timestamp": t1,
            "fundingTimestamp": t2,
            "fundingRate": Decimal("0.0001"),
        }
    )
    with pytest.raises(ValidationError, match="published_ts"):
        row.to_domain()


def test_funding_published_ts_is_utc() -> None:
    """Funding.published_ts.tzinfo is UTC."""
    from shortfire.ingest.mexc.schemas import MexcFundingRow

    row = MexcFundingRow.model_validate(
        {
            "symbol": "BTC/USDT:USDT",
            "timestamp": 1_684_675_200_000,
            "fundingTimestamp": 1_684_675_200_000,
            "fundingRate": Decimal("0.0001"),
        }
    )
    funding = row.to_domain()
    assert funding.published_ts.tzinfo == UTC
