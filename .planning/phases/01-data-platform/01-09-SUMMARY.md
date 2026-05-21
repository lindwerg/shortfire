---
phase: 1
plan: 9
subsystem: ingest
tags:
  - apscheduler
  - asyncio
  - universe-filter
  - scheduler
  - lifespan
  - fastapi
  - hypothesis
  - kv-state
dependency_graph:
  requires:
    - "01-05 (Coinglass ingest + dead-letter)"
    - "01-06 (MEXC candles + CoinGecko)"
    - "01-07 (MEXC OI + ws streams)"
    - "01-08 (MEXC ws orchestration)"
  provides:
    - "Universe snapshot job (UNIV-01..04)"
    - "Tier-1 designation by 7d volume (D-46)"
    - "APScheduler 4 AsyncScheduler bootstrap (D-75)"
    - "D-77 job graph — 11 schedules"
    - "kv_state round-robin cursor persistence"
    - "FastAPI lifespan composition: scheduler + ws TaskGroup (D-76)"
    - "UNIV-03 Hypothesis point-in-time property test"
    - "ORCH-01 lifespan smoke integration test"
  affects:
    - "src/shortfire/entrypoints/data_platform.py"
    - "src/shortfire/ingest/universe/"
    - "src/shortfire/ingest/scheduler/"
    - "src/shortfire/ingest/state/"
tech_stack:
  added:
    - "apscheduler[sqlalchemy,asyncpg]==4.0.0a6 (pinned alpha; legitimacy verified at checkpoint)"
    - "sniffio>=1.3 (asyncpg event broker dependency)"
  patterns:
    - "AsyncScheduler + SQLAlchemyDataStore + AsyncpgEventBroker (D-75)"
    - "CoalescePolicy.latest + misfire_grace_time on all schedules (P1-A / Pattern 5)"
    - "Top-level async callables — no closures (D-79)"
    - "COPY staging table for hypertable writes (D-62)"
    - "kv_state JSONB cursor for round-robin ingest continuations"
    - "asynccontextmanager with AsyncGenerator return type (pyright strict)"
    - "Hypothesis @given + suppress_health_check for integration property tests (UNIV-03)"
    - "noqa: SIM117 for intentional nested async with ordering (D-76)"
key_files:
  created:
    - "src/shortfire/ingest/universe/__init__.py"
    - "src/shortfire/ingest/universe/snapshot.py"
    - "src/shortfire/ingest/universe/tier1.py"
    - "src/shortfire/ingest/state/__init__.py"
    - "src/shortfire/ingest/state/kv_state.py"
    - "src/shortfire/ingest/scheduler/__init__.py"
    - "src/shortfire/ingest/scheduler/bootstrap.py"
    - "src/shortfire/ingest/scheduler/jobs.py"
    - "tests/unit/ingest/test_universe_filter.py"
    - "tests/unit/ingest/test_new_listing_detection.py"
    - "tests/unit/ingest/test_kv_state.py"
    - "tests/unit/scheduler/__init__.py"
    - "tests/unit/scheduler/test_job_graph.py"
    - "tests/integration/ingest/test_universe_point_in_time.py"
    - "tests/integration/ingest/test_universe_daily_refresh.py"
    - "tests/integration/scheduler/__init__.py"
    - "tests/integration/scheduler/test_scheduler_lifespan.py"
  modified:
    - "pyproject.toml (add apscheduler + sniffio)"
    - "src/shortfire/entrypoints/data_platform.py (lifespan: scheduler + ws TaskGroup)"
decisions:
  - "APScheduler 4.0.0a6 pinned exact (alpha; legitimacy checkpoint cleared before install)"
  - "D-78: ws streams are TaskGroup-owned under FastAPI lifespan; APScheduler handles cron/interval only"
  - "D-79: all 11 job callables are top-level async functions — no closures; ensures APScheduler serialization"
  - "UNIV-02: universe_snapshot_job writes ALL USDT-perp symbols (qualifying + non-qualifying) for completeness; is_qualifying flag discriminates"
  - "kv_state uses INSERT ... ON CONFLICT DO UPDATE to persist cursor state; job_id prefix determines source/dataset"
  - "APScheduler 4 creates tables named schedules/tasks/jobs/job_results/metadata (NOT apscheduler_* prefix)"
  - "Degraded mode: if MEXC settings absent, data_platform.py runs scheduler-only (ws streams skipped)"
metrics:
  duration: "~25h (multi-session across checkpoint)"
  completed: "2026-05-22"
  tasks_completed: 2
  files_created: 17
  files_modified: 2
