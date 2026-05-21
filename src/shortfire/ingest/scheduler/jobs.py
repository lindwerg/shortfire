"""D-77 job graph — all cron + interval schedules for the data-platform service.

Every callable in this module is:
  - A top-level async function (D-79: serializable, no closures, no bound methods)
  - Imported by APScheduler directly from this module path
  - Fetches dependencies (engine, settings, clients) via shortfire.ingest.context singletons

D-77 job graph (full):
  | Job ID                    | Trigger                         |
  |---------------------------|---------------------------------|
  | mexc.candles.backfill.1d  | IntervalTrigger(hours=24)       |
  | mexc.oi.poll              | IntervalTrigger(minutes=5)      |
  | coinglass.funding_agg     | IntervalTrigger(minutes=5)      |
  | coinglass.oi              | IntervalTrigger(minutes=5)      |
  | coinglass.liq             | IntervalTrigger(minutes=10)     |
  | coinglass.lsr             | IntervalTrigger(minutes=15)     |
  | coingecko.universe        | CronTrigger(hour=0, min=30 UTC) |
  | universe.snapshot         | CronTrigger(hour=0, min=5 UTC)  |
  | backup.pg_dump            | CronTrigger(hour=1, min=0 UTC)  |
  | freshness.check           | IntervalTrigger(minutes=1)      |
  | dead_letter.alert         | IntervalTrigger(minutes=5)      |

All schedules use CoalescePolicy.latest + misfire_grace_time to prevent post-deploy
burst-429 (P1-A anti-pattern per RESEARCH.md Pattern 5).

B2 guarantee: zero placeholder bodies. All round-robin callables have COMPLETE
implementations using load_kv_state / save_kv_state for cursor persistence.
"""

from __future__ import annotations

from datetime import UTC

import structlog
from apscheduler import AsyncScheduler, CoalescePolicy
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from shortfire.ingest.context import get_engine, get_settings

log = structlog.get_logger("ingest.scheduler.jobs")


# ---------------------------------------------------------------------------
# Universe snapshot + tier-1 (D-77: universe.snapshot)
# ---------------------------------------------------------------------------


async def universe_snapshot_job_callable() -> None:
    """D-77 universe.snapshot cron 00:05 UTC — daily point-in-time snapshot."""
    from shortfire.ingest.mexc.client import build_mexc_swap_client
    from shortfire.ingest.universe.snapshot import universe_snapshot_job
    from shortfire.ingest.universe.tier1 import recompute_tier1

    engine = get_engine()
    settings = get_settings()

    if settings.mexc is None:
        log.warning("scheduler.universe_snapshot.skipped", reason="mexc settings absent")
        return

    mexc = build_mexc_swap_client(settings)
    try:
        n = await universe_snapshot_job(engine, mexc, coingecko_client=None)
        await recompute_tier1(engine)
        log.info("scheduler.job.universe_snapshot.completed", rows_written=n)
    finally:
        await mexc.close()


# ---------------------------------------------------------------------------
# CoinGecko universe (D-77: coingecko.universe)
# ---------------------------------------------------------------------------


async def coingecko_universe_job_callable() -> None:
    """D-77 coingecko.universe cron 00:30 UTC — daily metadata refresh."""
    from shortfire.ingest.coingecko import universe
    from shortfire.ingest.coingecko.client import CoinGeckoClient

    engine = get_engine()
    settings = get_settings()

    if settings.coingecko is None:
        log.warning("scheduler.coingecko.universe.skipped", reason="coingecko not configured")
        return

    client = CoinGeckoClient(settings)
    try:
        await universe.fetch_and_write_daily(engine, client)
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Coinglass funding aggregates (D-77: coinglass.funding_agg)
# ---------------------------------------------------------------------------


