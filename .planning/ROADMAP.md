# Roadmap: MEXC Futures Sniper (ShortFIRE)

## Overview

Six phases take ShortFIRE from empty repo to live capital under hybrid autonomy. The path is dictated by hard sequencing constraints: schema decisions (universe snapshots, source attribution, L2 capture, TIMESTAMPTZ) cannot be retrofitted, so the data platform ships before any modeling. ML methodology (purged walk-forward, leakage Hypothesis tests, precision@N metric, funding-window-aware labeling) ships before the first model trains, because leakage discovered later invalidates everything downstream. A correct event-driven backtester then gates paper trading, paper trading is a hard ≥1-month gate on live, and live capital flows through staged autonomy (signal-only → semi-auto → full-auto) with a separate `risk-guard` Railway service. Every phase is verifiable end-to-end on Railway by virtue of commit→push→deploy from Phase 0.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 0: Foundation** - TDD scaffolding, Railway+TimescaleDB, CI/CD, domain types, observability skeleton (completed 2026-05-21)
- [ ] **Phase 1: Data Platform** - MEXC/Coinglass/CoinGecko ingest, typed hypertables, universe snapshots, 1-2yr backfill
- [ ] **Phase 2: Strategy Research + ML Methodology** - Causal feature primitives, pump detection, triple-barrier labeling, PurgedWalkForward, XGBoost/LightGBM baseline with MLflow + SHAP
- [ ] **Phase 3: Backtester + Strategy Framework** - Strategy Protocol, event-driven backtester with book-walk slippage, ShortAfterPumpStrategy, deterministic reproducibility
- [ ] **Phase 4: Paper Trading (HARD GATE)** - PaperOrderRouter, full risk module, kill switch, ≥1-month positive-EV paper run with <10% backtest divergence
- [ ] **Phase 5: Live Trading** - Two-key MEXC auth, RemoteRiskGuard service, signal-only → semi-auto → full-auto escalation, Grafana, live edge tracker

## Phase Details

### Phase 0: Foundation

**Goal**: Project scaffolding exists end-to-end on Railway with TDD, CI/CD, secret hygiene, and domain types in place — so every subsequent commit can be deployed and tested in the real environment from the first line of production code.
**Depends on**: Nothing (first phase)
**Requirements**: FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, FOUND-06, FOUND-07, FOUND-08, OPS-01, OPS-02, OPS-03, OPS-04, OPS-07, OPS-08, TEST-01, TEST-02, TEST-05, TEST-06
**Success Criteria** (what must be TRUE):

  1. A fresh `git clone` followed by `uv sync` produces a green `pytest` run on a developer machine, including Hypothesis property tests on the pure domain types (`Candle`, `OrderBook`, `Funding`, `Signal`, `Order`, `Position`, `RiskLimits`).
  2. Pushing to `main` triggers GitHub Actions (ruff + pyright + pytest with coverage); a failing test blocks merge; a green build auto-deploys to Railway and the service answers `/metrics` with Prometheus output and a structured-JSON `/health` line containing a correlation ID.
  3. `pydantic-settings` rejects startup if any required env var is missing, with a clear actionable error message, and a leaked secret committed to the repo is blocked by pre-commit + GitHub secret scanning before it lands on `main`.
  4. `alembic upgrade head` against the Railway Postgres applies a TimescaleDB-aware migration (creates a hypertable with `create_hypertable`, attaches a compression policy) and the migration is rerun-safe.
  5. `tests/fakes/` exposes `FakeMexcClient`, `FakeCoinglassClient`, `FakeCoinGeckoClient`, and `InMemoryCandleRepo` interfaces that downstream phases can import without touching any network.

**Plans**: 8 plans
Plans:
**Wave 1**

