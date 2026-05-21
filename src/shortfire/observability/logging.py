"""Structlog logging configuration for all shortfire services.

Pattern 5 from RESEARCH.md — structlog + asgi-correlation-id + Prometheus observability stack.

Key design decisions:
- merge_contextvars MUST be the FIRST processor (Pitfall 2: async correlation-id propagation).
  Without this, correlation_id is lost when logging across asyncio task boundaries.
- add_correlation_id pulls the asgi-correlation-id contextvar into the event dict as `request_id`.
- JSONRenderer is always the LAST processor — produces NDJSON per UI-SPEC §Log Event Schema.
- Bridges stdlib/uvicorn loggers through the same processor chain.

Usage:
    from shortfire.observability.logging import configure_logging
    configure_logging("INFO")
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger


def add_correlation_id(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Structlog processor: pulls the current asgi-correlation-id contextvar into the event dict.

    Injects `request_id` (the canonical key used by asgi-correlation-id and UI-SPEC §Reserved key
    namespace). When present inside a request scope, log consumers can join lines by request_id.

    Per UI-SPEC §Reserved key namespace, both `correlation_id` and `request_id` are aliases.
    We inject as `request_id` here because asgi-correlation-id uses that name; the entrypoints
    bind `correlation_id` separately via structlog.contextvars.bind_contextvars.
    """
    # Import here to allow testing without a full ASGI app running
    try:
        from asgi_correlation_id import correlation_id  # type: ignore[import-untyped]

        if rid := correlation_id.get():
            event_dict["request_id"] = rid
    except ImportError:
        pass
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog with NDJSON output, correlation-id injection, and contextvar merging.

    The processor chain (ORDER IS CRITICAL — see Pitfall 2):
      1. merge_contextvars  — FIRST: merges bound contextvars (service_name, env, correlation_id)
                              into every log event. Must be first so async propagation works.
      2. add_correlation_id — pulls asgi-correlation-id contextvar into event dict as `request_id`
      3. add_log_level      — adds `level` key (lowercase, e.g. "info")
      4. TimeStamper        — adds `ts` (ISO-8601 UTC with Z suffix, key="ts" per UI-SPEC)
      5. StackInfoRenderer  — renders stack_info if present
      6. format_exc_info    — renders tracebacks into single `exception` key (UI-SPEC: no multi-line)
      7. JSONRenderer       — LAST: serializes to JSON string (NDJSON output)

    Note: add_logger_name is omitted — it requires a stdlib Logger and is incompatible
    with PrintLoggerFactory. The `service_name` contextvar fulfills the same purpose.

    Args:
        log_level: One of "DEBUG", "INFO", "WARN", "ERROR" (D-33 gate enforces INFO in CI).
    """
    # key="ts" per UI-SPEC §Log Event Schema mandatory base fields (default key is "timestamp")
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts")

    # Level integer from name; getattr avoids pyright private-access warning
    level_int: int = getattr(logging, log_level, logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,  # MUST be first — propagates contextvars
        add_correlation_id,  # pulls asgi-correlation-id contextvar into `request_id`
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bridge uvicorn / stdlib loggers through a StreamHandler to stdout.
    # We use PrintLoggerFactory (writes directly to stdout) for structlog-native loggers.
    # Stdlib loggers (uvicorn, sqlalchemy, etc.) still use basicConfig below.
    logging.basicConfig(
        level=log_level,
        handlers=[logging.StreamHandler(sys.stdout)],
        format="%(message)s",  # stdlib output is plain; structlog handles its own JSON
        force=True,  # override any existing root handler configuration
    )
