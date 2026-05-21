"""APScheduler 4 AsyncScheduler factory + lifespan context manager (D-75, D-76).

D-75: AsyncScheduler with SQLAlchemyDataStore + AsyncpgEventBroker.
      NEVER PostgresJobStore (v3 nomenclature — banned per D-75 grep guard).
D-76: scheduler_lifespan is an async context manager that:
      1. Constructs AsyncScheduler with the data-store + event-broker.
      2. Registers all D-77 jobs (idempotent via conflict_policy=do_nothing).
      3. Starts scheduler in background.
      4. Yields the scheduler instance.
      5. On exit: scheduler cleanup is handled automatically by __aexit__ of AsyncScheduler.

Import note: 'from apscheduler import AsyncScheduler' — v4 unified package (confirmed
             against 4.0.0a6 in RESEARCH.md §2 + pyproject legitimacy checkpoint).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from apscheduler import AsyncScheduler
from apscheduler.datastores.sqlalchemy import SQLAlchemyDataStore
from apscheduler.eventbrokers.asyncpg import AsyncpgEventBroker
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger("ingest.scheduler.bootstrap")


def build_async_scheduler(engine: AsyncEngine) -> AsyncScheduler:
    """Construct AsyncScheduler with SQLAlchemy persistence + asyncpg event broker (D-75).

    Uses the same AsyncEngine for both data-store and event-broker — the engine must
    be backed by asyncpg (postgresql+asyncpg:// URL).

    Never uses PostgresJobStore — that is the APScheduler 3.x nomenclature (D-75).

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.

    Returns:
        Configured AsyncScheduler (not yet started).
    """
    data_store = SQLAlchemyDataStore(engine)
    event_broker = AsyncpgEventBroker.from_async_sqla_engine(engine)
    return AsyncScheduler(data_store, event_broker)


@asynccontextmanager
async def scheduler_lifespan(engine: AsyncEngine) -> AsyncGenerator[AsyncScheduler, None]:
    """Async context that starts AsyncScheduler + registers D-77 jobs + shuts down cleanly.

    The scheduler is entered as its own async context manager, which handles:
      - Creating the APScheduler internal tables (apscheduler_schedules, etc.)
      - Starting the background processing loop
      - Stopping + joining on context exit

    Jobs are registered via register_all_jobs() with idempotent conflict_policy
    (APScheduler 4: ConflictPolicy.do_nothing means re-runs don't raise).

    Args:
        engine: SQLAlchemy AsyncEngine backed by asyncpg.

    Yields:
        Running AsyncScheduler instance.
    """
    from shortfire.ingest.scheduler.jobs import register_all_jobs

    scheduler = build_async_scheduler(engine)

    async with scheduler:
        await register_all_jobs(scheduler)
        await scheduler.start_in_background()
        log.info("scheduler.started")
        try:
            yield scheduler
        finally:
            log.info("scheduler.stopping")
            # async with scheduler.__aexit__ handles stop + wait on context exit
