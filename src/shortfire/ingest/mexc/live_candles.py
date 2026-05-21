"""Client-side 1m candle aggregator from watch_trades stream.

D-43: watch_ohlcv is explicitly BANNED per ccxt#27253 + Pitfall 11.
This module builds 1m candles client-side from the watch_trades stream and COPYs
them into raw_mexc_candles_1m via copy_into_hypertable.

Decisions honored:
  D-43: No watch_ohlcv; MinuteAggregator consumes watch_trades_for_symbols
  D-47: 1-minute batched COPY (flush_seconds parameter)
  D-49: freshness gauge updated on every successful write (gauge stores time.time())
  Pitfall 27: this coroutine is always managed by asyncio.TaskGroup in streams.py —
              never spawned with bare asyncio.create_task
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.base import ts_from_ms
from shortfire.ingest.dead_letter.writer import write_to_dead_letter
from shortfire.ingest.mexc.client import MexcClient
from shortfire.ingest.storage.copy import copy_into_hypertable
from shortfire.observability.events import assert_event_registered
from shortfire.observability.metrics_data_platform import build_data_platform_metrics

log = structlog.get_logger("ingest.mexc.live_candles")


class MinuteAggregator:
    """Client-side 1m candle aggregator from a watch_trades stream (D-43, ccxt#27253 mitigation).

    State machine per symbol:
      - on_trade() updates the partial bucket for the trade's minute
      - When a trade arrives in the NEXT minute, the previous partial bucket is finalized
        and returned; the new partial is started
      - The last partial is NOT emitted until a trade in a subsequent minute arrives

    Thread-safety: not thread-safe; intended for single-coroutine use within TaskGroup.
    """

    def __init__(self) -> None:
        # symbol → partial bucket dict {ts, open, high, low, close, volume}
        self._partial: dict[str, dict[str, Any]] = {}

    def on_trade(
        self,
        symbol: str,
        ts: datetime,
        price: Decimal,
        qty: Decimal,
    ) -> dict[str, Any] | None:
        """Update aggregator with one trade; return a FINALIZED 1m bucket if minute rolled over.

        Args:
            symbol: ccxt-unified swap symbol (e.g. 'BTC/USDT:USDT')
            ts: Tz-aware UTC datetime of the trade
            price: Trade price as Decimal
            qty: Trade quantity as Decimal

        Returns:
            dict with keys (ts, open, high, low, close, volume) if minute boundary crossed;
            None if still building the current partial bucket.
        """
        # Snap to minute boundary (strip seconds/microseconds)
        bucket_ts = ts.replace(second=0, microsecond=0)

        if symbol not in self._partial:
            # First trade for this symbol — start a new partial
            self._partial[symbol] = {
                "ts": bucket_ts,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }
            return None

        cur = self._partial[symbol]
        if bucket_ts != cur["ts"]:
            # Minute rolled over — finalize the previous partial and start a new one
            finalized = dict(cur)  # shallow copy is sufficient (all scalars)
            self._partial[symbol] = {
                "ts": bucket_ts,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }
            return finalized

        # Same minute — update the running partial bucket (immutable Decimal; reassign)
        updated_high = price if price > cur["high"] else cur["high"]
        updated_low = price if price < cur["low"] else cur["low"]
        self._partial[symbol] = {
            "ts": cur["ts"],
            "open": cur["open"],
            "high": updated_high,
            "low": updated_low,
            "close": price,
            "volume": cur["volume"] + qty,
        }
        return None


async def trades_aggregator_loop(
    engine: AsyncEngine,
    mexc_client: MexcClient,
    symbols: list[str],
    flush_seconds: float = 60.0,
) -> None:
    """Read MEXC trade tape, aggregate into 1m candles, COPY in batches.

    D-43: watch_ohlcv is banned (ccxt#27253). This loop is the live source for
    raw_mexc_candles_1m.
    D-47: 1-minute batched COPY (flush_seconds=60.0 default).
    D-49: every successful write updates the freshness gauge with time.time() (unix).
    Pitfall 27: this coroutine is always run under asyncio.TaskGroup in streams.py.

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        mexc_client: MexcClient wrapping a ccxt.pro.mexc instance.
        symbols: List of ccxt-unified swap symbols to aggregate.
        flush_seconds: Seconds between batch COPY flushes (default 60s).
    """
    assert_event_registered("ws.connected")
    log.info("ws.connected", source="mexc_native", stream="trades_aggregator")
    agg = MinuteAggregator()
    buffer: list[tuple[Any, ...]] = []
    last_flush = time.monotonic()
    metrics = build_data_platform_metrics()
    raw = mexc_client.ws_client  # ccxt.pro.mexc instance (via ws_client property)

    try:
        while True:
            try:
                trades = await raw.watch_trades_for_symbols(symbols)
            except Exception as exc:
                metrics.ws_reconnects_total.labels(source="mexc_native", stream="trades_aggregator").inc()
                log.warning(
                    "ws.reconnect",
                    source="mexc_native",
                    stream="trades_aggregator",
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(2.0)
                continue

            for t in trades:
                try:
                    ts = ts_from_ms(t["timestamp"])
                    price = Decimal(str(t["price"]))
                    qty = Decimal(str(t["amount"]))
                    fin = agg.on_trade(t["symbol"], ts, price, qty)
                    if fin is not None:
                        buffer.append(
                            (
                                t["symbol"],
                                fin["ts"],
                                fin["open"],
                                fin["high"],
                                fin["low"],
                                fin["close"],
                                fin["volume"],
                                "mexc_native",
                                "ok",
                            )
                        )
                except Exception as exc:
                    await write_to_dead_letter(
                        "mexc_native",
                        "trades_aggregator_loop",
                        t.get("symbol"),
                        str(t)[:8000],
                        type(exc).__name__,
                        str(exc)[:2000],
                    )

            now = time.monotonic()
            if buffer and (now - last_flush >= flush_seconds):
                n = await copy_into_hypertable(
                    engine,
                    "raw_mexc_candles_1m",
                    buffer,
                    columns=(
                        "symbol",
                        "ts",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "source",
                        "quality_flag",
                    ),
                    conflict_columns=("symbol", "ts"),
                )
                seen_symbols = {r[0] for r in buffer}
                for sym in seen_symbols:
                    metrics.source_freshness_seconds.labels(
                        source="mexc_native", dataset="candles_1m", symbol=sym
                    ).set(time.time())
                metrics.ingest_rows_total.labels(source="mexc_native", dataset="candles_1m").inc(n)
                buffer.clear()
                last_flush = now

    finally:
        assert_event_registered("ws.disconnected")
        log.info("ws.disconnected", source="mexc_native", stream="trades_aggregator")
