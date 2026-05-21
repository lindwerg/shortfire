"""FakeMexcClient — deterministic stub conforming to MexcClient Protocol (FOUND-08, TEST-05).

Phase 0: only fetch_ohlcv + place_order + cancel_order had meaningful bodies.
Phase 1 (plan 01-05): adds deterministic synthetic OHLCV generator + paginated fetch (D-93).

Design choices:
  - with_synthetic_candles(classmethod) is the canonical constructor for integration and
    unit pagination tests. Its exact signature is fixed — 01-11 STOR-08 test consumes it.
  - generate_synthetic_candles(instance method) returns a bare tuple; useful for unit tests
    that need raw Candles without a full FakeMexcClient lifecycle.
  - fetch_ohlcv paginates from _canned_per_symbol[symbol] in 1000-row pages matching
    ccxt's limit=1000 REST behaviour so the backfill cursor-advance logic is exercised.
  - concurrency tracking (max_observed_concurrency) lets tests assert Semaphore cap.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from shortfire.domain.market import Candle, Funding, OrderBook
from shortfire.domain.trading import Order


class FakeMexcClient:
    """Deterministic fake for Phase 0+ unit tests.

    Basic usage (Phase 0 style — backward compatible):
        client = FakeMexcClient(candles=(c1, c2, ...))

    Paginated synthetic usage (Phase 1 — for backfill + integration tests):
        client = FakeMexcClient.with_synthetic_candles(
            symbols=("BTC/USDT:USDT",),
            timeframe="1m",
            since=...,
            until=...,
        )
    """

    def __init__(self, candles: tuple[Candle, ...] = ()) -> None:
        self._candles = candles
        self._placed_orders: list[Order] = []

        # Paginated fetch state — populated by with_synthetic_candles
        self._canned_per_symbol: dict[str, list[Candle]] = {}
        self._page_cursor: dict[str, int] = {}
        self._timeframe: str = "1m"

        # Concurrency probe
        self._in_flight: int = 0
        self.max_observed_concurrency: int = 0

    # -----------------------------------------------------------------------
    # Canonical classmethod constructor (W6 reconciliation — 01-11 STOR-08 test)
    # -----------------------------------------------------------------------

    @classmethod
    def with_synthetic_candles(
        cls,
        *,
        symbols: tuple[str, ...],
        timeframe: str,
        since: datetime,
        until: datetime,
        base_price: Decimal = Decimal("30000"),
    ) -> FakeMexcClient:
        """Construct a FakeMexcClient pre-seeded with deterministic OHLCV.

        Generates exactly ceil((until-since) / timeframe_delta) candles per symbol.
        Candles are consumed in 1000-row pages by fetch_ohlcv to simulate ccxt
        REST pagination behaviour (limit=1000 per D-42).

        Price walk (deterministic): close[i] = base_price + Decimal(i) * Decimal("10");
        high = close + 50; low = close - 50; open = close; volume = 100.
        Every emitted Candle carries source='mexc_native' (D-59).

        Args:
            symbols: Tuple of ccxt-unified swap symbols (D-40).
            timeframe: OHLCV timeframe string — used to compute bucket intervals.
            since: Window start (inclusive), tz-aware UTC.
            until: Window end (exclusive), tz-aware UTC.
            base_price: Starting price for the deterministic walk.

        Returns:
            FakeMexcClient with _canned_per_symbol populated.
        """
        instance = cls()
        instance._timeframe = timeframe
        for sym in symbols:
            instance._canned_per_symbol[sym] = list(
                instance.generate_synthetic_candles(sym, timeframe, since, until, base_price)
            )
            instance._page_cursor[sym] = 0
        return instance

    # -----------------------------------------------------------------------
    # Instance method for raw candle generation (unit test convenience)
    # -----------------------------------------------------------------------

    def generate_synthetic_candles(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
        base_price: Decimal = Decimal("30000"),
    ) -> tuple[Candle, ...]:
        """Generate deterministic synthetic OHLCV candles for [since, until).

        Useful for unit tests that need a raw Candle tuple without a full
        FakeMexcClient paginated lifecycle.

        Timeframe mapping (minutes):
            1m → 1, 5m → 5, 15m → 15, 1h → 60, 4h → 240, 1d → 1440
        """
        _TF_MINUTES: dict[str, int] = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }
        step_minutes = _TF_MINUTES.get(timeframe, 1)
        step = timedelta(minutes=step_minutes)

        candles: list[Candle] = []
        ts = since
        i = 0
        while ts < until:
            close = base_price + Decimal(str(i * 10))
            candles.append(
                Candle(
                    symbol=symbol,
                    source="mexc_native",
                    timeframe=timeframe,  # type: ignore[arg-type]
                    ts=ts,
                    open=close,
                    high=close + Decimal("50"),
                    low=close - Decimal("50"),
                    close=close,
                    volume=Decimal("100"),
                )
            )
            ts += step
            i += 1

        return tuple(candles)

    # -----------------------------------------------------------------------
    # Protocol methods
    # -----------------------------------------------------------------------

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]:
        """Return candles in 1000-row pages from _canned_per_symbol when pre-seeded.

        Falls back to filtering self._candles by symbol and time window for the
        Phase-0-style constructor so existing tests remain unaffected.
        """
        # Concurrency tracking
        self._in_flight += 1
        if self._in_flight > self.max_observed_concurrency:
            self.max_observed_concurrency = self._in_flight

        try:
            if symbol in self._canned_per_symbol:
                # Paginated path — used by backfill tests
                cursor = self._page_cursor.get(symbol, 0)
                page = tuple(self._canned_per_symbol[symbol][cursor : cursor + 1000])
                self._page_cursor[symbol] = cursor + len(page)
                return page
            else:
                # Legacy path — backward compatible with Phase-0 constructor
                return tuple(c for c in self._candles if c.symbol == symbol and since <= c.ts <= until)
        finally:
            self._in_flight -= 1

    async def fetch_funding_rate_history(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Funding, ...]:
        return ()

    async def fetch_order_book(
        self,
        symbol: str,
        depth: int = 20,
    ) -> OrderBook:
        raise NotImplementedError("Phase 1 fills this in")

    @property
    def placed_orders(self) -> list[Order]:
        """Read-only access to recorded orders for test assertions."""
        return self._placed_orders

    async def place_order(self, order: Order) -> str:
        """Record the order and return a deterministic fake exchange order id."""
        self._placed_orders.append(order)
        return f"fake-order-id-{len(self._placed_orders)}"

    async def cancel_order(self, client_order_id: str) -> None:
        return None
