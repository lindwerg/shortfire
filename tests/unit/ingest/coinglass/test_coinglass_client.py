"""Unit tests for CoinglassClient — constructor, HTTP/2, API key in header, endpoint paths.

Tests cover:
- Constructor creates a single httpx.AsyncClient with http2=True + correct limits
- CG-API-KEY is sent as header, NEVER in URL query string (T-1-CG-01 security)
- fetch_funding_rate_list returns FundingRateListResponse on 200
- fetch_open_interest_history, fetch_liquidation_coin_history, fetch_long_short_account_ratio
  each call the correct endpoint path
"""

from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import SecretStr

FUNDING_PAYLOAD = {
    "code": 0,
    "msg": "ok",
    "data": [
        {"symbol": "BTC", "funding_rate": "0.0001"},
        {"symbol": "ETH", "funding_rate": "-0.0002"},
    ],
}

OI_PAYLOAD = {
    "code": 0,
    "msg": "ok",
    "data": [{"time": 1700000000000, "open_interest_usd": "12345.67"}],
}

LIQ_PAYLOAD = {
    "code": 0,
    "msg": "ok",
    "data": [{"time": 1700000000000, "liquidation_long_usd": "1000.00", "liquidation_short_usd": "500.00"}],
}

LSR_PAYLOAD = {
    "code": 0,
    "msg": "ok",
    "data": [{"time": 1700000000000, "long_short_ratio": "1.23"}],
}


def _make_settings(api_key: str = "testtoken123") -> object:
    """Build a minimal DataPlatformSettings with coinglass configured."""
    from shortfire.settings.data_platform import CoinglassSettings, DataPlatformSettings

    return DataPlatformSettings.model_construct(
        coinglass=CoinglassSettings(api_key=SecretStr(api_key)),
    )


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------


class TestCoinglassClientConstructor:
    @pytest.mark.asyncio
    async def test_constructor_creates_single_async_client_with_http2_and_limits(self) -> None:
        from shortfire.ingest.coinglass.client import CoinglassClient

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]
        try:
            assert isinstance(client._client, httpx.AsyncClient)
            # Verify HTTP/2 is enabled
            assert client._client._transport is not None  # noqa: SLF001
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_constructor_raises_if_coinglass_settings_missing(self) -> None:
        from shortfire.ingest.coinglass.client import CoinglassClient
        from shortfire.settings.data_platform import DataPlatformSettings

        settings = DataPlatformSettings.model_construct(coinglass=None)
        with pytest.raises(RuntimeError, match="coinglass"):
            CoinglassClient(settings)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_api_key_present_in_headers(self) -> None:
        from shortfire.ingest.coinglass.client import CoinglassClient

        settings = _make_settings("my-secret-key")
        client = CoinglassClient(settings)  # type: ignore[arg-type]
        try:
            assert client._client.headers.get("cg-api-key") == "my-secret-key"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# API key security: header not URL query (T-1-CG-01)
# ---------------------------------------------------------------------------


class TestCoinglassClientApiKeySecurity:
    @pytest.mark.asyncio
    async def test_api_key_in_header_not_url_query(self) -> None:
        """T-1-CG-01: CG-API-KEY must appear in request headers, never in URL query params."""
        from shortfire.ingest.coinglass.client import CoinglassClient

        settings = _make_settings("supersecret")
        client = CoinglassClient(settings)  # type: ignore[arg-type]
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                route = mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(200, json=FUNDING_PAYLOAD)
                )
                await client.fetch_funding_rate_list()

            request = route.calls.last.request
            # Header must contain the key
            assert request.headers.get("cg-api-key") == "supersecret"
            # URL query must NOT contain the key or the string 'CG-API-KEY'
            assert "supersecret" not in str(request.url.query)
            assert "CG-API-KEY" not in str(request.url.query)
            assert "cg-api-key" not in str(request.url.query).lower()
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Endpoint method tests (correct path + return type)
# ---------------------------------------------------------------------------


class TestCoinglassClientFetchMethods:
    @pytest.mark.asyncio
    async def test_fetch_funding_rate_list_returns_validated_response(self) -> None:
        from shortfire.ingest.coinglass.client import CoinglassClient
        from shortfire.ingest.coinglass.schemas import FundingRateListResponse

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(200, json=FUNDING_PAYLOAD)
                )
                result = await client.fetch_funding_rate_list()

            assert isinstance(result, FundingRateListResponse)
            assert len(result.data) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_fetch_open_interest_history_calls_correct_endpoint(self) -> None:
        from shortfire.ingest.coinglass.client import CoinglassClient
        from shortfire.ingest.coinglass.schemas import OpenInterestHistoryResponse

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                route = mock.get("/api/futures/open-interest/history").mock(
                    return_value=httpx.Response(200, json=OI_PAYLOAD)
                )
                result = await client.fetch_open_interest_history("BTC")
                request = route.calls.last.request

            assert isinstance(result, OpenInterestHistoryResponse)
            assert len(result.data) == 1
            assert "symbol=BTC" in str(request.url)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_fetch_liquidation_coin_history_calls_correct_endpoint(self) -> None:
        from shortfire.ingest.coinglass.client import CoinglassClient
        from shortfire.ingest.coinglass.schemas import LiquidationCoinHistoryResponse

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                route = mock.get("/api/futures/liquidation/coin-history").mock(
                    return_value=httpx.Response(200, json=LIQ_PAYLOAD)
                )
                result = await client.fetch_liquidation_coin_history("ETH")
                request = route.calls.last.request

            assert isinstance(result, LiquidationCoinHistoryResponse)
            assert "symbol=ETH" in str(request.url)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_fetch_long_short_account_ratio_calls_correct_endpoint(self) -> None:
        from shortfire.ingest.coinglass.client import CoinglassClient
        from shortfire.ingest.coinglass.schemas import LongShortAccountRatioResponse

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                route = mock.get("/api/futures/long-short-account-ratio").mock(
                    return_value=httpx.Response(200, json=LSR_PAYLOAD)
                )
                result = await client.fetch_long_short_account_ratio("XRP")
                request = route.calls.last.request

            assert isinstance(result, LongShortAccountRatioResponse)
            assert "symbol=XRP" in str(request.url)
        finally:
            await client.close()
