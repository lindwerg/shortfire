"""Unit tests for Coinglass v4 response schemas (D-52, Pitfall G).

Tests cover:
- Valid payload parsing for all four schemas
- extra='allow' tolerates unknown Coinglass fields without breaking (Pitfall G)
- strict=True rejects wrong types (e.g. funding_rate="not_a_number")
- to_record / to_records always sets source='coinglass_aggregate'
- to_record returns exactly the right tuple shape
- Hypothesis property test: to_record output invariants
"""

from __future__ import annotations

from decimal import Decimal

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helpers — canned payloads matching wire format from Coinglass v4 docs
# ---------------------------------------------------------------------------

FUNDING_PAYLOAD = {
    "code": 0,
    "msg": "ok",
    "data": [
        {"symbol": "BTC", "funding_rate": "0.0001", "next_funding_time": 1700000000000},
        {"symbol": "ETH", "funding_rate": "-0.0002", "next_funding_time": 1700000000000},
    ],
}

OI_PAYLOAD = {
    "code": 0,
    "msg": "ok",
    "data": [
        {"time": 1700000000000, "open_interest_usd": "123456789.12"},
        {"time": 1700003600000, "open_interest_usd": "987654321.00"},
    ],
}

LIQ_PAYLOAD = {
    "code": 0,
    "msg": "ok",
    "data": [
        {
            "time": 1700000000000,
            "liquidation_long_usd": "10000.50",
            "liquidation_short_usd": "5000.25",
        },
    ],
}

LSR_PAYLOAD = {
    "code": 0,
    "msg": "ok",
    "data": [
        {"time": 1700000000000, "long_short_ratio": "1.23"},
        {"time": 1700003600000, "long_short_ratio": "0.87"},
    ],
}


# ---------------------------------------------------------------------------
# FundingRateListResponse
# ---------------------------------------------------------------------------


class TestFundingRateListResponse:
    def test_valid_payload_parses_correctly(self) -> None:
        from shortfire.ingest.coinglass.schemas import FundingRateListResponse

        resp = FundingRateListResponse.model_validate(FUNDING_PAYLOAD)
        assert resp.code == 0
        assert resp.msg == "ok"
        assert len(resp.data) == 2
        assert resp.data[0].symbol == "BTC"
        assert resp.data[0].funding_rate == Decimal("0.0001")

    def test_extra_allow_tolerates_unknown_fields(self) -> None:
        """Pitfall G: Coinglass sometimes renames or adds fields — extra='allow' must not crash."""
        from shortfire.ingest.coinglass.schemas import FundingRateListResponse

        payload_with_extra = {**FUNDING_PAYLOAD, "version": "v4", "page_total": 100}
        resp = FundingRateListResponse.model_validate(payload_with_extra)
        assert len(resp.data) == 2

    def test_strict_rejects_non_numeric_funding_rate(self) -> None:
        from shortfire.ingest.coinglass.schemas import FundingRateListResponse

        bad_payload = {
            "code": 0,
            "msg": "ok",
            "data": [{"symbol": "BTC", "funding_rate": "not_a_number"}],
        }
        with pytest.raises(ValidationError):
            FundingRateListResponse.model_validate(bad_payload)

    def test_to_record_returns_6_tuple_with_coinglass_aggregate_source(self) -> None:
        from shortfire.ingest.coinglass.schemas import FundingRateListResponse

        resp = FundingRateListResponse.model_validate(FUNDING_PAYLOAD)
        row = resp.data[0]
        record = row.to_record()
        assert len(record) == 5  # (symbol, ts, funding_rate, source, quality_flag)
        assert record[3] == "coinglass_aggregate"
        assert record[4] == "ok"

    def test_to_record_source_always_coinglass_aggregate(self) -> None:
        """D-59: source attribution is non-negotiable — even if caller tries another value."""
        from shortfire.ingest.coinglass.schemas import FundingRateListResponse

        resp = FundingRateListResponse.model_validate(FUNDING_PAYLOAD)
        row = resp.data[0]
        # Default call
        record = row.to_record()
        assert record[3] == "coinglass_aggregate"

    def test_model_config_has_correct_flags(self) -> None:
        from shortfire.ingest.coinglass.schemas import FundingRateListResponse

        cfg = FundingRateListResponse.model_config
        assert cfg.get("extra") == "allow"
        assert cfg.get("frozen") is True

    def test_funding_rate_none_is_allowed(self) -> None:
        """Coinglass returns null funding_rate for some symbols — must not crash."""
        from shortfire.ingest.coinglass.schemas import FundingRateListResponse

        payload = {
            "code": 0,
            "msg": "ok",
            "data": [{"symbol": "BTC", "funding_rate": None}],
        }
        resp = FundingRateListResponse.model_validate(payload)
        assert resp.data[0].funding_rate is None


# ---------------------------------------------------------------------------
# OpenInterestHistoryResponse
# ---------------------------------------------------------------------------


