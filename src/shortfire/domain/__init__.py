"""Domain layer — pure Pydantic v2 types with no I/O dependencies.

8 core types: Candle, OrderBook, OrderBookLevel, Funding, Liquidation, Signal, Order, Position, RiskLimits.

All types are frozen+strict Pydantic v2 BaseModel except Position (frozen=False, strict=True).
Money fields are Decimal — never float (D-09).
Enum-like fields are Literal[...] (D-10).
Timestamps are timezone-aware (D-12).
"""

# Market data types (D-14: market.py)
from shortfire.domain.market import (
    Candle,
    Funding,
    Liquidation,
    LiquidationSide,
    OrderBook,
    OrderBookLevel,
    Source,
    Timeframe,
)

__all__ = [
    # market types
    "Candle",
    "Funding",
    "Liquidation",
    "LiquidationSide",
    "OrderBook",
    "OrderBookLevel",
    "Source",
    "Timeframe",
]
