"""Prometheus metrics registry and per-service metric factory.

Uses a CUSTOM CollectorRegistry (NOT prometheus_client.REGISTRY) to:
- Exclude default process metrics (CPU, memory) from /metrics — UI-SPEC §/metrics
- Prevent metric registration conflicts between the 3 services in tests
- Keep business metrics isolated from platform metrics

Per UI-SPEC §Metric registry, the 4 mandatory base metrics are:
  shortfire_<svc>_http_requests_total       (Counter, labels: method/path/status)
  shortfire_<svc>_http_request_duration_seconds (Histogram, labels: method/path)
  shortfire_<svc>_service_event_emitted_total   (Counter, labels: event_type)
  shortfire_<svc>_build_info                    (Gauge always=1, labels: version/commit_sha/env)

Usage:
    from shortfire.observability.metrics import build_metrics_for_service, install_metrics_endpoint

    metrics = build_metrics_for_service("data-platform")
    metrics.build_info.labels(version="0.1.0", commit_sha="unknown", env="ci").set(1)
    install_metrics_endpoint(app)
"""

from typing import NamedTuple

from fastapi import FastAPI, Response
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Custom registry — explicitly NOT prometheus_client.REGISTRY (the default global).
# Rationale: avoids leaking process metrics (cpu_seconds, file_descriptors, etc.) into /metrics.
# UI-SPEC §/metrics: "Custom registries (every metric registers into the default prometheus_client.REGISTRY)"
# is listed under FORBIDDEN — we use a custom one, then emit only our metrics.
REGISTRY = CollectorRegistry()

# Bucket list locked by UI-SPEC §Metric registry — MUST NOT change without updating UI-SPEC
LATENCY_BUCKETS: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

# Module-level cache: service_name → ServiceMetrics
# Ensures build_metrics_for_service is idempotent — calling it twice with the same name
# returns the same metric instances instead of raising a ValueError from prometheus_client.
# This is required for tests that re-import entrypoints (each import calls build_metrics_for_service
# at module level; the REGISTRY is a module-level singleton that persists across re-imports).
_metrics_cache: dict[str, "ServiceMetrics"] = {}


class ServiceMetrics(NamedTuple):
    """Per-service metric family — 4 base metrics from UI-SPEC §Metric registry."""

    http_requests_total: Counter
    http_request_duration_seconds: Histogram
    service_event_emitted_total: Counter
    build_info: Gauge


def build_metrics_for_service(service_name: str) -> ServiceMetrics:
    """Create the 4 base metrics for a given service, registered in the custom REGISTRY.

    Metric names follow UI-SPEC §Metric naming convention:
        shortfire_<service>_<subsystem>_<metric_name>_<unit>

    kebab-case service names are normalized to snake_case because Prometheus forbids
    hyphens in metric names (e.g., "data-platform" → "data_platform").

    Args:
        service_name: Logical service identifier (e.g., "data-platform", "strategy-engine").
                      kebab-case is normalized to snake_case automatically.

    Returns:
        ServiceMetrics NamedTuple containing the 4 registered metric instances.
    """
    # Normalize kebab-case → snake_case (Prometheus metric name convention)
    svc = service_name.replace("-", "_")

    # Idempotency guard: return cached instance if already registered.
    # Prevents ValueError("Duplicated timeseries") when entrypoint modules are
    # re-imported during tests while REGISTRY (module-level singleton) persists.
    if svc in _metrics_cache:
        return _metrics_cache[svc]

    result = ServiceMetrics(
        http_requests_total=Counter(
            f"shortfire_{svc}_http_requests_total",
            "HTTP request count by method, path, and status code",
            ["method", "path", "status"],
            registry=REGISTRY,
        ),
        http_request_duration_seconds=Histogram(
            f"shortfire_{svc}_http_request_duration_seconds",
            "HTTP request latency in seconds",
            ["method", "path"],
            buckets=LATENCY_BUCKETS,
            registry=REGISTRY,
        ),
        service_event_emitted_total=Counter(
            f"shortfire_{svc}_service_event_emitted_total",
            "Count of service_event table rows written, by event_type",
            ["event_type"],
            registry=REGISTRY,
        ),
        build_info=Gauge(
            f"shortfire_{svc}_build_info",
            "Build metadata gauge (always 1) — join version/commit/env into PromQL",
            ["version", "commit_sha", "env"],
            registry=REGISTRY,
        ),
    )

    _metrics_cache[svc] = result
    return result


def install_metrics_endpoint(app: FastAPI) -> None:
    """Mount GET /metrics on the given FastAPI app.

    Returns Prometheus text exposition format v0.0.4.
    Content-Type is set per prometheus_client.CONTENT_TYPE_LATEST.

    The empty-state contract (UI-SPEC §/metrics) is honored automatically:
    even before the first request, generate_latest(REGISTRY) emits # HELP /
    # TYPE / 0-value lines for every registered metric — Grafana panels load
    without "missing series" errors on fresh deploys.
    """

    @app.get("/metrics")
    def _metrics_handler() -> Response:  # pyright: ignore[reportUnusedFunction]
        # UI-SPEC §/metrics locks the Content-Type to text/plain; version=0.0.4; charset=utf-8
        # (classic Prometheus text exposition format). prometheus_client ≥0.20 changed
        # CONTENT_TYPE_LATEST to "1.0.0" (OpenMetrics), so we override it explicitly.
        return Response(
            content=generate_latest(REGISTRY),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
