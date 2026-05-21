---
phase: "01"
plan: "04"
subsystem: db-schema
tags: [alembic, timescaledb, continuous-aggregates, orm, tdd]
dependency_graph:
  requires: ["01-01", "01-02", "01-03"]
  provides: ["migrations-0009-0014", "orm-models-aux", "create_continuous_aggregate-helper", "STOR-05-keystone"]
  affects: ["01-05", "01-06", "01-07"]
tech_stack:
  added: ["create_continuous_aggregate helper (D-95 carve-out)"]
  patterns:
    - "Two-call CA DDL: CREATE MATERIALIZED VIEW WITH NO DATA + add_continuous_aggregate_policy"
    - "Composite PK (id, ts) on TimescaleDB hypertables for non-time-dimension tables"
    - "DateTime(timezone=True) in ORM to avoid TIMESTAMP grep guard"
    - "D-27 discipline: all TimescaleDB DDL through helpers, no raw op.execute in migrations"
key_files:
  created:
    - alembic/versions/0009_raw_coinglass.py
    - alembic/versions/0010_raw_coingecko_market.py
    - alembic/versions/0011_universe_snapshots.py
    - alembic/versions/0012_symbols_lookup.py
    - alembic/versions/0013_dead_letter_and_ingest_runs.py
    - alembic/versions/0014_continuous_aggregates_5m_15m_1h_4h.py
    - src/shortfire/db/models/__init__.py
    - src/shortfire/db/models/symbols.py
    - src/shortfire/db/models/ingest_runs.py
    - src/shortfire/db/models/dead_letter.py
    - tests/integration/db/test_phase1_aux_schema.py
    - tests/integration/db/test_symbols_soft_delete.py
    - tests/unit/db/test_create_continuous_aggregate_helper.py
    - tests/integration/db/test_continuous_aggregates.py
  modified:
    - src/shortfire/db/timescale.py
decisions:
  - "create_continuous_aggregate uses two separate op.execute calls (CREATE VIEW + policy) to avoid asyncpg multi-statement prepared statement restriction"
  - "CREATE MATERIALIZED VIEW ... WITH NO DATA avoids transaction block error inside Alembic transaction_per_migration=True"
  - "dead_letter.raw_payload is TEXT not JSONB — malformed JSON payloads must be storable"
  - "universe_snapshots uses DATE partition column (not TIMESTAMPTZ) — D-64 locked"
  - "symbols is relational (no create_hypertable) — D-63 locked"
  - "Composite PK (id, ts) on dead_letter and ingest_runs — TimescaleDB requires partition column in PK"
  - "ON DELETE CASCADE banned everywhere in public schema — test greps all alembic/versions/*.py"
metrics:
  duration_minutes: 180
  completed_date: "2026-05-21T18:22:14Z"
  tasks_completed: 2
  files_created: 14
  files_modified: 1
---

# Phase 01 Plan 04: Auxiliary Schema + Continuous Aggregates Summary

**One-liner:** Alembic migrations 0009-0014 covering Coinglass/CoinGecko/universe/symbols/ingest_runs/dead_letter hypertables plus TimescaleDB continuous aggregate helper with locked D-67 refresh policies and STOR-05 keystone parity test.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Migrations 0009-0013 + ORM models (Symbol, IngestRun, DeadLetter) + integration tests | `08b048f` | 13 files created |
| 2 | `create_continuous_aggregate` helper + migration 0014 (5m/15m/1h/4h CAs) + unit + integration tests | `5fb2834` | 4 files created, 1 modified |

## Verification

- Unit tests: 5/5 (CA helper SQL shape, group_by, schedule_interval params)
- Integration tests: 33/33 (aux schema, CA existence, STOR-05 parity, symbols soft-delete, no-CASCADE)
- Full DB test suite: 76/76
- Pre-commit guards: all green (TIMESTAMP-without-tz, ON DELETE CASCADE, ruff format/lint, secrets)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TimescaleDB PK constraint error on dead_letter and ingest_runs**
- **Found during:** Task 1 — integration test run
- **Issue:** `ERROR: cannot create a unique index without the column "ts"` — TimescaleDB requires partition column in PK
- **Fix:** Changed PK from `(id)` to `(id, ts)` in both migration 0013 and ORM models
- **Files modified:** `alembic/versions/0013_dead_letter_and_ingest_runs.py`, `src/shortfire/db/models/ingest_runs.py`, `src/shortfire/db/models/dead_letter.py`
- **Commit:** `08b048f`

