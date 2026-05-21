---
phase: 00-foundation
plan: "06"
subsystem: testing
tags: [python, docker, testcontainers, timescaledb, migrations, integration-tests, asyncpg, alembic]

# Dependency graph
requires:
  - phase: 00-04
    provides: Alembic async env.py + 2 migrations (init extension + service_event hypertable with compression policy) + db/timescale.py DDL helpers

provides:
  - docker-compose.yml providing local TimescaleDB (timescale/timescaledb:2.18.0-pg16) for developer machines (D-25)
  - Session-scoped testcontainers PostgresContainer fixture that amortizes container startup across all integration tests (Pitfall 5)
  - Session-scoped migrated_db fixture that runs alembic upgrade head once per session against a real Timescale container
  - Function-scoped clean_service_event fixture that TRUNCATEs between tests for isolation
  - 3 D-31 integration tests: idempotent rerun, hypertable existence, compression policy existence
  - FOUND-03 runtime gate satisfied — migrations proved on a real Timescale 2.18.0-pg16 instance
  - OPS-07 partial runtime evidence — migration discipline exercised against real Timescale before Railway wiring in 00-07

affects:
  - 00-07-PLAN.md (preDeployCommand migration wiring builds on this runtime gate evidence)
  - 00-08-PLAN.md (CI integration test step runs pytest -m integration)
  - Phase 1 data platform (any phase touching TimescaleDB can trust the migration is environment-agnostic)

# Tech tracking
tech-stack:
  added:
    - testcontainers[postgres] (session-scoped PostgresContainer against timescale/timescaledb:2.18.0-pg16)
    - greenlet (required by SQLAlchemy async — added as direct project dependency)
  patterns:
    - Session-scoped testcontainer fixture: start once per session, truncate between tests (Pitfall 5 mitigation)
    - URL rewrite pattern: strip +psycopg2 from testcontainers URL before passing to alembic subprocess; asyncpg connect uses plain postgresql:// form
    - Subprocess alembic: run via subprocess.run(["uv", "run", "alembic", "upgrade", "head"]) with DATABASE_URL injected via env, not Python import
    - timescaledb_information system views for assertion: .hypertables for existence, .jobs for compression policy, .job_stats / compression_settings for column-level verification

key-files:
  created:
    - docker-compose.yml
    - tests/integration/conftest.py
    - tests/integration/db/__init__.py
    - tests/integration/db/test_alembic_and_hypertables.py
  modified:
    - pyproject.toml (added greenlet dependency)
    - uv.lock (updated lockfile)

key-decisions:
  - "greenlet added as explicit project dependency — SQLAlchemy 2.x async engine requires it at runtime; was previously a transitive dep not pinned"
  - "Compression-policy test asserts against actual TimescaleDB 2.18.0 schema columns (attname / segmentby_column_index / orderby_asc in _timescaledb_catalog.compression_settings) rather than the timescaledb_information.compression_settings view column names documented in older Timescale versions — view column names differ between Timescale minor versions; catalog-level assertion is stable"
  - "Session-scoped testcontainer pattern (Pitfall 5): single container start, alembic upgrade head once, TRUNCATE per test — total integration suite 3.41s vs ~60s with per-test container start"

patterns-established:
  - "Integration test isolation: session-scoped container + migration, function-scoped TRUNCATE — never recreate the container per test"
  - "URL normalization at conftest boundary: testcontainers returns postgresql+psycopg2://...; strip +psycopg2 before subprocess alembic; strip +asyncpg suffix for asyncpg.connect()"
  - "D-31 test triad: (1) idempotent rerun of alembic upgrade head, (2) hypertable existence via timescaledb_information.hypertables, (3) compression policy via timescaledb_information.jobs + catalog-level column verification"

requirements-completed:
  - FOUND-03
  - OPS-07
  - TEST-01
  - TEST-05

# Metrics
duration: ~35min
completed: 2026-05-21
---

# Phase 00 Plan 06: Docker Compose + TimescaleDB Integration Tests Summary

**testcontainers-driven FOUND-03 runtime gate: alembic upgrade head proven idempotent on real timescale/timescaledb:2.18.0-pg16 with service_event hypertable and compression policy (segment_by=service_name, order_by=ts DESC) verified via catalog assertions**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-05-21 (approx)
- **Completed:** 2026-05-21T13:07:07Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- docker-compose.yml ships local TimescaleDB for developer onboarding (D-25): `timescale/timescaledb:2.18.0-pg16`, TIMESCALEDB_TELEMETRY=off, healthcheck, named volume shortfire-pg
- Session-scoped testcontainers PostgresContainer fixture amortizes ~10s container startup; alembic upgrade head runs exactly once per session via subprocess (Pitfall 5 fully mitigated — total suite runtime 3.41s)
- 3 D-31 integration tests all pass: idempotent rerun exits 0, service_event confirmed hypertable, compression job confirmed with segment_by=service_name / order_by=ts DESC
- Human checkpoint verified: orchestrator re-ran the suite standalone (3 passed in 3.41s), docker-compose stack brought up and torn down cleanly

## Task Commits

Each task was committed atomically:

1. **Task 1: docker-compose.yml + session-scoped PostgresContainer + alembic upgrade head once-per-session** - `e6821e1` (feat)
2. **Task 2: 3 D-31 integration tests against real TimescaleDB container** - `aab495f` (feat)

**Plan metadata:** *(this commit)*

## Files Created/Modified

- `docker-compose.yml` — Local TimescaleDB service (timescale/timescaledb:2.18.0-pg16, TIMESCALEDB_TELEMETRY=off, healthcheck, volume shortfire-pg)
- `tests/integration/conftest.py` — Session-scoped PostgresContainer fixture, session-scoped migrated_db (alembic upgrade head once), function-scoped clean_service_event (TRUNCATE isolation)
- `tests/integration/db/__init__.py` — Empty package marker
- `tests/integration/db/test_alembic_and_hypertables.py` — 3 D-31 integration tests (idempotent, hypertable, compression policy)
- `pyproject.toml` — Added greenlet as explicit dependency
- `uv.lock` — Updated lockfile with greenlet pin

## Decisions Made

- **greenlet as explicit dependency:** SQLAlchemy 2.x async requires greenlet at runtime; it was previously present only as a transitive dependency, which is fragile. Added explicitly to pyproject.toml.
- **Compression-policy test rewritten against catalog schema:** `timescaledb_information.compression_settings` view column names differ across Timescale minor versions. Test now asserts against `_timescaledb_catalog` columns (`attname`, `segmentby_column_index`, `orderby_asc`) for stable semantics. Business invariant preserved: segment_by='service_name', order_by='ts DESC'.
- **URL normalization convention:** testcontainers returns `postgresql+psycopg2://...`; conftest strips `+psycopg2` for alembic subprocess; test file strips `+asyncpg` suffix for bare `asyncpg.connect()`. Documented in conftest.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added greenlet as explicit project dependency**
- **Found during:** Task 2 (integration test execution)
- **Issue:** SQLAlchemy 2.x async engine requires greenlet at runtime. It was a transitive dependency, not pinned — fragile in reproducible environments.
- **Fix:** Added `greenlet` to `[project.dependencies]` in pyproject.toml; uv.lock updated.
- **Files modified:** pyproject.toml, uv.lock
- **Verification:** Integration tests pass with greenlet present as direct dep.
- **Committed in:** aab495f (Task 2 commit)

**2. [Rule 1 - Bug] Compression-policy test rewritten against actual TimescaleDB 2.18.0 schema**
- **Found during:** Task 2 (test_service_event_has_compression_policy)
- **Issue:** The plan specified asserting `compress_segmentby='service_name'` and `compress_orderby='ts DESC'` from `timescaledb_information.compression_settings` — but the real Timescale 2.18.0-pg16 container exposed those columns under different names in that view (`attname`, `segmentby_column_index`, `orderby_asc` in `_timescaledb_catalog.compression_settings`). Direct use of the plan-specified column names would have raised `UndefinedColumnError`.
- **Fix:** Rewrote assertion to query `_timescaledb_catalog.compression_settings` joined with `pg_attribute` and verify `attname = 'service_name'` (segment) + `orderby_asc = false` (DESC order). Semantic invariant (segment_by=service_name, order_by=ts DESC) is fully preserved.
- **Files modified:** tests/integration/db/test_alembic_and_hypertables.py
- **Verification:** `test_service_event_has_compression_policy PASSED` — 3/3 tests green.
- **Committed in:** aab495f (Task 2 commit)
- **Human-approved:** Orchestrator verified both deviations accepted at checkpoint.

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 bug)
**Impact on plan:** Both fixes necessary for correctness. No scope creep. Semantic intent of all 3 tests fully preserved.

## Integration Test Evidence

```
tests/integration/db/test_alembic_and_hypertables.py::test_alembic_upgrade_is_idempotent PASSED
tests/integration/db/test_alembic_and_hypertables.py::test_service_event_is_hypertable PASSED
tests/integration/db/test_alembic_and_hypertables.py::test_service_event_has_compression_policy PASSED
3 passed in 3.41s
```

- Total runtime: 3.41s (well under 90s target — Pitfall 5 mitigation effective)
- Container image used: `timescale/timescaledb:2.18.0-pg16`
- Orchestrator additionally: spun up docker-compose stack standalone, confirmed healthy, ran same testcontainers suite again (3 passed in 3.41s), tore down cleanly

## Issues Encountered

None beyond the two auto-fixed deviations documented above. Docker was available in the execution environment.

## User Setup Required

None — no external service configuration required. `docker-compose up postgres` is self-contained for local dev.

## Next Phase Readiness

- FOUND-03 runtime gate satisfied — 00-07 (Railway deployment + preDeployCommand) can proceed
- OPS-07 runtime gate partially satisfied — migration discipline proven on real Timescale; 00-07 will wire `alembic upgrade head` as Railway preDeployCommand
- 00-08 (Fakes + GitHub Actions CI) can wire `pytest -m integration` step with confidence it passes in a Docker-available environment
- Remaining concern: CI Docker availability (GitHub Actions ubuntu-latest has Docker; Railway review environments may need a separate step) — surface at 00-08 planning

---
*Phase: 00-foundation*
*Completed: 2026-05-21*
