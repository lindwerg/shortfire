---
phase: 1
plan: "01"
subsystem: ingest
tags:
  - python
  - ingest
  - infrastructure
  - domain
  - tenacity
  - aiolimiter
  - asyncpg
  - timescaledb

dependency_graph:
  requires:
    - "Phase 0 domain types (Candle, OrderBook, Funding, Liquidation)"
    - "shortfire.db.engine.create_engine_from_env"
    - "shortfire.observability.metrics.build_metrics_for_service"
    - "shortfire.settings.data_platform.DataPlatformSettings"
  provides:
    - "copy_into_hypertable: asyncpg COPY staging helper for all hot-path hypertable writes"
    - "mexc_retry / coinglass_retry / coingecko_retry: per-source tenacity retry decorators"
    - "MEXC_LIMITER / COINGLASS_LIMITER / COINGECKO_LIMITER: aiolimiter token buckets"
    - "get_engine / get_settings / get_metrics: lazy process-wide singletons for APScheduler jobs"
    - "write_to_dead_letter: dead-letter queue writer for failed ingest rows"
    - "ts_from_ms: UTC datetime helper; log: structlog ingest logger"
    - "Widened Source Literal to 4 D-59 values; all Phase 0 tests updated"
  affects:
    - "All future ingest modules (plans 01-02 through 01-12) depend on this seam"

tech_stack:
  added:
    - "tenacity 9.x retry decorators (wait_exponential_jitter, before_sleep_log)"
    - "aiolimiter 1.2+ AsyncLimiter token buckets"
    - "asyncpg copy_records_to_table via SQLAlchemy get_raw_connection().driver_connection"
    - "structlog get_logger for structured ingest logging"
  patterns:
    - "UNLOGGED staging table → INSERT ... ON CONFLICT DO NOTHING (first-write-wins, D-62)"
    - "Module-level None sentinels with lazy init for APScheduler-compatible singletons (D-79)"
    - "Module-level imports (not lazy) in writer.py to enable unittest.mock.patch"

key_files:
  created:
    - src/shortfire/ingest/base.py
    - src/shortfire/ingest/context.py
    - src/shortfire/ingest/retry.py
    - src/shortfire/ingest/rate_limit.py
    - src/shortfire/ingest/storage/__init__.py
    - src/shortfire/ingest/storage/copy.py
    - src/shortfire/ingest/dead_letter/__init__.py
    - src/shortfire/ingest/dead_letter/writer.py
    - tests/unit/ingest/__init__.py
    - tests/unit/ingest/test_retry_policies.py
    - tests/unit/ingest/test_rate_limit.py
    - tests/unit/ingest/test_copy_into_hypertable.py
    - tests/unit/ingest/test_dead_letter_writer.py
  modified:
    - src/shortfire/domain/market.py
    - pyproject.toml
    - tests/unit/domain/test_candle.py
    - tests/unit/domain/test_orderbook.py
    - tests/unit/domain/test_liquidation.py
    - tests/unit/domain/test_funding.py
    - tests/unit/domain/test_timestamps_are_aware.py
    - tests/unit/clients/test_fakes_match_protocols.py

decisions:
  - "Source Literal widened from 3 values to 4 D-59 values in single atomic commit with all test updates"
  - "copy_into_hypertable uses assert raw_conn is not None to satisfy pyright strict after SQLAlchemy typed driver_connection as None"
  - "writer.py uses module-level imports (not lazy) so patch() can target shortfire.ingest.dead_letter.writer.copy_into_hypertable"
  - "TIMESTAMPTZ removed from docstring (replaced with plain English) to satisfy ban-naive-timestamp pre-commit hook"
  - "test_retry_policies.py uses _get_retrying(decorator: Any) -> Any with # type: ignore[attr-defined] on stub.retry to satisfy pyright strict without fighting tenacity's untyped decorator"

metrics:
  duration: "~45 minutes (dominated by tenacity actual retry wait times in tests)"
  completed: "2026-05-21T17:56:02Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 13
  files_modified: 6
---

# Phase 1 Plan 01: Ingest Infrastructure Seam Summary

**One-liner:** Domain Source Literal widened to 4 values + full ingest seam: per-source tenacity/aiolimiter, asyncpg COPY staging helper, process-wide singletons, dead-letter writer, base logger/timestamp.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Widen domain Source Literal (D-59) + update Phase 0 tests | `6875082` | market.py + 6 test files |
| 2 | Ingest infrastructure seam (retry, rate-limit, copy, context, dead-letter, base) | `9b9adef` | 8 new src files + 5 new test files + pyproject.toml |

## What Was Built

### Task 1 — Domain Source widening

`Source = Literal["mexc_native", "coinglass_aggregate", "coinglass_mexc_only", "coingecko"]` replaces the old 3-value literal. All Phase 0 fixtures and tests updated in the same commit. Two new regression tests added: `test_candle_rejects_old_mexc_source_label` and `test_candle_rejects_old_coinglass_source_label`.

### Task 2 — Ingest seam modules

- **`retry.py`**: Three tenacity decorators — `mexc_retry` (6 attempts, initial=2s, max=120s, also catches TimeoutError), `coinglass_retry` (5/1s/60s), `coingecko_retry` (4/1s/60s). All use `wait_exponential_jitter`, `before_sleep_log`, `reraise=True`.