- [x] 00-01-PLAN.md — Repo skeleton: uv + pyproject.toml + ruff/pyright/pytest configs + pre-commit (ruff + gitleaks + 3 grep guards) + .gitignore + .env.example + AGENTS.md + package layout

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 00-02-PLAN.md — 8 pure-Pydantic v2 domain types (Candle, OrderBook, Funding, Liquidation, Signal, Order, Position, RiskLimits) + Hypothesis property tests on every invariant (EXEC-02 + RISK-02 structural)
- [x] 00-03-PLAN.md — Per-service BaseAppSettings subclasses with SecretStr + safe_summary() + assert_no_trade_env_leaked() anti-leak guard + 4-layer secret-scan defense
- [x] 00-04-PLAN.md — DB layer: DeclarativeBase + naming convention + idempotent Timescale DDL helpers + Alembic async env + 2 migrations (init extension + service_event hypertable with compression policy)
- [x] 00-05-PLAN.md — Observability skeleton: structlog (merge_contextvars first) + asgi-correlation-id + Prometheus (4 base metrics) + 3 FastAPI entrypoints (data_platform, strategy_engine, dashboard) with /health + /metrics

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 00-06-PLAN.md — docker-compose for local TimescaleDB + testcontainers integration tests (alembic upgrade head idempotent, service_event is hypertable, compression policy exists) — runtime gate for FOUND-03
- [x] 00-07-PLAN.md — Railway 3-service deployment (Dockerfile + railway.toml + dashboard checkpoint for TimescaleDB marketplace + reference variables + preDeployCommand for migrations + branch protection + secret scanning)
- [x] 00-08-PLAN.md — 4 Protocol/Fake pairs (MexcClient/CoinglassClient/CoinGeckoClient/CandleRepo + their fakes in tests/fakes/) + GitHub Actions CI (ruff + pyright + pytest unit + pytest integration + gitleaks-action + coverage gate 80%)

### Phase 1: Data Platform

**Goal**: A strategy-agnostic, leak-aware historical and live data warehouse exists in TimescaleDB with daily universe snapshots, L2 capture, source attribution, and 1–2 years of backfill — so research and backtesting in later phases can never be invalidated by retrofitted schema decisions.
**Depends on**: Phase 0
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, DATA-06, DATA-07, DATA-08, DATA-09, DATA-10, DATA-11, DATA-12, STOR-01, STOR-02, STOR-03, STOR-04, STOR-05, STOR-06, STOR-07, STOR-08, STOR-09, STOR-10, UNIV-01, UNIV-02, UNIV-03, UNIV-04, ORCH-01, ORCH-02, ORCH-03, ORCH-04, OPS-05, OPS-06
**Success Criteria** (what must be TRUE):

  1. Backfill of ≥1 year of MEXC USDT-perp OHLCV (1m/5m/15m/1h/4h/1d), funding, OI, and L2 top-20 snapshots completes against the Coinglass Startup tier without duplicates, with every derivatives row carrying an explicit `source` column distinguishing `mexc_native` from `coinglass_aggregate`.
  2. Querying `universe_snapshots` at any historical timestamp T returns the set of MEXC perps qualifying at T (24h USD volume > $500K), not "listed today", and a Hypothesis test asserts point-in-time correctness; new listings detected within 24h.
  3. Re-running any ingest job is idempotent on `(symbol, ts, source)` — no duplicate rows, no schema drift; failed validations land in `dead_letter` rather than corrupting hypertables, and the `quality_flag` column flags gaps without silent interpolation.
  4. The three Railway services (`data-platform`, `strategy-engine` placeholder, `dashboard` placeholder) are live; every push to `main` auto-deploys; `data-platform` exposes per-source freshness gauges on `/metrics`, and Telegram fires a stale-data alert when any source exceeds its expected lag.
  5. Daily `pg_dump` to off-Railway storage (R2/B2) runs and a documented restore drill recreates the database; continuous aggregates exist for 5m/15m/1h/4h rollups; all timestamps are `TIMESTAMPTZ` and `ON DELETE CASCADE` is banned project-wide.