---

# Phase 1 Plan 9: Universe Snapshots + APScheduler 4 Bootstrap + D-77 Job Graph Summary

Universe snapshot job with survivorship-bias defence (UNIV-03 Hypothesis property), tier-1 designation by 7d volume, APScheduler 4.0.0a6 AsyncScheduler with SQLAlchemyDataStore + AsyncpgEventBroker, D-77 job graph (11 schedules), and FastAPI lifespan composition with MEXC ws TaskGroup under one lifespan context.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| Pre-task | Pin APScheduler 4.0.0a6 to pyproject.toml + uv sync | `3095c43` | pyproject.toml |
| 1 | Universe snapshot job + tier-1 + kv_state + UNIV-03 Hypothesis | `013d3d6` | snapshot.py, tier1.py, kv_state.py, 5 test files |
| 2 | APScheduler bootstrap + D-77 job graph + lifespan composition + ORCH-01 | `9416719` | bootstrap.py, jobs.py, data_platform.py, 4 test files |

## What Was Built

### Universe Snapshots (UNIV-01..04, STOR-06/07)

`src/shortfire/ingest/universe/snapshot.py` implements the daily universe snapshot job:
- `filter_qualifying_tickers(tickers)` — filters USDT-perp symbols by `quote_volume_usd > $500,000` (strict), marks `is_qualifying=True`
- Writes ALL symbols (qualifying + non-qualifying) to `universe_snapshots` hypertable for completeness (UNIV-02)
- Diffs yesterday vs today to detect new listings and delistings (UNIV-04)
- New symbols UPSERT into `symbols` table; delisted symbols get `symbols.delisted_at = now()` (STOR-07, never physical DELETE)
- `universe_at(engine, snapshot_date)` — point-in-time query returns exact qualifying symbol set for a given date, invariant under future writes (UNIV-03)

### Tier-1 Designation (D-46)

`src/shortfire/ingest/universe/tier1.py` implements `recompute_tier1(engine, top_n=50)`:
- Ranks symbols by 7-day SUM(volume) from `raw_mexc_candles_1d`
- Sets `symbols.tier=1` for top 50, `symbols.tier=2` for rest via bulk UPDATE

### kv_state Round-Robin Cursor (DATA-07/08)

`src/shortfire/ingest/state/kv_state.py`:
- `load_kv_state(engine, job_id)` — fetches latest `ingest_runs.kv_state` JSONB for job_id, parses JSON string if asyncpg returns string instead of dict, returns `{}` if no row
- `save_kv_state(engine, job_id, state)` — INSERT INTO ingest_runs with `kv_state = :st::jsonb`; derives `source` and `dataset` from job_id prefix (mexc → mexc_native, coinglass → coinglass_aggregate)

### APScheduler 4 Bootstrap (D-75/76)

`src/shortfire/ingest/scheduler/bootstrap.py`:
- `build_async_scheduler(engine)` — constructs `AsyncScheduler(SQLAlchemyDataStore(engine), AsyncpgEventBroker.from_async_sqla_engine(engine))`
- `scheduler_lifespan(engine) -> AsyncGenerator[AsyncScheduler, None]` — async context manager: enters `async with scheduler:`, calls `register_all_jobs`, `start_in_background()`, yields scheduler, auto-stops on exit

### D-77 Job Graph — 11 Schedules (ORCH-01/02)

`src/shortfire/ingest/scheduler/jobs.py` — `register_all_jobs(scheduler)` adds:

**Cron jobs (CronTrigger, timezone="UTC"):**
| Job ID | Schedule | Pattern |
|--------|----------|---------|
| universe.snapshot | 00:05 daily | Daily MEXC + CoinGecko universe refresh |
| coingecko.universe | 00:30 daily | CoinGecko coin metadata |
| backup.pg_dump | 01:00 daily | pg_dump to Railway volume |

**Interval jobs (IntervalTrigger):**
| Job ID | Interval |
|--------|----------|
| coinglass.funding_agg | 5m |
| coinglass.oi | 5m |
| coinglass.liq | 10m |
| coinglass.lsr | 15m |
| mexc.oi.poll | 5m |
| mexc.candles.backfill.1d | 6h |
| freshness.check | 30m |
| dead_letter.alert | 1h |

All 11 schedules use `coalesce=CoalescePolicy.latest` + `misfire_grace_time=300` per Pattern 5 (P1-A anti-burst defence).

All 11 callables are top-level async functions with primitive args (D-79, no closures).

Zero `... # planner fills in` placeholder bodies (B2 guarantee).

