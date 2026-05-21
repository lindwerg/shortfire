"""Trading domain types — Signal, Order, Position.

All types are pure Pydantic v2 BaseModel per D-07/D-08/D-09/D-10/D-11/D-12/D-13/D-14.
Position is the lone frozen=False exception (D-08) — mutable as fills land.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Literal type aliases — D-10 (NOT StrEnum)
# ---------------------------------------------------------------------------

SignalSide = Literal["short", "long"]
SignalKind = Literal["pump_short", "trend_long"]  # extend in Phase 2
OrderIntent = Literal["open", "close"]
OrderType = Literal["market", "limit"]


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------


class Signal(BaseModel):
    """ML-generated trade signal with confidence and optional SHAP attribution.

    Invariants (D-13):
      - ts must be timezone-aware
      - confidence in [0, 1]
    """

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str
    side: SignalSide
    kind: SignalKind
    ts: datetime
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    shap_top: tuple[tuple[str, Decimal], ...] = ()  # D-11: tuple, not list; Phase 4 SHAP attribution

    @model_validator(mode="after")
    def _reject_naive_ts(self) -> Self:
        if self.ts.tzinfo is None:
            raise ValueError("Signal.ts must be timezone-aware (UTC)")
        return self


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


class Order(BaseModel):
    """Exchange order for a futures position.

    Invariants (D-13):
      - ts must be timezone-aware
      - intent='close' implies reduce_only=True (EXEC-02 structural — cannot construct otherwise)
    """

    model_config = ConfigDict(frozen=True, strict=True)

    client_order_id: str
    symbol: str
    intent: OrderIntent
    side: SignalSide
    order_type: OrderType
    quantity: Decimal = Field(gt=Decimal("0"))
    price: Decimal | None = None  # None for market orders
    reduce_only: bool
    ts: datetime

    @model_validator(mode="after")
    def _reject_naive_ts(self) -> Self:
        if self.ts.tzinfo is None:
            raise ValueError("Order.ts must be timezone-aware (UTC)")
        return self

    @model_validator(mode="after")
    def _close_orders_must_be_reduce_only(self) -> Self:
        if self.intent == "close" and not self.reduce_only:
            raise ValueError("Order(intent='close') requires reduce_only=True (EXEC-02)")
        return self


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------


class Position(BaseModel):
    """Mutable state of an open futures position.

    Position is the lone D-08 carve-out: frozen=False because it mutates
    as fills land (event-sourced refactor deferred to Phase 3).
    Timestamp invariants still apply — mutable != exempt from D-12.
    """

    model_config = ConfigDict(frozen=False, strict=True)  # D-08: lone frozen=False

    symbol: str
    side: SignalSide
    qty: Decimal = Field(ge=Decimal("0"))
    avg_entry_price: Decimal = Field(ge=Decimal("0"))
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    opened_ts: datetime
    last_update_ts: datetime

    @model_validator(mode="after")
    def _reject_naive_ts(self) -> Self:
        for field_name, value in (
            ("opened_ts", self.opened_ts),
            ("last_update_ts", self.last_update_ts),
        ):
            if value.tzinfo is None:
                raise ValueError(f"Position.{field_name} must be timezone-aware (UTC)")
        return self