**Plans**: 11 plans
Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Domain `Source` literal widening (D-59) + ingest infrastructure (retry, rate-limit, copy_into_hypertable, dead_letter writer, context) + coverage gate removal of `src/shortfire/ingest/*` omit
- [x] 01-02-PLAN.md — Observability extensions (17 events, 8 metric families on existing REGISTRY, raw-httpx Telegram) + settings extensions (TelegramSettings + R2BackupSettings on DataPlatformSettings)
- [x] 01-03-PLAN.md — Alembic migrations 0003–0008 (7 MEXC-native hypertables: candles 1m+1d, funding, oi, trades, l2_top20, liquidations) + integration tests (schema/hypertable existence, source CHECK rejection, DATA-09 Hypothesis idempotency keystone)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 01-04-PLAN.md — Alembic migrations 0009–0014 (Coinglass×4 + CoinGecko + universe_snapshots + symbols relational + dead_letter + ingest_runs + continuous aggregates 5m/15m/1h/4h) + `create_continuous_aggregate` helper + 3 ORM models + STOR-05 CA-parity integration keystone

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 01-05-PLAN.md — Concrete `MexcClient` (ccxt 4.5 swap, pin `>=4.5.54,<4.6`) + 4 Pydantic v2 strict schemas with `to_domain()` + paginated REST OHLCV/funding backfill (`asyncio.Semaphore(8)`) + `FakeMexcClient.with_synthetic_candles` classmethod constructor + DATA-01 integration keystone
- [ ] 01-06-PLAN.md — Concrete `CoinglassClient` (httpx HTTP/2, `aiolimiter(28/60)` per Hobbyist) + 4 endpoint Pydantic schemas + 4 per-endpoint fetcher modules with `source='coinglass_aggregate'` + DATA-07 integration keystone
- [ ] 01-07-PLAN.md — Concrete `CoinGeckoClient` (httpx, Demo-tier `x-cg-demo-api-key` header) + 2 Pydantic schemas + daily universe-metadata fetcher writing to `raw_coingecko_market` + DATA-08 integration keystone

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 01-08-PLAN.md — MEXC live ws ingest (MinuteAggregator from `watch_trades` per D-43; `watch_ohlcv` banned; `watch_funding_rate` dual-timestamp; OI REST round-robin; L2 sampler tier-1/tier-2 cadences; trades 1-min batched COPY; liquidations ws-only per W3 demotion of D-48 with explicit decision log) under `asyncio.TaskGroup` (Pitfall 27) + active heartbeat watchdog + cross-REST divergence check writing `quality_flag='ws_rest_divergence'` (D-49 points 3+4) + gap-injection helper (STOR-09)

**Wave 5** *(blocked on Wave 4 completion)*

- [ ] 01-09-PLAN.md — Universe snapshot job (UNIV-01..04: $500K filter, point-in-time, new-listing/delisting diff, tier-1 designation) + APScheduler 4 `AsyncScheduler` bootstrap + D-77 11-job graph under FastAPI lifespan + `kv_state.py` helper for round-robin cursors + UNIV-03 Hypothesis keystone + ORCH-01 lifespan smoke

**Wave 6** *(blocked on Wave 5 completion)*

- [ ] 01-10-PLAN.md — Freshness gauges + stale-data Telegram alerter (D-87 severity routing) + dead_letter threshold alerter + R2 daily pg_dump backup (`--format=custom --compress=zstd:9`, `PGPASSWORD` env DSN, full D-81 retention roll-up: 7d+4w+6m+annual via S3 copy_object) + Dockerfile `postgresql-client-16` + `docs/RESTORE.md` + ORCH-04 + STOR-10 keystones

**Wave 7** *(blocked on Wave 6 completion)*

- [ ] 01-11-PLAN.md — ROADMAP/REQUIREMENTS Coinglass-tier patch (Hobbyist ~$35/mo per D-35) + `.env.example` Phase 1 secret block + STOR-08 6-day CI sanity slice + `docs/BACKFILL.md` + `docs/PHASE-1-SMOKE.md` + Railway 3-service deploy smoke + W5 mandatory ≥1yr backfill execution gate (operator pastes row-count tables into 01-11-SUMMARY.md before checkpoint approval)

### Phase 2: Strategy Research + ML Methodology

