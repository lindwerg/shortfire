"""Signed trades tape persister — 1-minute batched COPY into raw_mexc_trades.

D-47: watch_trades_for_symbols consumed; raw trades persisted in 1-minute batches.
D-49: freshness gauge updated on every successful write.
Pitfall 27: trades_persist_loop always runs under asyncio.TaskGroup in streams.py.

Note on dual consumption: both trades_aggregator_loop (live_candles.py) and
trades_persist_loop consume watch_trades_for_symbols. ccxt Pro caches the
underlying ws stream, so duplicate consumers are cheap. If the duplication cost
becomes non-trivial, merge into a single consumer that fans out. Documented in
01-08-SUMMARY.md for the next plan to decide.
"""

from __future__ import annotations

import asyncio
import time
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

log = structlog.get_logger("ingest.mexc.trades")


async def trades_persist_loop(
    engine: AsyncEngine,
    mexc_client: MexcClient,
    symbols: list[str],
    flush_seconds: float = 60.0,
) -> None:
    """Persist raw signed trades tape in 1-minute batches into raw_mexc_trades.

    D-47: trades collected in-memory for ~flush_seconds, then batched COPY.
    PK is (symbol, ts, exchange_trade_id) for idempotency (DATA-09).

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        mexc_client: MexcClient wrapping a ccxt.pro.mexc instance.
        symbols: List of ccxt-unified swap symbols to subscribe to.
        flush_seconds: Seconds between batch COPY flushes (default 60s).
    """
    assert_event_registered("ws.connected")
    log.info("ws.connected", source="mexc_native", stream="trades_persist")
    metrics = build_data_platform_metrics()
    raw = mexc_client.ws_client  # ccxt.pro.mexc instance (via ws_client property)
    buffer: list[tuple[Any, ...]] = []
    last_flush = time.monotonic()

    try:
        while True:
            try:
                trades = await raw.watch_trades_for_symbols(symbols)
            except Exception as exc:
                metrics.ws_reconnects_total.labels(source="mexc_native", stream="trades_persist").inc()
                log.warning(
                    "ws.reconnect",
                    source="mexc_native",
                    stream="trades_persist",
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(2.0)
                continue

            for t in trades:
                try:
                    buffer.append(
                        (
                            t["symbol"],
                            ts_from_ms(t["timestamp"]),
                            t["id"],
                            t["side"],
                            Decimal(str(t["price"])),
                            Decimal(str(t["amount"])),
                            "mexc_native",
                            "ok",
                        )
                    )
                except Exception as exc:
                    await write_to_dead_letter(
                        "mexc_native",
                        "trades_persist_loop",
                        t.get("symbol"),
                        str(t)[:8000],
                        type(exc).__name__,
                        str(exc)[:2000],
                    )

            now = time.monotonic()
            if buffer and (now - last_flush >= flush_seconds):
                n = await copy_into_hypertable(
                    engine,
                    "raw_mexc_trades",
                    buffer,
                    columns=(
                        "symbol",
                        "ts",
                        "exchange_trade_id",
                        "side",
                        "price",
                        "qty",
                        "source",
                        "quality_flag",
                    ),
                    conflict_columns=("symbol", "ts", "exchange_trade_id"),
                )
                seen_symbols = {r[0] for r in buffer}
                for sym in seen_symbols:
                    metrics.source_freshness_seconds.labels(
                        source="mexc_native", dataset="trades", symbol=sym
                    ).set(time.time())
                metrics.ingest_rows_total.labels(source="mexc_native", dataset="trades").inc(n)
                buffer.clear()
                last_flush = now

    finally:
        assert_event_registered("ws.disconnected")
        log.info("ws.disconnected", source="mexc_native", stream="trades_persist")
