"""Concrete Coinglass v4 client — httpx-backed, single AsyncClient per process.

D-50: ONE httpx.AsyncClient per process (http2=True; timeout=10.0;
       limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
D-51: Every call goes through COINGLASS_LIMITER (28 req/min, 5% headroom under 30/min Hobbyist quota)
D-52: Pydantic v2 strict schemas decode all wire responses; ValidationError → dead_letter
D-72: Every public method decorated with @coinglass_retry (tenacity: wait_exponential_jitter(1,60),
       stop_after_attempt(5), retry on httpx.HTTPStatusError|httpx.TransportError)
§18 security domain: CG-API-KEY sent as HTTP request header — NEVER in URL query params (T-1-CG-01)

Dead-letter routing invariant (D-52, D-74):
  - Permanent 4xx (non-429) → write_to_dead_letter + return None (do NOT raise — tenacity must not retry)
  - 5xx / 429 / transport error → raise httpx.HTTPStatusError (tenacity will retry)
  - Pydantic ValidationError on 200 → write_to_dead_letter + return None
"""

from __future__ import annotations

import httpx
import structlog
from pydantic import ValidationError

from shortfire.ingest.coinglass.schemas import (
    FundingRateListResponse,
    LiquidationCoinHistoryResponse,
    LongShortAccountRatioResponse,
    OpenInterestHistoryResponse,
)
from shortfire.ingest.dead_letter.writer import write_to_dead_letter
from shortfire.ingest.rate_limit import COINGLASS_LIMITER
from shortfire.ingest.retry import coinglass_retry
from shortfire.settings.data_platform import DataPlatformSettings

log = structlog.get_logger("ingest.coinglass.client")

_COINGLASS_BASE = "https://open-api-v4.coinglass.com"

# 5xx status codes that should raise for tenacity retry
_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class CoinglassClient:
    """Concrete Coinglass v4 client.

    D-50: single httpx.AsyncClient per process.
    D-51: every call throttled via COINGLASS_LIMITER (28/60).
    D-52: Pydantic v2 strict schema validation at boundary.
    D-72: @coinglass_retry on all public methods.
    §18: CG-API-KEY in header, never URL query.
    """

    def __init__(self, settings: DataPlatformSettings) -> None:
        if settings.coinglass is None:
            raise RuntimeError(
                "DataPlatformSettings.coinglass must be configured for ingest. "
                "Set COINGLASS__API_KEY environment variable."
            )
        self._api_key = settings.coinglass.api_key.get_secret_value()
        # D-50: ONE AsyncClient per process; HTTP/2; fixed timeout + connection limits
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=10.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={
                "CG-API-KEY": self._api_key,
                "Accept": "application/json",
            },
        )

    async def _call(self, endpoint: str, params: dict | None = None) -> dict | None:
        """Internal: rate-limited GET with dead_letter on permanent 4xx, raise on 5xx/429.

        D-51: acquired via COINGLASS_LIMITER before every request.
        T-1-CG-01: API key in header, never in params.
        T-1-CG-03: 429 raises httpx.HTTPStatusError so tenacity can retry.

        Returns:
            Parsed JSON dict on success (2xx), or None if permanent 4xx occurred.

        Raises:
            httpx.HTTPStatusError: on 429 or 5xx (tenacity will retry).
            httpx.TransportError: on network failure (tenacity will retry).
        """
        url = f"{_COINGLASS_BASE}{endpoint}"
        async with COINGLASS_LIMITER:
            r = await self._client.get(url, params=params)

        if r.status_code in _RETRY_STATUS_CODES:
            # Raise so tenacity's retry_if_exception_type catches it
            r.raise_for_status()

        if r.status_code >= 400:
            # Permanent 4xx (401, 403, 404, 422…) — dead_letter, no raise
            symbol: str | None = params.get("symbol") if params else None
            await write_to_dead_letter(
                "coinglass_aggregate",
                endpoint,
                symbol,
                r.text[:8000],
                "HTTPStatusError",
                f"HTTP {r.status_code}",
            )
            log.warning(
                "coinglass._call.4xx_dead_lettered",
                endpoint=endpoint,
                status=r.status_code,
            )
            return None

        return r.json()

    @coinglass_retry
    async def fetch_funding_rate_list(self) -> FundingRateListResponse | None:
        """Batch funding-rate-list endpoint (D-53: one call covers all active symbols).

        Returns:
            FundingRateListResponse on success, None on permanent 4xx or schema error.
        """
        endpoint = "/api/futures/funding-rate-list"
        payload = await self._call(endpoint)
        if payload is None:
            return None
        try:
            return FundingRateListResponse.model_validate(payload)
        except ValidationError as exc:
            await write_to_dead_letter(
                "coinglass_aggregate",
                endpoint,
                None,
                str(payload)[:8000],
                "ValidationError",
                str(exc)[:2000],
            )
            return None

    @coinglass_retry
    async def fetch_open_interest_history(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> OpenInterestHistoryResponse | None:
        """Per-symbol open interest history (D-53: round-robin through universe every 5 min).

        Args:
            symbol: Coinglass bare-coin symbol (e.g. "BTC").
            interval: Time interval ("1h", "4h", "1d").

        Returns:
            OpenInterestHistoryResponse on success, None on permanent error.
        """
        endpoint = "/api/futures/open-interest/history"
        payload = await self._call(endpoint, params={"symbol": symbol, "interval": interval})
        if payload is None:
            return None
        try:
            return OpenInterestHistoryResponse.model_validate(payload)
        except ValidationError as exc:
            await write_to_dead_letter(
                "coinglass_aggregate",
                endpoint,
                symbol,
                str(payload)[:8000],
                "ValidationError",
                str(exc)[:2000],
            )
            return None

    @coinglass_retry
    async def fetch_liquidation_coin_history(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> LiquidationCoinHistoryResponse | None:
        """Per-symbol liquidation history (long + short USD amounts per time bucket).

        Args:
            symbol: Coinglass bare-coin symbol (e.g. "BTC").
            interval: Time interval ("1h", "4h", "1d").

        Returns:
            LiquidationCoinHistoryResponse on success, None on permanent error.
        """
        endpoint = "/api/futures/liquidation/coin-history"
        payload = await self._call(endpoint, params={"symbol": symbol, "interval": interval})
        if payload is None:
            return None
        try:
            return LiquidationCoinHistoryResponse.model_validate(payload)
        except ValidationError as exc:
            await write_to_dead_letter(
                "coinglass_aggregate",
                endpoint,
                symbol,
                str(payload)[:8000],
                "ValidationError",
                str(exc)[:2000],
            )
            return None

    @coinglass_retry
    async def fetch_long_short_account_ratio(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> LongShortAccountRatioResponse | None:
        """Per-symbol long/short account ratio history.

        Args:
            symbol: Coinglass bare-coin symbol (e.g. "BTC").
            interval: Time interval ("1h", "4h", "1d").

        Returns:
            LongShortAccountRatioResponse on success, None on permanent error.
        """
        endpoint = "/api/futures/long-short-account-ratio"
        payload = await self._call(endpoint, params={"symbol": symbol, "interval": interval})
        if payload is None:
            return None
        try:
            return LongShortAccountRatioResponse.model_validate(payload)
        except ValidationError as exc:
            await write_to_dead_letter(
                "coinglass_aggregate",
                endpoint,
                symbol,
                str(payload)[:8000],
                "ValidationError",
                str(exc)[:2000],
            )
            return None

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient (call on service shutdown)."""
        await self._client.aclose()
