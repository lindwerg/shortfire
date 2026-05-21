# Requirements: MEXC Futures Sniper (ShortFIRE)

**Defined:** 2026-05-21
**Core Value:** Найти асимметричные точки входа в шорт после пампов с положительным expected value, доказанным на walk-forward валидации и paper trading — прежде чем рисковать реальным капиталом.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Foundation (FOUND)

- [x] **FOUND-01**: Repository scaffold with uv + ruff + pyright + pytest + Hypothesis is set up and CI runs on every push
- [x] **FOUND-02**: Railway project with PostgreSQL 16 + TimescaleDB 2.18 extension is provisioned and connected from GitHub
- [x] **FOUND-03**: Alembic migrations with TimescaleDB-aware DDL (`create_hypertable`, compression policies) are wired and tested
- [x] **FOUND-04**: Pure domain types (`Candle`, `OrderBook`, `Funding`, `Liquidation`, `Signal`, `Order`, `Position`, `RiskLimits`) are defined as Pydantic models with property tests on invariants
- [x] **FOUND-05**: Structured logging (structlog with correlation IDs) and Prometheus `/metrics` endpoint scaffolding exist in the service skeleton
- [x] **FOUND-06**: `.gitignore` covers `.env*`, secret scanning runs pre-commit, GitHub secret scanning is enabled
- [x] **FOUND-07**: pydantic-settings validates required env vars at service startup; missing/invalid config fails fast with clear error
- [x] **FOUND-08**: `tests/fakes/` directory exists with `FakeMexcClient`, `FakeCoinglassClient`, `FakeCoinGeckoClient`, `InMemoryCandleRepo` interfaces

### Data Platform — Ingest (DATA)

- [x] **DATA-01**: MEXC USDT-perp OHLCV candles (1m, 5m, 15m, 1h, 4h, 1d) ingest via ccxt for entire qualifying universe
- [x] **DATA-02**: MEXC funding rate history (per-symbol, both `settlement_ts` and `published_ts` timestamps) ingest
- [x] **DATA-03**: MEXC open interest history (per-symbol, hourly granularity) ingest
- [x] **DATA-04**: MEXC signed trades (recent N or websocket stream with persistence) ingest
- [x] **DATA-05**: MEXC L2 order book top-20 snapshots sampled every 5–10s per qualifying symbol
- [x] **DATA-06**: MEXC liquidation events ingest (via websocket or REST polling)
- [x] **DATA-07**: Coinglass funding-aggregate, OI-aggregate, long/short ratio, liquidation data ingest (within Startup tier $79/mo limits)
- [x] **DATA-08**: CoinGecko daily market metadata (price, volume, market cap, category, listing date) ingest
- [x] **DATA-09**: All ingest pipelines are idempotent on `(symbol, ts, source)` — re-ingest yields no duplicates or schema drift
- [ ] **DATA-10**: Ingest uses tenacity retries with exponential backoff and aiolimiter rate limits per API provider
- [x] **DATA-11**: Pydantic schema validation runs on every API response; validation failures land in a `dead_letter` table for inspection
- [x] **DATA-12**: Each derivatives row carries an explicit `source` column (e.g. `mexc_native`, `coinglass_aggregate`) — MEXC-native and Coinglass-aggregate are NEVER conflated

### Data Platform — Storage (STOR)

