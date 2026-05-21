"""Concrete MEXC ccxt-backed client satisfying the FOUND-08 MexcClient Protocol.

Decisions honored:
  D-40: defaultType='swap' for perpetual futures; symbol convention BTC/USDT:USDT
  D-41: ccxt >=4.5.54,<4.6 pinned in pyproject.toml
  D-49: freshness contract — tenacity retry covers transient failures
  D-73: aiolimiter MEXC_LIMITER (18 req/s) + ccxt internal throttler (enableRateLimit=True)
        as defense-in-depth — both layers must be satisfied
  Pitfall 8: verbose=False — NEVER log signing material; ccxt verbose mode logs API keys
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import ccxt.pro as ccxtpro
import structlog

from shortfire.domain.market import Candle, Funding, OrderBook, OrderBookLevel
from shortfire.domain.trading import Order
from shortfire.ingest.dead_letter.writer import write_to_dead_letter
from shortfire.ingest.mexc.schemas import MexcFundingRow, MexcOhlcvRow, MexcOpenInterestRow
from shortfire.ingest.rate_limit import MEXC_LIMITER
from shortfire.ingest.retry import mexc_retry
from shortfire.settings.data_platform import DataPlatformSettings

log = structlog.get_logger("ingest.mexc.client")


def build_mexc_swap_client(settings: DataPlatformSettings) -> MexcClient:
    """Factory: construct a MexcClient from DataPlatformSettings.

    D-40: options={'defaultType': 'swap', 'recvWindow': 10000}
    D-41: ccxt >=4.5.54,<4.6 pin
    D-73: enableRateLimit=True (ccxt internal throttler, second layer after MEXC_LIMITER)
    Pitfall 8: verbose=False — never log signing material

    Raises:
        RuntimeError: if settings.mexc is None (credentials not configured).
    """
    if settings.mexc is None:
        raise RuntimeError(
            "DataPlatformSettings.mexc must be configured for live ingest "
            "(set MEXC__READ_KEY + MEXC__READ_SECRET env vars)"
        )
    raw: ccxtpro.mexc = ccxtpro.mexc(  # type: ignore[attr-defined]
        {
            "apiKey": settings.mexc.read_key.get_secret_value(),
            "secret": settings.mexc.read_secret.get_secret_value(),
            "enableRateLimit": True,
            "options": {"defaultType": "swap", "recvWindow": 10000},
        }
    )
    raw.verbose = False  # Pitfall 8 — never log signing material
    return MexcClient(raw)


class MexcClient:
    """Concrete MEXC client satisfying the FOUND-08 MexcClient Protocol.

    Every public async method is wrapped with:
      @mexc_retry — tenacity 6-attempt exponential jitter (D-72)
      async with MEXC_LIMITER — aiolimiter 18 req/s token bucket (D-73)

    Dead-letter routing: any ccxt exception or Pydantic ValidationError from schema
    validation is written to dead_letter via write_to_dead_letter, then the loop
    continues (DATA-11 — validation failure must not crash the ingest loop).
    """

    def __init__(self, raw_client: Any) -> None:
        self._client = raw_client

    @property
    def ws_client(self) -> Any:
        """Expose the underlying ccxt.pro.mexc instance for ws stream operations.

        Used by live-ingest modules (live_candles, funding, trades, orderbook,
        liquidations) to call watch_* methods that are not part of the public
        MexcClient Protocol (plan 01-08, D-43/44/46/47/48).
        """
        return self._client

    @mexc_retry
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]:
        """Fetch up to 1000 OHLCV candles via ccxt REST fetch_ohlcv.

        D-42: limit=1000 per page; cursor advancing handled by backfill.py.
        D-40: symbol must be ccxt-unified form (e.g. 'BTC/USDT:USDT').
        """
        since_ms = int(since.timestamp() * 1000)
        async with MEXC_LIMITER:
            try:
                raw: list[list[Any]] = await self._client.fetch_ohlcv(
                    symbol, timeframe, since=since_ms, limit=1000
                )
            except Exception as exc:
                await write_to_dead_letter(
                    "mexc_native", "fetch_ohlcv", symbol, "", type(exc).__name__, str(exc)
                )
                raise
        candles: list[Candle] = []
        for row in raw:
            try:
                schema = MexcOhlcvRow.from_ccxt_row(row, symbol=symbol, timeframe=timeframe)
                candles.append(schema.to_domain())
            except Exception as exc:
                await write_to_dead_letter(
                    "mexc_native",
                    "fetch_ohlcv",
                    symbol,
                    str(row),
                    type(exc).__name__,
                    str(exc)[:2000],
                )
        return tuple(candles)

    @mexc_retry
    async def fetch_funding_rate_history(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Funding, ...]:
        """Fetch funding rate history via ccxt REST fetch_funding_rate_history.

        D-44: REST historical backfill; live funding via watch_funding_rate (plan 01-08).
        Captures both published_ts (timestamp) and settlement_ts (fundingTimestamp).
        """
        since_ms = int(since.timestamp() * 1000)
        async with MEXC_LIMITER:
            try:
                raw: list[dict[str, Any]] = await self._client.fetch_funding_rate_history(
                    symbol, since=since_ms, limit=1000
                )
            except Exception as exc:
                await write_to_dead_letter(
                    "mexc_native",
                    "fetch_funding_rate_history",
                    symbol,
                    "",
                    type(exc).__name__,
                    str(exc),
                )
                raise
        fundings: list[Funding] = []
        for d in raw:
            try:
                row = MexcFundingRow.model_validate(
                    {
                        "symbol": symbol,
                        "timestamp": d["timestamp"],
                        "fundingTimestamp": d.get("fundingTimestamp", d["timestamp"]),
                        "fundingRate": Decimal(str(d["fundingRate"])),
                        "info": d.get("info"),
                    }
                )
                fundings.append(row.to_domain())
            except Exception as exc:
                await write_to_dead_letter(
                    "mexc_native",
                    "fetch_funding_rate_history",
                    symbol,
                    str(d),
                    type(exc).__name__,
                    str(exc)[:2000],
                )
        return tuple(fundings)

    @mexc_retry
    async def fetch_open_interest_history(
        self,
        symbol: str,
        timeframe: str = "1h",
    ) -> tuple[MexcOpenInterestRow, ...]:
        """Fetch OI history via ccxt REST fetch_open_interest_history.

        D-45: OI is REST-only; no reliable WS stream on MEXC ccxt 4.5.x.
        """
        async with MEXC_LIMITER:
            try:
                raw: list[dict[str, Any]] = await self._client.fetch_open_interest_history(symbol, timeframe)
            except Exception as exc:
                await write_to_dead_letter(
                    "mexc_native",
                    "fetch_open_interest_history",
                    symbol,
                    "",
                    type(exc).__name__,
                    str(exc),
                )
                raise
        rows: list[MexcOpenInterestRow] = []
        for d in raw:
            try:
                rows.append(
                    MexcOpenInterestRow.model_validate(
                        {
                            "symbol": symbol,
                            "timestamp": d["timestamp"],
                            "openInterestAmount": Decimal(str(d.get("openInterestAmount") or "0")),
                            "openInterestValue": Decimal(str(d.get("openInterestValue") or "0")),
                            "info": d.get("info"),
                        }
                    )
                )
            except Exception as exc:
                await write_to_dead_letter(
                    "mexc_native",
                    "fetch_open_interest_history",
                    symbol,
                    str(d),
                    type(exc).__name__,
                    str(exc)[:2000],
                )
        return tuple(rows)

    @mexc_retry
    async def fetch_order_book(
        self,
        symbol: str,
        depth: int = 20,
    ) -> OrderBook:
        """Fetch L2 order book snapshot via ccxt REST fetch_order_book.

        D-46: L2 top-20; WS streaming via watch_order_book is plan 01-08's concern.
        """
        async with MEXC_LIMITER:
            try:
                raw: dict[str, Any] = await self._client.fetch_order_book(symbol, limit=depth)
            except Exception as exc:
                await write_to_dead_letter(
                    "mexc_native",
                    "fetch_order_book",
                    symbol,
                    "",
                    type(exc).__name__,
                    str(exc),
                )
                raise
        ts = (
            datetime.fromtimestamp(raw["timestamp"] / 1000, tz=UTC)
            if raw.get("timestamp")
            else datetime.now(UTC)
        )
        bids = tuple(
            OrderBookLevel(price=Decimal(str(b[0])), qty=Decimal(str(b[1]))) for b in raw["bids"][:depth]
        )
        asks = tuple(
            OrderBookLevel(price=Decimal(str(a[0])), qty=Decimal(str(a[1]))) for a in raw["asks"][:depth]
        )
        return OrderBook(symbol=symbol, source="mexc_native", ts=ts, bids=bids, asks=asks)

    async def place_order(self, order: Order) -> str:
        """Phase 5: trade-key required — data-platform client is read-only."""
        raise NotImplementedError("Phase 5: trade-key required; this is the read-only data-platform client")

    async def cancel_order(self, client_order_id: str) -> None:
        """Phase 5: trade-key required — data-platform client is read-only."""
        raise NotImplementedError("Phase 5: trade-key required; this is the read-only data-platform client")

    async def close(self) -> None:
        """Close the underlying ccxt aiohttp session."""
        await self._client.close()
