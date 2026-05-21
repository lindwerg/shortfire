"""FastAPI entrypoint for the data-platform Railway service.

Wires:
  - DataPlatformSettings (settings load at module import — fails fast on missing env vars, FOUND-07)
  - assert_no_trade_env_leaked() at startup (D-16 anti-leak guardrail)
  - structlog NDJSON pipeline (configure_logging)
  - asgi-correlation-id middleware (install_correlation_middleware)
  - /metrics (install_metrics_endpoint — custom CollectorRegistry, 4 base metrics)
  - /health (6-field JSON with sorted keys and single datetime.now() call)
  - lifespan: service.startup + service.settings.loaded + service.shutdown events

D-03: data-platform, strategy-engine, and dashboard share one container image;
each starts with a different `startCommand` (wired in Plan 00-07 Railway config).

D-16: assert_no_trade_env_leaked() is called immediately after Settings load.
       If MEXC_TRADE__* env vars are visible to this service, it crashes loudly.

D-21: settings logged via settings.safe_summary() only, never repr(settings).
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import orjson
import structlog
from asgi_correlation_id import correlation_id as correlation_id_var
from fastapi import FastAPI, Response

from shortfire import __version__
from shortfire.db.engine import create_engine_from_env
from shortfire.ingest.scheduler.bootstrap import scheduler_lifespan
from shortfire.observability.events import assert_event_registered
from shortfire.observability.logging import configure_logging
from shortfire.observability.metrics import build_metrics_for_service, install_metrics_endpoint
from shortfire.observability.middleware import install_correlation_middleware
from shortfire.settings.data_platform import DataPlatformSettings, assert_no_trade_env_leaked

# Settings load — fails fast (FOUND-07) on missing env vars
settings = DataPlatformSettings()  # pyright: ignore[reportCallIssue]

# Anti-leak guard — fails fast (D-16) if Phase 5 trade keys are visible to this service
assert_no_trade_env_leaked()

# Configure logging early so all subsequent log lines are NDJSON
configure_logging(settings.common.log_level)

log = structlog.get_logger("data-platform")

# Bind service-wide context into structlog contextvars (UI-SPEC §Log Event Schema)
# These fields appear on every log line emitted within this process.
structlog.contextvars.bind_contextvars(
    service_name=settings.service_name,
    env=settings.common.env,
)

# Metrics — 4 base metrics registered in the custom CollectorRegistry (UI-SPEC §Metric registry)
metrics = build_metrics_for_service(settings.service_name)
metrics.build_info.labels(
    version=__version__,
    commit_sha=os.getenv("COMMIT_SHA", "unknown"),
    env=settings.common.env,
).set(1)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: startup + scheduler + optional ws streams + shutdown.

    D-76: Composes AsyncScheduler (cron/interval jobs) + MEXC ws TaskGroup
    under one lifespan so graceful shutdown propagates to both.

    Ordering (critical):
      1. scheduler_lifespan enters first — initialises APScheduler DB tables
         and starts background job processing.
      2. mexc_ws_streams enters second (INSIDE scheduler ctx) — continuous ws
         streams start after the scheduler is ready.
      3. On lifespan exit: ws TaskGroup cancels first, then scheduler stops.
         This ensures ws streams stop emitting data before the scheduler's
         persistence layer closes (preventing ingest_runs writes after DB close).

    Degraded mode: if MEXC settings are absent, ws streams are skipped;
    scheduler still runs for non-MEXC jobs (Coinglass, CoinGecko, backups).

    D-78: continuous ws tasks are TaskGroup-owned here — NOT APScheduler-managed.
    """
    assert_event_registered("service.startup")
    log.info("service.startup", version=__version__, pid=os.getpid())

    assert_event_registered("service.settings.loaded")
    log.info("service.settings.loaded", **settings.safe_summary())

    engine = create_engine_from_env()

    if settings.mexc is None:
        # Degraded mode: no MEXC keys — ws streams disabled, scheduler-only
        log.warning("service.degraded", reason="MEXC settings absent — ws streams disabled")
        async with scheduler_lifespan(engine):
            yield
    else:
        from shortfire.ingest.mexc.client import build_mexc_swap_client
        from shortfire.ingest.mexc.streams import mexc_ws_streams

        mexc_client = build_mexc_swap_client(settings)
        try:
            # tier-1 / universe loaded at first scheduler run; first-boot uses empty set
            symbols: list[str] = []
            tier1: list[str] = []
            # D-76: nested contexts preserve ordering: scheduler enters first,
            # ws streams enter second; shutdown reverses: ws cancels, then scheduler stops.
            # noqa: SIM117 — nested `with` is intentional here to preserve ordering semantics
            async with scheduler_lifespan(engine):  # noqa: SIM117
                async with mexc_ws_streams(engine, mexc_client, symbols, tier1, settings):
                    yield
        finally:
            await mexc_client.close()
            await engine.dispose()

    assert_event_registered("service.shutdown")
    log.info("service.shutdown")


app = FastAPI(lifespan=lifespan, title=f"shortfire-{settings.service_name}")

install_correlation_middleware(app)
install_metrics_endpoint(app)


@app.get("/health")
def health() -> Response:
    """Readiness + liveness probe endpoint.

    Response body: 6 fields, alphabetically sorted keys per UI-SPEC §`GET /health`.
    ts: ISO-8601 UTC with millisecond precision (3 digits) and Z suffix.

    CRITICAL: ts is derived from a SINGLE datetime.now(timezone.utc) call.
    Two separate calls risk a millisecond-boundary mismatch (e.g. 00:00:01.999 vs
    00:00:02.000) if the clock ticks between the two calls.
    """
    now = datetime.now(UTC)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    body = {
        "correlation_id": correlation_id_var.get() or str(uuid4()),
        "env": settings.common.env,
        "service_name": settings.service_name,
        "status": "ok",
        "ts": ts,
        "version": __version__,
    }

    # orjson.OPT_SORT_KEYS guarantees alphabetical key order per UI-SPEC §`GET /health`
    return Response(
        content=orjson.dumps(body, option=orjson.OPT_SORT_KEYS),
        media_type="application/json",
    )