- [x] **STOR-01**: Typed-per-source TimescaleDB hypertables exist (`raw_mexc_candles_1m`, `raw_mexc_funding`, `raw_mexc_oi`, `raw_mexc_l2_top20`, `raw_coinglass_funding_agg`, `raw_coinglass_liq`, `raw_coingecko_market`, etc.)
- [x] **STOR-02**: Universal narrow schema (`metric_name, value`) is explicitly REJECTED — typed hypertables only
- [x] **STOR-03**: All time columns use `TIMESTAMPTZ` (UTC); never `TIMESTAMP` without timezone
- [x] **STOR-04**: Compression policies are applied after 7-day data age via `add_compression_policy`
- [x] **STOR-05**: Continuous aggregates exist for 5m / 15m / 1h / 4h rollups of 1m base data
- [x] **STOR-06**: Daily `universe_snapshots` hypertable captures full set of MEXC perp symbols listed AT each historical date (anti-survivorship)
- [x] **STOR-07**: Symbol lifecycle handled via soft delete (`delisted_at` column); `ON DELETE CASCADE` is banned
- [ ] **STOR-08**: Backfill of 1–2 years of historical data completes successfully for OHLCV + funding (Coinglass Startup tier limits accepted for 1m derivatives — defer Standard tier decision to Phase 2)
- [x] **STOR-09**: Backfill gaps are flagged with a `quality_flag` column rather than silently interpolated
- [ ] **STOR-10**: Daily `pg_dump` to external storage (R2/B2) runs and is verifiable

### Universe Filtering (UNIV)

- [x] **UNIV-01**: Dynamic universe filter: any MEXC perp with 24h USD volume > $500K qualifies for inclusion
- [x] **UNIV-02**: Universe membership refreshes daily and writes into `universe_snapshots`
- [x] **UNIV-03**: Querying universe at historical timestamp T returns "listed AT T" (point-in-time), not "listed today"
- [x] **UNIV-04**: New listing detection within 24h of MEXC listing announcement

### Scheduling & Orchestration (ORCH)

- [x] **ORCH-01**: APScheduler 4.x runs in the `data-platform` service with Postgres jobstore for persistence
- [x] **ORCH-02**: Ingest cadence is scheduler-controlled per source (e.g. MEXC OHLCV: every minute; Coinglass funding: hourly; CoinGecko: daily)
- [ ] **ORCH-03**: Data freshness gauge per source is exposed in Prometheus `/metrics`
- [ ] **ORCH-04**: Stale-data Telegram alert fires when any source exceeds expected lag

### Feature Engineering (FEAT)

- [ ] **FEAT-01**: Strategy-agnostic primitive library exists as pure functions: `rsi`, `divergence`, `funding_zscore`, `oi_roc`, `liq_cascade_magnitude`, `vwap`, `btc_corr`, `volume_profile_poc`
- [ ] **FEAT-02**: Every primitive has a Hypothesis property test asserting causality (duplicate row at T, shift by N seconds, value at original T must not change)
- [ ] **FEAT-03**: Multi-timeframe RSI features (1m/5m/15m/1h/4h) with explicit `closed='left'` rolling
- [ ] **FEAT-04**: Funding rate spike features (z-score over rolling window, with `settlement_ts` boundary respect)
- [ ] **FEAT-05**: OI rate-of-change features at multiple horizons
- [ ] **FEAT-06**: Liquidation cascade depth / magnitude features
- [ ] **FEAT-07**: Volume profile features (POC, value area high/low) per session
- [ ] **FEAT-08**: BTC correlation + decoupling features (rolling correlation, residual return)
- [ ] **FEAT-09**: Regime features (BTC 30d realized vol, BTC drawdown, market-wide funding average)
- [ ] **FEAT-10**: Funding-window-conditioned features (`seconds_to_next_funding`)
- [ ] **FEAT-11**: Listing-age feature (new < 30d, young 30–180d, mature > 180d)
- [ ] **FEAT-12**: Short-after-pump feature pipeline composes primitives into `features_short_after_pump_v<spec_hash>` table
- [ ] **FEAT-13**: Spec hash on feature pipeline auto-invalidates stale features on definition changes
- [ ] **FEAT-14**: `bfill` and forward-looking interpolation are project-banned (lint rule or pre-commit check)

### Pump Detection & Labeling (LABEL)

- [ ] **LABEL-01**: Algorithmic pump detector identifies pumps with parameterized thresholds (e.g. +X% return over Y minutes on Z× volume); writes to versioned `pump_events` table
- [ ] **LABEL-02**: Pump archaeology — `detector_version_id` ties every label set to a detector parameterization; re-running with new params adds new versioned rows, does not destroy history
- [ ] **LABEL-03**: Triple-barrier labeling (Lopez de Prado) with parameterized TP / SL / timeout in minutes — primary labeling method, finalized in Phase 2 after EDA per PROJECT.md
- [ ] **LABEL-04**: Label-window boundaries respect funding settlement times — Hypothesis property test enforces "labels never cross a funding window without explicit modeling"

