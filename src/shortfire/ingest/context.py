"""Process-wide singleton accessors for shared ingest dependencies (D-79).

APScheduler 4.x requires job callables to be top-level importable functions
with primitive (serializable) arguments — no closures, no instance methods.
This module provides lazy-initialized module-level singletons for the dependencies
that scheduled job functions look up at call time.

Singletons:
  get_engine()   — AsyncEngine (from create_engine_from_env)
  get_settings() — DataPlatformSettings (from DataPlatformSettings())
  get_metrics()  — ServiceMetrics (from build_metrics_for_service("data-platform"))

Thread-safety note:
  These are lazy-initialized singletons guarded by `if X is None` checks.
  In the single-threaded async event loop model of the data-platform service,
  concurrent initialization is not possible. For testing, the module-level
  variables can be patched via `unittest.mock.patch`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from shortfire.observability.metrics import ServiceMetrics
    from shortfire.settings.data_platform import DataPlatformSettings

# Module-level None sentinels — populated on first access
_engine: AsyncEngine | None = None
_settings: DataPlatformSettings | None = None
_metrics: ServiceMetrics | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide AsyncEngine, lazy-initializing on first call (D-79).

    Uses create_engine_from_env() from shortfire.db.engine.
    The engine is cached for the lifetime of the process.

    Returns:
        Configured SQLAlchemy AsyncEngine backed by asyncpg.
    """
    global _engine
    if _engine is None:
        from shortfire.db.engine import create_engine_from_env

        _engine = create_engine_from_env()
    return _engine


def get_settings() -> DataPlatformSettings:
    """Return the process-wide DataPlatformSettings, lazy-initializing on first call (D-79).

    Returns:
        DataPlatformSettings instance loaded from environment variables.
    """
    global _settings
    if _settings is None:
        from shortfire.settings.data_platform import DataPlatformSettings

        _settings = DataPlatformSettings()  # type: ignore[call-arg]  # pydantic-settings loads from env vars
    return _settings


def get_metrics() -> ServiceMetrics:
    """Return the process-wide ServiceMetrics, lazy-initializing on first call (D-79).

    Returns:
        ServiceMetrics for 'data-platform' registered on the custom REGISTRY.
    """
    global _metrics
    if _metrics is None:
        from shortfire.observability.metrics import build_metrics_for_service

        _metrics = build_metrics_for_service("data-platform")
    return _metrics
