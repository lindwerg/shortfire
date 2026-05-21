---
phase: 01
plan: 03
subsystem: data-platform
tags:
  - alembic
  - timescaledb
  - migrations
  - hypertables
  - mexc
  - integration-tests
  - tdd
dependency_graph:
  requires:
    - 01-01 (copy_into_hypertable pattern — created here since parallel wave)
    - 00-06 (testcontainers + conftest fixtures)
  provides:
    - 7 MEXC-native hypertables (raw_mexc_candles_1m/1d, funding, oi, trades, l2_top20, liquidations)
    - copy_into_hypertable helper (src/shortfire/ingest/storage/copy.py)
    - Wave-0 keystone integration tests (source CHECK, idempotency)
  affects:
    - 01-04 (Coinglass/CoinGecko migrations depend on 0008 as down_revision base)
    - 01-05+ (all ingest workers write to these tables)
tech_stack:
  added:
    - TimescaleDB hypertables with chunk intervals per D-58
    - asyncpg COPY path via copy_into_hypertable helper
    - Hypothesis composite strategy for OHLCV records
  patterns:
    - ON CONFLICT DO NOTHING idempotency (D-62, DATA-09)
    - source TEXT NOT NULL + CHECK constraint on every raw table (D-59, DATA-12)
    - quality_flag TEXT NOT NULL DEFAULT 'ok' + CHECK enum (D-60)
    - ingested_at TIMESTAMP(timezone=True) NOT NULL DEFAULT now() (D-61)
    - Compression via shortfire.db.timescale helpers only (D-27, D-66)
key_files:
  created:
    - alembic/versions/0003_raw_mexc_candles_1m_1d.py
    - alembic/versions/0004_raw_mexc_funding.py
    - alembic/versions/0005_raw_mexc_oi.py
    - alembic/versions/0006_raw_mexc_trades.py
    - alembic/versions/0007_raw_mexc_l2_top20.py
    - alembic/versions/0008_raw_mexc_liquidations.py
    - src/shortfire/ingest/storage/__init__.py
    - src/shortfire/ingest/storage/copy.py
    - tests/integration/db/test_phase1_mexc_schema.py
    - tests/integration/db/test_source_check.py
    - tests/integration/ingest/__init__.py
    - tests/integration/ingest/test_idempotency.py
  modified: []
decisions:
  - "D-27/D-66: Zero raw op.execute for hypertable/compression DDL — all through helpers"
  - "timescaledb_information.dimensions.time_interval returns Python timedelta (not microseconds int) — Timescale 2.18 confirmed against live image"
  - "candle_record Hypothesis strategy uses sort-based OHLCV derivation to avoid st.decimals InvalidArgument on tight ranges"
  - "asyncpg.CheckViolationError is the correct exception class (not asyncpg.exceptions.CheckViolationError — same class, direct access works)"
  - "copy_into_hypertable created in plan 01-03 (not 01-01 as planned) due to parallel wave dependency — plan 01-01 will need to reconcile or the worktree merge will handle"
metrics:
  duration_seconds: 637
  completed_date: "2026-05-21"
  task_count: 3
  file_count: 12
---

# Phase 01 Plan 03: MEXC Hypertable Migrations + Wave-0 Integration Tests Summary

Alembic migrations 0003–0008 land 7 MEXC-native hypertables on TimescaleDB 2.18 with locked chunk intervals, compression policies, source attribution CHECK constraints, and quality_flag enums — verified by 23 integration tests against a real testcontainer.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Migrations 0003–0005 + schema test framework | 256cf71 | 0003,0004,0005 migration files + test_phase1_mexc_schema.py |
| 2 | Migrations 0006–0008 + chunk interval test fix | 30ab712 | 0006,0007,0008 migration files + test_phase1_mexc_schema.py updated |
| 3 | Wave-0 integration tests + copy_into_hypertable | 1bb6575 | copy.py, test_source_check.py, test_idempotency.py |

## The 7 Hypertables Created

| Table | chunk_interval | compress_after | segment_by | PK / dedup key |
|-------|---------------|----------------|------------|----------------|
| raw_mexc_candles_1m | 1 day | 7 days | symbol | (symbol, ts) |
| raw_mexc_candles_1d | 90 days | 30 days | symbol | (symbol, ts) |
| raw_mexc_funding | 30 days | 7 days | symbol | (symbol, settlement_ts) |
| raw_mexc_oi | 7 days | 7 days | symbol | (symbol, ts) |
| raw_mexc_trades | 1 day | 2 days | symbol | (symbol, ts, exchange_trade_id) |
| raw_mexc_l2_top20 | 1 day | 2 days | symbol | (symbol, ts) |
| raw_mexc_liquidations | 7 days | 7 days | symbol | (symbol, ts, side, qty, price) |

## raw_mexc_trades PK Decision

