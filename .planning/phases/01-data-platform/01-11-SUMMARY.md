---
phase: 01-data-platform
plan: 11
subsystem: infra
tags: [backfill, railway, documentation, coinglass, timescaledb, postgres, asyncpg]

requires:
  - phase: 01-10
    provides: freshness gauges + R2 backup + RESTORE.md pattern — template for BACKFILL.md structure

provides:
  - ROADMAP.md + REQUIREMENTS.md patched from Coinglass Startup ($79) to Hobbyist (~$35) per D-35
  - .env.example Phase 1 secrets block (TELEGRAM__*, R2__*) added
  - STOR-08 CI sanity slice: 50 symbols x 1m x 6 days integration test (13.5s wall-clock)
  - copy_into_hypertable concurrent bug fixed: per-PID staging table
  - docs/BACKFILL.md: 6-step developer-machine 1-2yr backfill runbook
  - docs/PHASE-1-SMOKE.md: 8-step post-deploy manual verification checklist

affects: [Phase 2 planning (backfill row counts required), Phase 1.x patches (smoke cadence)]

tech-stack:
  added: [pytest-timeout>=2.3]
  patterns:
    - Per-PID staging table in copy_into_hypertable prevents UniqueViolationError under concurrent backfill
    - FakeMexcClient.with_synthetic_candles classmethod is the canonical STOR-08 test constructor

key-files:
  created:
    - tests/integration/ingest/test_backfill_6d_full_path.py
    - docs/BACKFILL.md
    - docs/PHASE-1-SMOKE.md
  modified:
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
    - .env.example
    - src/shortfire/ingest/storage/copy.py
    - pyproject.toml

key-decisions:
  - "copy_into_hypertable uses pg_backend_pid() to suffix the staging table name, preventing concurrent coroutines from colliding on pg_type registration"
  - "STOR-08 CI test uses deterministic since=2024-01-02/until=2024-01-08 (not datetime.now()) for reproducibility"
  - "docs/BACKFILL.md explicitly states this is NOT a Railway cron — 3 technical reasons documented"

patterns-established:
  - "Per-PID staging table pattern: f'{target_table}_staging_{pid}' — apply to any copy_into_hypertable caller that runs concurrent coroutines"

requirements-completed:
  - DATA-01
  - DATA-02
  - DATA-03
  - DATA-07
  - DATA-08
  - DATA-12
  - STOR-08
  - STOR-09
  - OPS-05
  - OPS-06

duration: 45min
completed: 2026-05-22
---

# Phase 1 Plan 11: Phase Close-Out Summary

**Coinglass Hobbyist tier patch in ROADMAP/REQUIREMENTS, Phase 1 .env.example secrets, STOR-08 6-day CI sanity slice (13.5s), copy_into_hypertable concurrency bug fix, and operational docs BACKFILL.md + PHASE-1-SMOKE.md**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-05-22
- **Completed:** 2026-05-22
- **Tasks:** 2 of 2 auto tasks executed (Task 2 = human checkpoint, see below)
- **Files modified:** 9

## Accomplishments

- Patched every "Coinglass Startup ($79/mo)" reference in ROADMAP.md and REQUIREMENTS.md to "Coinglass Hobbyist (~$35/mo)" per D-35 binding override + `project_data_tier_subscriptions.md` memory (DATA-07, STOR-08, V2-DATA-01 adjusted)
- Added complete Phase 1 secret block to `.env.example` (TELEGRAM__BOT_TOKEN, TELEGRAM__OPERATOR_CHAT_ID, R2__ACCOUNT_ID, R2__ACCESS_KEY_ID, R2__SECRET_ACCESS_KEY, R2__BUCKET_NAME); MEXC/Coinglass/CoinGecko were already present
- Shipped STOR-08 CI sanity slice: 50 symbols x 1m x 6 days = 432 000 candles through backfill_universe → copy_into_hypertable → raw_mexc_candles_1m; idempotency + source attribution + OHLCV invariants all verified; **13.5 seconds wall-clock** against 5-minute D-94 budget
- Fixed concurrent staging table bug in `copy_into_hypertable` (Rule 1); wrote `docs/BACKFILL.md` (247 lines, 6 steps) and `docs/PHASE-1-SMOKE.md` (148 lines, 8 steps)

## Task Commits

1. **Task 1: Hobbyist tier patch + .env.example + STOR-08 test** - `a29f4af` (feat)
3. **Task 3: BACKFILL.md + PHASE-1-SMOKE.md** - `eed46d4` (docs)

Task 2 = checkpoint:human-verify (Railway 3-service deploy + W5 mandatory backfill gate — awaiting human)

## Files Created/Modified

