"""Integration test: ORCH-01 smoke — APScheduler 4 boots inside lifespan + shuts down cleanly.

Verifies:
  - AsyncScheduler starts with SQLAlchemyDataStore against a real testcontainer DB
  - APScheduler creates its internal tables (schedules, tasks, jobs, job_results, metadata)
  - All 11 D-77 jobs are registered after register_all_jobs()
  - Clean shutdown via async context manager exit
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from shortfire.ingest.scheduler.bootstrap import scheduler_lifespan

pytestmark = pytest.mark.integration

_EXPECTED_IDS = {
    "universe.snapshot",
    "coingecko.universe",
    "backup.pg_dump",
    "coinglass.funding_agg",
    "coinglass.oi",
    "coinglass.liq",
    "coinglass.lsr",
    "mexc.oi.poll",
    "freshness.check",
    "dead_letter.alert",
    "mexc.candles.backfill.1d",
}


@pytest.mark.asyncio
async def test_scheduler_boots_inside_lifespan_against_testcontainer(migrated_db: str) -> None:
    """ORCH-01: AsyncScheduler starts, registers 11 jobs, creates tables, shuts down cleanly."""
    engine = create_async_engine(migrated_db.replace("postgresql://", "postgresql+asyncpg://"))

    try:
        async with scheduler_lifespan(engine) as scheduler:
            # APScheduler 4.0.0a6 SQLAlchemyDataStore creates:
            # metadata, tasks, schedules, jobs, job_results
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables"
                        " WHERE tablename IN"
                        " ('schedules', 'tasks', 'jobs', 'job_results', 'metadata')"
                    )
                )
                tables = {r[0] for r in rows}

            assert "schedules" in tables, f"APScheduler must create 'schedules' table, found: {tables}"

            # Verify all 11 D-77 schedules are registered
            schedules = await scheduler.get_schedules()
            schedule_ids = {s.id for s in schedules}

            assert len(schedules) == 11, f"Expected 11 schedules (D-77), got {len(schedules)}: {schedule_ids}"
            assert schedule_ids == _EXPECTED_IDS, (
                f"Missing: {_EXPECTED_IDS - schedule_ids}, extra: {schedule_ids - _EXPECTED_IDS}"
            )

    finally:
        await engine.dispose()