async def coinglass_funding_agg_job_callable() -> None:
    """D-77 coinglass.funding_agg every 5 min — funding rate aggregates."""
    from sqlalchemy import text

    from shortfire.ingest.coinglass import funding_agg
    from shortfire.ingest.coinglass.client import CoinglassClient

    engine = get_engine()
    settings = get_settings()

    if settings.coinglass is None:
        log.warning("scheduler.coinglass.funding_agg.skipped", reason="coinglass not configured")
        return

    # Build coinglass→unified symbol mapping from symbols table
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT symbol, coinglass_symbol FROM symbols"
                " WHERE coinglass_symbol IS NOT NULL AND delisted_at IS NULL"
            )
        )
        mapping = {r[1]: r[0] for r in rows}

    client = CoinglassClient(settings)
    try:
        await funding_agg.fetch_and_write(engine, client, coinglass_to_unified=mapping)
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Coinglass open interest — round-robin (D-77: coinglass.oi)
# ---------------------------------------------------------------------------


async def coinglass_oi_job_callable() -> None:
    """D-77 coinglass.oi every 5 min — OI round-robin step (B2 fix: full body)."""
    from sqlalchemy import text

    from shortfire.ingest.coinglass import oi as cg_oi
    from shortfire.ingest.coinglass.client import CoinglassClient
    from shortfire.ingest.state.kv_state import load_kv_state, save_kv_state

    engine = get_engine()
    settings = get_settings()

    if settings.coinglass is None:
        log.warning("scheduler.coinglass.oi.skipped", reason="coinglass not configured")
        return

    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT symbol, coinglass_symbol FROM symbols"
                " WHERE coinglass_symbol IS NOT NULL AND delisted_at IS NULL"
                " ORDER BY tier ASC, symbol ASC"
            )
        )
        pairs = [(r[0], r[1]) for r in rows]

    if not pairs:
        log.warning("scheduler.coinglass.oi.skipped", reason="no symbols with coinglass_symbol")
        return

    kv = await load_kv_state(engine, job_id="coinglass.oi")
    cursor = int(kv.get("last_symbol_index", 0)) % len(pairs)
    # Hobbyist budget: 28 req/min ÷ 5-min interval → ~140 req/cycle; 5 per step keeps headroom
    batch_size = 5
    end = min(cursor + batch_size, len(pairs))
    slice_ = pairs[cursor:end]

    client = CoinglassClient(settings)
    try:
        for symbol_unified, coinglass_symbol in slice_:
            await cg_oi.fetch_and_write(
                engine,
                client,
                symbol_unified=symbol_unified,
                coinglass_symbol=coinglass_symbol,
                interval="1h",
            )
    finally:
        await client.close()

    kv["last_symbol_index"] = end if end < len(pairs) else 0
    await save_kv_state(engine, job_id="coinglass.oi", state=kv)


# ---------------------------------------------------------------------------
# Coinglass liquidations — round-robin (D-77: coinglass.liq)
# ---------------------------------------------------------------------------


async def coinglass_liq_job_callable() -> None:
    """D-77 coinglass.liq every 10 min — liquidation round-robin step (B2 fix)."""
    from sqlalchemy import text

    from shortfire.ingest.coinglass import liq as cg_liq
    from shortfire.ingest.coinglass.client import CoinglassClient
    from shortfire.ingest.state.kv_state import load_kv_state, save_kv_state

    engine = get_engine()
    settings = get_settings()

    if settings.coinglass is None:
        log.warning("scheduler.coinglass.liq.skipped", reason="coinglass not configured")
        return

    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT symbol, coinglass_symbol FROM symbols"
                " WHERE coinglass_symbol IS NOT NULL AND delisted_at IS NULL"
                " ORDER BY tier ASC, symbol ASC"
            )
        )
        pairs = [(r[0], r[1]) for r in rows]

    if not pairs:
        return

    kv = await load_kv_state(engine, job_id="coinglass.liq")
    cursor = int(kv.get("last_symbol_index", 0)) % len(pairs)
    batch_size = 3  # 10-min interval; liq endpoint costs more per call
    end = min(cursor + batch_size, len(pairs))
    slice_ = pairs[cursor:end]

    client = CoinglassClient(settings)
    try:
        for symbol_unified, coinglass_symbol in slice_:
            await cg_liq.fetch_and_write(
                engine,
                client,
                symbol_unified=symbol_unified,
                coinglass_symbol=coinglass_symbol,
                interval="1h",
            )
    finally:
        await client.close()

    kv["last_symbol_index"] = end if end < len(pairs) else 0
    await save_kv_state(engine, job_id="coinglass.liq", state=kv)


# ---------------------------------------------------------------------------
# Coinglass long/short ratio — round-robin (D-77: coinglass.lsr)
# ---------------------------------------------------------------------------