### FastAPI Lifespan Composition (D-76/78)

`src/shortfire/entrypoints/data_platform.py`:
- Full mode: `async with scheduler_lifespan(engine):` (outer) → `async with mexc_ws_streams(engine, mexc_client, symbols, tier1, settings):` (inner)
- Ordering is intentional per D-76: scheduler enters first, ws streams enter second; shutdown reverses: ws cancels, scheduler stops; prevents ingest_runs writes after DB close
- Degraded mode: if `settings.mexc is None`, runs scheduler-only (ws streams skipped)
- Uses `await mexc_client.close()` (public method, not `_client.close()`)

## Verification

- **Unit tests**: 138 passed (includes 6 universe filter/listing, 5 kv_state, 8 job graph, 119 prior tests)
- **Integration**: UNIV-03 Hypothesis property (15 examples, point-in-time invariance), UNIV daily refresh smoke, ORCH-01 APScheduler lifespan smoke (testcontainer)
- **Pyright**: 0 errors, 1 known warning (ccxt.pro missing stubs — pre-existing)
- **Ruff**: All checks pass

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] APScheduler 4 table names differ from expected**
- **Found during:** Task 2 integration test (ORCH-01)
- **Issue:** Initial ORCH-01 test checked for `tablename LIKE 'apscheduler_%'` but APScheduler 4.0.0a6 creates tables named `schedules`, `tasks`, `jobs`, `job_results`, `metadata` (no prefix)
- **Fix:** Updated test query to `WHERE tablename IN ('schedules', 'tasks', ...)` and assertion to `assert "schedules" in tables`
- **Files modified:** `tests/integration/scheduler/test_scheduler_lifespan.py`
- **Commit:** `9416719`

**2. [Rule 1 - Bug] pyright reportPrivateUsage on mexc_client._client.close()**
- **Found during:** Task 2 pyright check
- **Issue:** `mexc_client._client.close()` flagged as reportPrivateUsage; MexcClient has a public `close()` method
- **Fix:** Changed to `await mexc_client.close()`
- **Files modified:** `src/shortfire/entrypoints/data_platform.py`
- **Commit:** `9416719`

**3. [Rule 1 - Bug] AsyncIterator deprecation in scheduler_lifespan return type**
- **Found during:** Task 2 pyright check
- **Issue:** `@asynccontextmanager` with `-> AsyncIterator[AsyncScheduler]` is deprecated in Python 3.13+; pyright strict flag
- **Fix:** Changed to `-> AsyncGenerator[AsyncScheduler, None]` with updated import
- **Files modified:** `src/shortfire/ingest/scheduler/bootstrap.py`
- **Commit:** `9416719`

**4. [Rule 2 - Missing critical] noqa: SIM117 for intentional nested async with**
- **Found during:** Task 2 ruff check
- **Issue:** Ruff SIM117 flagged nested `async with` blocks in data_platform.py; the nesting is intentional per D-76 ordering semantics
- **Fix:** Added `# noqa: SIM117` comment with explanation
- **Files modified:** `src/shortfire/entrypoints/data_platform.py`
- **Commit:** `9416719`

**5. [Rule 1 - Bug] test_kv_state.py SIM108 if/else should be ternary**
- **Found during:** Pre-commit hook on Task 2 commit attempt
- **Issue:** ruff SIM108 found `if row_value is None: mock_first = None else: mock_first = (row_value,)` not as ternary
- **Fix:** Changed to `mock_first = None if row_value is None else (row_value,)`
- **Files modified:** `tests/unit/ingest/test_kv_state.py`
- **Commit:** `9416719` (after re-staging)

## Known Stubs

None. All job callables have complete implementations with `load_kv_state`/`save_kv_state` wired. Zero placeholder bodies.

## Threat Flags

None. No new network endpoints, auth paths, or trust-boundary crossings introduced beyond what the plan specified.

## Self-Check: PASSED

Files created/exist:
- `src/shortfire/ingest/universe/snapshot.py` — FOUND
- `src/shortfire/ingest/universe/tier1.py` — FOUND
- `src/shortfire/ingest/state/kv_state.py` — FOUND
- `src/shortfire/ingest/scheduler/bootstrap.py` — FOUND
- `src/shortfire/ingest/scheduler/jobs.py` — FOUND

Commits exist:
- `3095c43` chore(01-09): pin apscheduler 4.0.0a6 — FOUND
- `013d3d6` feat(01-09): universe snapshot job — FOUND
- `9416719` feat(01-09): APScheduler bootstrap + D-77 job graph — FOUND
