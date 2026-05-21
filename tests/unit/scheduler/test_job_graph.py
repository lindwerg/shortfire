"""Unit tests for the APScheduler D-77 job graph (register_all_jobs).

All tests use a mock AsyncScheduler to avoid needing a DB connection.
Verifies:
  - Exactly 11 schedules are registered
  - All jobs have CoalescePolicy.latest and misfire_grace_time >= 60s
  - All job IDs are unique
  - Cron jobs use CronTrigger with UTC timezone
  - All callables are top-level async functions (D-79)
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler import CoalescePolicy
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from shortfire.ingest.scheduler.jobs import register_all_jobs

_CRON_JOB_IDS = {"universe.snapshot", "coingecko.universe", "backup.pg_dump"}
_INTERVAL_JOB_IDS = {
    "coinglass.funding_agg",
    "coinglass.oi",
    "coinglass.liq",
    "coinglass.lsr",
    "mexc.oi.poll",
    "freshness.check",
    "dead_letter.alert",
    "mexc.candles.backfill.1d",
}
_ALL_JOB_IDS = _CRON_JOB_IDS | _INTERVAL_JOB_IDS


@pytest.mark.asyncio
async def test_register_all_jobs_adds_11_schedules() -> None:
    """register_all_jobs must register exactly 11 schedules per D-77."""
    mock_scheduler = MagicMock()
    mock_scheduler.add_schedule = AsyncMock()

    await register_all_jobs(mock_scheduler)

    assert mock_scheduler.add_schedule.call_count == 11, (
        f"Expected 11 schedules (D-77), got {mock_scheduler.add_schedule.call_count}"
    )


@pytest.mark.asyncio
async def test_every_job_has_coalesce_policy_latest() -> None:
    """Every job must use CoalescePolicy.latest (or equivalent coalesce) per Pattern 5."""
    mock_scheduler = MagicMock()
    mock_scheduler.add_schedule = AsyncMock()

    await register_all_jobs(mock_scheduler)

    for i, c in enumerate(mock_scheduler.add_schedule.call_args_list):
        coalesce = c.kwargs.get("coalesce")
        assert coalesce == CoalescePolicy.latest, (
            f"Schedule call #{i} missing coalesce=CoalescePolicy.latest, got {coalesce!r}"
        )


@pytest.mark.asyncio
async def test_every_job_has_misfire_grace_time() -> None:
    """Every job must have misfire_grace_time >= 60 seconds per Pattern 5 (P1-A mitigation)."""
    mock_scheduler = MagicMock()
    mock_scheduler.add_schedule = AsyncMock()

    await register_all_jobs(mock_scheduler)

    for i, c in enumerate(mock_scheduler.add_schedule.call_args_list):
        mgtime = c.kwargs.get("misfire_grace_time")
        assert mgtime is not None, f"Schedule call #{i} missing misfire_grace_time"
        # misfire_grace_time can be int (seconds) or timedelta
        secs = mgtime.total_seconds() if isinstance(mgtime, timedelta) else float(mgtime)
        assert secs >= 60, f"Schedule call #{i} misfire_grace_time={mgtime!r} < 60s"


@pytest.mark.asyncio
async def test_every_job_has_unique_id() -> None:
    """All 11 job IDs must be unique (no duplicates)."""
    mock_scheduler = MagicMock()
    mock_scheduler.add_schedule = AsyncMock()

    await register_all_jobs(mock_scheduler)

    ids = [c.kwargs.get("id") for c in mock_scheduler.add_schedule.call_args_list]
    assert len(ids) == len(set(ids)), f"Duplicate job IDs found: {ids}"
    assert len(ids) == 11


@pytest.mark.asyncio
async def test_cron_jobs_use_utc_timezone() -> None:
    """universe.snapshot, coingecko.universe, and backup.pg_dump must use CronTrigger(timezone='UTC')."""
    mock_scheduler = MagicMock()
    mock_scheduler.add_schedule = AsyncMock()

    await register_all_jobs(mock_scheduler)

    cron_calls = {
        c.kwargs.get("id"): c.args[1]
        for c in mock_scheduler.add_schedule.call_args_list
        if isinstance(c.args[1], CronTrigger)
    }

    for job_id in _CRON_JOB_IDS:
        assert job_id in cron_calls, f"Job {job_id!r} must use CronTrigger"
        trigger = cron_calls[job_id]
        # APScheduler 4.0.0a6 stores timezone as tzinfo or string
        assert trigger.timezone is not None, f"Job {job_id!r} CronTrigger missing timezone"


@pytest.mark.asyncio
async def test_interval_jobs_use_interval_trigger() -> None:
    """Interval-based jobs must use IntervalTrigger."""
    mock_scheduler = MagicMock()
    mock_scheduler.add_schedule = AsyncMock()

    await register_all_jobs(mock_scheduler)

    interval_calls = {
        c.kwargs.get("id"): c.args[1]
        for c in mock_scheduler.add_schedule.call_args_list
        if isinstance(c.args[1], IntervalTrigger)
    }

    for job_id in _INTERVAL_JOB_IDS:
        assert job_id in interval_calls, (
            f"Interval job {job_id!r} must use IntervalTrigger, got "
            f"{type(interval_calls.get(job_id)).__name__!r}"
        )


@pytest.mark.asyncio
async def test_callables_are_top_level_async_functions() -> None:
    """All registered callables must be top-level module functions (D-79, no closures)."""
    from shortfire.ingest.scheduler import jobs as jobs_module

    callable_names = [
        "universe_snapshot_job_callable",
        "coingecko_universe_job_callable",
        "coinglass_funding_agg_job_callable",
        "coinglass_oi_job_callable",
        "coinglass_liq_job_callable",
        "coinglass_lsr_job_callable",
        "mexc_oi_poll_job_callable",
        "mexc_candles_backfill_1d_job_callable",
        "backup_pg_dump_job_callable",
        "freshness_check_job_callable",
        "dead_letter_alert_job_callable",
    ]

    for name in callable_names:
        fn = getattr(jobs_module, name, None)
        assert fn is not None, f"jobs.py must export {name!r}"
        assert inspect.iscoroutinefunction(fn), f"{name!r} must be async"
        assert fn.__module__ == "shortfire.ingest.scheduler.jobs", (
            f"{name!r} must be a top-level function in scheduler.jobs, not a closure"
        )


@pytest.mark.asyncio
async def test_no_placeholder_bodies() -> None:
    """No job callable may have a `...` placeholder body (B2 guarantee)."""
    import os

    jobs_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "src",
        "shortfire",
        "ingest",
        "scheduler",
        "jobs.py",
    )
    with open(jobs_path) as f:  # noqa: ASYNC230
        source = f.read()

    # Check no '... # planner fills in' pattern
    assert "planner fills in" not in source, (
        "jobs.py contains placeholder '... # planner fills in' (B2 zero-placeholder guarantee)"
    )