async def coinglass_lsr_job_callable() -> None:
    """D-77 coinglass.lsr every 15 min — L/S ratio round-robin step (B2 fix)."""
    from sqlalchemy import text

    from shortfire.ingest.coinglass import lsr as cg_lsr
    from shortfire.ingest.coinglass.client import CoinglassClient
    from shortfire.ingest.state.kv_state import load_kv_state, save_kv_state

    engine = get_engine()
    settings = get_settings()

    if settings.coinglass is None:
        log.warning("scheduler.coinglass.lsr.skipped", reason="coinglass not configured")
        return

    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT symbol, coinglass_symbol FROM symbols"
                " WHERE coinglass_symbol IS NOT NULL AND delisted_at IS NULL"
                " ORDER BY tier ASC, symbol ASC"
            )
        )
        pairs = [(r[0], r[1]) for r in rows]

    if not pairs:
        return

    kv = await load_kv_state(engine, job_id="coinglass.lsr")
    cursor = int(kv.get("last_symbol_index", 0)) % len(pairs)
    batch_size = 5
    end = min(cursor + batch_size, len(pairs))
    slice_ = pairs[cursor:end]

    client = CoinglassClient(settings)
    try:
        for symbol_unified, coinglass_symbol in slice_:
            await cg_lsr.fetch_and_write(
                engine,
                client,
                symbol_unified=symbol_unified,
                coinglass_symbol=coinglass_symbol,
                interval="1h",
            )
    finally:
        await client.close()

    kv["last_symbol_index"] = end if end < len(pairs) else 0
    await save_kv_state(engine, job_id="coinglass.lsr", state=kv)


# ---------------------------------------------------------------------------
# MEXC OI poll — round-robin (D-77: mexc.oi.poll)
# ---------------------------------------------------------------------------


async def mexc_oi_poll_job_callable() -> None:
    """D-77 mexc.oi.poll every 5 min — REST OI round-robin step (B2 fix)."""
    from sqlalchemy import text

    from shortfire.ingest.mexc.client import build_mexc_swap_client
    from shortfire.ingest.mexc.oi import oi_round_robin_step
    from shortfire.ingest.state.kv_state import load_kv_state, save_kv_state

    engine = get_engine()
    settings = get_settings()

    if settings.mexc is None:
        log.warning("scheduler.mexc.oi.poll.skipped", reason="mexc settings absent")
        return

    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT symbol FROM symbols WHERE delisted_at IS NULL ORDER BY tier ASC, symbol ASC")
        )
        symbols = [r[0] for r in rows]

    if not symbols:
        return

    kv = await load_kv_state(engine, job_id="mexc.oi.poll")
    client = build_mexc_swap_client(settings)
    try:
        kv = await oi_round_robin_step(engine, client, symbols, batch_size=10, kv_state=kv)
    finally:
        await client.close()

    await save_kv_state(engine, job_id="mexc.oi.poll", state=kv)


# ---------------------------------------------------------------------------
# MEXC 1d candles backfill — gap-repair (D-77: mexc.candles.backfill.1d)
# ---------------------------------------------------------------------------


async def mexc_candles_backfill_1d_job_callable() -> None:
    """D-77 mexc.candles.backfill.1d every 24h — gap-repair sweep (B2 fix).

    Sweeps the last 25 hours of 1m candles for every qualifying symbol via REST
    backfill. ON CONFLICT DO NOTHING means already-ingested rows are no-ops, so
    this is a pure gap-repair pass that picks up minutes the live ws stream missed
    (D-77 + Pitfall 11).
    """
    from datetime import datetime, timedelta

    from sqlalchemy import text

    from shortfire.ingest.mexc.backfill import backfill_universe
    from shortfire.ingest.mexc.client import build_mexc_swap_client

    engine = get_engine()
    settings = get_settings()

    if settings.mexc is None:
        log.warning("scheduler.mexc.candles.backfill.skipped", reason="mexc settings absent")
        return

    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT symbol FROM symbols WHERE delisted_at IS NULL ORDER BY tier ASC, symbol ASC")
        )
        symbols = [r[0] for r in rows]

    if not symbols:
        log.warning("scheduler.mexc.candles.backfill.1d.skipped", reason="no qualifying symbols")
        return

    client = build_mexc_swap_client(settings)
    try:
        since = datetime.now(UTC) - timedelta(hours=25)
        until = datetime.now(UTC)
        results = await backfill_universe(
            engine,
            client,
            symbols,
            timeframes=["1m"],
            since=since,
            until=until,
            max_concurrency=8,
        )
        total = sum(results.values())
        log.info(
            "scheduler.mexc.candles.backfill.1d.completed",
            rows_written=total,
            n_symbols=len(symbols),
        )
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Placeholder callables for plan 01-10 features
# (Registered now with stable IDs; implementation ships in plan 01-10)
# ---------------------------------------------------------------------------


