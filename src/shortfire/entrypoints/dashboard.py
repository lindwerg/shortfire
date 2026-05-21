"""FastAPI entrypoint for the dashboard Railway service.

Wires:
  - DashboardSettings (settings load at module import — fails fast on missing env vars, FOUND-07)
  - structlog NDJSON pipeline (configure_logging)
  - asgi-correlation-id middleware (install_correlation_middleware)
  - /metrics (install_metrics_endpoint — custom CollectorRegistry, 4 base metrics)
  - /health (6-field JSON with sorted keys and single datetime.now() call)
  - lifespan: service.startup + service.settings.loaded + service.shutdown events

D-03: data-platform, strategy-engine, and dashboard share one container image;
each starts with a different `startCommand` (wired in Plan 00-07 Railway config).

Note: dashboard has no anti-leak guard (no trade credentials at all, not even read-only MEXC).

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
from shortfire.observability.events import assert_event_registered
from shortfire.observability.logging import configure_logging
from shortfire.observability.metrics import build_metrics_for_service, install_metrics_endpoint
from shortfire.observability.middleware import install_correlation_middleware
from shortfire.settings.dashboard import DashboardSettings

# Settings load — fails fast (FOUND-07) on missing env vars
settings = DashboardSettings()  # pyright: ignore[reportCallIssue]

# Configure logging early so all subsequent log lines are NDJSON
configure_logging(settings.common.log_level)

log = structlog.get_logger("dashboard")

# Bind service-wide context into structlog contextvars (UI-SPEC §Log Event Schema)
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
    """FastAPI lifespan: emit service.startup and service.settings.loaded events."""
    assert_event_registered("service.startup")
    log.info("service.startup", version=__version__, pid=os.getpid())

    assert_event_registered("service.settings.loaded")
    log.info("service.settings.loaded", **settings.safe_summary())

    yield

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