- **`rate_limit.py`**: Module-level `AsyncLimiter` instances: `MEXC_LIMITER(18, 1)`, `COINGLASS_LIMITER(28, 60)`, `COINGECKO_LIMITER(28, 60)`.

- **`storage/copy.py`**: `async def copy_into_hypertable(engine, target_table, records, columns, conflict_columns) -> int`. Pattern: materialize → short-circuit if empty → UNLOGGED staging table → TRUNCATE → asyncpg `copy_records_to_table` → `INSERT ... ON CONFLICT (...) DO NOTHING` → return count. Structural test asserts "DO UPDATE" never appears in module source.

- **`context.py`**: Lazy module-level singletons `get_engine()`, `get_settings()`, `get_metrics()` using `if X is None` guards. Required for APScheduler 4.x top-level importable job callables (D-79).

- **`dead_letter/writer.py`**: `async def write_to_dead_letter(source, endpoint, symbol, raw_payload, error_type, error_msg, retries_attempted=0)`. Truncates `error_msg[:2000]`, decodes bytes payloads with `errors='replace'`, writes `quality_flag="schema_warn"`.

- **`base.py`**: `log = structlog.get_logger("ingest")` and `def ts_from_ms(ms: int) -> datetime` for tz-aware UTC conversion.

- **`pyproject.toml`**: Removed `"src/shortfire/ingest/*"` from `[tool.coverage.run] omit` (D-91).

## Verification

- 278/278 unit tests pass (`uv run pytest tests/unit -x -q`)
- 0 pyright errors (`uv run pyright src/`) — 32 warnings are expected `reportMissingTypeStubs` for internal modules imported in test functions
- 0 ruff errors (`uv run ruff check src/ tests/unit/ingest`)
- All pre-commit hooks pass including `ban-naive-timestamp`
- All 6 ingest modules import cleanly

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] pre-commit hook ban-naive-timestamp matched TIMESTAMPTZ in docstring**
- **Found during:** Task 2 commit
- **Issue:** The `dead_letter/writer.py` docstring contained `ts  TIMESTAMPTZ NOT NULL DEFAULT now()`. The hook regex `TIMESTAMP[^(]` matches `TIMESTAMPTZ` (Z is not `(`), causing the hook to fail.
- **Fix:** Replaced the SQL schema block in the docstring with a plain-English column list. The schema is defined in Alembic migrations, not duplicated in source docstrings.
- **Files modified:** `src/shortfire/ingest/dead_letter/writer.py`
- **Commit:** `9b9adef`

**2. [Rule 2 - Missing] assert for asyncpg driver_connection type narrowing**
- **Found during:** Task 2 pyright check
- **Issue:** `raw_connection_obj.driver_connection` is typed as `None` by pyright (SQLAlchemy's PoolProxiedConnection has `driver_connection: None` in stubs). All subsequent asyncpg calls on `raw_conn` were flagged as `reportOptionalMemberAccess`.
- **Fix:** Added `assert raw_conn is not None` after assignment to narrow the type for pyright.
- **Files modified:** `src/shortfire/ingest/storage/copy.py`
- **Commit:** `9b9adef`

**3. [Rule 1 - Bug] Module-level vs lazy imports in writer.py broke mock.patch**
- **Found during:** Task 2 — RED test run
- **Issue:** `copy_into_hypertable` and `get_engine` were initially imported inside the function body (lazy). `patch("shortfire.ingest.dead_letter.writer.copy_into_hypertable")` raised `AttributeError` because the names were not bound at module level.
- **Fix:** Moved both imports to module level so `patch()` can target the module's namespace.
- **Files modified:** `src/shortfire/ingest/dead_letter/writer.py`
- **Commit:** `9b9adef`

**4. [Rule 1 - Bug] pyright reportUntypedFunctionDecorator on _get_retrying helper**
- **Found during:** Task 2 pyright check
- **Issue:** `_get_retrying(decorator)` had no type annotations; `stub.retry` flagged as `Cannot access attribute "retry" for class "FunctionType"`.
- **Fix:** Added `decorator: Any` and `-> Any` annotations, plus `# type: ignore[attr-defined]` on `stub.retry`. This is correct: tenacity's decorator returns a wrapped callable with `.retry` injected at runtime, not in type stubs.
- **Files modified:** `tests/unit/ingest/test_retry_policies.py`
- **Commit:** `9b9adef`

## Known Stubs

None. All ingest helpers return real computed values — no hardcoded stubs, no placeholder data.

## Threat Flags

None. No new network endpoints, no auth paths introduced. The dead_letter table receives internal-only writes with no external read path (T-1-INF-02 accepted risk, deferred to Phase 5).

## Self-Check: PASSED

- `src/shortfire/ingest/base.py` — FOUND
- `src/shortfire/ingest/context.py` — FOUND
- `src/shortfire/ingest/retry.py` — FOUND
- `src/shortfire/ingest/rate_limit.py` — FOUND
- `src/shortfire/ingest/storage/copy.py` — FOUND
- `src/shortfire/ingest/dead_letter/writer.py` — FOUND
- `tests/unit/ingest/test_retry_policies.py` — FOUND
- `tests/unit/ingest/test_rate_limit.py` — FOUND
- `tests/unit/ingest/test_copy_into_hypertable.py` — FOUND
- `tests/unit/ingest/test_dead_letter_writer.py` — FOUND
- Commit `6875082` — FOUND (Task 1)
- Commit `9b9adef` — FOUND (Task 2)
