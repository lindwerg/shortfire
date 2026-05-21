"""CoinGecko v3 response schemas — Pydantic v2 strict (D-52, D-55, D-57).

Two schemas for the two endpoints used in Phase 1:
  - CoinsMarketsRow  — one item from /coins/markets (daily universe snapshot)
  - CoinDetailResponse — /coins/{id} detail for category + listing_date enrichment (D-55)

Design choices:
  D-52 Pydantic v2 strict=True: rejects type coercions at validation time.
  Pitfall G extra='allow': CoinGecko occasionally adds fields; unknown extras pass through
    without breaking ingest. Required-field renames → ValidationError → dead_letter.
  D-57 raw_payload JSONB: full wire payload retained for Phase 2 EDA / forensic replay.
  T-1-CG-04 source attribution: 'coingecko' literal hardcoded in to_record, never from wire.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import orjson
from pydantic import BaseModel, ConfigDict
from pydantic import TypeAdapter as _TypeAdapter

# Lenient adapters for pre-processing wire values before strict model_validate
_datetime_adapter: _TypeAdapter[datetime] = _TypeAdapter(datetime)
_date_adapter: _TypeAdapter[date] = _TypeAdapter(date)


class CoinsMarketsRow(BaseModel):
    """One row from /coins/markets endpoint.

    Pitfall G extra='allow' for forward-compat — CoinGecko adds fields without notice.
    strict=True ensures numeric strings don't silently coerce to Decimal.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="allow")

    id: str
    symbol: str  # bare-coin form e.g. "btc" — to_record uppercases for DB
    name: str
    current_price: Decimal | None = None
    market_cap: Decimal | None = None
    total_volume: Decimal | None = None
    last_updated: datetime | None = None
    raw_payload: dict[str, Any] | None = None  # full wire payload retained for forensics

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> CoinsMarketsRow:
        """Construct from /coins/markets row, retaining raw_payload.

        Picks only the known fields for strict validation; extra unknown fields
        are handled by extra='allow' on the pydantic model level.
        Pre-converts numeric fields to Decimal so strict=True is satisfied
        (CoinGecko JSON returns float/int; strict mode rejects implicit coercion).
        """
        _decimal_fields = ("current_price", "market_cap", "total_volume")
        data: dict[str, Any] = {}
        for k in ("id", "symbol", "name", "current_price", "market_cap", "total_volume", "last_updated"):
            if k not in raw:
                continue
            v = raw[k]
            if k in _decimal_fields and v is not None:
                # strict=True rejects float/int → Decimal coercion; pre-convert via str round-trip.
                # Wrap in ValueError so callers catch a consistent exception type.
                try:
                    data[k] = Decimal(str(v))
                except Exception as exc:
                    raise ValueError(f"Cannot convert {k}={v!r} to Decimal: {exc}") from exc
            elif k == "last_updated" and isinstance(v, str):
                # strict=True rejects str → datetime; pre-parse with lenient adapter
                data[k] = _datetime_adapter.validate_python(v)
            else:
                data[k] = v
        return cls.model_validate({**data, "raw_payload": raw})

    def to_record(self, ts: datetime, symbol_unified: str | None = None) -> tuple[Any, ...]:
        """Build the 10-tuple for raw_coingecko_market INSERT.

        Column order matches migration 0010:
          (symbol, ts, price_usd, volume_24h_usd, market_cap_usd, category,
           listing_date, raw_payload, source, quality_flag)

        Args:
            ts: Snapshot timestamp — caller passes datetime.now(timezone.utc) for the daily run.
                All rows in one daily batch share the same ts for consistent snapshots.
            symbol_unified: Optional override — if None, bare-coin symbol is uppercased.
                Caller may pass 'BTC/USDT:USDT' for the full unified form.

        Returns:
            10-tuple ready for copy_into_hypertable.
        """
        sym = symbol_unified or self.symbol.upper()
        return (
            sym,  # symbol
            ts,  # ts
            self.current_price,  # price_usd
            self.total_volume,  # volume_24h_usd
            self.market_cap,  # market_cap_usd
            None,  # category — CoinDetailResponse enrichment (not available from /coins/markets)
            None,  # listing_date — CoinDetailResponse enrichment
            # raw_payload: asyncpg binary COPY requires JSON string, not dict (T-1-CG-05)
            orjson.dumps(self.raw_payload).decode() if self.raw_payload is not None else None,
            "coingecko",  # source — T-1-CG-04: always literal, never from wire
            "ok",  # quality_flag
        )


class CoinDetailResponse(BaseModel):
    """/coins/{id} response — used for listing_date + category enrichment (D-55).

    Phase 1: fetch_coin_detail is available on CoinGeckoClient but the daily
    universe job (plan 01-07) does NOT call it per-coin (too many API calls for
    30 req/min Demo quota). Category/listing_date enrichment is deferred to
    the new-symbol detection job in plan 01-09.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="allow")

    id: str
    symbol: str
    name: str
    categories: tuple[str, ...] = ()
    genesis_date: date | None = None  # CoinGecko's "listing_date" equivalent (D-55)
    market_data: dict[str, Any] | None = None
    raw_payload: dict[str, Any] | None = None  # retained for Phase 2 forensic replay

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> CoinDetailResponse:
        """Construct from /coins/{id} response, filtering None from categories.

        Pre-converts genesis_date string to date object for strict=True compatibility.
        """
        data: dict[str, Any] = {
            k: raw[k]
            for k in ("id", "symbol", "name", "categories", "genesis_date", "market_data")
            if k in raw
        }
        # categories may arrive with None items; filter them out
        if "categories" in data and isinstance(data["categories"], list):
            data["categories"] = tuple(c for c in data["categories"] if c is not None)  # type: ignore[misc]
        # genesis_date arrives as a string; strict=True needs a date object
        if "genesis_date" in data and isinstance(data["genesis_date"], str):
            data["genesis_date"] = _date_adapter.validate_python(data["genesis_date"])
        return cls.model_validate({**data, "raw_payload": raw})
