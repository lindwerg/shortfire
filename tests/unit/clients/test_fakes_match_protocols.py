"""Protocol-conformance tests for all 4 fakes (FOUND-08, TEST-05).

Tests:
1. isinstance checks: each fake satisfies its Protocol (runtime_checkable)
2. FakeMexcClient.fetch_ohlcv happy path returns all matching candles
3. FakeMexcClient.fetch_ohlcv time filter returns only candles in [since, until]
4. FakeMexcClient.place_order returns a string id and records the order
5. FakeMexcClient.fetch_funding_rate_history raises NotImplementedError (Phase 0 boundary)
6. InMemoryCandleRepo round-trip: insert then fetch_by_symbol returns all inserted candles
7. InMemoryCandleRepo time-range filter: fetch_by_time_range returns only the matching candle
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from shortfire.clients.coingecko import CoinGeckoClient
from shortfire.clients.coinglass import CoinglassClient
from shortfire.clients.mexc import MexcClient
from shortfire.clients.repos import CandleRepo
from shortfire.domain.market import Candle
from shortfire.domain.trading import Order
from tests.fakes.coingecko import FakeCoinGeckoClient
from tests.fakes.coinglass import FakeCoinglassClient
from tests.fakes.mexc import FakeMexcClient
from tests.fakes.repos import InMemoryCandleRepo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def _candle(symbol: str, ts: datetime, price: str = "100") -> Candle:
    p = Decimal(price)
    return Candle(
        symbol=symbol,
        source="mexc",
        timeframe="1m",
        ts=ts,
        open=p,
        high=p,
        low=p,
        close=p,
        volume=Decimal("1"),
    )


def _order(symbol: str = "BTCUSDT") -> Order:
    return Order(
        client_order_id="test-order-1",
        symbol=symbol,
        intent="open",
        side="short",
        order_type="market",
        quantity=Decimal("0.01"),
        price=None,
        reduce_only=False,
        ts=_utc(2024, 1, 1),
    )


# ---------------------------------------------------------------------------
# Test 1: isinstance checks (runtime_checkable Protocol conformance)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fake_instance, protocol_cls",
    [
        (FakeMexcClient(), MexcClient),
        (FakeCoinglassClient(), CoinglassClient),
        (FakeCoinGeckoClient(), CoinGeckoClient),
        (InMemoryCandleRepo(), CandleRepo),
    ],
)
def test_fake_satisfies_protocol(fake_instance: object, protocol_cls: type) -> None:
    """Each fake must satisfy its Protocol via runtime isinstance check."""
    assert isinstance(fake_instance, protocol_cls), (
        f"{type(fake_instance).__name__} does not satisfy {protocol_cls.__name__}"
    )


# ---------------------------------------------------------------------------
# Test 2: FakeMexcClient.fetch_ohlcv happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_mexc_fetch_ohlcv_returns_all_candles() -> None:
    """fetch_ohlcv with a window covering all candles returns all 3 in order."""
    ts1 = _utc(2024, 1, 1, 0)
    ts2 = _utc(2024, 1, 1, 1)
    ts3 = _utc(2024, 1, 1, 2)
    c1 = _candle("BTCUSDT", ts1)
    c2 = _candle("BTCUSDT", ts2)
    c3 = _candle("BTCUSDT", ts3)

    fake = FakeMexcClient(candles=(c1, c2, c3))
    result = await fake.fetch_ohlcv("BTCUSDT", "1m", since=ts1, until=ts3)

    assert result == (c1, c2, c3)


# ---------------------------------------------------------------------------
# Test 3: FakeMexcClient.fetch_ohlcv time filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_mexc_fetch_ohlcv_time_filter() -> None:
    """fetch_ohlcv with since=c2.ts filters out c1, returns only c2 and c3."""
    ts1 = _utc(2024, 1, 1, 0)
    ts2 = _utc(2024, 1, 1, 1)
    ts3 = _utc(2024, 1, 1, 2)
    c1 = _candle("BTCUSDT", ts1)
    c2 = _candle("BTCUSDT", ts2)
    c3 = _candle("BTCUSDT", ts3)

    fake = FakeMexcClient(candles=(c1, c2, c3))
    result = await fake.fetch_ohlcv("BTCUSDT", "1m", since=ts2, until=ts3)

    assert result == (c2, c3)


# ---------------------------------------------------------------------------
# Test 4: FakeMexcClient.place_order returns id and records order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_mexc_place_order_returns_id_and_records() -> None:
    """place_order returns a string matching fake-order-id-N and records the order."""
    import re

    fake = FakeMexcClient()
    order = _order()

    order_id = await fake.place_order(order)

    assert isinstance(order_id, str)
    assert re.fullmatch(r"fake-order-id-\d+", order_id) is not None
    assert len(fake.placed_orders) == 1
    assert fake.placed_orders[0] is order


# ---------------------------------------------------------------------------
# Test 5: FakeMexcClient.fetch_funding_rate_history raises NotImplementedError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_mexc_fetch_funding_rate_raises_not_implemented() -> None:
    """fetch_funding_rate_history raises NotImplementedError — Phase 0 boundary doc."""
    fake = FakeMexcClient()
    with pytest.raises(NotImplementedError):
        await fake.fetch_funding_rate_history(
            "BTCUSDT",
            since=_utc(2024, 1, 1),
            until=_utc(2024, 1, 2),
        )


# ---------------------------------------------------------------------------
# Test 6: InMemoryCandleRepo round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_memory_candle_repo_round_trip() -> None:
    """insert then fetch_by_symbol returns the candles as a tuple (D-11 convention)."""
    ts1 = _utc(2024, 1, 1, 0)
    ts2 = _utc(2024, 1, 1, 1)
    c1 = _candle("ETHUSDT", ts1)
    c2 = _candle("ETHUSDT", ts2)

    repo = InMemoryCandleRepo()
    await repo.insert((c1, c2))
    result = await repo.fetch_by_symbol("ETHUSDT")

    assert isinstance(result, tuple)
    assert result == (c1, c2)


# ---------------------------------------------------------------------------
# Test 7: InMemoryCandleRepo time-range filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_memory_candle_repo_time_range_filter() -> None:
    """fetch_by_time_range with a narrow window returns only the matching candle."""
    ts1 = _utc(2024, 1, 1, 0)
    ts2 = _utc(2024, 1, 1, 6)
    ts3 = _utc(2024, 1, 1, 12)
    c1 = _candle("SOLUSDT", ts1)
    c2 = _candle("SOLUSDT", ts2)
    c3 = _candle("SOLUSDT", ts3)

    repo = InMemoryCandleRepo()
    await repo.insert((c1, c2, c3))
    result = await repo.fetch_by_time_range("SOLUSDT", since=ts2, until=ts2)

    assert result == (c2,)