async def backup_pg_dump_job_callable() -> None:
    """D-77 backup.pg_dump cron 01:00 UTC — placeholder, implementation in plan 01-10."""
    log.info("scheduler.backup.placeholder", reason="implementation lands in plan 01-10")


async def freshness_check_job_callable() -> None:
    """D-77 freshness.check every 1 min — placeholder, implementation in plan 01-10."""
    log.info("scheduler.freshness.placeholder", reason="implementation lands in plan 01-10")


async def dead_letter_alert_job_callable() -> None:
    """D-77 dead_letter.alert every 5 min — placeholder, implementation in plan 01-10."""
    log.info("scheduler.dead_letter_alert.placeholder", reason="implementation lands in plan 01-10")


# ---------------------------------------------------------------------------
# Job graph registration — D-77
# ---------------------------------------------------------------------------


async def register_all_jobs(scheduler: AsyncScheduler) -> None:
    """Idempotent registration of the full D-77 job graph.

    Uses CoalescePolicy.latest (fire once with the most recent scheduled time if
    several misfires accumulated) + misfire_grace_time per RESEARCH.md Pattern 5.
    ConflictPolicy defaults to do_nothing — re-running register_all_jobs on an
    existing scheduler does not raise (idempotency contract per D-79).

    Args:
        scheduler: Running AsyncScheduler (started in background).
    """
    # --- Interval jobs ---
    await scheduler.add_schedule(
        coinglass_funding_agg_job_callable,
        IntervalTrigger(minutes=5),
        id="coinglass.funding_agg",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=300,
    )
    await scheduler.add_schedule(
        coinglass_oi_job_callable,
        IntervalTrigger(minutes=5),
        id="coinglass.oi",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=300,
    )
    await scheduler.add_schedule(
        coinglass_liq_job_callable,
        IntervalTrigger(minutes=10),
        id="coinglass.liq",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=600,
    )
    await scheduler.add_schedule(
        coinglass_lsr_job_callable,
        IntervalTrigger(minutes=15),
        id="coinglass.lsr",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=900,
    )
    await scheduler.add_schedule(
        mexc_oi_poll_job_callable,
        IntervalTrigger(minutes=5),
        id="mexc.oi.poll",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=300,
    )
    await scheduler.add_schedule(
        freshness_check_job_callable,
        IntervalTrigger(minutes=1),
        id="freshness.check",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=60,
    )
    await scheduler.add_schedule(
        dead_letter_alert_job_callable,
        IntervalTrigger(minutes=5),
        id="dead_letter.alert",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=300,
    )
    await scheduler.add_schedule(
        mexc_candles_backfill_1d_job_callable,
        IntervalTrigger(hours=24),
        id="mexc.candles.backfill.1d",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=3600,
    )

    # --- Cron jobs (all UTC) ---
    await scheduler.add_schedule(
        universe_snapshot_job_callable,
        CronTrigger(hour=0, minute=5, timezone="UTC"),
        id="universe.snapshot",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=3600,
    )
    await scheduler.add_schedule(
        coingecko_universe_job_callable,
        CronTrigger(hour=0, minute=30, timezone="UTC"),
        id="coingecko.universe",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=3600,
    )
    await scheduler.add_schedule(
        backup_pg_dump_job_callable,
        CronTrigger(hour=1, minute=0, timezone="UTC"),
        id="backup.pg_dump",
        coalesce=CoalescePolicy.latest,
        misfire_grace_time=3600,
    )

    log.info("scheduler.jobs.registered", n_jobs=11)