**Goal**: The leakage-prevention infrastructure (purged walk-forward, embargo, funding-window-aware labeling, causal-rolling Hypothesis tests, precision@N metric) plus a first XGBoost/LightGBM baseline with MLflow + SHAP exists — so any model that proceeds to the backtester is methodologically defensible and the deferred labeling-method decision can finally be made on data, not vibes.
**Depends on**: Phase 1
**Requirements**: FEAT-01, FEAT-02, FEAT-03, FEAT-04, FEAT-05, FEAT-06, FEAT-07, FEAT-08, FEAT-09, FEAT-10, FEAT-11, FEAT-12, FEAT-13, FEAT-14, LABEL-01, LABEL-02, LABEL-03, LABEL-04, ML-01, ML-02, ML-03, ML-04, ML-05, ML-06, ML-07, ML-08, TRAIN-01, TRAIN-02, TRAIN-03, TRAIN-04, TRAIN-05, TRAIN-06, TRAIN-07, TEST-03, TEST-04
**Success Criteria** (what must be TRUE):

  1. Every feature primitive (`rsi`, `divergence`, `funding_zscore`, `oi_roc`, `liq_cascade_magnitude`, `vwap`, `btc_corr`, `volume_profile_poc`, regime, listing-age, seconds-to-next-funding) passes a Hypothesis property test asserting "duplicating row T and shifting by N seconds does not change the feature value at original T"; `bfill` / forward-looking interpolation are banned by a lint rule.
  2. A custom `PurgedWalkForward` splitter with `label_horizon` and `embargo_pct` enforces — via Hypothesis property test — that no training index falls within `label_horizon + embargo` of any test index; sklearn `TimeSeriesSplit` is explicitly absent from the codebase; label-window boundaries respect funding settlement timestamps.
  3. A versioned `pump_events` table records detector outputs with a `detector_version_id`; triple-barrier labeling with parameterized TP/SL/timeout is finalized after EDA (deferred per PROJECT.md); the chosen method is documented with a decision log entry.
  4. An XGBoost 3.2 baseline trained with Optuna 4.x (≤200 trials, MedianPruner, PurgedWalkForward) beats a rule-based sanity baseline (e.g. "short if RSI 1h > 80 AND funding z > 2") on a never-touched holdout using **precision @ top-N signals per day per symbol** — AUC and raw accuracy are explicitly NOT the gating metric; a LightGBM 4.6 secondary is logged for comparison.
  5. MLflow 3.x records every training run with code commit hash and data snapshot id; SHAP per-signal explanations are stored in the DB; calibration via isotonic regression is part of the eval pipeline; coverage gate is met (80% project-wide, 95% on `risk/` + `execution/` even though those modules are still scaffolding).

**Plans**: TBD
**Research flag**: Labeling method (triple-barrier vs alternatives), pump detector thresholds, walk-forward window choice, and the Coinglass Standard tier ($299/mo) upgrade decision are deferred to planning-time EDA per PROJECT.md and research/SUMMARY.md.

### Phase 3: Backtester + Strategy Framework

**Goal**: A deterministic event-driven backtester with realistic fees, depth-aware slippage, partial fills, and funding accounting validates that the Phase 2 model survives realistic execution — and the strategy framework (Protocol + Registry + DB-driven params) is shaped so paper, live, and future strategies all share the same code path.
**Depends on**: Phase 2
**Requirements**: STRAT-01, STRAT-02, STRAT-03, STRAT-04, STRAT-05, BACK-01, BACK-02, BACK-03, BACK-04, BACK-05, BACK-06, BACK-07, BACK-08, BACK-09, BACK-10, BACK-11, BACK-12, TEST-07
**Success Criteria** (what must be TRUE):

  1. A single `Strategy` Protocol (`features_required`, `generate_signals`, `position_sizing_hint`) plus `StrategyRegistry` is the only entry point used by the backtester, and `ShortAfterPumpStrategy` is the first concrete implementation; strategy params live in the `strategy_instances` table (NOT YAML / code), and `SignalIntent` flows through a `RiskGuard` shim that already exists as scaffolding.
  2. Running the backtester twice with the same `data_snapshot_id + code_commit_hash` produces bitwise-identical P&L (reproducibility test); a `quantstats` tearsheet plus bootstrapped equity-curve confidence intervals are auto-generated; a parameter robustness sweep across small perturbations produces stable results.
  3. The MEXC fee model with effective dates is the single source of truth for maker/taker; slippage is computed by walking captured L2 snapshots; partial fills, stop-loss book-walk from trigger price (NOT at trigger), funding payments at 8h crossings, and explicit signal-time vs execution-time separation are all visible in the trade log.
  4. The walk-forward backtest harness re-fits the model at each split using `PurgedWalkForward`, concatenates OOS predictions, and reports per-split top-K feature stability — exposing overfitting through high variance.
  5. The backtest produces a positive expected-value strategy on the never-touched holdout with realistic costs applied; if it does not, the project stops here and revisits Phase 2 — paper trading is not entered with a known-negative backtest.

