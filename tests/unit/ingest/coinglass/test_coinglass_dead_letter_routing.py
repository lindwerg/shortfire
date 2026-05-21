"""Unit tests for dead-letter routing in CoinglassClient (D-52, D-74, T-1-CG-03).

Tests cover:
- 4xx-non-429 → write_to_dead_letter called, returns None (no raise, no retry)
- 429 → raises httpx.HTTPStatusError (tenacity will retry), dead_letter NOT called
- ValidationError on 200 → write_to_dead_letter called with error_type="ValidationError", returns None
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from pydantic import SecretStr


def _make_settings(api_key: str = "testtoken") -> object:
    from shortfire.settings.data_platform import CoinglassSettings, DataPlatformSettings

    return DataPlatformSettings.model_construct(
        coinglass=CoinglassSettings(api_key=SecretStr(api_key)),
    )


class TestDeadLetterRouting:
    @pytest.mark.asyncio
    async def test_4xx_non_429_routes_to_dead_letter_and_no_raise(self) -> None:
        """T-1-CG-01 / D-52: 401 → dead_letter, returns None, no exception propagated.

        tenacity must NOT see this error — only 429/5xx/transport should bubble up.
        """
        from shortfire.ingest.coinglass.client import CoinglassClient

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]

        mock_dead_letter = AsyncMock()
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(401, text="Unauthorized")
                )
                with patch(
                    "shortfire.ingest.coinglass.client.write_to_dead_letter",
                    mock_dead_letter,
                ):
                    result = await client.fetch_funding_rate_list()

        finally:
            await client.close()

        # Must return None (not raise)
        assert result is None

        # dead_letter must have been called exactly once
        mock_dead_letter.assert_called_once()
        call_kwargs = mock_dead_letter.call_args

        # Positional or keyword — check core fields
        args = call_kwargs[0] if call_kwargs[0] else []
        kwargs = call_kwargs[1] if call_kwargs[1] else {}

        # error_type must be HTTPStatusError
        error_type = args[4] if len(args) > 4 else kwargs.get("error_type", "")
        assert error_type == "HTTPStatusError"

        # error_msg must contain "HTTP 401"
        error_msg = args[5] if len(args) > 5 else kwargs.get("error_msg", "")
        assert "401" in error_msg

    @pytest.mark.asyncio
    async def test_403_routes_to_dead_letter(self) -> None:
        """403 is also a permanent 4xx (non-429) — must route to dead_letter, not raise."""
        from shortfire.ingest.coinglass.client import CoinglassClient

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]

        mock_dead_letter = AsyncMock()
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(403, text="Forbidden")
                )
                with patch(
                    "shortfire.ingest.coinglass.client.write_to_dead_letter",
                    mock_dead_letter,
                ):
                    result = await client.fetch_funding_rate_list()
        finally:
            await client.close()

        assert result is None
        mock_dead_letter.assert_called_once()
        args = mock_dead_letter.call_args[0]
        assert "403" in (args[5] if len(args) > 5 else mock_dead_letter.call_args[1].get("error_msg", ""))

    @pytest.mark.asyncio
    async def test_429_raises_for_tenacity_retry_dead_letter_not_called(self) -> None:
        """T-1-CG-03: 429 must raise httpx.HTTPStatusError so tenacity can retry.

        dead_letter is NOT called for 429 — that's reserved for permanent failures.
        """
        from shortfire.ingest.coinglass.client import CoinglassClient

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]

        mock_dead_letter = AsyncMock()
        try:
            with (
                respx.mock(base_url="https://open-api-v4.coinglass.com") as mock,
                patch(
                    "shortfire.ingest.coinglass.client.write_to_dead_letter",
                    mock_dead_letter,
                ),
                pytest.raises(httpx.HTTPStatusError),
            ):
                mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(429, text="Too Many Requests")
                )
                # coinglass_retry is bounded (stop_after_attempt=5), so this would
                # retry 5 times and then reraise. We test via _call directly to
                # avoid the full retry loop in unit tests.
                await client._call("/api/futures/funding-rate-list")  # type: ignore[reportPrivateUsage]  # noqa: SLF001
        finally:
            await client.close()

        # dead_letter must NOT have been called for 429
        mock_dead_letter.assert_not_called()

    @pytest.mark.asyncio
    async def test_500_raises_for_tenacity_retry_dead_letter_not_called(self) -> None:
        """5xx must raise so tenacity can retry (transient server error)."""
        from shortfire.ingest.coinglass.client import CoinglassClient

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]

        mock_dead_letter = AsyncMock()
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(500, text="Internal Server Error")
                )
                with (
                    patch(
                        "shortfire.ingest.coinglass.client.write_to_dead_letter",
                        mock_dead_letter,
                    ),
                    pytest.raises(httpx.HTTPStatusError),
                ):
                    await client._call("/api/futures/funding-rate-list")  # type: ignore[reportPrivateUsage]  # noqa: SLF001
        finally:
            await client.close()

        mock_dead_letter.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_error_routes_to_dead_letter_returns_none(self) -> None:
        """D-52: Pydantic ValidationError on 200 → dead_letter with error_type='ValidationError'."""
        from shortfire.ingest.coinglass.client import CoinglassClient

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]

        malformed_payload = {
            "code": 0,
            "msg": "ok",
            "data": [{"symbol": "BTC", "funding_rate": "THIS_IS_NOT_A_NUMBER"}],
        }

        mock_dead_letter = AsyncMock()
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(200, json=malformed_payload)
                )
                with patch(
                    "shortfire.ingest.coinglass.client.write_to_dead_letter",
                    mock_dead_letter,
                ):
                    result = await client.fetch_funding_rate_list()
        finally:
            await client.close()

        # Returns None without raising
        assert result is None

        # dead_letter called with ValidationError
        mock_dead_letter.assert_called_once()
        args = mock_dead_letter.call_args[0]
        error_type = args[4] if len(args) > 4 else mock_dead_letter.call_args[1].get("error_type", "")
        assert error_type == "ValidationError"

    @pytest.mark.asyncio
    async def test_200_with_valid_payload_does_not_call_dead_letter(self) -> None:
        """Sanity: a valid 200 response should not trigger dead_letter at all."""
        from shortfire.ingest.coinglass.client import CoinglassClient

        VALID_PAYLOAD = {
            "code": 0,
            "msg": "ok",
            "data": [{"symbol": "BTC", "funding_rate": "0.0001"}],
        }

        settings = _make_settings()
        client = CoinglassClient(settings)  # type: ignore[arg-type]

        mock_dead_letter = AsyncMock()
        try:
            with respx.mock(base_url="https://open-api-v4.coinglass.com") as mock:
                mock.get("/api/futures/funding-rate-list").mock(
                    return_value=httpx.Response(200, json=VALID_PAYLOAD)
                )
                with patch(
                    "shortfire.ingest.coinglass.client.write_to_dead_letter",
                    mock_dead_letter,
                ):
                    result = await client.fetch_funding_rate_list()
        finally:
            await client.close()

        assert result is not None
        mock_dead_letter.assert_not_called()