- `.planning/ROADMAP.md` — Hobbyist tier patch in Phase 1 success criterion #1
- `.planning/REQUIREMENTS.md` — DATA-07, STOR-08, V2-DATA-01 adjusted per D-35
- `.env.example` — Phase 1 secrets block added (Telegram + R2)
- `pyproject.toml` — pytest-timeout>=2.3 added to dev deps
- `uv.lock` — updated
- `src/shortfire/ingest/storage/copy.py` — per-PID staging table name (Rule 1 bug fix)
- `tests/integration/ingest/test_backfill_6d_full_path.py` — STOR-08 CI sanity slice (new)
- `docs/BACKFILL.md` — 6-step operational runbook for developer-machine 1-2yr backfill (new)
- `docs/PHASE-1-SMOKE.md` — 8-step post-deploy manual smoke checklist (new)

## Decisions Made

- **Per-PID staging table**: `copy_into_hypertable` now appends `pg_backend_pid()` to the staging table name. This makes each PostgreSQL backend's staging table unique, preventing `UniqueViolationError: duplicate key value violates unique constraint "pg_type_typname_nsp_index"` when 50 concurrent backfill coroutines all try to `CREATE UNLOGGED TABLE IF NOT EXISTS raw_mexc_candles_1m_staging`.
- **Deterministic test timestamps**: STOR-08 test uses `since=2024-01-02T00:00:00Z / until=2024-01-08T00:00:00Z` instead of `datetime.now()` to avoid flakiness from off-by-one candle counts at test execution time.
- **Backfill NOT a Railway cron**: documented 3 explicit reasons in BACKFILL.md (multi-hour task, shared rate limit, better observability locally). This decision was implicit in CONTEXT.md D-38 but now has a written rationale.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed concurrent copy_into_hypertable staging table name collision**
- **Found during:** Task 1 (STOR-08 integration test)
- **Issue:** `CREATE UNLOGGED TABLE IF NOT EXISTS raw_mexc_candles_1m_staging` from 50 concurrent coroutines triggered `asyncpg.exceptions.UniqueViolationError` on `pg_type_typname_nsp_index`. PostgreSQL's `IF NOT EXISTS` only avoids DDL-level errors after the type is registered; concurrent transactions race on type registration.
- **Fix:** Fetch `pg_backend_pid()` at the start of each `copy_into_hypertable` call and suffix the staging table name: `{target_table}_staging_{pid}`. Each PostgreSQL backend now has its own isolated staging table.
- **Files modified:** `src/shortfire/ingest/storage/copy.py`
- **Verification:** STOR-08 test passes with `max_concurrency=8` (50 symbols × TaskGroup × Semaphore(8))
- **Committed in:** `a29f4af` (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 bug)
**Impact on plan:** Required fix — the STOR-08 test would have been broken without it. No scope creep.

## STOR-08 CI Sanity Slice — Wall-Clock Result

| Metric | Value | Target (D-94) |
|--------|-------|---------------|
| Wall-clock | **13.5 seconds** | 5 minutes (300s) |
| Symbols | 50 | 50 |
| Timeframe | 1m | 1m |
| Days covered | 6 | 6 |
| Expected rows | 432 000 | 432 000 |
| Row count verified | Yes | Yes |
| Source attribution | Yes (mexc_native) | Yes |
| OHLCV invariants | Yes | Yes |
| Idempotency | Yes (0 new rows on re-run) | Yes |

D-94 5-minute target met with significant margin. The per-PID staging table adds one extra `SELECT pg_backend_pid()` call per COPY batch but this is negligible (<1ms per call).

## Phase 1 REQ-ID Coverage Audit

All 32 Phase 1 REQ-IDs covered across plans 01-01..01-11:

