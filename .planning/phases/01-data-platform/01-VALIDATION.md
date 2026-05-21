---
phase: 1
slug: data-platform
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-21
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `01-RESEARCH.md` §Validation Architecture. Authoritative test framework + sampling rates + per-requirement verification map.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4 + pytest-asyncio (auto mode) + Hypothesis 6.x |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (already wired in Phase 0) |
| **Quick run command** | `uv run pytest tests/unit -x -q` |
| **Full suite command** | `uv run pytest --cov=src/shortfire --cov-report=term-missing` |
| **Integration-only** | `uv run pytest -m integration` (requires Docker + testcontainers — Phase 0 baseline `tests/integration/db/test_alembic_and_hypertables.py`) |
| **Estimated runtime — quick** | ~30 sec |
| **Estimated runtime — full** | ~5 min (incl. 6-day CI backfill slice per CONTEXT.md D-94) |
| **Coverage gate** | 80% project-wide (CONTEXT.md D-91); `src/shortfire/ingest/*` removed from `omit` list in Phase 1 |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit -x -q` (~30 sec)
- **After every plan wave:** Run `uv run pytest --cov=src/shortfire --cov-report=term-missing -m "integration or not integration"` (~5 min target with the 6-day CI backfill slice)
- **Before `/gsd:verify-work`:** Full suite must be green AND coverage ≥80% AND `pytest tests/integration -v` shows backfill idempotency, universe point-in-time, and dead_letter routing all green
- **Max feedback latency:** 30 seconds (per-task), 300 seconds (per-wave)

---

## Per-Task Verification Map

> Plans and task IDs are filled in by the planner. The columns below pre-bind every Phase 1 requirement to a concrete automated command. Planner is expected to populate `Task ID`, `Plan`, and `Wave` columns when emitting PLAN.md files.

| Requirement | Behavior under test | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|---------------------|------------|-----------------|-----------|-------------------|-------------|--------|
| DATA-01 | MEXC OHLCV ingest produces correct rows (1m/5m/15m/1h/4h/1d) | T-1-DATA-01 | Pydantic schema rejects malformed candle payloads | unit + integration | `uv run pytest tests/integration/ingest/test_mexc_ohlcv.py -v` | ❌ W0 | ⬜ pending |
| DATA-02 | Funding row carries both `settlement_ts` AND `published_ts` | — | Hypothesis invariant: `published_ts <= settlement_ts + 1h` | unit (Hypothesis) | `uv run pytest tests/unit/ingest/test_mexc_funding_schema.py` | ❌ W0 | ⬜ pending |
| DATA-03 | OI hourly cadence respected; round-robin scheduler honors throttle | — | aiolimiter prevents burst that exceeds Coinglass quota | unit | `uv run pytest tests/unit/ingest/test_oi_round_robin.py` | ❌ W0 | ⬜ pending |
| DATA-04 | Signed trades persisted in 1-min batches (live aggregator from `watch_trades`) | — | client-side minute aggregator emits one closed candle per minute boundary | unit + integration | `uv run pytest tests/unit/ingest/test_minute_aggregator.py` | ❌ W0 | ⬜ pending |
| DATA-05 | L2 top-20 sampled per tier cadence | — | sampling cadence matches per-tier expected lag under freezegun | unit | `uv run pytest tests/unit/ingest/test_l2_sampling.py` | ❌ W0 | ⬜ pending |
| DATA-06 | Liquidations dual-source (MEXC native + Coinglass aggregate) | — | both code paths exercised; each row carries correct `source` | unit | `uv run pytest tests/unit/ingest/test_liquidations.py` | ❌ W0 | ⬜ pending |
| DATA-07 | Coinglass ingest stays under rate limit (Hobbyist 30 req/min) | T-1-RATE-01 | aiolimiter token-bucket prevents 429s; backoff under tenacity | integration via respx + aiolimiter | `uv run pytest tests/integration/ingest/test_coinglass.py` | ❌ W0 | ⬜ pending |
| DATA-08 | CoinGecko daily universe refresh ingests $500K+ symbols | — | rate-limited, cached, idempotent | integration via respx | `uv run pytest tests/integration/ingest/test_coingecko.py` | ❌ W0 | ⬜ pending |
| DATA-09 | **Idempotent on `(symbol, ts, source)`** — re-run yields no dupes | T-1-IDEM-01 | `ON CONFLICT DO NOTHING` via `copy_into_hypertable` | **Hypothesis property test** | `uv run pytest tests/integration/ingest/test_idempotency.py -v` | ❌ W0 | ⬜ pending |
| DATA-10 | Retry + rate-limit policy under synthetic 5xx | — | tenacity exhausts with bounded latency; dead_letter on exhaustion | unit (tenacity) + freezegun | `uv run pytest tests/unit/ingest/test_retry_policies.py` | ❌ W0 | ⬜ pending |
| DATA-11 | Pydantic validation failures route to `dead_letter` | — | malformed payload → `dead_letter` row → ingest loop unblocked | integration with malformed fixture | `uv run pytest tests/integration/ingest/test_dead_letter.py` | ❌ W0 | ⬜ pending |
| DATA-12 | `source` column has CHECK constraint at DB level | T-1-SCHEMA-01 | INSERT with bad source rolls back | integration | `uv run pytest tests/integration/db/test_source_check.py` | ❌ W0 | ⬜ pending |
| STOR-01..04 | Hypertables exist; compression policy attached; chunk_time_interval correct | — | Schema introspection confirms hypertable shape | integration (extends `test_alembic_and_hypertables.py`) | `uv run pytest tests/integration/db/test_phase1_schema.py` | ❌ W0 | ⬜ pending |
| STOR-05 | Continuous aggregates 5m/15m/1h/4h refresh and match hand-rolled SQL | — | CA SUM/MAX/MIN identical to a SQL ground-truth over the same window | integration (Hypothesis-friendly) | `uv run pytest tests/integration/db/test_continuous_aggregates.py` | ❌ W0 | ⬜ pending |
| STOR-06 | `universe_snapshots` hypertable + point-in-time row-set semantics | — | append-only daily snapshot writes; valid_from/valid_to discipline | integration | `uv run pytest tests/integration/ingest/test_universe_point_in_time.py` | ❌ W0 | ⬜ pending |
| STOR-07 | `symbols` soft-delete; `ON DELETE CASCADE` banned project-wide | T-1-DDL-01 | Pre-commit grep guard + integration DDL probe | grep-guard (pre-commit) + integration | `uv run pytest tests/integration/db/test_symbols_soft_delete.py` | ❌ W0 | ⬜ pending |
| STOR-08 | 1-year backfill is idempotent (CI runs a 6-day slice per D-94) | T-1-BACKFILL-01 | Re-running CI backfill produces zero new rows | integration | `uv run pytest tests/integration/ingest/test_backfill_6d.py -v` | ❌ W0 | ⬜ pending |
| STOR-09 | `quality_flag` flags gaps; **no silent interpolation** | — | gap detector marks `quality_flag='gap'` rather than synthesizing rows | unit + integration | `uv run pytest tests/integration/ingest/test_gap_quality_flag.py` | ❌ W0 | ⬜ pending |
| STOR-10 | Daily `pg_dump` → R2 + restore drill | T-1-BACKUP-01 | mock R2 via `moto`; manual restore drill documented | integration (`moto`) + manual drill | `uv run pytest tests/integration/backup/test_pg_dump_r2.py` + `docs/RESTORE.md` | ❌ W0 | ⬜ M (manual restore) |
| UNIV-01 | `$500K` 24h-USD-volume filter logic | — | qualifying set is exactly volume > $500K | unit | `uv run pytest tests/unit/ingest/test_universe_filter.py` | ❌ W0 | ⬜ pending |
| UNIV-02 | Daily universe refresh writes a new row-set | — | new snapshot has correct `valid_from`/`valid_to` boundaries | integration | `uv run pytest tests/integration/ingest/test_universe_daily_refresh.py` | ❌ W0 | ⬜ pending |
| UNIV-03 | **Point-in-time correctness** — querying at T returns the set qualifying AT T | T-1-LEAK-01 | universe_at(T) is invariant under future writes | **Hypothesis property test** | `uv run pytest tests/integration/ingest/test_universe_point_in_time.py::test_point_in_time_property` | ❌ W0 | ⬜ pending |
| UNIV-04 | New-listing detected within 24h | — | diff job fires Telegram alert on first appearance | unit (diff) + integration (alert path) | `uv run pytest tests/integration/ingest/test_new_listing_detection.py` | ❌ W0 | ⬜ pending |
| ORCH-01 | APScheduler 4 `AsyncScheduler` boots with `SQLAlchemyDataStore` | — | lifespan smoke test: scheduler starts, persists, shuts down cleanly | integration | `uv run pytest tests/integration/scheduler/test_scheduler_lifespan.py` | ❌ W0 | ⬜ pending |
| ORCH-02 | Per-source cadence respected by `add_schedule` graph | — | freezegun + scheduler.add_schedule introspection | unit | `uv run pytest tests/unit/scheduler/test_job_graph.py` | ❌ W0 | ⬜ pending |
| ORCH-03 | Freshness gauge updates on every write | — | gauge before/after `copy_into_hypertable` differs | unit | `uv run pytest tests/unit/ingest/test_freshness_gauges.py` | ❌ W0 | ⬜ pending |
| ORCH-04 | Stale-data Telegram alert fires when gauge > 2× expected lag | T-1-ALERT-01 | mock Telegram endpoint via respx, freezegun-shift time | integration | `uv run pytest tests/integration/freshness/test_stale_alert.py` | ❌ W0 | ⬜ pending |
| OPS-05 | `commit → push → deploy` works (Railway auto-deploy) | — | manual smoke: push small change, verify all 3 services redeploy | manual | `git push origin main` + observe Railway logs | n/a | ⬜ M (manual) |
| OPS-06 | All 3 Railway services live (`data-platform`, `strategy-engine`, `dashboard`) | — | `curl /health` returns 200 from all 3 | manual smoke | `curl https://{service}.up.railway.app/health` × 3 | n/a | ⬜ M (manual) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · M = manual-only*

