"""CoinGecko Demo-tier httpx client (D-36, D-55, D-56).

Architectural decisions:
  D-36:  CoinGecko tier = Demo, ~$35/mo, 30 req/min actual quota.
  D-55:  CoinGecko is universe-metadata-only — NO minute-cadence calls.
         Endpoints: /coins/markets (daily universe, 250/page) + /coins/{id} (category enrichment).
  D-56:  COINGECKO_LIMITER = 28/60 — 5% headroom under 30 req/min Demo quota.
  D-72:  coingecko_retry — bounded tenacity retry on 5xx + 429 + transport errors.
  T-1-CG-01: API key sent as x-cg-demo-api-key header ONLY — never in URL query.
  T-1-CG-02: Pydantic v2 strict schemas at boundary; extra='allow' for schema drift.
  T-1-CG-03: aiolimiter(28, 60) + bounded tenacity; daily cadence makes DoS risk low.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
import structlog
from pydantic import ValidationError

from shortfire.ingest.coingecko.schemas import CoinDetailResponse, CoinsMarketsRow
from shortfire.ingest.dead_letter.writer import write_to_dead_letter
from shortfire.ingest.rate_limit import COINGECKO_LIMITER
from shortfire.ingest.retry import coingecko_retry
from shortfire.settings.data_platform import DataPlatformSettings

log = structlog.get_logger("ingest.coingecko.client")

_COINGECKO_BASE = "https://api.coingecko.com/api/v3"


class CoinGeckoClient:
    """Concrete CoinGecko Demo-tier client.

    D-36 ~$35/mo Demo; D-56 28/60 limiter; D-55 universe-only (daily cadence).
    One shared httpx.AsyncClient per process — HTTP/2 reduces TLS overhead.
    API key in x-cg-demo-api-key header (T-1-CG-01 — never in URL query).
    """

    def __init__(self, settings: DataPlatformSettings) -> None:
        if settings.coingecko is None:
            raise RuntimeError("DataPlatformSettings.coingecko must be configured for CoinGecko ingest")
        self._api_key = settings.coingecko.api_key.get_secret_value()
        # http2=True requires the 'h2' package (httpx[http2]) — D-50 mirrors Coinglass client shape
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=10.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={
                "x-cg-demo-api-key": self._api_key,  # T-1-CG-01: header only
                "accept": "application/json",
            },
        )

    async def _call(self, endpoint: str, params: dict[str, Any] | None = None) -> Any | None:
        """Internal: rate-limited GET with dead_letter routing on permanent 4xx errors.

        Rate limit (D-56): acquires COINGECKO_LIMITER before sending.
        5xx + 429: raise_for_status() — tenacity retries on these.
        4xx-non-429 (permanent): write_to_dead_letter, return None, NO raise.
        """
        url = f"{_COINGECKO_BASE}{endpoint}"
        async with COINGECKO_LIMITER:
            r = await self._client.get(url, params=params)

        if r.status_code in (429, 500, 502, 503, 504):
            # Retryable errors — raise so tenacity can retry
            r.raise_for_status()

        if r.status_code >= 400:
            # Permanent 4xx (401, 403, 404, etc.) — dead_letter, no retry
            await write_to_dead_letter(
                "coingecko",
                endpoint,
                params.get("id") if params else None,
                r.text[:8000],
                "HTTPStatusError",
                f"HTTP {r.status_code}",
            )
            return None

        return r.json()

    @coingecko_retry
    async def fetch_coins_markets(
        self,
        vs_currency: str = "usd",
        per_page: int = 250,
        page: int = 1,
    ) -> tuple[CoinsMarketsRow, ...] | None:
        """/coins/markets — paginated universe metadata (D-55).

        Returns the top-N USD-volume coins sorted by market_cap_desc.
        Page 1 with per_page=250 covers the ~250-coin active universe for v1.
        If /coins/markets returns >250 results, pagination is available via
        the `page` arg; the daily universe job (plan 01-09) calls page=1 only.

        Returns:
            Tuple of CoinsMarketsRow, or None if the call failed permanently.
        """
        payload = await self._call(
            "/coins/markets",
            params={
                "vs_currency": vs_currency,
                "per_page": per_page,
                "page": page,
                "order": "market_cap_desc",
            },
        )
        if payload is None:
            return None
        try:
            if not isinstance(payload, list):
                raise ValueError(f"Expected list from /coins/markets, got {type(payload).__name__}")
            # cast: r.json() returns Any; isinstance check confirms list at runtime
            payload_list = cast(list[dict[str, Any]], payload)
            rows: tuple[CoinsMarketsRow, ...] = tuple(CoinsMarketsRow.from_raw(raw) for raw in payload_list)
            return rows
        except (ValidationError, ValueError, TypeError) as exc:
            payload_str = str(payload)[:8000]  # type: ignore[reportUnknownArgumentType]
            await write_to_dead_letter(
                "coingecko",
                "/coins/markets",
                None,
                payload_str,
                "ValidationError",
                str(exc)[:2000],
            )
            return None

    @coingecko_retry
    async def fetch_coin_detail(self, coin_id: str) -> CoinDetailResponse | None:
        """/coins/{id} — category + listing_date enrichment for new-symbol detection (D-55).

        Called by the universe-snapshot job (plan 01-09) when a new symbol appears.
        NOT called in the daily universe job (too expensive at 30 req/min Demo quota).

        Returns:
            CoinDetailResponse, or None if the call failed permanently.
        """
        payload = await self._call(
            f"/coins/{coin_id}",
            params={
                "id": coin_id,
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
            },
        )
        if payload is None:
            return None
        try:
            return CoinDetailResponse.from_raw(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            await write_to_dead_letter(
                "coingecko",
                f"/coins/{coin_id}",
                coin_id,
                str(payload)[:8000],
                "ValidationError",
                str(exc)[:2000],
            )
            return None

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient."""
        await self._client.aclose()
