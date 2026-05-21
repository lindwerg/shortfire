"""Per-symbol L2 top-20 orderbook sampler (D-46).

D-46: watch_order_book(symbol, limit=20) via ccxt Pro; per-symbol async tasks.
Sampling cadence: tier-1=5s (top-50 by volume), tier-2=10s (rest of universe).
Tier assignment is handled by the caller (streams.py) which passes sample_seconds.

D-49: freshness gauge updated on every successful COPY.
Pitfall 27: l2_sample_loop runs under asyncio.TaskGroup in streams.py — one task per symbol.
JSONB decision: bids/asks stored as orjson.dumps([[str(price), str(qty)], ...]).decode()
               so asyncpg can encode them as TEXT that PostgreSQL casts to JSONB.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import orjson
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.base import ts_from_ms
from shortfire.ingest.dead_letter.writer import write_to_dead_letter
from shortfire.ingest.mexc.client import MexcClient
from shortfire.ingest.storage.copy import copy_into_hypertable
from shortfire.observability.metrics_data_platform import build_data_platform_metrics

log = structlog.get_logger("ingest.mexc.orderbook")


async def l2_sample_loop(
    engine: AsyncEngine,
    mexc_client: MexcClient,
    symbol: str,
    sample_seconds: float,
) -> None:
    """Per-symbol L2 top-20 sampler with configurable cadence (D-46).

    Tier-1 symbols (top-50 by 7d volume) use sample_seconds=5.0.
    Tier-2 symbols (rest of qualifying universe) use sample_seconds=10.0.
    Tier assignment is the caller's responsibility (streams.py).

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        mexc_client: MexcClient; ws_client property used for watch_order_book.
        symbol: ccxt-unified swap symbol to watch.
        sample_seconds: Minimum seconds between L2 record writes.
    """
    log.info("ws.connected", source="mexc_native", stream="l2", symbol=symbol)
    metrics = build_data_platform_metrics()
    raw = mexc_client.ws_client  # ccxt.pro.mexc instance
    last_emit = 0.0  # monotonic timestamp of last successful COPY

    try:
        while True:
            try:
                book: dict[str, Any] = await raw.watch_order_book(symbol, limit=20)
            except Exception as exc:
                metrics.ws_reconnects_total.labels(source="mexc_native", stream="l2").inc()
                log.warning(
                    "ws.reconnect",
                    source="mexc_native",
                    stream="l2",
                    symbol=symbol,
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(2.0)
                continue

            now = time.monotonic()
            if now - last_emit < sample_seconds:
                # Cadence not elapsed — discard this snapshot
                continue

            last_emit = now

            try:
                ts = ts_from_ms(book["timestamp"]) if book.get("timestamp") else datetime.now(UTC)
                # JSONB encoding: orjson serializes to bytes, decode to str for asyncpg TEXT→JSONB cast
                bids_json = orjson.dumps([[str(b[0]), str(b[1])] for b in book["bids"][:20]]).decode()
                asks_json = orjson.dumps([[str(a[0]), str(a[1])] for a in book["asks"][:20]]).decode()

                record = (symbol, ts, bids_json, asks_json, "mexc_native", "ok")

                await copy_into_hypertable(
                    engine,
                    "raw_mexc_l2_top20",
                    [record],
                    columns=("symbol", "ts", "bids", "asks", "source", "quality_flag"),
                    conflict_columns=("symbol", "ts"),
                )
                metrics.source_freshness_seconds.labels(
                    source="mexc_native", dataset="l2_top20", symbol=symbol
                ).set(time.time())
                metrics.ingest_rows_total.labels(source="mexc_native", dataset="l2_top20").inc()

            except Exception as exc:
                await write_to_dead_letter(
                    "mexc_native",
                    "watch_order_book",
                    symbol,
                    "",
                    type(exc).__name__,
                    str(exc)[:2000],
                )

    finally:
        log.info("ws.disconnected", source="mexc_native", stream="l2", symbol=symbol)