### ML Methodology (ML)

- [ ] **ML-01**: Custom `PurgedWalkForward` splitter with `label_horizon` and `embargo_pct` parameters; sklearn `TimeSeriesSplit` is explicitly REJECTED
- [ ] **ML-02**: Hypothesis property test: no training index falls within `label_horizon + embargo` of any test index
- [ ] **ML-03**: Class imbalance handled via cost-sensitive loss / `scale_pos_weight` — NOT naive `class_weight='balanced'`
- [ ] **ML-04**: Primary evaluation metric is precision @ top-N signals per day per symbol; AUC and raw accuracy are explicitly NOT the gating metrics
- [ ] **ML-05**: Threshold tuning happens on a separate validation holdout, not the test set
- [ ] **ML-06**: Calibration check via isotonic regression or reliability diagram is part of the model evaluation pipeline
- [ ] **ML-07**: Rule-based sanity baseline (e.g. "short if RSI 1h > 80 AND funding z > 2") is benchmarked against ML model — ML must beat the baseline OOS to qualify
- [ ] **ML-08**: 3-set protocol enforced: train → validation → never-touched holdout; holdout untouched until final report

### ML Training & Tracking (TRAIN)

- [ ] **TRAIN-01**: XGBoost 3.2 baseline model trains end-to-end on the short-after-pump feature pipeline
- [ ] **TRAIN-02**: LightGBM 4.6 secondary model trains for comparison
- [ ] **TRAIN-03**: Optuna 4.x hyperparameter search (TPE + MedianPruner, ≤200 trials per run) uses the `PurgedWalkForward` splitter
- [ ] **TRAIN-04**: MLflow 3.x tracks every training run on the shared Postgres backend
- [ ] **TRAIN-05**: Every MLflow run records code commit hash AND data snapshot id (reproducibility)
- [ ] **TRAIN-06**: SHAP explainability is computed for every model artifact and per-signal explanations are stored in DB for downstream Telegram rendering
- [ ] **TRAIN-07**: Stability test: training across N walk-forward splits, top-K features and metric variance are reported — overfitting is detected by high variance

### Strategy Framework (STRAT)

- [ ] **STRAT-01**: `Strategy` Protocol defines `features_required`, `generate_signals`, `position_sizing_hint`
- [ ] **STRAT-02**: `StrategyRegistry` is the entry point for backtester, paper trading, and live; adding a new strategy requires a registered subclass plus a row in `strategy_instances`
- [ ] **STRAT-03**: `strategy_instances` table stores params per strategy (NOT YAML/code); promotion paper → live = row update, not deploy
- [ ] **STRAT-04**: ShortAfterPumpStrategy is the first concrete `Strategy` implementation
- [ ] **STRAT-05**: Risk logic lives OUTSIDE strategy logic — strategy emits `SignalIntent`; `RiskGuard` decides actual order

### Backtester (BACK)

- [ ] **BACK-01**: Event-driven backtester (NOT vectorized for execution); same `Strategy` interface used by paper and live
- [ ] **BACK-02**: MEXC fee model with effective dates (maker/taker, VIP discounts, periodic promos) is a single source of truth
- [ ] **BACK-03**: Depth-conditioned slippage model walks the L2 book against captured snapshots
- [ ] **BACK-04**: Partial fills are modeled
- [ ] **BACK-05**: Funding payments at 8h crossings are accounted for in P&L (mark-to-market each settlement)
- [ ] **BACK-06**: Signal-time vs execution-time are distinguished; signals at bar-close cannot fill at bar-close (latency offset enforced)
- [ ] **BACK-07**: Stop-loss orders fill via book-walk from the trigger price, NOT at the trigger price
- [ ] **BACK-08**: Walk-forward backtest harness re-fits the model at each split and concatenates OOS predictions
- [ ] **BACK-09**: Parameter robustness sweep tests strategy stability across small parameter perturbations
- [ ] **BACK-10**: Backtest output is deterministic given `data_snapshot_id + code_commit_hash`
- [ ] **BACK-11**: `quantstats` (or equivalent) tearsheets are auto-generated per backtest
- [ ] **BACK-12**: Equity curve bootstrapped confidence intervals quantify uncertainty

