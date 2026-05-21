"""Market data domain types — Candle, OrderBookLevel, OrderBook, Funding, Liquidation.

All types are pure Pydantic v2 BaseModel with frozen=True and strict=True (D-07, D-08).
Money fields use Decimal exclusively — no float (D-09).
Enum-like fields use Literal[...] (D-10).
Collection fields on frozen models use tuple[X, ...] not list[X] (D-11).
Timestamps reject naive datetime via @model_validator(mode='after') (D-12).
Construction-time invariants per D-13.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Literal type aliases — D-10 (NOT StrEnum)
# ---------------------------------------------------------------------------

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
Source = Literal["mexc", "coinglass", "coingecko"]
LiquidationSide = Literal["short", "long"]


# ---------------------------------------------------------------------------
# Candle
# ---------------------------------------------------------------------------


class Candle(BaseModel):
    """OHLCV candlestick for a single timeframe bucket.

    Invariants (D-13):
      - ts must be timezone-aware
      - low <= open, close <= high
    """

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str
    source: Source
    timeframe: Timeframe
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Field(ge=Decimal("0"))

    @model_validator(mode="after")
    def _reject_naive_ts(self) -> Self:
        if self.ts.tzinfo is None:
            raise ValueError("Candle.ts must be timezone-aware (UTC)")
        return self

    @model_validator(mode="after")
    def _low_le_extremes_le_high(self) -> Self:
        if not (
            self.low <= self.open
            and self.low <= self.close
            and self.open <= self.high
            and self.close <= self.high
        ):
            raise ValueError(
                "Candle invariant violated: low <= open,close <= high "
                f"(low={self.low}, open={self.open}, close={self.close}, high={self.high})"
            )
        return self


# ---------------------------------------------------------------------------
# OrderBook
# ---------------------------------------------------------------------------


class OrderBookLevel(BaseModel):
    """Single price level in an order book.

    Fields must be strictly positive (D-13: price > 0, qty > 0).
    """

    model_config = ConfigDict(frozen=True, strict=True)

    price: Decimal = Field(gt=Decimal("0"))
    qty: Decimal = Field(gt=Decimal("0"))


class OrderBook(BaseModel):
    """Level-2 order book snapshot.

    Invariants (D-13):
      - ts must be timezone-aware
      - bids descending by price
      - asks ascending by price
      - not crossed (bids[0].price < asks[0].price)
    """

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str
    source: Source
    ts: datetime
    bids: tuple[OrderBookLevel, ...]  # D-11: tuple, not list
    asks: tuple[OrderBookLevel, ...]  # D-11: tuple, not list

    @model_validator(mode="after")
    def _reject_naive_ts(self) -> Self:
        if self.ts.tzinfo is None:
            raise ValueError("OrderBook.ts must be timezone-aware (UTC)")
        return self

    @model_validator(mode="after")
    def _bids_descending(self) -> Self:
        for i in range(1, len(self.bids)):
            if self.bids[i].price >= self.bids[i - 1].price:
                raise ValueError(
                    "OrderBook invariant violated: bids must be strictly descending by price "
                    f"(bids[{i - 1}].price={self.bids[i - 1].price}, bids[{i}].price={self.bids[i].price})"
                )
        return self

    @model_validator(mode="after")
    def _asks_ascending(self) -> Self:
        for i in range(1, len(self.asks)):
            if self.asks[i].price <= self.asks[i - 1].price:
                raise ValueError(
                    "OrderBook invariant violated: asks must be strictly ascending by price "
                    f"(asks[{i - 1}].price={self.asks[i - 1].price}, asks[{i}].price={self.asks[i].price})"
                )
        return self

    @model_validator(mode="after")
    def _not_crossed(self) -> Self:
        if self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            raise ValueError(
                "OrderBook invariant violated: book is crossed "
                f"(best_bid={self.bids[0].price} >= best_ask={self.asks[0].price})"
            )
        return self


# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------


class Funding(BaseModel):
    """Perpetual futures funding rate event.

    Invariants (D-13):
      - published_ts, settlement_ts, next_funding_ts (if set) must be timezone-aware
      - published_ts <= settlement_ts
    """

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str
    source: Source
    published_ts: datetime
    settlement_ts: datetime
    rate: Decimal  # can be negative — no Field constraint
    next_funding_ts: datetime | None = None

    @model_validator(mode="after")
    def _reject_naive_ts(self) -> Self:
        for field_name, value in (
            ("published_ts", self.published_ts),
            ("settlement_ts", self.settlement_ts),
        ):
            if value.tzinfo is None:
                raise ValueError(f"Funding.{field_name} must be timezone-aware (UTC)")
        if self.next_funding_ts is not None and self.next_funding_ts.tzinfo is None:
            raise ValueError("Funding.next_funding_ts must be timezone-aware (UTC)")
        return self

    @model_validator(mode="after")
    def _published_le_settlement(self) -> Self:
        if self.published_ts > self.settlement_ts:
            raise ValueError(
                "Funding invariant violated: published_ts must be <= settlement_ts "
                f"(published_ts={self.published_ts}, settlement_ts={self.settlement_ts})"
            )
        return self


# ---------------------------------------------------------------------------
# Liquidation
# ---------------------------------------------------------------------------


class Liquidation(BaseModel):
    """Forced liquidation event on a perpetual futures position.

    Invariants (D-13):
      - ts must be timezone-aware
      - qty > 0, price > 0
    """

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str
    source: Source
    ts: datetime
    side: LiquidationSide
    qty: Decimal = Field(gt=Decimal("0"))
    price: Decimal = Field(gt=Decimal("0"))

    @model_validator(mode="after")
    def _reject_naive_ts(self) -> Self:
        if self.ts.tzinfo is None:
            raise ValueError("Liquidation.ts must be timezone-aware (UTC)")
        return self
