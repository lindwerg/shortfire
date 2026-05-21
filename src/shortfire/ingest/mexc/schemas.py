"""Pydantic v2 strict schemas for MEXC wire format → domain type adapters.

Each schema validates a ccxt-normalized MEXC response row and provides a
to_domain() method that constructs the canonical domain type.

Decisions honored:
  D-44: dual timestamps for funding (published_ts from 'timestamp', settlement_ts from
        'fundingTimestamp') — both must be captured per Pitfall 2/16
  D-59: source='mexc_native' on every row
  Pitfall 2: published vs settlement ambiguity mitigated by capturing both fields
  Pitfall 17: all ts conversions use fromtimestamp(..., tz=timezone.utc) — never naive

Schema shapes (ccxt 4.5.x unified format):
  OHLCV:   [ts_ms, open, high, low, close, volume] — list/tuple, 6 elements
  Funding: {timestamp, fundingTimestamp, fundingRate, symbol, ...}
  OI:      {timestamp, openInterestAmount, openInterestValue, symbol, ...}
  Trades:  {id, timestamp, side, price, amount, symbol, ...}
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from shortfire.domain.market import Candle, Funding


class MexcOhlcvRow(BaseModel):
    """Pydantic v2 schema for a single ccxt OHLCV array row from MEXC REST.

    ccxt returns: [ts_ms, open, high, low, close, volume]
    Use from_ccxt_row() classmethod to construct from the raw list form.

    D-59: to_domain() sets source='mexc_native'.
    Pitfall 17: ts is tz-aware UTC, constructed via fromtimestamp(..., tz=timezone.utc).
    """

    model_config = ConfigDict(frozen=True, strict=True, populate_by_name=True)

    symbol: str
    timeframe: str
    ts_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @classmethod
    def from_ccxt_row(cls, row: list[Any], *, symbol: str, timeframe: str) -> MexcOhlcvRow:
        """Construct from a 6-element ccxt OHLCV array [ts_ms, o, h, l, c, v].

        Raises ValidationError if any numeric field is not Decimal-coercible.
        """
        if len(row) < 6:
            raise ValueError(f"OHLCV row must have 6 elements, got {len(row)}: {row!r}")
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            ts_ms=int(row[0]),
            open=Decimal(str(row[1])),
            high=Decimal(str(row[2])),
            low=Decimal(str(row[3])),
            close=Decimal(str(row[4])),
            volume=Decimal(str(row[5])),
        )

    def to_domain(self) -> Candle:
        """Convert to canonical Candle domain type with source='mexc_native'.

        Constructs a tz-aware UTC datetime from ts_ms.
        Domain invariants (low <= open,close <= high; tz-aware ts) fire here.
        """
        return Candle(
            symbol=self.symbol,
            source="mexc_native",
            timeframe=self.timeframe,  # type: ignore[arg-type]
            ts=datetime.fromtimestamp(self.ts_ms / 1000, tz=UTC),
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


class MexcFundingRow(BaseModel):
    """Pydantic v2 schema for a ccxt funding rate history entry from MEXC REST.

    ccxt unified funding rate response fields:
      timestamp:       int (ms) — when this record was published (published_ts)
      fundingTimestamp: int (ms) — when the funding rate will be applied (settlement_ts)
      fundingRate:     str/Decimal — the rate value
      symbol:          str — trading symbol
      info:            dict | None — raw exchange response (optional)

    D-44: dual-timestamp capture — BOTH published and settlement are stored.
    Pitfall 2: published vs settlement distinction is critical for Phase 2 signal timing.
    """

    model_config = ConfigDict(frozen=True, strict=True, populate_by_name=True)

    symbol: str
    timestamp: int
    fundingTimestamp: int
    fundingRate: Decimal
    info: dict[str, Any] | None = None

    def to_domain(self) -> Funding:
        """Convert to canonical Funding domain type with source='mexc_native'.

        D-44: published_ts = timestamp field, settlement_ts = fundingTimestamp.
        Domain invariant published_ts <= settlement_ts fires via Funding._published_le_settlement.
        """
        return Funding(
            symbol=self.symbol,
            source="mexc_native",
            published_ts=datetime.fromtimestamp(self.timestamp / 1000, tz=UTC),
            settlement_ts=datetime.fromtimestamp(self.fundingTimestamp / 1000, tz=UTC),
            rate=self.fundingRate,
        )


class MexcOpenInterestRow(BaseModel):
    """Pydantic v2 schema for a ccxt open interest history entry from MEXC REST.

    ccxt unified OI fields:
      timestamp:           int (ms)
      openInterestAmount:  Decimal | None — base currency notional
      openInterestValue:   Decimal | None — quote currency notional
      symbol:              str
      info:                dict | None — raw exchange response

    D-45: OI is REST-only for MEXC; no WS streaming.
    D-59: source="mexc_native" on every row.
    """

    model_config = ConfigDict(frozen=True, strict=True, populate_by_name=True)

    source: str = "mexc_native"  # D-59 — hardcoded attribution; never user-supplied
    symbol: str
    timestamp: int
    openInterestAmount: Decimal | None = None
    openInterestValue: Decimal | None = None
    info: dict[str, Any] | None = None

    def to_record(self) -> tuple[str, datetime, Decimal | None, str, str, None]:
        """Return 6-tuple for copy_into_hypertable against raw_mexc_oi.

        Column order: (symbol, ts, open_interest, source, quality_flag, ingested_at)
        ingested_at=None lets the DB DEFAULT now() apply.
        D-59: source='mexc_native'.
        """
        ts = datetime.fromtimestamp(self.timestamp / 1000, tz=UTC)
        return (self.symbol, ts, self.openInterestAmount, self.source, "ok", None)


class MexcTradeRow(BaseModel):
    """Pydantic v2 schema for a ccxt signed trades entry from MEXC REST/WS.

    ccxt unified trade fields:
      id:        str — exchange trade ID (stable per D-47)
      timestamp: int (ms)
      side:      Literal["buy", "sell"]
      price:     Decimal
      amount:    Decimal
      symbol:    str

    D-47: exchange_trade_id from 'id' field is stable for MEXC ccxt 4.5.
    D-59: source="mexc_native" on every row.
    """

    model_config = ConfigDict(frozen=True, strict=True, populate_by_name=True)

    source: str = "mexc_native"  # D-59 — hardcoded attribution; never user-supplied
    symbol: str
    id: str
    timestamp: int
    side: Literal["buy", "sell"]
    price: Decimal
    amount: Decimal

    def to_record(self) -> tuple[str, datetime, str, str, Decimal, Decimal, str, str, None]:
        """Return 9-tuple for copy_into_hypertable against raw_mexc_trades.

        Column order: (symbol, ts, exchange_trade_id, side, price, qty, source, quality_flag, ingested_at)
        D-47: exchange_trade_id uses the stable ccxt 'id' field.
        D-59: source='mexc_native'.
        """
        ts = datetime.fromtimestamp(self.timestamp / 1000, tz=UTC)
        return (self.symbol, ts, self.id, self.side, self.price, self.amount, self.source, "ok", None)
