"""Top-level MEXC ws stream orchestrator — mexc_ws_streams async context manager.

Manages all MEXC live-ingest streams under one asyncio.TaskGroup with:
  - Heartbeat watchdog (D-49 point 3): raises RuntimeError after >60s staleness
  - Cross-REST divergence check (D-49 point 4): flags ws_rest_divergence on >0.5% mismatch
  - Reconnect protocol (D-49 points 1+2): each stream loop catches transport exceptions,
    increments ws_reconnects_total, awaits backoff, resumes

D-78: continuous ws tasks live under FastAPI lifespan TaskGroup — separate concern from
       APScheduler-managed cron/interval jobs (OI, universe snapshot, backup).
Pitfall 27: ZERO asyncio.create_task calls without holding reference — all tasks created
             via TaskGroup.create_task.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from shortfire.ingest.mexc.client import MexcClient
from shortfire.ingest.mexc.funding import funding_live_loop
from shortfire.ingest.mexc.liquidations import liquidations_dual_source_loop
from shortfire.ingest.mexc.live_candles import trades_aggregator_loop
from shortfire.ingest.mexc.orderbook import l2_sample_loop
from shortfire.ingest.mexc.trades import trades_persist_loop
from shortfire.observability.events import assert_event_registered
from shortfire.observability.metrics_data_platform import build_data_platform_metrics

log = structlog.get_logger("ingest.mexc.streams")

# D-49 constants — documented as class-level constants for easy tuning
HEARTBEAT_INTERVAL_S: float = 30.0  # D-49 point 3 — check freshness gauge every 30s
HEARTBEAT_TIMEOUT_S: float = 60.0  # D-49 point 3 — respawn trigger after >60s staleness
CROSS_REST_INTERVAL_S: float = 60.0  # D-49 point 4 — REST cross-check every 60s
CROSS_REST_DIVERGENCE_THRESHOLD: Decimal = Decimal("0.005")  # D-49 point 4 — 0.5% mismatch


async def _heartbeat_watchdog(
    mexc_client: MexcClient,
    stream_names: tuple[str, ...],
    shutdown_event: asyncio.Event,
) -> None:
    """D-49 point 3: check freshness gauge every 30s; raise RuntimeError if any stream stale >60s.

    Implementation reads the shortfire_data_platform_source_freshness_seconds Prometheus gauge
    which is updated by each ingest loop on every successful write (D-49). When the gauge
    value is a unix timestamp >60s in the past, the stream is considered stale and the
    watchdog raises RuntimeError to trigger supervisor respawn.

    Args:
        mexc_client: MexcClient (unused directly — reserved for future ccxt last-received probe).
        stream_names: Tuple of dataset names to check (e.g. ('candles_1m', 'funding', ...)).
        shutdown_event: Signal to stop the watchdog loop cleanly on context exit.
    """
    while not shutdown_event.is_set():
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)

        metrics = build_data_platform_metrics()
        now_unix = time.time()

        for metric_family in metrics.source_freshness_seconds.collect():
            for sample in metric_family.samples:
                if sample.labels.get("source") != "mexc_native":
                    continue
                dataset = sample.labels.get("dataset")
                if dataset not in stream_names:
                    continue
                gauge_unix = sample.value
                if gauge_unix <= 0:
                    continue  # sentinel value (e.g. liquidations ws-unavailable path)
                lag_s = now_unix - gauge_unix
                if lag_s > HEARTBEAT_TIMEOUT_S:
                    assert_event_registered("ws.stale")
                    log.error(
                        "ws.stale",
                        source="mexc_native",
                        stream=dataset,
                        lag_s=int(lag_s),
                        threshold_s=int(HEARTBEAT_TIMEOUT_S),
                    )
                    raise RuntimeError(
                        f"mexc_native/{dataset} stale {int(lag_s)}s > {HEARTBEAT_TIMEOUT_S}s — respawn"
                    )


async def _cross_rest_divergence_check(
    engine: AsyncEngine,
    mexc_client: MexcClient,
    tier1_symbols: tuple[str, ...],
    shutdown_event: asyncio.Event,
) -> None:
    """D-49 point 4: every 60s, cross-check one rotating tier-1 symbol's ws-derived close vs REST.

    On >0.5% mismatch, UPDATEs raw_mexc_candles_1m.quality_flag='ws_rest_divergence' for the
    affected bucket. This is the first consumer of the 'ws_rest_divergence' enum value declared
    in migration 0008 (D-60).

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        mexc_client: MexcClient with fetch_ohlcv REST method.
        tier1_symbols: Tuple of tier-1 symbols to rotate through.
        shutdown_event: Signal to stop the check loop cleanly on context exit.
    """
    if not tier1_symbols:
        return

    symbols_list = list(tier1_symbols)
    cursor = 0

    while not shutdown_event.is_set():
        await asyncio.sleep(CROSS_REST_INTERVAL_S)

        sym = symbols_list[cursor % len(symbols_list)]
        cursor += 1

        try:
            now_dt = datetime.now(UTC)
            since_dt = now_dt - timedelta(minutes=3)
            rest_candles = await mexc_client.fetch_ohlcv(sym, "1m", since_dt, now_dt)
            if not rest_candles or len(rest_candles) < 2:
                continue
            # Use second-most-recent candle (most-recent may be partial)
            ref_candle = rest_candles[-2]
            ref_close = ref_candle.close
            ref_bucket = ref_candle.ts.replace(second=0, microsecond=0)

            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT close FROM raw_mexc_candles_1m WHERE symbol=:s AND ts=:ts"),
                        {"s": sym, "ts": ref_bucket},
                    )
                ).first()

            if row is None:
                continue  # ws hasn't written this bucket yet — race condition, skip

            ws_close = Decimal(str(row[0]))
            if ref_close == Decimal("0"):
                continue

            diff = abs(ws_close - ref_close) / ref_close
            if diff > CROSS_REST_DIVERGENCE_THRESHOLD:
                log.warning(
                    "ws.rest.divergence",
                    symbol=sym,
                    bucket=ref_bucket.isoformat(),
                    ws_close=str(ws_close),
                    rest_close=str(ref_close),
                    diff_pct=str(diff),
                )
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE raw_mexc_candles_1m "
                            "SET quality_flag='ws_rest_divergence' "
                            "WHERE symbol=:s AND ts=:ts AND quality_flag='ok'"
                        ),
                        {"s": sym, "ts": ref_bucket},
                    )

        except Exception as exc:
            log.warning("ws.rest.divergence.check_failed", symbol=sym, error_type=type(exc).__name__)


@asynccontextmanager
async def mexc_ws_streams(
    engine: AsyncEngine,
    mexc_client: MexcClient,
    symbols: list[str],
    tier1_symbols: list[str],
    settings: Any = None,
) -> AsyncGenerator[None, None]:
    """Manage all MEXC ws streams under one TaskGroup with heartbeat watchdog + divergence check.

    D-46: per-symbol L2 tasks with tier-1/tier-2 cadences (5s/10s).
    D-49 points 3+4: heartbeat watchdog + cross-REST divergence check as co-managed tasks.
    D-78: this context manager is wired into FastAPI lifespan — separate from APScheduler.
    Pitfall 27: ALL tasks created via TaskGroup.create_task — zero bare asyncio.create_task.

    The TaskGroup propagates exceptions from any child task to all siblings (Python 3.11+
    structured concurrency semantics). If the heartbeat watchdog raises RuntimeError on
    staleness, the entire group is cancelled and the exception escapes via except* — the
    caller (FastAPI lifespan) is responsible for respawning.

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.
        mexc_client: MexcClient wrapping a ccxt.pro.mexc instance.
        symbols: Full symbol universe for candles/funding/trades/liquidations/L2.
        tier1_symbols: Top-50 symbols by 7d rolling volume (L2 tier-1 cadence 5s).
        settings: DataPlatformSettings (reserved for future use — not consumed directly here).

    Yields:
        None — context manager; tasks run for the duration of the async with block.
    """
    shutdown_event = asyncio.Event()
    stream_names = ("candles_1m", "funding", "trades", "l2_top20", "liquidations")
    tier1_set = set(tier1_symbols)

    try:
        async with asyncio.TaskGroup() as tg:
            # Core live-ingest streams
            tg.create_task(
                trades_aggregator_loop(engine, mexc_client, symbols),
                name="mexc.candles.live.aggregator",
            )
            tg.create_task(
                funding_live_loop(engine, mexc_client, symbols),
                name="mexc.funding.live",
            )
            tg.create_task(
                trades_persist_loop(engine, mexc_client, symbols),
                name="mexc.trades.live",
            )
            tg.create_task(
                liquidations_dual_source_loop(engine, mexc_client, symbols),
                name="mexc.liquidations.live",
            )

            # Per-symbol L2 sampler tasks with tier cadence (D-46)
            for sym in symbols:
                cadence = 5.0 if sym in tier1_set else 10.0
                tg.create_task(
                    l2_sample_loop(engine, mexc_client, sym, cadence),
                    name=f"mexc.l2.live.{sym}",
                )

            # D-49 point 3: heartbeat watchdog
            tg.create_task(
                _heartbeat_watchdog(mexc_client, stream_names, shutdown_event),
                name="mexc.heartbeat.watchdog",
            )

            # D-49 point 4: cross-REST divergence check
            tg.create_task(
                _cross_rest_divergence_check(engine, mexc_client, tuple(tier1_symbols), shutdown_event),
                name="mexc.cross_rest.divergence",
            )

            yield

            # Signal watchdog tasks to exit cleanly when the context exits normally
            shutdown_event.set()

    except* RuntimeError as eg:
        # Watchdog raised RuntimeError on staleness — supervisor (FastAPI lifespan) must respawn.
        # The except* form (PEP 654, Python 3.11+) captures ExceptionGroup from TaskGroup.
        for exc in eg.exceptions:
            log.error(
                "mexc.streams.watchdog_triggered_respawn",
                error_type=type(exc).__name__,
                reason=str(exc),
            )
        raise  # re-raise so the caller (FastAPI lifespan) knows to re-enter
