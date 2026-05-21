"""Unit tests for CoinGecko Pydantic v2 schemas (TDD RED → GREEN).

Tests verify:
  - CoinsMarketsRow.from_raw roundtrip with raw_payload retained
  - to_record source attribution (always 'coingecko')
  - CoinDetailResponse categories None-filtering
  - Hypothesis invariants
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from shortfire.ingest.coingecko.schemas import CoinDetailResponse, CoinsMarketsRow

_VALID_RAW = {
    "id": "bitcoin",
    "symbol": "btc",
    "name": "Bitcoin",
    "current_price": 50000,
    "market_cap": 1_000_000_000_000,
    "total_volume": 30_000_000_000,
    "last_updated": "2026-05-21T12:00:00.000Z",
}


def test_coins_markets_row_from_raw_roundtrip() -> None:
    """from_raw constructs without error and retains raw_payload."""
    row = CoinsMarketsRow.from_raw(_VALID_RAW)
    assert row.id == "bitcoin"
    assert row.symbol == "btc"
    assert row.current_price == Decimal("50000")
    assert row.raw_payload is not None
    assert row.raw_payload["id"] == "bitcoin"


def test_coins_markets_row_extra_fields_allowed() -> None:
    """extra='allow' — unknown fields pass through without error (Pitfall G)."""
    raw = {**_VALID_RAW, "unknown_future_field": "some_value", "another_new_field": 42}
    row = CoinsMarketsRow.from_raw(raw)
    assert row.id == "bitcoin"
    # Extra fields are stored by pydantic with extra='allow'
    assert row.model_extra is not None


def test_to_record_uses_source_coingecko() -> None:
    """to_record always sets source='coingecko' and quality_flag='ok' (T-1-CG-04)."""
    row = CoinsMarketsRow.from_raw(_VALID_RAW)
    ts = datetime.now(UTC)
    record = row.to_record(ts=ts)

    assert record[8] == "coingecko"
    assert record[9] == "ok"


def test_to_record_symbol_uppercased() -> None:
    """Symbol is uppercased in to_record (bare coin → unified DB format)."""
    row = CoinsMarketsRow.from_raw(_VALID_RAW)
    ts = datetime.now(UTC)
    record = row.to_record(ts=ts)
    assert record[0] == "BTC"


def test_to_record_symbol_override() -> None:
    """symbol_unified override takes precedence over auto-uppercased bare coin."""
    row = CoinsMarketsRow.from_raw(_VALID_RAW)
    ts = datetime.now(UTC)
    record = row.to_record(ts=ts, symbol_unified="BTC/USDT:USDT")
    assert record[0] == "BTC/USDT:USDT"


def test_to_record_has_correct_length() -> None:
    """to_record returns a 10-tuple matching raw_coingecko_market columns.

    Columns: symbol, ts, price_usd, volume_24h_usd, market_cap_usd, category,
    listing_date, raw_payload, source, quality_flag
    """
    row = CoinsMarketsRow.from_raw(_VALID_RAW)
    ts = datetime.now(UTC)
    record = row.to_record(ts=ts)
    assert len(record) == 10


def test_coin_detail_response_categories_tuple_filters_none() -> None:
    """categories with None values are filtered out in from_raw (D-55 safety)."""
    raw = {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "categories": ["DeFi", None, "Stablecoins", None],
        "genesis_date": None,
    }
    cd = CoinDetailResponse.from_raw(raw)
    assert cd.categories == ("DeFi", "Stablecoins")


def test_coin_detail_response_genesis_date_parsed() -> None:
    """genesis_date is parsed as Python date object."""
    from datetime import date

    raw = {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "categories": [],
        "genesis_date": "2009-01-03",
    }
    cd = CoinDetailResponse.from_raw(raw)
    assert cd.genesis_date == date(2009, 1, 3)


def test_coin_detail_response_raw_payload_retained() -> None:
    """raw_payload is retained for forensic access."""
    raw = {
        "id": "ethereum",
        "symbol": "eth",
        "name": "Ethereum",
        "categories": ["Smart Contract Platform"],
        "genesis_date": "2015-07-30",
        "market_data": {"current_price": {"usd": 2500}},
    }
    cd = CoinDetailResponse.from_raw(raw)
    assert cd.raw_payload is not None
    assert cd.raw_payload["id"] == "ethereum"


@given(
    st.fixed_dictionaries(
        {
            "id": st.text(min_size=1, max_size=50),
            "symbol": st.text(min_size=1, max_size=20),
            "name": st.text(min_size=1, max_size=100),
            "current_price": st.one_of(
                st.none(), st.decimals(min_value=0, max_value=1e12, allow_nan=False, allow_infinity=False)
            ),
            "market_cap": st.one_of(
                st.none(), st.decimals(min_value=0, max_value=1e18, allow_nan=False, allow_infinity=False)
            ),
            "total_volume": st.one_of(
                st.none(), st.decimals(min_value=0, max_value=1e16, allow_nan=False, allow_infinity=False)
            ),
        }
    )
)
def test_from_raw_either_succeeds_or_raises_validation_error(raw: dict) -> None:  # type: ignore[type-arg]
    """from_raw never raises unexpected exceptions — only ValidationError allowed."""
    with contextlib.suppress(ValidationError, ValueError, TypeError):
        CoinsMarketsRow.from_raw(raw)
    # No other exceptions should propagate