class TestOpenInterestHistoryResponse:
    def test_valid_payload_parses_correctly(self) -> None:
        from shortfire.ingest.coinglass.schemas import OpenInterestHistoryResponse

        resp = OpenInterestHistoryResponse.model_validate(OI_PAYLOAD)
        assert len(resp.data) == 2
        assert resp.data[0].open_interest_usd == Decimal("123456789.12")

    def test_to_records_returns_correct_tuples(self) -> None:
        from shortfire.ingest.coinglass.schemas import OpenInterestHistoryResponse

        resp = OpenInterestHistoryResponse.model_validate(OI_PAYLOAD)
        records = resp.to_records(symbol_unified="BTC/USDT:USDT")
        assert len(records) == 2
        # Each record: (symbol_unified, ts_utc, open_interest_usd, source, quality_flag)
        assert records[0][0] == "BTC/USDT:USDT"
        assert records[0][3] == "coinglass_aggregate"
        assert records[0][4] == "ok"
        # ts is tz-aware UTC
        assert records[0][1].tzinfo is not None

    def test_extra_allow_tolerates_unknown_fields(self) -> None:
        from shortfire.ingest.coinglass.schemas import OpenInterestHistoryResponse

        payload = {**OI_PAYLOAD, "exchange": "all", "instrument": "perpetual"}
        resp = OpenInterestHistoryResponse.model_validate(payload)
        assert len(resp.data) == 2

    def test_model_config_has_correct_flags(self) -> None:
        from shortfire.ingest.coinglass.schemas import OpenInterestHistoryResponse

        cfg = OpenInterestHistoryResponse.model_config
        assert cfg.get("extra") == "allow"
        assert cfg.get("frozen") is True


# ---------------------------------------------------------------------------
# LiquidationCoinHistoryResponse
# ---------------------------------------------------------------------------


class TestLiquidationCoinHistoryResponse:
    def test_valid_payload_parses_correctly(self) -> None:
        from shortfire.ingest.coinglass.schemas import LiquidationCoinHistoryResponse

        resp = LiquidationCoinHistoryResponse.model_validate(LIQ_PAYLOAD)
        assert len(resp.data) == 1
        assert resp.data[0].liquidation_long_usd == Decimal("10000.50")
        assert resp.data[0].liquidation_short_usd == Decimal("5000.25")

    def test_to_records_returns_two_rows_per_data_point(self) -> None:
        """Each data point produces two records: one 'long', one 'short'."""
        from shortfire.ingest.coinglass.schemas import LiquidationCoinHistoryResponse

        resp = LiquidationCoinHistoryResponse.model_validate(LIQ_PAYLOAD)
        records = resp.to_records(symbol_unified="BTC/USDT:USDT")
        assert len(records) == 2  # 1 data point × 2 sides
        sides = {r[2] for r in records}  # side is at index 2
        assert sides == {"long", "short"}
        assert all(r[4] == "coinglass_aggregate" for r in records)  # source at index 4

    def test_extra_allow_tolerates_unknown_fields(self) -> None:
        from shortfire.ingest.coinglass.schemas import LiquidationCoinHistoryResponse

        payload = {**LIQ_PAYLOAD, "currency": "USD"}
        resp = LiquidationCoinHistoryResponse.model_validate(payload)
        assert len(resp.data) == 1

    def test_model_config_has_correct_flags(self) -> None:
        from shortfire.ingest.coinglass.schemas import LiquidationCoinHistoryResponse

        cfg = LiquidationCoinHistoryResponse.model_config
        assert cfg.get("extra") == "allow"
        assert cfg.get("frozen") is True


# ---------------------------------------------------------------------------
# LongShortAccountRatioResponse
# ---------------------------------------------------------------------------


class TestLongShortAccountRatioResponse:
    def test_valid_payload_parses_correctly(self) -> None:
        from shortfire.ingest.coinglass.schemas import LongShortAccountRatioResponse

        resp = LongShortAccountRatioResponse.model_validate(LSR_PAYLOAD)
        assert len(resp.data) == 2
        assert resp.data[0].long_short_ratio == Decimal("1.23")

    def test_to_records_returns_correct_tuples(self) -> None:
        from shortfire.ingest.coinglass.schemas import LongShortAccountRatioResponse

        resp = LongShortAccountRatioResponse.model_validate(LSR_PAYLOAD)
        records = resp.to_records(symbol_unified="BTC/USDT:USDT")
        assert len(records) == 2
        assert records[0][0] == "BTC/USDT:USDT"
        assert records[0][3] == "coinglass_aggregate"
        assert records[0][4] == "ok"
        assert records[0][1].tzinfo is not None

    def test_extra_allow_tolerates_unknown_fields(self) -> None:
        from shortfire.ingest.coinglass.schemas import LongShortAccountRatioResponse

        payload = {**LSR_PAYLOAD, "exchange_type": "futures"}
        resp = LongShortAccountRatioResponse.model_validate(payload)
        assert len(resp.data) == 2

    def test_model_config_has_correct_flags(self) -> None:
        from shortfire.ingest.coinglass.schemas import LongShortAccountRatioResponse

        cfg = LongShortAccountRatioResponse.model_config
        assert cfg.get("extra") == "allow"
        assert cfg.get("frozen") is True


# ---------------------------------------------------------------------------
# Hypothesis: FundingRateListRow.to_record invariants
# ---------------------------------------------------------------------------


@given(
    funding_rate=st.decimals(
        min_value=Decimal("-0.1"),
        max_value=Decimal("0.1"),
        places=8,
        allow_nan=False,
        allow_infinity=False,
    )
)
@settings(max_examples=50)
def test_to_record_invariant_source_always_coinglass_aggregate(funding_rate: Decimal) -> None:
    """Property: to_record() always returns source='coinglass_aggregate' regardless of funding_rate."""
    from shortfire.ingest.coinglass.schemas import FundingRateListRow

    row = FundingRateListRow(symbol="BTC", funding_rate=funding_rate)
    record = row.to_record()
    assert record[3] == "coinglass_aggregate"
    assert record[4] == "ok"