### Paper Trading (PAPER)

- [ ] **PAPER-01**: `PaperOrderRouter` implementation uses SAME code path as `MexcOrderRouter` (live); execution module is broker-swappable
- [ ] **PAPER-02**: Paper trading runs against the live ccxt Pro feed for the qualifying universe
- [ ] **PAPER-03**: Paper trading applies SAME book-walk slippage model as the backtester
- [ ] **PAPER-04**: Artificial latency injection (200–500ms, randomized) between signal and order placement
- [ ] **PAPER-05**: Maker/taker classification rule is IDENTICAL between paper and live (no optimistic maker assumption in paper)
- [ ] **PAPER-06**: Paper-vs-backtest reconciliation report runs daily; divergence > 10% triggers investigation BEFORE live promotion
- [ ] **PAPER-07**: Per-trade audit log records signal, model version, SHAP top-N, intended order, simulated fill, P&L
- [ ] **PAPER-08**: Pre-registered model version locks for the paper trading window; mid-paper model swap voids the gate
- [ ] **PAPER-09**: ≥ 1 month positive EV in paper trading is required before any live consideration

### Risk Management (RISK)

- [ ] **RISK-01**: Quarter-Kelly position sizing on BIAS-CORRECTED edge (CI shrinkage applied), not raw backtest mean
- [ ] **RISK-02**: Hard absolute caps INDEPENDENT of Kelly: max 5% per trade, max 15% gross exposure
- [ ] **RISK-03**: Capital-tier-aware position sizing scales correctly from $500 to $50K+ accounts (account-aware function `position_sizing(equity, kelly, min_notional, max_concurrent)`)
- [ ] **RISK-04**: ATR-based stop-loss + optional trailing stop + time-based exit
- [ ] **RISK-05**: Max concurrent positions limit enforced
- [ ] **RISK-06**: Per-symbol exposure limit enforced
- [ ] **RISK-07**: Daily loss circuit breaker auto-halts new orders when threshold tripped
- [ ] **RISK-08**: Max drawdown circuit breaker auto-halts new orders when peak-to-trough exceeds threshold
- [ ] **RISK-09**: Position reconciliation loop every 60s compares local state with MEXC exchange state and alerts on divergence
- [ ] **RISK-10**: Kill switch is available via Telegram `/halt`, HTTP endpoint, AND triggers automatically on circuit breaker breach
- [ ] **RISK-11**: Kill switch tested monthly via documented fire-drill procedure
- [ ] **RISK-12**: `InProcessRiskGuard` runs in paper (Phase 4); `RemoteRiskGuard` on separate Railway service runs in live (Phase 5) — fails closed on timeout/error
- [ ] **RISK-13**: Live edge tracker compares realized vs backtested edge; auto-pauses if realized < 0.5× backtested over rolling 30 trades

### Execution (EXEC)

- [ ] **EXEC-01**: Mandatory `place_order(intent='open'|'close')` wrapper sets `reduceOnly=True` mechanically on close orders; raw ccxt order calls are inaccessible outside the wrapper
- [ ] **EXEC-02**: Hypothesis invariant: every order with `intent='close'` has `params.reduceOnly == True`
- [ ] **EXEC-03**: MEXC position mode (hedge vs one-way) is asserted at service startup; mismatch fails startup
- [ ] **EXEC-04**: Client order IDs are generated for dedup and stored alongside exchange order ids
- [ ] **EXEC-05**: Slippage protection (max slippage %) on market orders; reject if pre-trade book walk exceeds threshold
- [ ] **EXEC-06**: Order state machine handles pending → submitted → partial → filled / canceled / failed transitions
- [ ] **EXEC-07**: Graceful SIGTERM shutdown cancels open orders and flushes state
- [ ] **EXEC-08**: Pre-trade margin reservation prevents "insufficient margin" rejections mid-pump
- [ ] **EXEC-09**: Per-endpoint priority queue for rate-limit-aware order placement during high-activity periods