PK is `(symbol, ts, exchange_trade_id)`. The `exchange_trade_id` column stores the stable
unique ID returned by MEXC via ccxt 4.5 unified trades response. This was confirmed stable
per D-47. The informational fallback tuple `(symbol, ts, side, price, qty)` is documented
in a comment in the migration file but NOT used as the actual PK.

## Hypothesis Idempotency Test

- `max_examples=20`, `deadline=10_000ms`
- Actual execution time per Hypothesis run: ~6 seconds total (including container startup)
- Strategy: `candle_record()` composite generates 9-tuples via sort-based OHLCV derivation
  (avoids `st.decimals` `InvalidArgument` on tight min/max ranges)
- `suppress_health_check=[HealthCheck.function_scoped_fixture]` required for `migrated_db`
  session-scoped fixture used with `@given`

CI budget implication: At `max_examples=20` with `deadline=10s`, the property test
contributes ~6s to the integration suite. Raising to `max_examples=50` is safe if CI
wall-clock allows; stay at 20 for the Wave-0 baseline.

## asyncpg.CheckViolationError vs asyncpg.exceptions.CheckViolationError

Both paths work — `asyncpg.CheckViolationError` is re-exported at the top-level `asyncpg`
namespace. The test uses `asyncpg.CheckViolationError` directly (no `.exceptions.` prefix needed).

## Timescale 2.18 Dimension Column Finding

The plan spec referenced `chunk_time_interval_microseconds` (INT) as the column for chunk
interval in `timescaledb_information.dimensions`. This column does NOT exist in Timescale 2.18.
The correct column is `time_interval` which returns a Python `timedelta` (PostgreSQL INTERVAL).
The test was fixed in commit 30ab712 before going green.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] timescaledb_information.dimensions column name mismatch**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** Plan spec said use `interval_length` (INT microseconds); Timescale 2.18
  actually uses `time_interval` (INTERVAL → Python `timedelta`)
- **Fix:** Updated test to query `time_interval` and compare `timedelta` values
- **Files modified:** tests/integration/db/test_phase1_mexc_schema.py
- **Commit:** 30ab712

**2. [Rule 2 - Missing critical functionality] copy_into_hypertable created in 01-03**
- **Found during:** Task 3 planning
- **Issue:** Plan 01-01 (parallel wave) was expected to ship `copy_into_hypertable`;
  Task 3 idempotency test requires it. Since both plans are Wave 1, created it here.
- **Fix:** Created `src/shortfire/ingest/storage/copy.py` and `storage/__init__.py`
- **Files created:** src/shortfire/ingest/storage/copy.py, __init__.py
- **Commit:** 1bb6575
- **Note:** Plan 01-01 will encounter this file on merge; conflict is additive (same content
  per RESEARCH.md Pattern 1 spec).

**3. [Rule 1 - Bug] Hypothesis InvalidArgument in candle_record strategy**
- **Found during:** Task 3 (GREEN phase)
- **Issue:** `st.decimals(min_value=low, max_value=high, places=10)` raises InvalidArgument
  when low ≈ high and the range has fewer than 10 representable decimal values
- **Fix:** Replaced bounded st.decimals with sort-based derivation (4 independent money
  draws sorted to produce valid low/close/open/high)
- **Files modified:** tests/integration/ingest/test_idempotency.py
- **Commit:** 1bb6575

**4. [Rule 1 - Bug] TIMESTAMPTZ in docstrings triggered TIMESTAMP[^(] pre-commit guard**
- **Found during:** Task 1 (pre-commit)
- **Issue:** Docstring text `TIMESTAMPTZ` matched the grep pattern `TIMESTAMP[^(]`
- **Fix:** Changed docstring references from `TIMESTAMPTZ` to `TIMESTAMP(timezone=True)`
- **Files modified:** 0003, 0004, 0005 migration files
- **Commit:** 256cf71

## Wave-0 Keystone Test Results

All 23 integration tests pass against `timescale/timescaledb:2.18.0-pg16`:
- 16 in test_phase1_mexc_schema.py (hypertable existence, compression policy, chunk intervals)
- 6 in test_source_check.py (CHECK rejection, 4 valid values, pg_constraint coverage)
- 1 in test_idempotency.py (Hypothesis DATA-09 property)

Phase 0 grep guards all green:
- `TIMESTAMP[^(]`: CLEAN
- `ON DELETE CASCADE`: CLEAN
- `op.execute(` (raw DDL): CLEAN in migrations 0003–0008

## Threat Surface Scan

No new security surface beyond what the plan's threat model covers. All new endpoints are
hypertable DDL (migration-time only, no user input). All test queries are parametrized
asyncpg calls against system views.

## Known Stubs

None. All 7 hypertables are fully created with correct schema. copy_into_hypertable
implements the full COPY → staging → INSERT ON CONFLICT DO NOTHING path.

## Self-Check: PASSED