---

## Wave 0 Requirements

Phase 0 test harness covers framework wiring; new artifacts Phase 1 needs (each enumerated in 01-RESEARCH.md §Validation Architecture → Wave 0 gaps):

- [ ] `tests/integration/ingest/test_idempotency.py` — DATA-09 Hypothesis property
- [ ] `tests/integration/ingest/test_universe_point_in_time.py` — UNIV-03 Hypothesis property
- [ ] `tests/integration/db/test_phase1_schema.py` — STOR-01..04 hypertable + compression
- [ ] `tests/integration/db/test_continuous_aggregates.py` — STOR-05 CA-vs-SQL parity
- [ ] `tests/integration/db/test_source_check.py` — DATA-12 CHECK constraint
- [ ] `tests/integration/ingest/test_dead_letter.py` — DATA-11 routing path
- [ ] `tests/integration/backup/test_pg_dump_r2.py` — STOR-10 backup (mock via `moto`)
- [ ] `tests/integration/freshness/test_stale_alert.py` — ORCH-04 Telegram alerter
- [ ] `tests/integration/scheduler/test_scheduler_lifespan.py` — ORCH-01 lifespan
- [ ] `tests/fakes/repos.py` — expand `InMemoryCandleRepo` with synthetic OHLCV generators (Hypothesis-friendly) per D-93
- [ ] `tests/fakes/coinglass.py` — Coinglass response fixtures (read-only API key contract test)
- [ ] `tests/fakes/mexc.py` — synthetic trades for minute aggregator
- [ ] `moto` added to dev dependencies — for R2 mocking

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Railway auto-deploy on `git push origin main` | OPS-05 | Railway CI/CD is external infra; tested by behavior, not code | Push a no-op commit, watch Railway dashboard, confirm all 3 services pick up new deploy ≤5 min |
| All 3 Railway services live + healthy | OPS-06 | Cross-service end-to-end health requires real cloud env | `curl https://{data-platform,strategy-engine,dashboard}.up.railway.app/health` each returns `{"status":"ok"}` |
| `pg_dump → R2 → pg_restore` round-trip drill | STOR-10 | Restore drill must run end-to-end against real R2 bucket (mocked path is `moto`) | Follow `docs/RESTORE.md` (planner emits this doc): trigger backup, download from R2, restore into a fresh Postgres, verify row counts match |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify command OR are listed under Manual-Only Verifications with explicit `docs/RESTORE.md`-style instructions
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all `❌ W0` references above (Wave 1 must land them before any plan declares green)
- [ ] No watch-mode flags in CI (`pytest --watch`, `vitest watch`, etc. — never)
- [ ] Feedback latency < 30 s per task, < 300 s per wave
- [ ] `nyquist_compliant: true` set in frontmatter once Wave 0 lands and the four keystone Hypothesis tests (DATA-09 idempotency, UNIV-03 point-in-time, STOR-05 CA parity, DATA-11 dead-letter) are green

**Approval:** pending
