"""Observability layer — structlog NDJSON logging, Prometheus /metrics, correlation-id middleware.

Public re-exports for convenient single-import access:

    from shortfire.observability import (
        configure_logging,
        install_correlation_middleware,
        install_metrics_endpoint,
        build_metrics_for_service,
        REGISTRY,
        ServiceMetrics,
        EVENTS,
        assert_event_registered,
    )

Implemented in Plan 00-05.
"""

from shortfire.observability.events import EVENTS, assert_event_registered
from shortfire.observability.logging import configure_logging
from shortfire.observability.metrics import (
    REGISTRY,
    ServiceMetrics,
    build_metrics_for_service,
    install_metrics_endpoint,
)
from shortfire.observability.middleware import install_correlation_middleware

__all__ = [
    "EVENTS",
    "REGISTRY",
    "ServiceMetrics",
    "assert_event_registered",
    "build_metrics_for_service",
    "configure_logging",
    "install_correlation_middleware",
    "install_metrics_endpoint",
]