**2. [Rule 1 - Bug] TIMESTAMP grep guard triggered by SQLAlchemy imports in ORM models**
- **Found during:** Task 1 — pre-commit run
- **Issue:** `from sqlalchemy import TIMESTAMP` in ORM model files triggered the `TIMESTAMP[^(]` guard
- **Fix:** Switched all ORM model files to use `DateTime(timezone=True)` instead of TIMESTAMP
- **Files modified:** `src/shortfire/db/models/symbols.py`, `src/shortfire/db/models/ingest_runs.py`, `src/shortfire/db/models/dead_letter.py`
- **Commit:** `08b048f`

**3. [Rule 1 - Bug] ON DELETE CASCADE grep guard triggered by docstring content**
- **Found during:** Task 1 (migration 0012 docstring), Task 2 (migration 0014 downgrade docstring)
- **Issue:** Explanatory text in docstrings contained the literal string "ON DELETE CASCADE" which the file-grep test catches
- **Fix 0012:** Replaced "ON DELETE CASCADE" with "cascade deletes" in docstring
- **Fix 0014:** Replaced "ON DELETE CASCADE" in explanatory sentence with "cascade-on-delete FK syntax"
- **Files modified:** `alembic/versions/0012_symbols_lookup.py`, `alembic/versions/0014_continuous_aggregates_5m_15m_1h_4h.py`
- **Commit:** `08b048f`, `5fb2834`

**4. [Rule 1 - Bug] asyncpg multi-statement prepared statement error for CA DDL**
- **Found during:** Task 2 — design-time (caught from asyncpg docs)
- **Issue:** asyncpg forbids multiple SQL commands in a single prepared statement; original plan had a single `op.execute` with both CREATE VIEW and policy SELECT
- **Fix:** Split into two separate `op.execute()` calls; updated unit tests to expect `call_count == 2` with `_combined_sql()` helper
- **Files modified:** `src/shortfire/db/timescale.py`, `tests/unit/db/test_create_continuous_aggregate_helper.py`
- **Commit:** `5fb2834`

**5. [Rule 1 - Bug] CASCADE check too broad — caught TimescaleDB internal schema objects**
- **Found during:** Task 1 — integration test run
- **Issue:** `pg_constraint` query without namespace filter returned 19 CASCADE constraints from TimescaleDB catalog
- **Fix:** Added `AND n.nspname = 'public'` to scope cascade check to user tables only
- **Files modified:** `tests/integration/db/test_symbols_soft_delete.py`
- **Commit:** `08b048f`

**6. [Rule 1 - Bug] CREATE MATERIALIZED VIEW WITH DATA fails inside Alembic transaction block**
- **Found during:** Task 2 — design-time (TimescaleDB docs)
- **Issue:** `CREATE MATERIALIZED VIEW ... WITH DATA` cannot run inside `transaction_per_migration=True`
- **Fix:** Added `WITH NO DATA` to CREATE statement; CA refresh policy handles future materialization
- **Files modified:** `src/shortfire/db/timescale.py`, `alembic/versions/0014_continuous_aggregates_5m_15m_1h_4h.py`
- **Commit:** `5fb2834`

## Known Stubs

None — all migrations fully wired, ORM models complete, test assertions on real schema.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundary changes. Schema-only migrations with pre-commit guards enforcing no unsafe patterns.

## Self-Check: PASSED

Files verified present:
- `alembic/versions/0014_continuous_aggregates_5m_15m_1h_4h.py` FOUND
- `src/shortfire/db/timescale.py` FOUND (create_continuous_aggregate present)
- `src/shortfire/db/models/symbols.py` FOUND
- `src/shortfire/db/models/ingest_runs.py` FOUND
- `src/shortfire/db/models/dead_letter.py` FOUND
- `tests/unit/db/test_create_continuous_aggregate_helper.py` FOUND
- `tests/integration/db/test_continuous_aggregates.py` FOUND

Commits verified:
- `08b048f` feat(01-04): migrations 0009-0013 + ORM models for aux schema FOUND
- `5fb2834` feat(01-04): create_continuous_aggregate helper + migration 0014 + STOR-05 tests FOUND