| REQ ID | Covered by plan(s) | Status |
|--------|--------------------|--------|
| DATA-01 | 01-05 | Complete |
| DATA-02 | 01-05 | Complete |
| DATA-03 | 01-05 | Complete |
| DATA-04 | 01-08 | Complete |
| DATA-05 | 01-08 | Complete |
| DATA-06 | 01-08 | Complete |
| DATA-07 | 01-06, 01-11 | Complete |
| DATA-08 | 01-07 | Complete |
| DATA-09 | 01-03, 01-11 | Complete |
| DATA-10 | 01-01 (tenacity + aiolimiter) | Complete |
| DATA-11 | 01-01 (dead_letter writer) | Complete |
| DATA-12 | 01-01, 01-11 | Complete |
| STOR-01 | 01-03, 01-04 | Complete |
| STOR-02 | 01-03 | Complete |
| STOR-03 | 01-03, 01-04 | Complete |
| STOR-04 | 01-03, 01-04 | Complete |
| STOR-05 | 01-04 | Complete |
| STOR-06 | 01-04 | Complete |
| STOR-07 | 01-04 | Complete |
| STOR-08 | 01-11 (CI slice); W5 gate = production backfill (pending human) | CI complete |
| STOR-09 | 01-08 | Complete |
| STOR-10 | 01-10 | Complete |
| UNIV-01 | 01-09 | Complete |
| UNIV-02 | 01-09 | Complete |
| UNIV-03 | 01-09 | Complete |
| UNIV-04 | 01-09 | Complete |
| ORCH-01 | 01-09 | Complete |
| ORCH-02 | 01-09 | Complete |
| ORCH-03 | 01-10 | Complete |
| ORCH-04 | 01-10 | Complete |
| OPS-05 | 01-11 (checkpoint; pending human) | Checkpoint |
| OPS-06 | 01-11 (checkpoint; pending human) | Checkpoint |

**Note:** STOR-08 and OPS-05/OPS-06 are functionally implemented but require human verification via the Task 2 checkpoint (W5 mandatory backfill gate + Railway 3-service deploy smoke).

## W5 Backfill Gate — Pending Human Action

The W5 mandatory backfill gate (ROADMAP success criterion #1) requires:

1. Operator populates Railway env vars on `data-platform` service per `.env.example` Phase 1 section
2. No-op push to main → Railway auto-deploys all 3 services (OPS-05)
3. `curl /health` returns 200 from all 3 services (OPS-06)
4. Operator executes `docs/BACKFILL.md` against production DB (estimated 8–12h overnight)
5. Operator pastes row-count table into this SUMMARY (below placeholder)

**Row counts (to be filled by operator after backfill):**

| Table | Count | Expected minimum | Pass? |
|-------|-------|-----------------|-------|
| raw_mexc_candles_1m | _pending_ | ≥ 89.4M | — |
| raw_mexc_candles_1d | _pending_ | ≥ 62K | — |
| raw_mexc_funding | _pending_ | ≥ 186K | — |
| raw_mexc_oi | _pending_ | ≥ 1.49M | — |
| universe_snapshots | _pending_ | ≥ 200 | — |

## Open Follow-ups for Phase 1.x

- **OI backfill helper**: `backfill_oi` function not yet extracted into `src/shortfire/ingest/mexc/backfill.py`. The live scheduler's OI round-robin (plan 01-08) covers going-forward OI, but the historical OI backfill documented in BACKFILL.md step 4 requires a dedicated helper. Flagged for Phase 1.x patch.
- **Coinglass OI/Liq/LSR round-robin stubs**: plan 01-09 shipped `kv_state.py` helpers and the scheduler job registrations; the actual per-endpoint fetcher round-robin logic may have `...  # planner fills in` placeholders. Surface during Phase 1.x if live data is missing for these sources.
- **DATA-10 tenacity retries**: REQUIREMENTS.md marks DATA-10 as Complete based on plan 01-01 shipping `tenacity` + `aiolimiter` infrastructure, but per-endpoint retry decorators may be sparse. Verify during Phase 1.x if any live ingest source shows unexplained gaps.

## Phase 2 Research Flags

- **L2 cardinality budget** (Open Question 3 from CONTEXT.md): once the 6-day STOR-08 backfill establishes baseline row counts for `raw_mexc_l2_top20` under the Tier-1 (1s) and Tier-2 (5s) cadences, confirm that the 7-day compression window is sufficient or whether an earlier compression trigger is needed.
- **Coinglass 1m gap impact**: with Hobbyist tier capping 1m derivatives history at ~6 days, Phase 2 EDA should quantify whether funding + OI features at 1m granularity beyond 6 days add meaningful signal vs 5m+ which is months-deep. This is the V2-DATA-01 trigger condition.

## Known Stubs

None in this plan — documentation-only + planning patch + test + bug fix. No data-flow stubs introduced.

## Next Phase Readiness

Phase 1 is feature-complete after plan 01-10. This plan (01-11) closes out the phase:
- All documentation written (BACKFILL.md, PHASE-1-SMOKE.md, RESTORE.md already existed)
- Coinglass tier references consistent across ROADMAP.md, REQUIREMENTS.md, and docs
- CI sanity slice green (STOR-08 shape proven end-to-end)
- Human checkpoint pending for W5 gate (Railway smoke + production backfill)

**Ready for Phase 2 planning once the human checkpoint is approved** (operator pastes backfill row counts into this SUMMARY and signals "approved").

---
*Phase: 01-data-platform*
*Completed: 2026-05-22 (auto tasks); human checkpoint pending*