### Live Trading (LIVE)

- [ ] **LIVE-01**: Two MEXC API keys: `READ_KEY` (read-only, ingest only) and `TRADE_KEY` (trade-only, no withdraw) — withdraw permission disabled on both
- [ ] **LIVE-02**: Optional third "panic-button" key for manual position closure during emergencies, rotated manually
- [ ] **LIVE-03**: API keys are stored in Railway Variables; never in git, logs, or ccxt verbose output
- [ ] **LIVE-04**: structlog redactor strips keys from log lines before emission
- [ ] **LIVE-05**: IP allowlist on TRADE_KEY if Railway egress IP is stable (verified empirically)
- [ ] **LIVE-06**: Hybrid autonomy staging — start in `signal-only`, then `semi-auto` (Telegram inline keyboard confirm), then `full-auto` — controlled via `strategy_instances.autonomy` row (no deploy required)
- [ ] **LIVE-07**: Promotion criteria from each autonomy stage are documented and enforced (sustained positive realized edge, minimum trade count, no breached circuit breakers)
- [ ] **LIVE-08**: Slippage model calibrates from paper-trading fills and updates the backtester slippage parameters
- [ ] **LIVE-09**: Monthly model retrain cadence with champion/challenger gate; challenger promotes only after beating champion OOS
- [ ] **LIVE-10**: Weekly walk-forward re-run with drift alerts (feature distribution KS-statistic)
- [ ] **LIVE-11**: Fee reconciliation cron weekly; alert if realized fees diverge from FeeModel by > 5%

### Observability (OBS)

- [ ] **OBS-01**: Telegram bot sends signal alerts with SHAP top-N feature contributions rendered ("shorting because: RSI 4h=88 (+0.31), funding z=2.4 (+0.22), OI Δ1h=+18% (+0.18)")
- [ ] **OBS-02**: Telegram daily equity / P&L summary
- [ ] **OBS-03**: Telegram severity-tagged channels (INFO/WARN/CRIT) separate routine signals from emergencies
- [ ] **OBS-04**: Telegram `/halt`, `/resume`, `/status` commands work and are authenticated to operator chat id
- [ ] **OBS-05**: Prometheus `/metrics` endpoint on every service exposes data freshness, ingest counts, signal counts, position counts, equity, latency histograms
- [ ] **OBS-06**: Grafana dashboards live at Phase 5 (live trading) — NOT earlier: equity curve, daily P&L, win rate, exposure, drawdown, per-source data freshness
- [ ] **OBS-07**: Sentry (free tier) captures uncaught exceptions and surfaces stack traces in Telegram

### DevOps / CI-CD (OPS)

- [x] **OPS-01**: GitHub repository created with protected `main` branch
- [x] **OPS-02**: Railway project connected to GitHub repo; auto-deploys on push to `main`
- [x] **OPS-03**: GitHub Actions CI runs on every PR: ruff + pyright + pytest (with coverage)
- [x] **OPS-04**: CI blocks merge on failing tests or coverage drop below 80% (95% on `risk/` and `execution/` modules)
- [ ] **OPS-05**: Commit → push → deploy to Railway after every completed task (per PROJECT.md DevOps requirement)
- [ ] **OPS-06**: Three Railway services at v1: `data-platform`, `strategy-engine`, `dashboard`; fourth `risk-guard` added at live launch
- [x] **OPS-07**: Database migration discipline — Alembic migration files reviewed, applied in deploy step
- [x] **OPS-08**: Pre-commit hooks: ruff format, ruff lint, secret scan

### Testing & TDD (TEST)