**Plans**: TBD

### Phase 4: Paper Trading (HARD GATE before live)

**Goal**: Paper trading runs against the live ccxt feed through the SAME execution code path as live, with the full risk module, kill switch, latency injection, and per-trade audit log — and clears PROJECT.md's hard gate of ≥1 month positive EV with <10% paper-vs-backtest divergence before any live key is ever created.
**Depends on**: Phase 3
**Requirements**: PAPER-01, PAPER-02, PAPER-03, PAPER-04, PAPER-05, PAPER-06, PAPER-07, PAPER-08, PAPER-09, RISK-01, RISK-02, RISK-03, RISK-04, RISK-05, RISK-06, RISK-07, RISK-08, RISK-09, RISK-10, RISK-11, RISK-12, EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05, EXEC-06, EXEC-07, EXEC-08, EXEC-09, OBS-01, OBS-02, OBS-03, OBS-04, OBS-05
**Success Criteria** (what must be TRUE):

  1. `place_order(intent='open'|'close')` is the only way to submit an order from anywhere in the codebase; a Hypothesis invariant asserts every `intent='close'` order has `params.reduceOnly == True`; raw ccxt order calls are statically inaccessible outside this wrapper; MEXC position-mode assertion runs at service startup and fails fast on mismatch.
  2. The kill switch works end-to-end before the first paper trade: Telegram `/halt`, an HTTP endpoint, and automatic trips on daily-loss / max-drawdown / per-symbol-exposure / max-concurrent breaches all halt new orders; a documented monthly fire-drill procedure exercises it; `InProcessRiskGuard` fails closed on timeout/error.
  3. ≥1 month of paper trading on the live ccxt Pro feed produces positive expected value with quarter-Kelly position sizing (on bias-corrected edge with CI shrinkage, plus the hard 5% per-trade / 15% gross caps independent of Kelly) and capital-tier-aware sizing across the $500–$50K range.
  4. The daily paper-vs-backtest reconciliation report shows <10% divergence over the gate window — backed by identical slippage model, identical maker/taker classification, and 200–500ms randomized latency injection in paper; pre-registered model version is locked for the entire gate (mid-paper swap voids the gate).
  5. Every paper trade lands in a per-trade audit log with signal, model version, SHAP top-N, intended order, simulated fill, and P&L; Telegram alerts render SHAP top-N inline ("shorting because: RSI 4h=88 (+0.31), funding z=2.4 (+0.22), OI Δ1h=+18% (+0.18)") on the appropriate severity channel; the position reconciliation loop runs every 60s against a fake exchange state and alerts on divergence; the Prometheus `/metrics` endpoint now exposes signal/position/equity/latency histograms in addition to data-platform metrics.

**Plans**: TBD
**Research flag**: Latency injection breakpoints (200–500ms range) and the paper-vs-backtest divergence threshold need empirical anchoring against early paper data — surface during planning.

### Phase 5: Live Trading — Signal-Only → Semi-Auto → Full-Auto

