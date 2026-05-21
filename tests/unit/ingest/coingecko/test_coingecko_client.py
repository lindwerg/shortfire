"""Unit tests for CoinGeckoClient (TDD RED → GREEN).

Tests verify:
  - API key sent as x-cg-demo-api-key header, never in URL (T-1-CG-01)
  - Pagination params and request shape
  - 4xx-non-429 routes to dead_letter without raising
  - 429 raises (so tenacity can retry)
  - Pydantic ValidationError routes to dead_letter, returns None
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from pydantic import SecretStr

from shortfire.ingest.coingecko.client import CoinGeckoClient
from shortfire.ingest.coingecko.schemas import CoinsMarketsRow
from shortfire.settings.data_platform import CoingeckoSettings, DataPlatformSettings


def _build_settings(api_key: str = "test-demo-key-12345") -> DataPlatformSettings:
    """Build a minimal DataPlatformSettings with CoinGecko configured."""
    return DataPlatformSettings.model_construct(
        service_name="data-platform",
        coingecko=CoingeckoSettings(api_key=SecretStr(api_key)),
    )


_CANNED_MARKETS_PAYLOAD = [
    {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "current_price": 50000,
        "market_cap": 1_000_000_000_000,
        "total_volume": 30_000_000_000,
        "last_updated": "2026-05-21T12:00:00.000Z",
    },
    {
        "id": "ethereum",
        "symbol": "eth",
        "name": "Ethereum",
        "current_price": 2500,
        "market_cap": 300_000_000_000,
        "total_volume": 15_000_000_000,
        "last_updated": "2026-05-21T12:00:00.000Z",
    },
]


@pytest.mark.asyncio
async def test_header_carries_demo_api_key_url_does_not() -> None:
    """API key must appear in header x-cg-demo-api-key, NEVER in URL query (T-1-CG-01)."""
    token = "super-secret-demo-token-xyz"
    settings = _build_settings(api_key=token)

    with respx.mock(base_url="https://api.coingecko.com/api/v3") as mock:
        mock.get("/coins/markets").mock(return_value=httpx.Response(200, json=_CANNED_MARKETS_PAYLOAD))
        client = CoinGeckoClient(settings)
        await client.fetch_coins_markets(vs_currency="usd", per_page=250, page=1)

        # Access calls INSIDE the with block (respx clears calls on __exit__)
        assert len(mock.calls) == 1
        request = mock.calls[0].request
        # Key in header (case-insensitive lookup via httpx)
        assert request.headers.get("x-cg-demo-api-key") == token
        # Key NOT in URL query
        assert token not in str(request.url.query)
        assert "x-cg-demo-api-key" not in str(request.url.query).lower()

        await client.close()


@pytest.mark.asyncio
async def test_fetch_coins_markets_paginates_per_page_250() -> None:
    """Request URL must contain per_page=250 and order=market_cap_desc."""
    settings = _build_settings()

    with respx.mock(base_url="https://api.coingecko.com/api/v3") as mock:
        mock.get("/coins/markets").mock(return_value=httpx.Response(200, json=_CANNED_MARKETS_PAYLOAD))
        client = CoinGeckoClient(settings)
        result = await client.fetch_coins_markets(vs_currency="usd", per_page=250, page=1)

        # Access calls INSIDE the with block
        assert len(mock.calls) == 1
        request = mock.calls[0].request
        query_str = str(request.url.query)
        assert "per_page=250" in query_str
        assert "page=1" in query_str
        assert "order=market_cap_desc" in query_str

        await client.close()

    assert result is not None
    assert len(result) == 2
    assert isinstance(result[0], CoinsMarketsRow)


@pytest.mark.asyncio
async def test_401_routes_to_dead_letter_no_raise() -> None:
    """401 is a permanent 4xx — must route to dead_letter and return None without raising."""
    settings = _build_settings()

    with (
        patch("shortfire.ingest.coingecko.client.write_to_dead_letter", new_callable=AsyncMock) as mock_dl,
        respx.mock(base_url="https://api.coingecko.com/api/v3") as mock,
    ):
        mock.get("/coins/markets").mock(return_value=httpx.Response(401, text="Unauthorized"))
        client = CoinGeckoClient(settings)
        result = await client.fetch_coins_markets()
        await client.close()

        # Verify inside with block
        assert len(mock.calls) == 1

    assert result is None
    mock_dl.assert_called_once()
    call_kwargs = mock_dl.call_args
    # error_type should be HTTPStatusError (positional arg at index 4)
    assert call_kwargs[0][4] == "HTTPStatusError" or (call_kwargs[1].get("error_type") == "HTTPStatusError")


@pytest.mark.asyncio
async def test_429_raises_for_retry() -> None:
    """429 must raise httpx.HTTPStatusError (tenacity catches and retries)."""
    settings = _build_settings()

    with respx.mock(base_url="https://api.coingecko.com/api/v3") as mock:
        mock.get("/coins/markets").mock(return_value=httpx.Response(429, text="Too Many Requests"))
        client = CoinGeckoClient(settings)
        with pytest.raises(httpx.HTTPStatusError):
            # Access the internal _call directly to bypass tenacity retry decorator
            # pyright: ignore[reportPrivateUsage] — intentional for unit test isolation
            await client._call(  # type: ignore[misc]
                "/coins/markets",
                params={"vs_currency": "usd", "per_page": 1, "page": 1, "order": "market_cap_desc"},
            )
        await client.close()


@pytest.mark.asyncio
async def test_validation_error_routes_to_dead_letter() -> None:
    """Pydantic ValidationError on malformed payload routes to dead_letter, returns None."""
    settings = _build_settings()
    # current_price="not_a_decimal" will fail Decimal(str("not_a_decimal")) in from_raw
    malformed = [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": "not_a_decimal"}]

    with (
        patch("shortfire.ingest.coingecko.client.write_to_dead_letter", new_callable=AsyncMock) as mock_dl,
        respx.mock(base_url="https://api.coingecko.com/api/v3") as mock,
    ):
        mock.get("/coins/markets").mock(return_value=httpx.Response(200, json=malformed))
        client = CoinGeckoClient(settings)
        result = await client.fetch_coins_markets()
        await client.close()

    # Either the whole list fails schema or per-row parsing fails
    assert result is None or (result is not None and len(result) == 0)
    # dead_letter was called at least once
    assert mock_dl.call_count >= 1


@pytest.mark.asyncio
async def test_fetch_coin_detail_returns_coin_detail_response() -> None:
    """fetch_coin_detail returns CoinDetailResponse with category tuple and genesis_date."""
    from shortfire.ingest.coingecko.schemas import CoinDetailResponse

    settings = _build_settings()
    canned_detail = {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "categories": ["Cryptocurrency", "Proof of Work"],
        "genesis_date": "2009-01-03",
        "market_data": {"current_price": {"usd": 50000}},
    }

    with respx.mock(base_url="https://api.coingecko.com/api/v3") as mock:
        mock.get("/coins/bitcoin").mock(return_value=httpx.Response(200, json=canned_detail))
        client = CoinGeckoClient(settings)
        result = await client.fetch_coin_detail(coin_id="bitcoin")

        # Access inside the with block
        assert len(mock.calls) == 1
        await client.close()

    assert result is not None
    assert isinstance(result, CoinDetailResponse)
    assert "Cryptocurrency" in result.categories
    assert result.genesis_date is not None