- [x] **TEST-01**: pytest + Hypothesis + pytest-asyncio configured; respx/aioresponses for API client mocks
- [x] **TEST-02**: TDD discipline — every module starts with a failing test; documented in `CONTRIBUTING.md` or `AGENTS.md`
- [ ] **TEST-03**: Property tests cover: feature causality, label-window funding boundaries, walk-forward purge invariants, `reduceOnly` invariants, order state machine transitions
- [ ] **TEST-04**: Coverage gate: 80% project-wide, 95% on `risk/` and `execution/` modules
- [x] **TEST-05**: `tests/fakes/` provides deterministic fakes for every external boundary (MEXC, Coinglass, CoinGecko, OrderRouter, RiskGuard)
- [x] **TEST-06**: freezegun is used for time-dependent tests
- [ ] **TEST-07**: Backtest reproducibility test: same `data_snapshot_id + code_commit` produces identical P&L

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Strategy Expansion (V2-STRAT)

- **V2-STRAT-01**: Meta-labeling layer (Lopez de Prado primary + meta)
- **V2-STRAT-02**: Second strategy on shared data layer (plug into Phase 3 framework)
- **V2-STRAT-03**: CatBoost / PyTorch sequence models as ensemble members
- **V2-STRAT-04**: Long-side setups as separate strategy (not mixed into short model)

### Data Expansion (V2-DATA)

- **V2-DATA-01**: Coinglass Standard tier ($299/mo) upgrade — conditional on Phase 2 EDA proving 1m derivatives > 12 days adds edge
- **V2-DATA-02**: Backtest-grade L2 reconstruction replay for top-impact trades

### Infrastructure (V2-INFRA)

- **V2-INFRA-01**: Prefect 3 self-hosted migration (if APScheduler DAG dependencies emerge)
- **V2-INFRA-02**: ClickHouse migration (if TimescaleDB compression + continuous aggregates prove inadequate at scale)
- **V2-INFRA-03**: NautilusTrader migration (if Nautilus stabilizes and custom backtester maintenance burden justifies)

### Multi-Exchange (V2-EXCH)