**Goal**: Real capital trades under staged autonomy with a separate `risk-guard` Railway service, two MEXC keys (read-only + trade-no-withdraw), a live edge tracker auto-pausing on degradation, and Grafana dashboards live for the first time — the final gate where research, methodology, and execution discipline pay back.
**Depends on**: Phase 4
**Requirements**: LIVE-01, LIVE-02, LIVE-03, LIVE-04, LIVE-05, LIVE-06, LIVE-07, LIVE-08, LIVE-09, LIVE-10, LIVE-11, RISK-13, OBS-06, OBS-07
**Success Criteria** (what must be TRUE):

  1. Two MEXC API keys exist with hard-coded constraints: `READ_KEY` (read-only, ingest only) and `TRADE_KEY` (trade-only, withdraw permission disabled); both are stored in Railway Variables, never in git or logs; structlog redaction is verified; an optional manually-rotated panic-button key is documented; IP allowlist is enabled on `TRADE_KEY` if Railway egress IP is empirically stable.
  2. A fourth Railway service `risk-guard` is live and reachable on the private network, running `RemoteRiskGuard` that fails closed on timeout / error; a strategy-engine crash cannot disable risk enforcement; staged autonomy (`signal-only` → `semi-auto` → `full-auto`) is controlled by a row update to `strategy_instances.autonomy` with documented promotion criteria and no deploy required.
  3. The live edge tracker (RISK-13) compares realized vs backtested edge on a rolling 30-trade window and auto-pauses the strategy if realized drops below 0.5× backtested; monthly model retrain runs with a champion/challenger gate (challenger promotes only after beating champion OOS); weekly walk-forward re-run fires drift alerts on feature-distribution KS-statistic.
  4. Grafana dashboards (equity curve, daily P&L, win rate, exposure, drawdown, per-source data freshness) are live for the first time in the project — Phases 0–4 deliberately used Telegram + structured logs; Sentry captures uncaught exceptions and surfaces stack traces to Telegram.
  5. Weekly fee reconciliation alerts when realized fees diverge from the `FeeModel` by >5%; the slippage model is recalibrated from paper-trading fills and the backtester's slippage parameters are updated accordingly; pre-trade margin reservation prevents "insufficient margin" rejections mid-pump; per-endpoint priority queue handles rate-limit pressure during high-activity periods.

**Plans**: TBD
**Research flag**: MEXC API quirks under live conditions (hedge vs one-way mode, `reduceOnly` behavior in May 2026 ccxt minor, recv_window tuning, IP allowlist Railway egress stability) require paper-then-live smoke tests; capital-tier-aware position sizing piecewise function needs concrete breakpoints once a real account is funded.

## Progress

**Execution Order:**
Phases execute in numeric order: 0 → 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Foundation | 8/8 | Complete   | 2026-05-21 |
| 1. Data Platform | 3/11 | In Progress|  |
| 2. Strategy Research + ML Methodology | 0/TBD | Not started | - |
| 3. Backtester + Strategy Framework | 0/TBD | Not started | - |
| 4. Paper Trading (HARD GATE) | 0/TBD | Not started | - |
| 5. Live Trading | 0/TBD | Not started | - |

## Hard Gates (from research/SUMMARY.md)

These gates are non-negotiable and enforced at the listed phase transitions. They override granularity, schedule, or any pressure to compress phases.

| Gate | Where Enforced | Why |
|------|----------------|-----|
| Schema invariants (`universe_snapshots`, `source` column, TIMESTAMPTZ, L2 capture) before first training | Phase 1 → Phase 2 transition | Cannot be retrofitted; survivorship + slippage realism depend on this |
| Hypothesis property tests for leakage before first model trains | Phase 2 commit-zero | Leakage discovered later invalidates everything downstream |
| Backtester produces positive-EV strategy on never-touched holdout with realistic costs | Phase 3 → Phase 4 transition | No point paper-trading a known-negative strategy |
| Kill switch infrastructure exists and tested before first paper trade | Phase 4 commit-zero | First time you need a kill switch in live is too late |
| ≥1 month paper trading with positive EV and paper-vs-backtest divergence <10% | Phase 4 → Phase 5 transition | PROJECT.md hard constraint |
| `place_order(intent=)` wrapper with Hypothesis `reduceOnly` invariant before first live trade | Phase 4 wrapper, Phase 5 gate | Single most expensive solo-dev mistake |
| Two MEXC API keys (read-only + trade-no-withdraw) before any live key created | Phase 5 commit-zero | API key leakage is catastrophic |
| Live edge tracker (realized vs backtest) functional before full-auto promotion | Phase 5 staged autonomy progression | Staged autonomy is the trust gate |
| No Phase 6+ work until live signal-only EV-positive | Roadmap discipline (milestone exit) | Premature scaling = premature optimization |
