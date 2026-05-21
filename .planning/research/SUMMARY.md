# Project Research Summary

**Project:** MEXC Futures Sniper (ShortFIRE)
**Domain:** Crypto futures ML trading platform — MEXC USDT-perp short-after-pump strategy on a strategy-agnostic data platform, solo operator, Railway-deployed, hybrid autonomy escalation (signal-only → semi-auto → full-auto)
**Researched:** 2026-05-21
**Confidence:** HIGH for stack lock-ins, table-stakes feature set, and critical research/execution pitfalls; MEDIUM for exact phase ordering (depends on Phase 2 EDA outcomes); KNOWN-RISK on Coinglass historical depth and MEXC API behavior under live conditions

## Executive Summary

This project is **four products glued together on one Postgres+TimescaleDB instance**: a strategy-agnostic time-series data warehouse (MEXC + Coinglass + CoinGecko), an offline ML research loop (walk-forward + MLflow + SHAP), a paper-trading simulator on live feeds, and a hybrid-autonomy live execution stack. The competitive position is **purpose-built ML research platform meets MEXC-specific memecoin perp execution** — none of the open-source crypto bots (freqtrade, jesse, NautilusTrader, Hummingbot) treat ML as a first-class concern with SHAP-per-signal explainability, funding-window-aware labeling, and Coinglass derivatives stitching. That is the moat.

The recommended approach is **TDD-first, Python-only, single-Postgres, three-Railway-services**: `data-platform` (ingest + features), `strategy-engine` (signals + paper/live execution), `dashboard` (read-only FastAPI). A fourth `risk-guard` service spins up only when real capital goes live. Stack is locked: Python 3.12 + FastAPI + ccxt 4.5 + Polars 1.40 (batch) + pandas 2.2 (model boundary) + XGBoost 3.2 / LightGBM 4.6 + Optuna 4.x + MLflow 3.x + APScheduler 4.x + asyncpg/psycopg v3 + Hypothesis. Coinglass Startup tier ($79/mo) is the floor; Coinglass Standard ($299/mo) is a Phase-2 conditional upgrade.

The dominant risks are not technical — they are **research-integrity risks** (survivorship bias, look-ahead leakage, walk-forward done wrong, regime blindness, paper-trading better than live) and **capital-destroying execution mistakes** (missing `reduceOnly` flag, unrealistic slippage, API key leakage, missing kill switch). The roadmap MUST treat the following as Phase 1 commit-zero non-negotiables: daily universe snapshots, L2 order book sampling, schema with `source` attribution on every derivatives row, TIMESTAMPTZ enforcement, structured logging, and Hypothesis property tests for leakage invariants. Without these from day 1, retrofitting is either impossible (survivorship) or extremely expensive (slippage realism).

## Key Findings

### Recommended Stack

The stack is **uncontroversial defaults compressing operational surface area to what one person can maintain**. See STACK.md for full details and version pins.

**Core lock-ins (decided, not deferred):**