- **V2-EXCH-01**: Binance / Bybit / OKX execution adapters via the `OrderRouter` interface

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Multi-user / SaaS / billing | Solo tool only; auth/multi-tenant adds zero edge |
| Spot trading | Need futures + leverage for the asymmetric post-pump short hypothesis |
| Long setups in same model | Different statistical regime; separate strategy if pursued |
| Twitter/NLP sentiment | Signal-to-noise far worse than derivatives proxies; PROJECT.md excludes |
| DEX futures (dYdX, GMX) | Different liquidity profile and execution cost model |
| Mobile app | Telegram + Grafana sufficient for solo operator |
| Custom dashboard GUI from scratch | Grafana + Telegram cover the need |
| Real-time tick architecture | 1m-bar strategy doesn't need sub-second latency |
| HFT-style L3 microstructure features | Strategy horizon (scalp/intraday) doesn't justify |
| Reinforcement learning for v1 | Notoriously unstable on financial time series; defer post-validation |
| Online live parameter optimization | Defeats circuit-breaker invariants and risk envelope |
| 100% test coverage as a goal | 80% project-wide, 95% on risk/execution is the rule |
| L3 order book storage | L2 top-20 is sufficient for slippage modeling |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-01 | Phase 0 | Complete |
| FOUND-02 | Phase 0 | Complete |
| FOUND-03 | Phase 0 | Complete |
| FOUND-04 | Phase 0 | Complete |
| FOUND-05 | Phase 0 | Complete |
| FOUND-06 | Phase 0 | Complete |
| FOUND-07 | Phase 0 | Complete |
| FOUND-08 | Phase 0 | Complete |
| DATA-01 | Phase 1 | Complete |
| DATA-02 | Phase 1 | Complete |
| DATA-03 | Phase 1 | Complete |
| DATA-04 | Phase 1 | Complete |
| DATA-05 | Phase 1 | Complete |
| DATA-06 | Phase 1 | Complete |
| DATA-07 | Phase 1 | Complete |
| DATA-08 | Phase 1 | Complete |
| DATA-09 | Phase 1 | Complete |
| DATA-10 | Phase 1 | Pending |
| DATA-11 | Phase 1 | Complete |
| DATA-12 | Phase 1 | Complete |
| STOR-01 | Phase 1 | Complete |
| STOR-02 | Phase 1 | Complete |
| STOR-03 | Phase 1 | Complete |
| STOR-04 | Phase 1 | Complete |
| STOR-05 | Phase 1 | Complete |
| STOR-06 | Phase 1 | Complete |
| STOR-07 | Phase 1 | Complete |
| STOR-08 | Phase 1 | Pending |
| STOR-09 | Phase 1 | Complete |
| STOR-10 | Phase 1 | Pending |
| UNIV-01 | Phase 1 | Complete |
| UNIV-02 | Phase 1 | Complete |
| UNIV-03 | Phase 1 | Complete |
| UNIV-04 | Phase 1 | Complete |
| ORCH-01 | Phase 1 | Complete |
| ORCH-02 | Phase 1 | Complete |
| ORCH-03 | Phase 1 | Pending |
| ORCH-04 | Phase 1 | Pending |
| FEAT-01 | Phase 2 | Pending |
| FEAT-02 | Phase 2 | Pending |
| FEAT-03 | Phase 2 | Pending |
| FEAT-04 | Phase 2 | Pending |
| FEAT-05 | Phase 2 | Pending |
| FEAT-06 | Phase 2 | Pending |
| FEAT-07 | Phase 2 | Pending |
| FEAT-08 | Phase 2 | Pending |
| FEAT-09 | Phase 2 | Pending |
| FEAT-10 | Phase 2 | Pending |
| FEAT-11 | Phase 2 | Pending |
| FEAT-12 | Phase 2 | Pending |
| FEAT-13 | Phase 2 | Pending |
| FEAT-14 | Phase 2 | Pending |
| LABEL-01 | Phase 2 | Pending |
| LABEL-02 | Phase 2 | Pending |
| LABEL-03 | Phase 2 | Pending |
| LABEL-04 | Phase 2 | Pending |
| ML-01 | Phase 2 | Pending |
| ML-02 | Phase 2 | Pending |
| ML-03 | Phase 2 | Pending |
| ML-04 | Phase 2 | Pending |
| ML-05 | Phase 2 | Pending |
| ML-06 | Phase 2 | Pending |
| ML-07 | Phase 2 | Pending |
| ML-08 | Phase 2 | Pending |
| TRAIN-01 | Phase 2 | Pending |
| TRAIN-02 | Phase 2 | Pending |
| TRAIN-03 | Phase 2 | Pending |
| TRAIN-04 | Phase 2 | Pending |
| TRAIN-05 | Phase 2 | Pending |
| TRAIN-06 | Phase 2 | Pending |
| TRAIN-07 | Phase 2 | Pending |
| STRAT-01 | Phase 3 | Pending |
| STRAT-02 | Phase 3 | Pending |
| STRAT-03 | Phase 3 | Pending |
| STRAT-04 | Phase 3 | Pending |
| STRAT-05 | Phase 3 | Pending |
| BACK-01 | Phase 3 | Pending |
| BACK-02 | Phase 3 | Pending |
| BACK-03 | Phase 3 | Pending |
| BACK-04 | Phase 3 | Pending |
| BACK-05 | Phase 3 | Pending |
| BACK-06 | Phase 3 | Pending |
| BACK-07 | Phase 3 | Pending |
| BACK-08 | Phase 3 | Pending |
| BACK-09 | Phase 3 | Pending |
| BACK-10 | Phase 3 | Pending |
| BACK-11 | Phase 3 | Pending |
| BACK-12 | Phase 3 | Pending |
| PAPER-01 | Phase 4 | Pending |
| PAPER-02 | Phase 4 | Pending |
| PAPER-03 | Phase 4 | Pending |
| PAPER-04 | Phase 4 | Pending |
| PAPER-05 | Phase 4 | Pending |
| PAPER-06 | Phase 4 | Pending |
| PAPER-07 | Phase 4 | Pending |
| PAPER-08 | Phase 4 | Pending |
| PAPER-09 | Phase 4 | Pending |
| RISK-01 | Phase 4 | Pending |
| RISK-02 | Phase 4 | Pending |
| RISK-03 | Phase 4 | Pending |
| RISK-04 | Phase 4 | Pending |
| RISK-05 | Phase 4 | Pending |
| RISK-06 | Phase 4 | Pending |
| RISK-07 | Phase 4 | Pending |
| RISK-08 | Phase 4 | Pending |
| RISK-09 | Phase 4 | Pending |
| RISK-10 | Phase 4 | Pending |
| RISK-11 | Phase 4 | Pending |
| RISK-12 | Phase 4 | Pending |
| RISK-13 | Phase 5 | Pending |
| EXEC-01 | Phase 4 | Pending |
| EXEC-02 | Phase 4 | Pending |
| EXEC-03 | Phase 4 | Pending |
| EXEC-04 | Phase 4 | Pending |
| EXEC-05 | Phase 4 | Pending |
| EXEC-06 | Phase 4 | Pending |
| EXEC-07 | Phase 4 | Pending |
| EXEC-08 | Phase 4 | Pending |
| EXEC-09 | Phase 4 | Pending |
| LIVE-01 | Phase 5 | Pending |
| LIVE-02 | Phase 5 | Pending |
| LIVE-03 | Phase 5 | Pending |
| LIVE-04 | Phase 5 | Pending |
| LIVE-05 | Phase 5 | Pending |
| LIVE-06 | Phase 5 | Pending |
| LIVE-07 | Phase 5 | Pending |
| LIVE-08 | Phase 5 | Pending |
| LIVE-09 | Phase 5 | Pending |
| LIVE-10 | Phase 5 | Pending |
| LIVE-11 | Phase 5 | Pending |
| OBS-01 | Phase 4 | Pending |
| OBS-02 | Phase 4 | Pending |
| OBS-03 | Phase 4 | Pending |
| OBS-04 | Phase 4 | Pending |
| OBS-05 | Phase 4 | Pending |
| OBS-06 | Phase 5 | Pending |
| OBS-07 | Phase 5 | Pending |
| OPS-01 | Phase 0 | Complete |
| OPS-02 | Phase 0 | Complete |
| OPS-03 | Phase 0 | Complete |
| OPS-04 | Phase 0 | Complete |
| OPS-05 | Phase 1 | Pending |
| OPS-06 | Phase 1 | Pending |
| OPS-07 | Phase 0 | Complete |
| OPS-08 | Phase 0 | Complete |
| TEST-01 | Phase 0 | Complete |
| TEST-02 | Phase 0 | Complete |
| TEST-03 | Phase 2 | Pending |
| TEST-04 | Phase 2 | Pending |
| TEST-05 | Phase 0 | Complete |
| TEST-06 | Phase 0 | Complete |
| TEST-07 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 152 total (counted across all sections)
- Mapped to phases: 152 ✓
- Unmapped: 0 ✓

**Coverage by phase:**

| Phase | Count | Requirements |
|-------|-------|--------------|
| Phase 0: Foundation | 18 | FOUND-01..08, OPS-01..04, OPS-07, OPS-08, TEST-01, TEST-02, TEST-05, TEST-06 |
| Phase 1: Data Platform | 32 | DATA-01..12, STOR-01..10, UNIV-01..04, ORCH-01..04, OPS-05, OPS-06 |
| Phase 2: Strategy Research + ML Methodology | 35 | FEAT-01..14, LABEL-01..04, ML-01..08, TRAIN-01..07, TEST-03, TEST-04 |
| Phase 3: Backtester + Strategy Framework | 18 | STRAT-01..05, BACK-01..12, TEST-07 |
| Phase 4: Paper Trading (HARD GATE) | 35 | PAPER-01..09, RISK-01..12, EXEC-01..09, OBS-01..05 |
| Phase 5: Live Trading | 14 | LIVE-01..11, RISK-13, OBS-06, OBS-07 |
| **Total** | **152** | |

---
*Requirements defined: 2026-05-21*
*Last updated: 2026-05-21 after roadmap creation (traceability populated)*