- **Python 3.12** — sweet spot for pandas/polars/xgboost/lightgbm wheel coverage; 3.13 buys nothing here.
- **FastAPI 0.115 + uvicorn 0.42 + Pydantic 2.7** — standard async Python API stack; Pydantic v2 for schema validation at every external boundary (MEXC/Coinglass/CoinGecko/env vars).
- **PostgreSQL 16 + TimescaleDB 2.18 on Railway** — single managed DB for time-series + relational + MLflow + Optuna + APScheduler. Hypercore hybrid row+columnar compression reaches 10-20x on candle data. ClickHouse is a Phase-3+ fallback if row count crosses ~500M with degraded query latency.
- **ccxt 4.5.54+** — unified MEXC client for REST + websockets, same code for paper and live. Pin minor version; MEXC swap endpoint shifts between ccxt minors (#28532, May 2026). Use `watch_trades` + client-side OHLCV build, NOT `watch_ohlcv` (#27253 hang).
- **Polars 1.40 (batch) + pandas 2.2 (model boundary)** — Polars for backfill/feature compute, pandas only at XGBoost/sklearn interop boundary.
- **XGBoost 3.2 primary + LightGBM 4.6 secondary + Optuna 4.x + MLflow 3.x + SHAP 0.45** — XGBoost as forgiving production default, LightGBM as fast secondary, Optuna for hyperparam search, MLflow self-hosted on same Postgres, SHAP for per-signal explainability (gating autonomy escalation).
- **APScheduler 4.x in-process for v1** — single scheduler in `data-platform` service, Postgres jobstore for persistence. Prefect 3 migration deferred to Phase 3+ if DAG dependencies emerge.
- **asyncpg (hot-path COPY) + psycopg v3 + SQLAlchemy 2.x Core** — ORM only for low-volume relational tables; raw COPY for hypertable inserts.
- **uv (package manager) + Ruff + pyright + pytest + Hypothesis + pytest-asyncio + freezegun + respx/aioresponses** — testing stack with property tests on every trading invariant.
- **Custom event-driven backtester for v1** — NautilusTrader is still 1.x with breaking changes; evaluate post-edge-validation only.
- **Telegram (python-telegram-bot 21.x) + Grafana Cloud free + Prometheus + structlog + Sentry free** — operator interface + observability.

**Paid services floor: ~$84/mo** (Railway $5 + Coinglass Startup $79). Plan for ~$300+/mo if Coinglass Standard becomes necessary in Phase 2 (for >12-day 1m derivatives history).

**Deferred decisions (Phase-conditional, not lock-ins):**

- Coinglass Standard tier ($299/mo) — only if backtest fidelity needs >12 days of 1m derivatives history. Decided in Phase 2 after EDA.
- ClickHouse migration — only if TimescaleDB compression + continuous aggregates prove inadequate at scale. Phase 3+.
- Prefect 3 self-hosted — only if APScheduler outgrows DAG/retry/observability needs.
- CatBoost / PyTorch sequence models — Phase 3+, gated on baseline XGBoost/LightGBM proving edge.
- Labeling method (triple-barrier vs alternatives) — explicitly deferred to Phase 2 per PROJECT.md, after EDA.

### Expected Features

See FEATURES.md for full taxonomy with complexity sizing and dependency graph.

**Must have (v1 table stakes — bot is not viable without these):**

- **Data Platform:** MEXC OHLCV (1m–1d) + funding + OI + signed trades + L2 orderbook (top 20, 5–10s sampling); Coinglass funding-aggregate + OI + liquidations; CoinGecko market metadata (daily); idempotent ingest with retries/dead-letters; **daily universe snapshots** (`universe_snapshots` hypertable); **`source` column on every derivatives row** (MEXC-native vs Coinglass-aggregate are different signals); symbol lifecycle handling (no `ON DELETE CASCADE`, soft-delete with `delisted_at`); Alembic migrations with TimescaleDB-aware DDL.
- **Strategy Research:** algorithmic pump detector with versioned `pump_events` table; **triple-barrier labeling**; **walk-forward CV with purging + embargo** (custom `PurgedWalkForward`, NOT sklearn `TimeSeriesSplit`); **funding-window-aware label boundaries** with Hypothesis property tests; feature pipeline (multi-TF RSI + divergences, CVD + CVD divergence, OI ROC, funding z-score, liquidation cascade magnitude, volume profile/POC, BTC correlation + decoupling, BTC dominance regime); XGBoost + LightGBM baseline with Optuna tuning; MLflow tracking with code-commit + data-snapshot tags; **SHAP per-trade explainability stored in DB**.
- **Backtester:** event-driven (NOT vectorized for execution); MEXC fee model (maker/taker, with effective dates); **depth-conditioned slippage** (book-walk against L2 snapshot); partial fills; funding payment accounting; signal-time vs execution-time separation; walk-forward harness; parameter robustness sweeps; `quantstats` tearsheets; deterministic + data-snapshot-pinned for reproducibility.
- **Paper Trading:** live ccxt Pro feed + simulated execution using SAME execution code path as live; **artificial latency injection** (200–500ms) and identical slippage model to backtester; backtest-vs-paper reconciliation report (divergence < 10%); per-trade audit log.
- **Risk Management:** quarter-Kelly position sizing (on BIAS-CORRECTED edge with CI shrinkage, not raw backtest mean); **hard absolute cap** independent of Kelly (5% per trade, 15% gross); ATR-based stop-loss + trailing + time-based exit; max concurrent positions; daily loss + max drawdown circuit breakers; per-symbol exposure limit; **position reconciliation loop** every 60s against exchange state; **kill switch** (Telegram `/halt` + HTTP endpoint + automatic on breach) **tested monthly**.
- **Execution:** ccxt-based MEXC order placement with **mandatory `place_order(intent='open'|'close')` wrapper** that mechanically sets `reduceOnly=True` on close; client order IDs for dedup; slippage protection on market orders; order book aware sizing; order state machine; graceful SIGTERM shutdown; **two API keys** (read-only ingest, trade-no-withdraw execution).
- **Observability:** Grafana dashboard (equity, P&L, win rate, exposure, drawdown); per-source data freshness gauges; Prometheus `/metrics`; Telegram alerts with severity tags; structured JSON logs (structlog) with correlation IDs.
- **DevOps:** GitHub protected main; CI = ruff + pyright + pytest with 80%+ coverage gate (95%+ on risk and execution modules); Railway auto-deploy on push to main; Railway env vars + pydantic-settings validation + pre-commit secret scanning.

**Should have (v1.x — earn after paper trading passes; differentiators):**

- Multi-source funding/OI stitched features (MEXC-native + Coinglass aggregate as DISTINCT features with explicit `source` attribution).
- Liquidation cascade depth feature (recursive cluster modeling, not just $-magnitude).
- BTC-decoupling regime classifier (HMM or threshold-based).
- Per-trade SHAP rendered in Telegram alerts ("shorting because: RSI 4h=88 (+0.31), funding z=2.4 (+0.22), OI Δ1h=+18% (+0.18)") — non-negotiable trust gate for autonomy escalation.
- Pump archaeology (versioned `pump_events` with detector_version_id; regenerate labels without losing prior versions).
- Slippage model calibration from paper-trading fills → backtester update.
- Scheduled weekly walk-forward re-run with drift alerts.
- Model staleness monitoring (feature distribution KS-statistic).
- Funding-window-conditioned features (`seconds_to_next_funding`).
- Listing-age feature (new < 30d, young 30–180d, mature > 180d).
- Adaptive position sizing by capital tier ($500 → $50K+).
- Operator-in-the-loop semi-auto (Telegram inline keyboard "Execute" / "Skip").

**Defer (v2+ — only after live edge validated):**

- Meta-labeling (Lopez de Prado primary + meta).
- Second strategy on shared data layer (the multi-strategy interface ships in v1 but additional strategies wait).
- CatBoost / PyTorch sequence models.
- Coinglass Standard tier upgrade (conditional).
- Backtest L2 reconstruction replay for top-impact trades.
- Multi-exchange execution (Binance/Bybit/OKX).
- Prefect / ClickHouse migrations.

**Explicit anti-features (BANNED — bake into REQUIREMENTS.md "Out of Scope"):**

- Multi-user / SaaS / billing (solo only).
- Spot trading (need futures + leverage for asymmetry).
- Long setups in same model (different statistical regime; separate strategy).
- Twitter/NLP sentiment (signal-to-noise far worse than derivatives proxies; PROJECT.md already excludes).
- DEX futures (dYdX/GMX — different liquidity profile).
- Mobile app (Telegram + Grafana suffices).
- Custom GUI from scratch (Grafana + Telegram).
- Real-time tick-by-tick architecture (1m-bar strategy doesn't need sub-second latency).
- HFT-style L3 microstructure features.
- Reinforcement learning for v1.
- Online live parameter optimization.
- 100% test coverage as a goal (80% rule; 95%+ on risk/execution).
- L3 order book storage.

### Architecture Approach

See ARCHITECTURE.md for full design including DDL examples, Strategy protocol, and Railway topology.

**Six logical layers, three Railway services at v1 (four when going live):**

1. **Ingest (Layer 1)** — One client per data source (`MexcIngest` via ccxt, `CoinglassIngest` + `CoinGeckoIngest` via httpx). Pydantic schema validation, tenacity retries, aiolimiter rate limits, asyncpg COPY into raw hypertables. Idempotent on `(symbol, ts, source)`.
2. **Storage (Layer 2 — TimescaleDB)** — **Typed-per-source hypertables**, NOT universal `(symbol, ts, metric, value)` EAV (5–10x storage tax). One hypertable per `(source, dataset)`. Compression policies after 7 days. Continuous aggregates for 5m/15m/1h/4h rollups. Curated views + feature-snapshot tables on top.
3. **Feature Compute (Layer 3)** — Strategy-agnostic primitive library (`rsi`, `divergence`, `funding_zscore`, `oi_roc`, `liq_cascade`, `vwap`, `btc_corr`) — pure functions, no I/O. Per-strategy feature pipelines compose primitives and write to `features_<strategy>_v<spec_hash>` tables. **Spec hash invalidates stale features automatically.**
4. **Strategy (Layer 4)** — `Strategy` Protocol (`features_required`, `generate_signals`, `position_sizing_hint`) + `StrategyRegistry`. **Strategy params live in DB (`strategy_instances` table), not YAML/code.** Promotion paper → live = row update, not deploy. Backtester is strategy-agnostic and takes a Strategy instance.
5. **Execution + Risk (Layer 5)** — `OrderRouter` interface with `PaperOrderRouter` + `MexcOrderRouter` implementations (same code path). `RiskGuard` sits between Strategy and OrderRouter; in-process during paper, becomes a separate Railway service at live launch (must remain available even if strategy-engine crashes). `PositionTracker` reconciles with exchange every 60s.
6. **Observability + Control (Layer 6)** — FastAPI dashboard (read-only), Prometheus `/metrics`, Telegram bot for alerts + kill switch.

**Railway topology:**

- `data-platform` service — APScheduler + ingest workers + feature compute.
- `strategy-engine` service — signal generation + paper/live OrderRouter + PositionTracker + in-process RiskGuard (until live).
- `dashboard` service — FastAPI read-only API.
- **Postgres+TimescaleDB managed service** — the single source of truth and message bus (LISTEN/NOTIFY + polling; no Kafka, no Redis Streams).
- `risk-guard` service — added only at live launch; exposes `/check`, `/halt`, `/resume`; reachable on private network.

**Key architectural decisions:**

- **One Postgres for everything** (timeseries + relational + MLflow + Optuna + APScheduler jobstore). The DB is the message bus at solo scale.
- **No feature-store service** (Feast/Tecton overkill). `features_<strategy>_v<hash>` Postgres tables versioned by spec hash.
- **Backtest === paper === live** through same `Strategy.generate_signals` and `OrderRouter` interface. Different code paths between backtest and live are the #1 source of "edge that disappears in production."
- **Risk logic OUTSIDE strategy logic.** Strategy emits `SignalIntent` regardless of position state; RiskGuard decides what to do.
- **`tests/fakes/` is first-class.** Every external boundary has a fake (`FakeMexcClient`, `InMemoryCandleRepo`, `FakeOrderRouter`, `FakeRiskGuard`) for deterministic property tests.

### Critical Pitfalls

See PITFALLS.md for all 30 pitfalls, the technical-debt patterns table, integration gotchas, "looks done but isn't" checklist, and recovery strategies. The top capital-or-research-destroying pitfalls and where they get addressed:

1. **Survivorship-biased training universe (Pitfall 1, RESEARCH-INVALID, +17–400% backtest inflation).** Most memecoin perps that pumped 200% and never recovered (perfect short setups) have been delisted on MEXC. ccxt only returns live markets. **Cannot be retrofitted.** Prevention: daily `universe_snapshots` hypertable from Phase 1 commit 1; cross-reference Coinglass delisted lists; universe at historical timestamp T = "listed AT T," not "listed today."

2. **Look-ahead bias in feature engineering (Pitfall 2, RESEARCH-INVALID).** `df.rolling(window).mean()` without `closed='left'`, global z-score before train/test split, `bfill`/`interpolate` looking forward, funding rate publish vs settlement timestamp confusion. Prevention: **causal rolling invariant** project-wide; **Hypothesis property test for every feature**: "if I duplicate row T and shift by N seconds, feature value at original T must not change"; funding schema stores both `settlement_ts` and `published_ts`; ban `bfill` outright.

3. **Walk-forward done wrong (Pitfall 3, RESEARCH-INVALID).** `sklearn.model_selection.TimeSeriesSplit` does NOT purge or embargo. Optuna's TPE will hunt and exploit the leak. Prevention: **custom `PurgedWalkForward`** with explicit `label_horizon` and `embargo_pct` parameters; embargo ≥ label horizon; Hypothesis test: "no training index within `label_horizon + embargo` of any test index"; Optuna uses the purged splitter, not a bypass.

4. **Unrealistic slippage on illiquid MEXC memecoin perps (Pitfall 4, CAPITAL, can flip +1.5%/trade to −0.5%).** Flat-% slippage on $500K-volume coins is fantasy. **L2 snapshots cannot be retrofitted** — must collect from Phase 1. Prevention: top-20 L2 sampled every 5–10s during ingest; backtester walks the book for VWAP fills; stops fill via book-walk from trigger price, not AT trigger price; per-symbol liquidity tiers; paper-vs-live slippage parity test before live.

5. **Missing `reduceOnly` flag on exits (Pitfall 6, CAPITAL, has wiped accounts in single incidents).** Close order without `reduceOnly=True` becomes a NEW long, doubling exposure during a pump exactly when you needed to flatten. Prevention: **mandatory `place_order(intent='open'|'close')` wrapper** that mechanically sets `reduceOnly=True` on close — raw ccxt order calls inaccessible outside the wrapper; Hypothesis invariant: "every order with intent='close' has params.reduceOnly == True"; assert MEXC position mode at startup; pre/post-trade balance assertions.

6. **No kill switch / no daily-loss circuit breaker (Pitfall 19, CAPITAL).** Bot misbehaves overnight, account drains. Prevention: **Telegram `/halt` + dead-man switch service on different Railway service + daily PnL breaker + per-trade-burst breaker + order-rate breaker**; tested monthly; kill switch skeleton exists from Phase 4 (paper), not Phase 5.

7. **API key leakage (Pitfall 8, CAPITAL, total).** Trading key in git, in logs, in ccxt verbose URLs. Prevention: **two MEXC keys** (`READ_KEY` read-only for ingest, `TRADE_KEY` trade-only no-withdraw for execution); withdraw permission disabled on both; Railway Variables only; `.gitignore` `.env*`; pre-commit secret scanner; structlog redaction; ccxt verbose off in prod; IP allowlist if Railway egress IP is stable; **emergency panic-button key** rotated manually.

8. **Imbalanced classes — short-after-pump positives are rare, false positives dominate (Pitfall 9, RESEARCH-INVALID + CAPITAL).** Default XGBoost learns "predict 0 always" → 95–99% accuracy → zero useful signals. Naive `class_weight='balanced'` over-aggressively flips to many false positives. Prevention: **metric = precision @ top-N signals per day per symbol**, not AUC/accuracy; threshold tuning on a separate holdout; cost-sensitive loss (each FP costs ~0.2%); calibration check; rule-based sanity baseline.

9. **Regime change blindness (Pitfall 10, RESEARCH-INVALID + CAPITAL).** Train on declining/ranging crypto, deploy in bull market → short-after-pump repeatedly stopped out. Prevention: walk-forward must span at least one regime change; explicit regime features (BTC 30d realized vol, BTC drawdown, market-wide funding average); regime-stratified evaluation; monthly retrain cadence.

10. **Paper-trading fills better than live would (Pitfall 28, RESEARCH-INVALID).** Paper "passes" gate, live underperforms because paper used candle-close fills, assumed maker, zero latency. Prevention: **paper uses SAME book-walk slippage model as backtester**; inject 200–500ms artificial latency; identical maker/taker classification rule; paper-vs-backtest PnL reconciliation within 10%.

## Implications for Roadmap

Both ARCHITECTURE.md (Phase 0–5+) and FEATURES.md (4 phases) converge on the same canonical ordering. PROJECT.md's hard gates (≥1–2 months paper trading before live; kill switch before paper; schema invariants before training) further constrain it. The recommended canonical phase plan:

### Phase 0: Foundation
**Rationale:** TDD-first culture and CI/CD pipeline must exist before any production code. Project bootstrap is small, low-risk, and unblocks everything.
**Delivers:** Repo + uv + ruff + pyright + pytest + Hypothesis scaffold; Railway project + Postgres+TimescaleDB service; Alembic + hypertable DDL tooling; GitHub Actions CI → Railway auto-deploy; pure domain types (`Candle`, `OrderBook`, `Funding`, `Signal`, `Order`, `Position`, `RiskLimits`) with property tests on invariants; observability skeleton (structlog, prometheus_client, `/metrics` endpoint); `.gitignore` `.env*` + pre-commit secret scanning; GitHub secret scanning enabled.
**Uses:** Stack: Python 3.12, uv, FastAPI scaffold, pydantic-settings, TimescaleDB 2.18 PG16.
**Avoids:** Pitfall 8 (API key leakage scaffolding), Pitfall 20 (premature optimization — no Grafana yet), Pitfall 25 (schema migration discipline established up front).

### Phase 1: Data Platform (strategy-agnostic foundation)
**Rationale:** Strategy work is impossible without a clean, leak-aware, source-attributed historical dataset. The schema decisions here cannot be retrofitted — survivorship snapshots, L2 capture, source attribution, TIMESTAMPTZ enforcement.
**Delivers:** `IngestClient` Protocol + fakes; Pydantic schemas for all 3 sources; MEXC/Coinglass/CoinGecko ingest with retries + rate limits; asyncpg COPY-based bulk inserts into typed hypertables (OHLCV 1m–1d, funding, OI, signed trades, L2 top-20 @ 5–10s, liquidations); **daily `universe_snapshots`**; **`source` column on every derivatives row**; symbol lifecycle handling (soft delete, no cascade); idempotent backfill 1–2 years (within Coinglass tier limits — accept 12 days of 1m derivatives at Startup tier); continuous aggregates for 5m/15m/1h/4h; data freshness monitoring + Telegram alerts on stale data; gap detection assertions; daily `pg_dump` to external storage (R2/B2); APScheduler bootstrapped in `data-platform` service.
**Addresses:** All "Data Platform" table stakes from FEATURES.md.
**Avoids:** Pitfall 1 (survivorship — **commit-1 universe snapshots**), Pitfall 4 (slippage — **L2 capture is mandatory now**), Pitfall 11 (stale websocket — freshness gauges), Pitfall 16 (Coinglass aggregate confusion — source attribution at schema level), Pitfall 17 (timezone bugs — TIMESTAMPTZ everywhere + startup time-sync), Pitfall 21 (backfill gaps — `quality_flag` not interpolation), Pitfall 26 (backup missing — daily off-Railway pg_dump), Pitfall 27 (silent task failures — TaskGroup + heartbeats).

### Phase 2: Strategy Research + Feature Engineering + ML Methodology
**Rationale:** Before training any model, the leakage-prevention infrastructure (purging, embargo, funding-window-aware labeling, Hypothesis property tests) must exist. The labeling method itself is explicitly deferred per PROJECT.md until EDA reveals what the data supports — but the methodology framework is non-deferrable.
**Delivers:** FeatureProvider primitives library (rsi, divergence, funding_zscore, oi_roc, liq_cascade, vwap, btc_corr, volume_profile/POC, BTC-dominance regime) — each with Hypothesis property tests for causality; Jupyter notebooks for EDA (pump distributions, feature diagnostics) — read-only research, production never imports; **algorithmic pump detector** + versioned `pump_events` table (pump archaeology); **triple-barrier labeling** with parameterized TP/SL/timeout; **`PurgedWalkForward` splitter** with embargo; **funding-window-aware label boundary tests** (Hypothesis); class-imbalance handling via cost-sensitive loss / scale_pos_weight; metric = precision @ top-N (NOT AUC/accuracy); calibration check (isotonic regression); short-after-pump feature pipeline with spec-hash versioning; XGBoost + LightGBM baseline with Optuna (≤200 trials, MedianPruner); MLflow tracking with code-commit + data-snapshot tags; SHAP per-trade explainability stored in DB; rule-based sanity baseline; 3-set protocol (train → validation → never-touched holdout).
**Addresses:** All "Strategy #1 Research Loop" table stakes from FEATURES.md.
**Avoids:** Pitfall 2 (look-ahead — causal rolling invariant + Hypothesis tests), Pitfall 3 (walk-forward done wrong — custom PurgedWalkForward), Pitfall 9 (imbalanced classes — precision@N metric), Pitfall 10 (regime blindness — regime features + walk-forward spans regime changes), Pitfall 18 (hyperparameter overfitting — 3-set protocol + trial cap + stability test).
**Decides (deferred from PROJECT.md):** labeling method (triple-barrier vs alternatives), pump detector thresholds, whether Coinglass Standard tier ($299/mo) is needed for >12-day 1m derivatives backfill.

### Phase 3: Backtester + Strategy Framework
**Rationale:** A correct backtester is the gate to paper trading. Once Phase 2 features and a trained model exist, the strategy-agnostic event-driven backtester reveals whether the edge survives realistic fees/slippage/funding.
**Delivers:** Strategy Protocol + StrategyRegistry; `strategy_instances` + `signals` + `trades_paper` schema; generic event-driven backtester (FeeModel with effective dates, depth-aware SlippageModel via book-walk, partial fills, funding payment accounting, latency separation); **ShortAfterPumpStrategy** implementation; ML training pipeline (`walk_forward_splits`, `train`, `eval`, MLflow logging) — these are *shared* utilities called by the strategy; SHAP + feature importance reports; backtest reproducibility (data_snapshot_id + code commit hash); parameter robustness sensitivity sweep; `quantstats` tearsheets; equity curve bootstrapped confidence intervals; **strategy params in DB, not YAML** (versioned strategy configs FK from every signal/trade).
**Addresses:** All "Backtesting & Simulation" table stakes from FEATURES.md.
**Avoids:** Pitfall 4 (slippage — book-walk in backtester), Pitfall 5 (fee model wrong — single source of truth, effective dates), Pitfall 7 (liquidation self-impact — position-size caps as % of book depth), Pitfall 13 (stops mis-modeled — ATR-based + book-walk fills from trigger), Pitfall 14 (Kelly over-leveraged — OOS edge with CI shrinkage, hard caps independent of Kelly), Pitfall 15 (funding surprise — mark-to-market every funding window), Pitfall 22 (book/trade mismatch — snapshot age reporting).

### Phase 4: Paper Trading (PROJECT.md HARD GATE before live)
**Rationale:** PROJECT.md mandates ≥1–2 months of positive paper trading on live feeds with low backtest-vs-paper divergence before any real capital. Paper trading uses the SAME execution code path as live — the `OrderRouter` interface with `PaperOrderRouter` implementation. Kill switch infrastructure exists here, not at live launch.
**Delivers:** `PaperOrderRouter` + `InProcessRiskGuard` + `PositionTracker`; `place_order(intent='open'|'close')` wrapper (mandatory, raw ccxt inaccessible outside) with Hypothesis invariant on `reduceOnly`; full risk module (quarter-Kelly with caps, ATR stops, daily/DD circuit breakers, max concurrent, per-symbol exposure, position reconciliation loop); **kill switch (Telegram `/halt` + HTTP endpoint + automatic on breach)** tested before first paper trade; `strategy-engine` service deploys to Railway; `dashboard` service (read-only FastAPI); Telegram bot (signal alerts with SHAP top-N rendered, daily equity summary, severity-tagged channels); per-trade audit log; **artificial latency injection** (200–500ms) in paper; **paper-vs-backtest reconciliation report** with divergence < 10% gate; pre-registered model version (no mid-paper switching); 1–2 months paper trading minimum.
**Addresses:** All "Paper Trading" + "Risk Management" + "Execution (paper mode)" + "Observability" table stakes.
**Avoids:** Pitfall 6 (reduceOnly — wrapper + Hypothesis invariant + paper simulates the bug), Pitfall 19 (kill switch — exists from Phase 4), Pitfall 28 (paper better than live — same slippage model + latency injection), Pitfall 29 (paper survivorship — pre-registered model + documented gate).

### Phase 5: Live Trading — Signal-Only → Semi-Auto → Full-Auto
**Rationale:** PROJECT.md gates live on paper success. Live escalation is staged: signal-only (operator executes manually) → semi-auto (Telegram inline keyboard confirm) → full-auto (only after sustained positive semi-auto). RiskGuard becomes a separate Railway service so a strategy-engine crash cannot disable risk enforcement.
**Delivers:** `RemoteRiskGuard` + `risk-guard` Railway service; `MexcOrderRouter` (live) with reconciler; **two MEXC API keys** (read-only ingest + trade-no-withdraw execution); emergency panic-button key (third key, manually rotated); IP allowlist if Railway egress is stable; capital-tier-aware position sizing (adapt to current balance, $500 → $50K+); slippage model calibration from paper fills → backtester update; scheduled weekly walk-forward re-run with drift alerts; model staleness monitoring (KS-statistic on feature distributions); live-vs-backtest edge tracker (auto-pause if realized < 0.5x backtested over 30 trades); monthly model retrain cadence with champion/challenger gate; staged autonomy via `strategy_instances.autonomy` row update (no deploy); Grafana dashboards live now (not earlier); fee reconciliation cron (weekly, divergence > 5% alert); pre-trade margin reservation; per-endpoint rate-limit priority queue.
**Addresses:** All "Live Trading" requirements from PROJECT.md.
**Avoids:** Pitfall 8 (API key leakage — two-key + no-withdraw + allowlist), Pitfall 10 (regime blindness — retrain cadence), Pitfall 12 (rate limit mid-pump — priority queue), Pitfall 14 (Kelly — live edge tracker circuit breaker), Pitfall 19 (kill switch hardened — separate process), Pitfall 23 (insufficient margin — pre-trade reservation), Pitfall 24 (model staleness — monthly retrain), Pitfall 30 (dashboard before edge — Grafana enters NOW, not earlier).

### Phase 6+: Additional Strategies / Optimization
**Rationale:** **No Phase 6+ work until Phase 4 paper EV-positive and Phase 5 live-signal-only shows realized edge within 0.5x of backtest.** Strategy #2 plugs into the Phase 3 framework with the 4-step recipe (new folder, tests, DB row, promote).
**Delivers:** Meta-labeling layer; second strategy on shared data layer; CatBoost / PyTorch sequence models as ensemble members; Coinglass Standard tier upgrade (if Phase-2 EDA demanded it); backtest L2 reconstruction replay; Prefect 3 migration (only if DAG dependencies emerged); ClickHouse migration (only if TimescaleDB exhausted).

### Phase Ordering Rationale

- **Schema-set-in-stone-from-day-1 forces Phase 1 = Data Platform.** Survivorship snapshots, L2 capture, `source` attribution, TIMESTAMPTZ — none of these can be retrofitted without re-doing months of work.
- **ML methodology infrastructure (purged walk-forward, leakage Hypothesis tests, precision@N metric) must exist BEFORE the first model trains.** Without it, you train on leaky labels, trust inflated metrics, and the strategy fails in paper 6 weeks later. This forces Phase 2 to ship the methodology before any modeling.
- **Backtester gates paper, paper gates live, by PROJECT.md decree.** The 1–2 month paper minimum cannot be compressed.
- **Kill switch exists from Phase 4, not Phase 5.** First time you need a kill switch in live is too late. Paper trading is the kill-switch infrastructure test.
- **SHAP per-signal explainability is a prerequisite for autonomy escalation**, not a "nice to have." Without it, the operator cannot build the trust to escalate from signal-only to semi-auto.
- **Position reconciliation must exist before live**, but paper doesn't have exchange state to reconcile — so the LOOP exists in Phase 4 against a fake exchange state, and is exercised live in Phase 5.
- **Strategy interface designed in Phase 3 with one strategy implementing it**, not "we'll add multi-strategy later." The interface ships in v1 even though only one strategy uses it.
- **Grafana dashboards enter at Phase 5, not earlier.** Phases 1–4 use Telegram + structured logs + Polars/Jupyter. Building dashboards before edge is proven is Pitfall 20/30 incarnate.
- **No Phase 6+ infra work (ClickHouse, Prefect, second strategy) until live signal-only shows realized edge within 0.5x of backtest.** Discipline written into milestone exit criteria.

### Hard Gates (PROJECT.md + research-derived, non-negotiable)

| Gate | Where Enforced | Why |
|------|----------------|-----|
| ≥1–2 months paper trading with positive EV before live | Phase 4 → Phase 5 transition | PROJECT.md hard constraint |
| Kill switch infrastructure exists and tested before first paper trade | Phase 4 commit-zero | Pitfall 19; can't introduce kill switch in live for the first time |
| Schema invariants (`universe_snapshots`, `source` column, TIMESTAMPTZ, L2 capture) before first training | Phase 1 → Phase 2 transition | Pitfalls 1, 4, 16, 17; cannot be retrofitted |
| Hypothesis property tests for leakage before first model trains | Phase 2 commit-zero | Pitfall 2; leakage discovered later invalidates everything |
| Paper-vs-backtest PnL reconciliation < 10% before live | Phase 4 → Phase 5 transition | Pitfall 28; closes the "paper passes, live fails" gap |
| `place_order(intent=)` wrapper with Hypothesis `reduceOnly` invariant before first live trade | Phase 4 wrapper, Phase 5 gate | Pitfall 6; single most expensive solo-dev mistake |
| Two MEXC API keys (read-only + trade-no-withdraw) before live key created | Phase 5 commit-zero | Pitfall 8 |
| Live edge tracker (realized vs backtest) before full-auto | Phase 5 (signal-only → semi-auto → full-auto progression) | Pitfall 14; staged autonomy is the trust gate |
| No Phase 6+ work until live signal-only EV-positive | Roadmap discipline (milestone exit) | Pitfall 20 |

### Research Flags

**Phases likely needing deeper research during planning (`/gsd:plan-phase --research-phase N` recommended):**

- **Phase 2 (Strategy Research + ML Methodology):** Labeling method is explicitly deferred per PROJECT.md — Phase 2 EDA will inform triple-barrier vs alternatives. Pump detector threshold tuning is iterative. Walk-forward window choice (90/14 day vs others) depends on backfill depth available. **PurgedWalkForward implementation** can pull from public references but needs care.
- **Phase 4 (Paper Trading methodology):** Latency injection calibration (200–500ms is a range, not a point) and the paper-vs-backtest divergence threshold need empirical anchoring against early paper data.
- **Phase 5 (Live execution):** MEXC API quirks under live conditions (hedge mode vs one-way mode, `reduceOnly` behavior in May 2026 ccxt minor, recv_window tuning, IP allowlist Railway egress stability) need verification with paper-then-live smoke tests. Capital-tier-aware position sizing piecewise function design needs research.

**Phases with well-documented patterns (skip deep research):**

- **Phase 0 (Foundation):** uv + ruff + pyright + pytest + Railway + Alembic are standard; nothing to research.
- **Phase 1 (Data Platform):** TimescaleDB + ccxt + httpx + APScheduler patterns are well-trodden in ARCHITECTURE.md; just execute.
- **Phase 3 (Backtester + Strategy Framework):** Strategy Protocol, event-driven backtester structure, MLflow integration patterns are clear in ARCHITECTURE.md; just implement.

### Open Questions Deferred (decided in later phases)

- **Labeling method** (Phase 2 decision after EDA) — triple-barrier is the leading candidate but PROJECT.md explicitly keeps it open.
- **Coinglass tier upgrade to Standard ($299/mo)** (Phase 2 decision) — only if 1m derivatives features need >12 days of history. Stay on Startup ($79/mo) unless EDA proves the need.
- **Slippage model calibration breakpoints** (Phase 4 decision after paper data) — bootstrap from conservative assumptions, measure paper fills, recalibrate.
- **Capital-tier-aware position sizing piecewise function** (Phase 5 decision) — concrete breakpoints depend on observed minimum notionals on MEXC at different capital levels.
- **NautilusTrader migration** (Phase 6+ decision) — only if/when Nautilus stabilizes (still 1.x with breaking changes per STACK.md) AND custom backtester maintenance burden justifies the swap.
- **ClickHouse / Prefect migrations** (Phase 6+ decisions, conditional on scaling) — defer until measured.

### Cross-Research Tensions and Resolutions

- **Architecture suggests Phase 0–5+ ordering; Features suggests 4 phases (v1 / v1.x / v2+).** Resolution: the canonical phase plan above uses Architecture's 0–5+ structure as the build sequence while folding Features' v1 / v1.x / v2+ classification into per-phase deliverables (P1=Phase 1–4, P2=Phase 5, P3=Phase 6+).
- **Architecture says "Risk Guard as Process Boundary" only when going live**; **Features says "kill switch is table stakes for v1 paper trading."** Resolution: kill switch CODE skeleton and Telegram integration exist from Phase 4 (paper) as `InProcessRiskGuard`; the SEPARATE PROCESS deployment (`risk-guard` Railway service) arrives at Phase 5 (live).
- **Stack says NautilusTrader is "Phase 3+ evaluation" but custom backtester is the v1 default.** Resolution: build custom event-driven backtester in Phase 3; revisit Nautilus only in Phase 6+ once strategy is proven AND Nautilus stabilizes.
- **Stack defaults to APScheduler in-process; Architecture says "no Kafka, no message bus."** Both agree, no tension. Migration to Prefect 3 is a Phase 3+ conditional.
- **Features lists "multi-strategy framework" as P1 (designed) / P2 (proven).** Architecture confirms: ship the Strategy Protocol in v1 even with one strategy implementing it; additional strategies are Phase 6+.
- **PROJECT.md says "Sentiment via on-chain/volume proxies is acceptable, NLP/Twitter is not."** Features and Pitfalls both reinforce: derivatives data is the higher-SNR alternative. No tension; bake into REQUIREMENTS.md "Out of Scope."

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions verified against PyPI / vendor pricing pages May 2026; core stack (FastAPI/Postgres/TimescaleDB/ccxt/XGBoost/Optuna/MLflow) is uncontroversial; only ambiguity is Coinglass tier (price-tier-known, depth-of-need-unknown until Phase 2). |
| Features | HIGH | Cross-validated against Lopez de Prado canon, MEXC vendor docs, and current crypto-bot best practices. Table-stakes feature list is comprehensive. Differentiator ranking is opinionated (always context-dependent) but the entries themselves are validated. |
| Architecture | HIGH | Layered + plugin-strategy registry pattern matches freqtrade/jesse/Hummingbot consensus. TimescaleDB schema choice (typed-per-source over EAV) supported by vendor docs and benchmarks. Railway 3-service split is the minimum that enforces blast-radius without billing waste. KNOWN-TENSION on feature store pattern (lightweight `features_<strategy>_v<hash>` tables in same Postgres is the right call at solo scale). |
| Pitfalls | HIGH | ML/research pitfalls grounded in Lopez de Prado + cross-verified crypto sources; MEXC quirks from vendor docs + ccxt issue tracker; execution/risk pitfalls well-documented in crypto futures forums; MEDIUM on Railway-specific ops edge cases (less written about, but standard Postgres ops knowledge applies). |

**Overall confidence:** HIGH for the synthesis. The dominant risks are not "did we pick the right tool" (we did) but "will we execute the discipline" — TDD, leakage prevention, kill switch first, no premature optimization, schema-in-stone-from-day-1.

### Gaps to Address

- **Pitfall 6 (`reduceOnly` mechanics in MEXC May-2026 API)** — needs field verification in paper trading before live. Plan: write a test in Phase 4 that intentionally omits `reduceOnly` on a paper close, verify the paper layer faithfully simulates the bug, then verify the wrapper prevents it.
- **Labeling method choice** — explicitly deferred to Phase 2 per PROJECT.md. Triple-barrier is the leading candidate but the framework is methodology-first, method-second; this is a feature, not a gap.
- **Coinglass Standard tier necessity** — depends on Phase 2 EDA finding that 1m derivatives features add edge beyond what 12 days of Startup data + 5m/1h derivatives history can capture. Plan: defer the $299/mo spend until EDA produces a quantified ablation.
- **Slippage model calibration breakpoints (per-tier liquidity classes)** — bootstrap from conservative assumptions in Phase 3 backtester, refine from paper-trading fills in Phase 4, paint-by-numbers calibration cron in Phase 5.
- **Railway egress IP stability** — needed to enable MEXC IP allowlist on trade key. Plan: verify with `curl ifconfig.me` from deployed service during Phase 5 setup; if unstable, accept reduced security and rely on key rotation + alerts.
- **Capital-tier-aware position sizing piecewise function** — concrete breakpoints depend on observed MEXC minimum notionals at different account sizes. Plan: design abstract in Phase 3 (`position_sizing_v2(equity, kelly_estimate, min_notional, max_concurrent) -> size`), implement concretely in Phase 5 once live account is funded.
- **Custom `PurgedWalkForward` implementation** — mlfinlab is license-restricted; reimplement the ~30-line core in-house with Hypothesis property test on the "no training index within label_horizon + embargo of any test index" invariant.

## Sources

### Primary (HIGH confidence)

- PROJECT.md — project brief, gates, autonomy escalation, deferred decisions
- STACK.md — verified May 2026 against PyPI (ccxt 4.5.54, NautilusTrader 1.227, Polars 1.40.1, XGBoost 3.2.0, LightGBM 4.6.x), Coinglass pricing, Railway TimescaleDB templates
- FEATURES.md — Lopez de Prado "Advances in Financial Machine Learning" canon; MEXC vendor docs (futures endpoints, fees announcements, liquidation mechanics); crypto pump-and-dump academic literature
- ARCHITECTURE.md — Tiger Data narrow-vs-wide time-series guidance, TimescaleDB issue #1616 maintainer guidance, Railway monorepo + FastAPI deployment docs, freqtrade/jesse multi-strategy architecture references
- PITFALLS.md — Lopez de Prado purging/embargo, ccxt MEXC issues #27253 (`watch_ohlcv` hang) and #28532 (swap order endpoint, May 2026), MEXC API fee/endpoint updates (Mar/May 2026), StratBase survivorship-bias-in-crypto study (58%+ delisted, 200–400% backtest inflation on memecoin baskets)

### Secondary (MEDIUM confidence)

- TimescaleDB vs ClickHouse benchmarks (sanj.dev 2026, tigerdata.com)
- Polars vs pandas benchmarks (2026)
- Optuna vs Hyperopt comparison
- MLflow vs W&B comparison
- Crypto bot risk management / kill switch patterns (2026 community guidance)
- Backtesting realism literature

### Tertiary (LOW confidence — flagged for field verification)

- Railway-specific operational edge cases (backup procedures, egress IP stability) — verify empirically during Phase 1/5 setup
- Solo-developer pattern observations (Pitfalls 20, 30) — treat as discipline reminders
- Exact MEXC `reduceOnly` behavior in May-2026 API across hedge mode vs one-way mode — verify with paper-trading test before any live key creation

---
*Research completed: 2026-05-21*
*Ready for roadmap: yes*
