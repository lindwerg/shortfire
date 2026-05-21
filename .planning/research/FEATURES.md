# Feature Research

**Domain:** Crypto futures ML trading system — MEXC USDT-perp short-after-pump strategy with strategy-agnostic data platform underneath (solo operator, Railway-deployed, hybrid autonomy escalation signal-only → semi-auto → full-auto)
**Researched:** 2026-05-21
**Confidence:** HIGH on table stakes and anti-features (cross-validated against current crypto-bot best practices, Lopez de Prado labeling literature, and MEXC-specific microstructure docs); MEDIUM on relative ranking of differentiators (always context-dependent)

## Executive Summary

A competent crypto-futures ML system is **four products glued together**:

1. **A time-series data warehouse** with idempotent ingest, schema versioning, and symbol-source attribution (MEXC-native vs Coinglass-aggregated funding are not interchangeable — tag at the row level).
2. **An offline research environment** (Jupyter + MLflow + walk-forward backtester) where features, labels, and models are discovered without leakage.
3. **A live signal/execution loop** with realistic slippage modeling, hard risk limits, and a kill switch that can be triggered from outside the bot process (Telegram, manual HTTP call, automatic on PnL breach).
4. **An observability and trust-building layer** so the operator can answer "why did this signal fire?" and "is my model still calibrated to current market conditions?" — without which hybrid-autonomy escalation is impossible.

**Table stakes that the project's current PROJECT.md already covers correctly:** MEXC OHLCV + funding + OI + liquidation ingest, walk-forward CV, paper trading before live, quarter-Kelly position sizing, hard stop-loss, kill switch, Telegram alerts.

**Table stakes that are NOT explicitly called out in PROJECT.md and SHOULD be in the roadmap:**
- **Funding-window-aware labeling and feature lookahead** (leakage vector specific to perps).
- **Symbol-source attribution at the schema level** (`source` column on funding/OI tables — MEXC vs Coinglass aggregate are different signals).
- **Universe drift handling** (delisted memecoin perps must not break backfill or foreign keys).
- **Order book L2 sampling strategy** (depth-N + sample-rate, not full snapshots).
- **Reconciliation between exchange state and local state** (positions, balances, open orders) — the silent killer of crypto bots.
- **Model staleness detection and retraining cadence** (drift in feature distributions, not just performance decay).

**Highest-leverage differentiators specific to this thesis:**
- **MEXC-listing-specific universe** (most short-after-pump signals live in low-cap memecoin perps that don't exist on Binance) — already a key project decision; treat the universe filter as a feature, not plumbing.
- **Multi-source derivatives stitching** — MEXC funding for "where my fills will land" + Coinglass aggregate funding for "what's the crowd doing" + liquidation cascade depth from Coinglass.
- **Pump archaeology** (algorithmic labeling of historical 50–200% pumps with reproducible parameters, versioned in the database so labels can be regenerated without retraining everything).
- **SHAP-per-trade explainability** — non-negotiable for trusting a black-box model enough to escalate autonomy.

**Anti-features to deliberately NOT build** (and these are common mistakes in solo crypto-bot projects):
- Sentiment via Twitter/NLP (PROJECT.md already excludes — keep it excluded).
- Multi-exchange execution in v1 (would dilute the MEXC-listing edge).
- Long setups (different statistical regime; separate strategy).
- A custom GUI dashboard from scratch (Grafana + Telegram covers it).
- A real-time tick-by-tick architecture for 1m+ signals (introduces latency-sensitive bugs without edge gain).

The rest of this document categorizes every feature into table stakes / differentiators / anti-features with complexity sizing (S/M/L) and dependencies so the roadmap phase ordering follows from the dependency graph.

## Feature Landscape

### Table Stakes (System is Non-Viable Without These)

Group A — **Data Ingest & Storage**

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| MEXC OHLCV ingest (1m/5m/15m/1h/4h/1d) for full USDT-perp universe | Foundation of every feature; price-action signals are the floor | M | Use ccxt `watch_trades()` + client-side `build_ohlcvc()` rather than `watch_ohlcv()` directly (MEXC ccxt#27253 hang). Backfill via REST in 500-bar chunks with rate limiting. |
| MEXC funding rate history per symbol | Without funding history, you cannot label or backtest funding-spike features | S | MEXC settles 8h; some pairs differ — store `funding_interval_seconds` per symbol, do NOT assume global constant. |
| MEXC open interest history per symbol | OI rate of change is a core pump-exhaustion feature | S | Sample at 1m for active universe, 5m for tail. Compress aggressively in TimescaleDB. |
| MEXC recent trades stream (signed for CVD) | Cumulative Volume Delta requires per-trade buy/sell attribution; OHLCV alone is insufficient | M | ccxt Pro `watch_trades` + Postgres COPY-based bulk insert via asyncpg. ~10-100 trades/sec/symbol at universe scale — partition aggressively. |
| MEXC order book snapshots (top-N depth) | Liquidity model for slippage calculation in backtest and live | M | **Don't snapshot full L2 at universe scale** — pick top 20 levels, sample every 5–10s for active subset, every 1m for full universe. ~10-50 MB/min full-L2 is untenable on Railway. |
| Coinglass aggregated funding & OI | Cross-exchange crowd positioning; MEXC-only funding misses the broader signal | M | Tag rows with `source='coinglass_aggregate'`. Schema must distinguish from MEXC-native rows. |
| Coinglass liquidation events | Cascade detection — core post-pump feature | M | Coinglass Startup tier ($79/mo) is the floor for usable 1m granularity. |
| CoinGecko market metadata (cap, category, supply, age) | Universe filtering and feature engineering (a 2-week-old memecoin behaves differently from a 3-year-old altcoin) | S | Daily refresh sufficient. Cache aggressively — free tier is 30 req/min. |
| Time-series storage (TimescaleDB hypertables) | Without column-store-grade compression you'll run out of disk in months | M | Hypercore (Timescale 2.18+) row+columnar hybrid. Compression policies, continuous aggregates for hot dashboards. |
| Idempotent ingest with retries and dead-letter handling | Network blips, exchange outages, schema drift will happen daily | M | `tenacity` for retries, `aiolimiter` for rate limits, dead-letter table in Postgres. Replay-on-restart from last persisted timestamp per symbol. |
| Schema validation at every API boundary | Silent schema drift on a single field destroys days of training data | S | Pydantic v2 models for every MEXC/Coinglass/CoinGecko response. Fail-fast on schema mismatch with structured log. |
| Dynamic universe filter ($500K+ 24h volume, daily refresh) | Bounds the problem; without it you'll burn rate limits on dead pairs | S | PROJECT.md decision. Implement as a versioned table (`universe_snapshots`) so backtests can reproduce historical universe membership. |
| Symbol lifecycle handling (delistings, renames) | Memecoin perps come and go in weeks on MEXC — schema must not break | M | No `ON DELETE CASCADE`; soft-delete with `delisted_at` timestamp; backfill must tolerate now-missing symbols. |
| Database migrations (Alembic, TimescaleDB-aware) | Schema will evolve over months; manual migration loses data | S | `op.execute()` for hypertable creates and compression policies. Test migrations on a copy before applying to prod. |

Group B — **Signal Generation (Pump Detection & Short Setup Identification)**

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Algorithmic pump detector (historical) | Cannot label training data without it; cannot evaluate signals without ground truth | M | Threshold-based + EWMA volatility-normalized: e.g., "+30% in <4h with volume >5x 30d-EWMA volume." Parameters must be in a config table, not hardcoded — you'll iterate. |
| Multi-timeframe RSI (1m, 5m, 15m, 1h, 4h) | Overheat detection requires multi-TF agreement; single-TF RSI is noise | S | `pandas-ta` for v1; revisit TA-Lib only if profiling shows indicator compute is bottleneck. |
| RSI divergence detection (bearish, price/RSI) | Classic exhaustion signal; not optional for short-after-pump | M | Pivot detection on RSI + price, vectorized. Test with synthetic candles to verify pivot logic. |
| Volume profile / Fixed Range Volume Profile / POC | Identifies thin price zones where reversal is statistically likely | M | Bin volume by price level over a rolling window; compute Point of Control (highest volume bin) and Value Area. |
| Funding rate spike detection (z-score vs rolling baseline) | Crowded-long signal; funding extremes precede mean reversion | S | Per-symbol z-score over rolling 7-30d window. |
| OI rate-of-change (1h, 4h, 24h) | Rising OI during pump = leveraged participation; falling OI = real distribution | S | Per-symbol delta normalized by rolling OI baseline. |
| Liquidation cascade magnitude | Forced-buyer exhaustion is a short setup; track $-magnitude and count | M | Sum liquidation $-notional over rolling windows; flag percentile breaches. |
| Cumulative Volume Delta (CVD) and CVD divergence | Distinguishes real demand from price drift; CVD-price divergence on a pump = distribution | M | Requires signed trade ingest (buy vs sell). Compute as cumulative sum of signed volume; detect divergence vs price via pivot comparison. |
| BTC/ETH correlation and decoupling detection | Universe-wide pumps differ from idiosyncratic memecoin pumps; signal must condition on regime | S | Rolling 1h/4h correlation per symbol vs BTC. Decoupling = correlation drops sharply during a pump. |
| BTC dominance / market regime feature | Risk-on memecoin regime ≠ BTC-dominance regime; same pump pattern has different forward returns | S | CoinGecko global market cap data, daily granularity. |
| Configurable signal-generation pipeline (declarative, versioned) | You will iterate on features dozens of times; a hardcoded pipeline becomes a rewrite | M | Feature config in YAML/Pydantic, versioned in DB. Each backtest run references a `feature_set_version` foreign key. |

Group C — **Labeling & Training**

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Triple-barrier labeling (Lopez de Prado) | The standard for path-dependent trade labeling; binary "did price drop X% before stop-out Y% within T bars" matches the strategy's TP/SL/timeout reality | M | Use existing reference implementation (`mlfinlab` license-restricted; reimplement the 30-line core in-house). Parameters: TP %, SL %, max-hold bars. Critical: barriers measured from entry-bar OPEN, not close, to avoid leakage. |
| Meta-labeling (act vs not-act on primary signal) | Improves precision: primary model says "short setup," meta model says "trust this one?" | M | Adds a stage but adds real edge in research literature on crypto pair trading. Defer to Phase 2 — wins from primary model first. |
| Walk-forward cross-validation with purging and embargo | Without purging, label-overlap leakage inflates Sharpe by 2-5x | M | `sklearn.model_selection.TimeSeriesSplit` is INSUFFICIENT — does not purge. Implement custom `PurgedKFold` per Lopez de Prado. Embargo length = max label-horizon length. |
| Funding-window-aware label boundaries | Labels that span a funding settlement embed information from a future funding tick into features | M | Property-based test (Hypothesis): assert label-end-time < next-funding-tick OR feature uses only data ≤ label-start. **This is a leakage vector specific to perps that generic ML pipelines miss.** |
| Sample weighting by uniqueness (concurrent labels) | Overlapping labels create artificial sample size; weight by inverse uniqueness | M | Lopez de Prado Ch. 4. Without this, validation metrics overstate confidence on overlapping events. |
| Class imbalance handling (short-after-pump events are rare) | Naive training on 1:99 imbalance learns "predict no-event always" | S | `scale_pos_weight` in XGBoost; SMOTE is generally a bad idea on time-series — prefer sample weighting + threshold tuning. |
| Hyperparameter tuning with walk-forward (Optuna) | Grid search overfits the validation set; Bayesian + pruning is the production standard | M | Optuna TPE sampler + MedianPruner + study persistence in Postgres. Budget: 50-200 trials per model. |
| Feature importance + SHAP per-trade attribution | Trust gate for autonomy escalation: "why did this fire?" must be answerable | M | SHAP for XGBoost is native. Store per-signal SHAP values in DB for later review. |
| Experiment tracking (MLflow) | Without it you cannot reproduce a backtest result from 3 weeks ago | S | Self-hosted MLflow against same Postgres. Tag every run with code commit hash, data snapshot ID, feature-set version. |

Group D — **Backtesting & Simulation**

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Event-driven backtester (not vectorized for execution decisions) | Stop-loss interactions, partial fills, and position sizing rules are path-dependent — vectorized backtests over-estimate edge by 20-50% | L | Custom event loop reading from TimescaleDB; vectorbt acceptable ONLY for closed-form rule screening. Defer NautilusTrader (still 1.x with breaking changes). |
| Realistic MEXC fee model (maker 0.02%, taker 0.05%, per-tier) | A 0.05% flat fee on a 50-trade-per-day strategy is the difference between 30% and -10% annual | S | Use ccxt's `market['taker']`/`market['maker']` — exchange-provided, version-tracked. |
| Slippage model conditioned on top-of-book depth | Flat-% slippage on memecoin perps is a fantasy; slippage scales with order-size-as-fraction-of-book-depth | M | Use stored L2 snapshots; for orders > X% of top-N depth, walk the book. **Don't backtest a $500K-volume coin with 0.05% flat slippage.** |
| Partial fills modeling | Live execution will partial-fill; backtest must, too | M | Cap fill size at fraction of next-bar volume; carry remainder to next bar with degraded slippage. |
| Funding payment accounting (positions held across funding ticks pay/receive) | Short held through a positive-funding tick PAYS — can flip a winning trade to losing | S | At each funding boundary in the backtest, debit/credit per-symbol funding rate × position notional. |
| Latency simulation (signal-time vs execution-time separation) | Signal at candle close, execute at next-candle open with slippage — not at signal price | S | Hard separation in code: `signal_emitted_at_ts` and `order_filled_at_ts` are different fields. |
| Walk-forward backtest harness (rolling train/test) | Single train-test split overfits parameters to one period | M | Roll forward in N-month windows; aggregate metrics across folds, not from one held-out set. |
| Parameter robustness analysis (sensitivity to TP/SL/hold-time perturbations) | A strategy whose Sharpe drops 80% when SL changes from 3% to 4% is overfit | M | Grid over ±20% perturbations of every parameter; report metric stability. |
| Backtest reproducibility (deterministic, snapshot-pinned) | Re-running a backtest must give identical results; data snapshot must be pinned to a timestamp | M | Each backtest stamped with `data_snapshot_id` (a `MAX(ingested_at)` cutoff) and code commit hash. |
| Tearsheet output (Sharpe, Sortino, Calmar, max DD, win rate, avg R, exposure) | Single-metric optimization is how strategies die; multi-metric tearsheet is the standard | S | `quantstats` library; complement with custom drawdown attribution per trade. |

Group E — **Paper Trading**

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Live data feed → simulated execution → tracked P&L | Backtest realism is asymptotic; paper trading on live feeds catches real-world gaps | M | Same execution code path as live, with a "simulated" broker swap. ccxt makes this clean — same client, different account. |
| Backtest-vs-paper-trading reconciliation report | If paper diverges from backtest on overlapping period, slippage/fee/feature model is wrong | M | Daily report: paper P&L vs what backtest would have shown given identical signals. Flag divergence > X std. |
| Paper trading minimum duration gate (≥1-2 months) before live | PROJECT.md hard constraint | S | Implement as a config flag + DB-enforced check that prevents live mode unless paper run length & metrics pass thresholds. |
| Per-trade audit log (signal → order → fill → close → P&L attribution) | Without this you cannot debug why a trade lost money | S | Append-only `trade_events` table with every state transition. |

Group F — **Risk Management**

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Quarter-Kelly position sizing | PROJECT.md decision; standard conservative sizing | S | Estimate p(win), R from rolling realized stats per setup type; size = 0.25 × Kelly. Cap absolute size at X% of equity regardless of Kelly output. |
| Hard stop-loss per trade | Without this a single bad trade nukes the account | S | Set at order-time; never moved against position (only trailing in favor allowed). |
| Trailing stop / time-based exit | Pump reversals don't go straight to target; trail to lock in or time-cut to free capital | M | Trailing % or ATR-based; time-cut after N bars without favorable progress. |
| Max concurrent positions | Prevents overexposure during signal cluster (memecoin pumps often cluster) | S | Hard cap (e.g., 5). On signal #6, queue or drop. |
| Daily loss limit (circuit breaker) | Per current best-practice 1-2% rule research, prevents one bad day from being catastrophic | S | E.g., -3% day → halt new entries; -5% week → halt entirely. Resets on UTC day boundary. |
| Max drawdown circuit breaker (account-level) | Drawdown asymmetry: 50% loss requires 100% gain to recover | S | E.g., -15% from equity high → halt; require manual restart. |
| Per-symbol exposure limit | Single memecoin going to zero (delisting, rug) must not nuke account | S | Cap notional per symbol as % of equity. |
| Kill switch (manual + automatic) | PROJECT.md decision; the single most important safety feature | M | Three triggers: Telegram command, HTTP endpoint, automatic on risk breach. Kill = cancel all open orders + close all positions at market + halt new orders + page operator. |
| Risk-limit-breach alert with auto-pause | Bots that breach limits and keep trading destroy accounts overnight | S | Breach → pause + alert; never silent. |
| Position reconciliation (exchange vs local) | The silent killer: local thinks 0 positions, exchange has 1 open from a missed fill | M | Every N seconds (60s default), fetch exchange positions/balances/open orders, reconcile against local state, alert on mismatch. **This is table stakes that solo bots routinely skip and then lose money to.** |

Group G — **Execution**

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| MEXC futures order placement (market, limit, stop, conditional) | Foundation of live mode | M | ccxt unified API; test every order type in paper mode first. Pin ccxt version (MEXC swap endpoint changed in ccxt#28532, May 2026). |
| Retries with exponential backoff on transient errors | Network blips, exchange rate limits, momentary 5xx | S | `tenacity` decorator. Distinguish idempotent retries (cancel) from non-idempotent (place order — use client order ID for dedup). |
| Client order ID for dedup | Without it, a retry on a timed-out order can create a duplicate position | S | UUID per intended order. MEXC accepts client order IDs on futures. |
| Slippage protection (max price deviation on market orders) | Wide-spread memecoin perps can fill at -5% slippage on a market order | S | Use limit-with-slippage instead of pure market; reject fill if mid moves > X bps between signal and order placement. |
| Order book aware sizing | Don't sell more than top-N depth × Y% to avoid walking the book | S | Pre-trade check against latest stored L2 snapshot. |
| Maker preference where viable | Maker rebate (or lower fee) compounds; 50%+ maker fills change strategy economics | M | Post-only limits at best bid/ask; if not filled in N seconds, cancel and re-cross with taker. |
| API key separation (read-only ingest key vs trade key, no withdraw) | MEXC permissions are coarse; principle of least privilege | S | Two keys in env vars; ingest service never sees trade key. |
| Order/position state machine with reconciliation hooks | Distributed-system reality: orders can be in "submitted," "ack'd," "partially-filled," "filled," "cancelled," "rejected," "unknown" — handle every state | M | Explicit FSM with persisted state per order. Unknown state → reconcile via exchange query. |
| Graceful shutdown (don't leave positions in flight on deploy) | Railway auto-deploys on push; mid-deploy crash without graceful shutdown = stuck orders | S | Signal handler for SIGTERM: stop new entries, wait for in-flight orders to settle (with timeout), then exit. |

Group H — **Observability & Trust**

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Strategy dashboard: equity curve, win rate, EV, max DD, exposure | Without this you can't tell if the bot is working today | M | Grafana scraping Prometheus endpoint exposed by FastAPI. Pre-built panels: live equity, today's P&L, open positions, signal count. |
| Pipeline health monitoring (data freshness per source) | Coinglass API outage → stale features → bad signals; you must see the staleness | S | Per-data-source `last_ingested_at` + `expected_cadence_seconds`. Stale = `now - last > 3× cadence`. |
| Model staleness monitoring (feature distribution drift) | Memecoin regime changes; model trained on Q1 may not work Q3 | M | Track rolling feature distributions (mean, p25, p50, p75, p95); alert on KS-statistic vs training distribution. |
| Telegram alerts: signals, fills, errors, risk breaches | PROJECT.md decision; primary operator channel | S | `python-telegram-bot`. Severity-tagged: INFO (signal), WARN (recoverable), ERROR (paged), CRITICAL (kill-switch fired). |
| Structured JSON logs | Trading bugs need replayable context; `print()` is not debugging | S | `structlog`. Every log line: timestamp, level, event_name, symbol (if applicable), correlation_id (per signal lifecycle). |
| Per-signal explainability log (SHAP values stored) | Trust gate for autonomy escalation | S | At signal generation, write top-N SHAP features + values to `signal_explanations` table. |
| Trade journal export | Manual review and tax reporting | S | CSV/Parquet export of all trades with full attribution columns. |

Group I — **Operational / DevOps**

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| GitHub-hosted code with protected main branch | PROJECT.md decision; standard hygiene | S | Branch protection: required PR review (self-approve fine for solo), required CI green. |
| CI: tests on every PR, merge blocked on failure | PROJECT.md decision | S | GitHub Actions. Steps: `uv sync` → `ruff check` → `pyright` → `pytest`. |
| CD: auto-deploy to Railway on push to main | PROJECT.md decision | S | Railway's GitHub integration. Don't add a separate deploy gate beyond CI — single env, fast feedback. |
| Secrets management (env vars, not in repo) | API key in repo = account drain in hours | S | Railway env vars; `pydantic-settings` validates presence at startup. Pre-commit hook for `gitleaks`. |
| API key rotation procedure (documented + tested) | Inevitable: key leaks, exchange rotates, you change accounts | S | Documented runbook; smoke test for key validity at startup. |
| Database backups (point-in-time recovery) | Railway managed Postgres has backups, but verify the restore path | S | Test restore on a copy quarterly. PITR window depends on Railway tier. |
| Strategy/config version control (in DB + git) | Backtest results must be reproducible to the exact config | M | `strategy_versions` table with config blob, code commit hash, created_at. Every signal/trade references a `strategy_version_id`. |
| Test coverage gate (80%+ per global rules) | TDD culture per PROJECT.md | S | `pytest-cov` in CI. |
| Property-based tests for invariants (Hypothesis) | Trading invariants (balance non-negative, no leakage in label generation, idempotent ingest) are best caught by fuzzing | M | Per global testing rules + ML-trading specifics. Encode: "label end < next funding tick," "sum of signed trades = OHLCV close - open delta," "feature window never extends into future." |
| Local development against prod-shaped data | Hard to iterate on features against synthetic data | M | `railway run` for prod env locally, OR nightly anonymized snapshot to dev DB. |

### Differentiators (Competitive Advantage for the Project's Specific Thesis)

These are the features where "competent" becomes "actually has edge." Not all are v1 — but the roadmap should ear-mark them as Phase 2+ targets, not "maybe later" hand-waves.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Multi-source funding/OI stitching with `source` attribution at row level | MEXC-native funding tells you "where your fill will land"; Coinglass aggregate tells you "what the crowd is doing." Combining them as conditioned features outperforms either alone. Most solo bots use one or the other. | M | Schema change, not algorithmic. Tag every funding/OI row with `source` enum. Features then explicitly distinguish `mexc_funding_z` vs `coinglass_agg_funding_z`. |
| Liquidation cascade depth feature (recursive cascade modeling) | Not just "how much was liquidated" but "did one liquidation trigger another within X seconds" — cascade depth predicts pump exhaustion better than total liquidation $ | M | Window analysis on liquidation event stream: cluster events within Δt, count cluster size and cumulative $. Coinglass data required. |
| BTC-decoupling regime feature with correlation regime classifier | A memecoin pumping while BTC is flat is a different setup from one pumping with BTC; gates which model to use | M | Train a simple regime classifier (HMM or threshold-based) on rolling BTC correlation + BTC volatility. Use as a feature OR as a model-selection gate. |
| Per-trade SHAP explanations stored + Telegram-rendered on signal | Critical for autonomy escalation: when the bot says "short ABC," the alert says "shorting because: RSI 4h=88 (SHAP +0.31), funding z=2.4 (SHAP +0.22), OI Δ1h=+18% (SHAP +0.18)" | M | SHAP per signal → top-N features → Telegram message template. Costs ~50ms per signal — acceptable. |
| Pump archaeology: versioned algorithmic pump labels in DB | When you iterate on pump detection thresholds (you will, dozens of times), you want to regenerate labels without losing prior versions. Enables A/B comparison of detector variants. | M | `pump_events` table with `detector_version_id`. Each label generation run creates a new version; backtests reference a specific version. |
| Walk-forward backtest scheduled to re-run weekly with drift report | Auto-rerun last quarter's backtest on this week's data; if metrics decay > X%, alert. Catches regime change without you noticing manually. | M | Scheduled job; persist baseline metrics; compare and alert. Adds compute cost but invaluable for trust. |
| Slippage model calibrated from actual paper-trading fills | Bootstrapping: backtest with conservative slippage assumption → paper trade → measure actual fill slippage per (symbol, size, top-of-book depth) bucket → update backtest slippage model. Closes the backtest-paper gap that kills strategies in live. | L | Adds an offline calibration step but is the single biggest win on backtest realism. |
| Multi-strategy framework with shared data layer | PROJECT.md explicitly designs for this; the differentiator is doing it RIGHT — i.e., strategies as plugins, not branches | M | Strategy interface: `generate_signals(features) -> Signals`; data and risk layers are shared. Don't fork the codebase per strategy. |
| Dynamic universe re-rank scored by historical pump frequency | Rather than just "$500K+ 24h volume," rank by "this symbol has had N qualifying pumps in last 90 days" — bias toward symbols where the strategy has historical signal | S | Computed daily from `pump_events` table. Adds a `pump_frequency_score` column to universe snapshot. |
| Adaptive position sizing tied to current capital tier | PROJECT.md: "system should correctly work from $500 to $50K+ accounts." Implement as a piecewise function — at low capital, prefer fewer larger trades to overcome minimum order sizes; at higher capital, sub-Kelly diversification across more setups | M | `position_sizing_v2(equity, kelly_estimate, min_notional, max_concurrent) -> size`. Critical for the project's actual use case. |
| Backtest replay with exact historical L2 order book reconstruction | For top 20% of trades by P&L impact, replay against actual stored L2 snapshots to verify slippage assumption was met. Catches optimistic backtests. | L | Storage-intensive; only worth doing for highest-impact trades. |
| Meta-labeling layer (Lopez de Prado) | Primary model: "is this a short setup?" (recall-oriented). Meta model: "should we actually act on this primary signal?" (precision-oriented). Documented win in pair-trading crypto literature. | M | Phase 2 after primary model has working baseline. |
| Funding-window-conditioned features (proximity to next funding tick) | Behavior near funding tick (T-15min to T+15min) differs from mid-window — feature that explicitly conditions on this captures the regime | S | `seconds_to_next_funding`, `seconds_since_last_funding` as features. Cheap, useful. |
| MEXC-listing-age feature | New listings (< 30 days) behave very differently — extreme volatility, thin liquidity, manipulation prone | S | From CoinGecko or first-seen-on-MEXC date. Bucket: new (<30d), young (30-180d), mature (>180d). |
| Operator-in-the-loop semi-auto mode (Telegram-confirm-to-execute) | PROJECT.md decision; differentiates from "either alerts or full-auto" — the middle tier where you build trust | M | Signal → Telegram inline keyboard ("Execute" / "Skip") → action on tap. Time-out after N minutes → skip. |
| Equity curve simulation with bootstrapped confidence intervals | "Sharpe 1.8" tells you nothing about variance; bootstrap 1000 resamples shows the realistic range | S | `quantstats` or custom; gives realistic expectations for live performance. |

### Anti-Features (Deliberately NOT Build — With Reasoning)

| Feature | Why Tempting | Why Problematic | Alternative |
|---------|--------------|-----------------|-------------|
| Sentiment via Twitter/X NLP scraping | "Social signals predict pumps!" | Twitter API is expensive ($100+/mo for usable tier as of 2026), NLP on crypto twitter is mostly noise, signal-to-noise dramatically worse than derivatives data, and PROJECT.md already excludes it explicitly | Use on-chain/volume/funding-rate-spike as sentiment PROXIES (already in scope). Re-evaluate ONLY if everything else proves insufficient and a specific Twitter signal is identified as causal. |
| Real-time tick-by-tick architecture | "Lower latency = more edge!" | Strategy operates on minute-bar timeframes; sub-second latency is irrelevant. Tick architecture introduces websocket buffer management, out-of-order handling, and reconnect bugs that destroy bots overnight. | Build on 1m-resolution event loop with second-resolution timestamps. ccxt Pro websockets for fresh data, but processing on candle-close. |
| Custom proprietary GUI dashboard built from scratch | "I want it to look good" | Months of frontend work for a tool only the solo operator uses. Every minute on dashboard is a minute not on alpha. | Grafana + Telegram. Done. Anti-template rules (web/design-quality.md) don't apply to dev-internal observability tools. |
| Multi-exchange execution in v1 | "Spread the risk" | PROJECT.md correctly excludes. Memecoin-listing edge is MEXC-specific; adding Binance dilutes signal AND adds operational surface. Schema must SUPPORT multi-exchange (symbol_source attribution) but execution stays MEXC-only. | Defer until MEXC edge is validated AND you specifically identify an exchange-arbitrage signal. |
| Long setups in v1 | "More trades = more EV" | Different statistical regime entirely. Long alpha in memecoin space is a fundamentally different strategy (early-listing momentum vs post-pump reversal). Mixing them in one model destroys both. | Separate strategy after short-after-pump validates. Strategy framework supports it; v1 implementation doesn't include it. |
| Sophisticated NLP / on-chain whale tracking for v1 | "Smart money signals" | On-chain whale tracking has high false-positive rate, requires Etherscan/Solscan API integration per chain (MEXC futures span many chains), and the alpha is being arbed away by professional services with $1M+ budgets. | Use volume + OI + liquidation as derivative proxies for "informed money is positioned." Re-evaluate after edge is validated. |
| Per-trade Twitter sentiment lookup at signal time | "Confirm before entering" | Latency-introducing dependency on external API; if Twitter API rate-limits or hangs, signal is delayed/missed. | If you eventually want a sentiment feature, ingest async into the warehouse (offline), use as a feature at training time — never as a synchronous live-decision dependency. |
| Microstructure HFT-style features (queue position, order flow toxicity, VPIN at sub-second) | "Institutional traders use these" | Requires raw L3 order book data MEXC doesn't expose, sub-millisecond clock sync (Railway-hosted bot has 50-200ms exchange RTT), and computational budget that doesn't fit. The strategy works at minute resolution — VPIN at minute resolution is meaningful; sub-second isn't useful here. | Use 1m-resolution CVD, OI rate of change, liquidation cascade depth. These capture 80% of what HFT-style features capture at the relevant timescale. |
| Self-built ML framework / from-scratch gradient boosters | "Full control" | XGBoost/LightGBM are 10+ years of optimization; you will not beat them in finite human time. | XGBoost primary, LightGBM secondary. Per STACK.md decision. |
| Reinforcement learning for v1 | "End-to-end optimization!" | RL on financial time series is notoriously unstable, hard to validate, needs orders of magnitude more data than supervised setups. Even pros struggle. | Supervised classification (triple-barrier labels). RL is a Phase 4+ exploration after deep supervised baseline. |
| Multi-tenant / SaaS-ifying the platform | "What if I commercialize this?" | PROJECT.md correctly excludes. Premature multi-tenant infrastructure is the #1 way solo trading projects die without ever shipping the first trade. | Solo-only. If commercialization ever becomes real, that's a separate project that can fork this code. |
| Custom DEX integration (dYdX, GMX) | "Decentralized!" | Different liquidity profile, different fee model, different oracle risks, different settlement. PROJECT.md correctly excludes. | CEX-only v1. Strategy framework should not bake in CEX-specific assumptions in interfaces, but DEX support is not on roadmap. |
| Automatic strategy parameter optimization in live (online learning) | "Always-current model!" | Online optimization in live trading is how bots overfit to last week's noise. The right cadence is: weekly walk-forward retrain in offline mode, deploy after validation. | Scheduled offline retrain (weekly), deploy to live only after passing walk-forward gates. Differentiator above covers the scheduling part. |
| 100% test coverage as a goal | "TDD!" | Global rules require 80%, which is correct. 100% means writing trivial tests for trivial code, slowing iteration. | 80%+ overall, 95%+ on risk-management and execution modules (where bugs = money). Hypothesis property-based tests fill the gap that line coverage misses. |
| Real-time L3 order book reconstruction storage | "Maximum fidelity!" | Even at MEXC scale, L3 storage cost is prohibitive on Railway and processing cost is non-trivial. L2 top-20 snapshot at 5-10s is the sweet spot. | L2 top-20, sampled. Already in table stakes above. |
| Universal indicator library (all 200+ TA-Lib indicators computed always) | "More features = more model power" | Curse of dimensionality, noise injection, training time inflation, harder SHAP interpretation. Pre-baked indicator dump is a research smell. | Curated feature set per hypothesis. Each new indicator must justify its inclusion via SHAP/feature importance after backtest. |
| Telegram-bot-style conversational interface ("show me last 10 trades") | "Convenient!" | Maintenance burden, no users beyond yourself, Grafana already shows it. | Telegram for ALERTS and CONFIRM/SKIP semi-auto interactions only. Reads go to Grafana. |

## Feature Dependencies

```
Data Ingest (MEXC OHLCV/funding/OI/trades, Coinglass, CoinGecko)
    │
    ├──requires──> TimescaleDB schema with symbol-source attribution
    │                  │
    │                  └──requires──> Schema migrations (Alembic)
    │
    ├──requires──> Idempotent ingest pipelines (tenacity + aiolimiter)
    │
    └──requires──> Symbol lifecycle handling (no-cascade deletes)

Universe Filter ($500K+ daily refresh)
    │
    └──requires──> CoinGecko or MEXC volume data + persisted universe_snapshots

Feature Engineering (RSI / divergences / CVD / OI ΔROC / funding spike / liq cascade / VP / BTC corr)
    │
    ├──requires──> Data Ingest (all sources)
    │
    ├──requires──> Universe Filter
    │
    └──requires──> Configurable signal-generation pipeline (versioned features)

Pump Detection (Algorithmic Labeling)
    │
    ├──requires──> Feature Engineering (volume/price features)
    │
    └──requires──> Versioned pump_events table (pump archaeology)

Triple-Barrier Labeling + Walk-Forward CV + Purging/Embargo + Funding-Window-Aware Labels
    │
    ├──requires──> Pump Detection
    │
    └──requires──> Property-based tests (Hypothesis) for leakage invariants

ML Training (XGBoost primary, LightGBM secondary, Optuna tuning)
    │
    ├──requires──> Triple-Barrier Labeling
    │
    ├──requires──> MLflow experiment tracking
    │
    └──requires──> Feature Engineering pipeline frozen at train-time snapshot

SHAP per-signal explanations
    │
    └──requires──> ML Training (model artifact in MLflow registry)

Event-Driven Backtester
    │
    ├──requires──> Data Ingest (historical)
    │
    ├──requires──> Feature Engineering
    │
    ├──requires──> ML Training (trained model)
    │
    ├──requires──> MEXC fee model + slippage model + partial-fill model + funding-payment accounting
    │
    └──enhances──> Backtest replay with L2 reconstruction

Paper Trading
    │
    ├──requires──> Data Ingest (live websockets via ccxt Pro)
    │
    ├──requires──> Feature Engineering (live mode)
    │
    ├──requires──> ML Training (deployed model)
    │
    ├──requires──> Risk Management (all components)
    │
    ├──requires──> Execution module in simulation mode (same code path as live)
    │
    └──enhances──> Slippage model calibration from paper fills

Risk Management (Kelly sizing, stops, max concurrent, daily/DD circuit breakers, position reconciliation)
    │
    ├──requires──> Data Ingest (live equity + position state from exchange)
    │
    └──conflicts──> Online/live parameter optimization (would defeat circuit-breaker invariants)

Live Execution
    │
    ├──requires──> Paper Trading (≥1-2 months positive)  ← PROJECT.md HARD GATE
    │
    ├──requires──> Risk Management
    │
    ├──requires──> API key separation (read-only ingest vs trade key)
    │
    ├──requires──> Position reconciliation
    │
    └──requires──> Kill switch

Hybrid Autonomy Escalation (signal-only → semi-auto → full-auto)
    │
    ├──requires──> Telegram alerts
    │
    ├──requires──> Telegram inline keyboard ("Execute" / "Skip") for semi-auto
    │
    ├──requires──> SHAP per-signal explanations (trust gate)
    │
    └──requires──> Live Execution

Observability (Grafana dashboard, pipeline health, model staleness, structured logs)
    │
    ├──requires──> Prometheus metrics exposed from FastAPI
    │
    ├──requires──> structlog JSON logs
    │
    └──enhances──> All other features (Trust gate for escalation)

Multi-Strategy Framework
    │
    └──requires──> Strategy interface designed BEFORE first strategy ships (or refactor later)
```

### Dependency Notes

- **Schema with symbol-source attribution must be in v1**, not retrofitted. Adding a `source` column to a populated hypertable later is painful and a leakage vector during migration.
- **Property-based tests for leakage must exist before the first ML model trains** — otherwise the model trains on leaky labels, you trust the metrics, and the strategy fails in paper trading 6 weeks later.
- **Paper trading depends on the EXACT execution code path being live-compatible.** Build the execution module with a swappable broker interface from day one; do not write a separate "simulator" that paper trades against and a "real" one for live.
- **Kill switch must exist before the first paper trade**, not the first live trade. Paper trading kill switch tests the kill-switch infrastructure; first time you need it in live is too late.
- **SHAP explanations are a prerequisite for autonomy escalation**, not a "nice to have" later. Without per-signal explainability, the operator cannot build the trust to escalate from signal-only to semi-auto.
- **Position reconciliation must exist before live mode.** Paper trading skips this because there's no exchange state to reconcile; first time you go live without it, a missed websocket reconnect leaves you with mystery positions.
- **Multi-strategy framework conflicts with hardcoded strategy-1 paths.** If you don't design the strategy interface in Phase 1, by the time strategy #2 arrives you're refactoring everything. Even with one strategy, write the interface and have strategy-1 implement it.

## MVP Definition

### Launch With (v1 — gated on PROJECT.md "Active" requirements)

Minimum viable product = data platform + first strategy + paper trading. No live trading in v1.

**Data Platform (table stakes):**
- [ ] MEXC OHLCV ingest (1m/5m/15m/1h/4h/1d) for full USDT-perp universe — **foundational**
- [ ] MEXC funding rate + open interest + recent trades — **all features depend on this**
- [ ] Coinglass funding + OI + liquidation ingest (Startup tier minimum) — **derivatives signal floor**
- [ ] CoinGecko market metadata daily — **universe filter + listing-age feature**
- [ ] TimescaleDB schema with symbol-source attribution and lifecycle handling — **schema-set-in-stone-from-day-1 decision**
- [ ] Idempotent ingest with retries, dead-letters, schema validation
- [ ] Backfill 1-2 years of historical data (within Coinglass tier limits — accept 12 days of 1m derivatives if budget is Startup tier)
- [ ] Dynamic universe filter ($500K+ 24h volume, persisted snapshots)

**Strategy #1 Research Loop (table stakes):**
- [ ] Algorithmic pump detector + versioned `pump_events` table — **labeling foundation**
- [ ] Triple-barrier labeling with parameterized TP/SL/timeout
- [ ] Walk-forward CV with purging and embargo (custom `PurgedKFold`)
- [ ] Funding-window-aware label boundary checks (Hypothesis property tests)
- [ ] Feature engineering pipeline: multi-TF RSI, RSI divergence, CVD + CVD divergence, OI ROC, funding z-score, liquidation cascade magnitude, volume profile/POC, BTC correlation, BTC-decoupling, listing-age, BTC-dominance regime
- [ ] XGBoost baseline + LightGBM secondary, Optuna walk-forward tuning
- [ ] MLflow experiment tracking with code-commit + data-snapshot tags
- [ ] SHAP per-trade explainability stored in DB
- [ ] EDA notebooks in `notebooks/` (Jupyter) — **research only, production code never imports**

**Backtesting & Paper Trading (table stakes):**
- [ ] Event-driven backtester with MEXC fee model, depth-conditioned slippage, partial fills, funding payment accounting, latency separation
- [ ] Walk-forward backtest harness with rolling windows
- [ ] Parameter robustness sensitivity sweep
- [ ] `quantstats` tearsheet output
- [ ] Paper trading on live ccxt Pro feed with simulated execution using the **same** execution-module code path as live
- [ ] Backtest-vs-paper reconciliation report
- [ ] Per-trade audit log (signal → order → fill → close → P&L)

**Risk Management (table stakes — must work in paper trading):**
- [ ] Quarter-Kelly position sizing
- [ ] Hard stop-loss + trailing stop + time-based exit
- [ ] Max concurrent positions cap
- [ ] Daily loss limit + max drawdown circuit breaker
- [ ] Per-symbol exposure limit
- [ ] Kill switch (Telegram command + HTTP endpoint + automatic on risk breach)
- [ ] Position reconciliation loop

**Execution (table stakes — runs in simulated mode in paper):**
- [ ] MEXC order placement with retries, client order IDs, slippage protection, order book aware sizing
- [ ] API key separation (read-only ingest vs trade key, no withdraw)
- [ ] Order state machine with reconciliation
- [ ] Graceful shutdown on SIGTERM

**Observability (table stakes):**
- [ ] Grafana dashboard: equity, P&L, win rate, exposure, drawdown
- [ ] Pipeline health monitoring (data freshness per source)
- [ ] Prometheus `/metrics` endpoint from FastAPI
- [ ] Telegram alerts (signals, fills, errors, risk breaches) with severity tags
- [ ] Structured JSON logs (structlog) with correlation IDs

**DevOps (table stakes — PROJECT.md decisions):**
- [ ] GitHub repo, protected main
- [ ] CI: ruff + pyright + pytest (80%+ coverage gate)
- [ ] Railway auto-deploy on push to main
- [ ] Secrets in Railway env vars, validated by pydantic-settings
- [ ] Alembic migrations (TimescaleDB-aware)

### Add After Paper-Trading Validation Passes (v1.x — gates Live Trading)

Triggers: ≥1-2 months paper trading with positive EV, walk-forward metrics holding on live data, low backtest-vs-paper divergence.

- [ ] Live MEXC execution (same code path as paper, broker swap)
- [ ] Signal-only autonomy mode (Telegram alerts, manual execution by operator)
- [ ] Semi-auto autonomy mode (Telegram inline keyboard, confirm-to-execute)
- [ ] Full-auto autonomy mode (only after sustained positive semi-auto)
- [ ] Multi-source funding/OI stitched features (MEXC-native + Coinglass aggregate as distinct features)
- [ ] Liquidation cascade depth feature (cluster modeling)
- [ ] BTC-decoupling regime classifier (HMM or threshold-based)
- [ ] Funding-window-conditioned features (seconds-to-next-funding)
- [ ] Listing-age feature
- [ ] Slippage model calibration from paper fills → backtest update
- [ ] Scheduled weekly walk-forward re-run with drift alerts
- [ ] Model staleness monitoring (feature distribution KS-statistic)
- [ ] Adaptive position sizing by capital tier
- [ ] Trade journal export (CSV/Parquet)

### Future Consideration (v2+ — only after live strategy is profitable)

- [ ] Meta-labeling layer (Lopez de Prado primary + meta)
- [ ] Backtest replay with stored L2 reconstruction (top-impact trades only)
- [ ] Second strategy (different hypothesis — long setups, pair trading, basis trades — uses same data layer)
- [ ] Multi-strategy framework hardening (strategy plugins, shared risk pool)
- [ ] Coinglass Standard tier ($299/mo) for 720-day hourly derivatives backfill — only if backtest realism demands it
- [ ] CatBoost as ensemble member if categorical features dominate
- [ ] Sequence models (PyTorch LSTM/Transformer) — only after gradient boosters prove edge
- [ ] Multi-exchange execution (Binance / Bybit / OKX) — only if MEXC-specific risk emerges
- [ ] Migration from APScheduler to Prefect 3 — only if DAG dependencies emerge
- [ ] Migration from TimescaleDB to ClickHouse — only if row count crosses 500M with degraded query latency

### Explicitly NOT in any version (Anti-Features summary)

- [ ] Multi-user / SaaS / billing
- [ ] Spot trading
- [ ] Long setups (until short-after-pump validates and a separate strategy is opened)
- [ ] Twitter/NLP sentiment
- [ ] Mobile app
- [ ] DEX futures
- [ ] Real-time tick architecture
- [ ] Custom GUI from scratch
- [ ] HFT-style L3 microstructure features
- [ ] Reinforcement learning
- [ ] Online live parameter optimization
- [ ] 100% test coverage as a goal (80% is the rule; 95%+ on risk and execution modules)
- [ ] L3 order book storage

## Feature Prioritization Matrix

P1 = must have for v1 launch; P2 = v1.x add after paper validation; P3 = v2+ future; X = anti-feature.

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| MEXC OHLCV ingest | HIGH | MEDIUM | P1 |
| MEXC funding + OI + trades | HIGH | MEDIUM | P1 |
| Coinglass derivatives ingest | HIGH | MEDIUM | P1 |
| CoinGecko metadata | MEDIUM | LOW | P1 |
| TimescaleDB schema (with source attribution) | HIGH | MEDIUM | P1 |
| Universe filter ($500K+) | HIGH | LOW | P1 |
| Idempotent ingest pipelines | HIGH | MEDIUM | P1 |
| Symbol lifecycle handling | HIGH | MEDIUM | P1 |
| Alembic migrations | HIGH | LOW | P1 |
| Algorithmic pump detector | HIGH | MEDIUM | P1 |
| Triple-barrier labeling | HIGH | MEDIUM | P1 |
| Walk-forward CV with purging/embargo | HIGH | MEDIUM | P1 |
| Funding-window-aware label boundary | HIGH | MEDIUM | P1 |
| Multi-TF RSI + divergences | HIGH | LOW | P1 |
| CVD + CVD divergence | HIGH | MEDIUM | P1 |
| OI rate of change | HIGH | LOW | P1 |
| Funding spike z-score | HIGH | LOW | P1 |
| Liquidation cascade magnitude | HIGH | MEDIUM | P1 |
| Volume profile / POC | MEDIUM | MEDIUM | P1 |
| BTC correlation + decoupling | HIGH | LOW | P1 |
| BTC dominance regime | MEDIUM | LOW | P1 |
| XGBoost + LightGBM baseline | HIGH | MEDIUM | P1 |
| Optuna walk-forward tuning | HIGH | MEDIUM | P1 |
| MLflow experiment tracking | HIGH | LOW | P1 |
| SHAP per-trade explanations | HIGH | MEDIUM | P1 |
| Event-driven backtester | HIGH | HIGH | P1 |
| MEXC fee model | HIGH | LOW | P1 |
| Depth-conditioned slippage model | HIGH | MEDIUM | P1 |
| Partial fills modeling | HIGH | MEDIUM | P1 |
| Funding payment accounting | HIGH | LOW | P1 |
| Latency separation in backtest | HIGH | LOW | P1 |
| Walk-forward backtest harness | HIGH | MEDIUM | P1 |
| Parameter robustness sweep | MEDIUM | MEDIUM | P1 |
| quantstats tearsheets | HIGH | LOW | P1 |
| Paper trading on live feed | HIGH | MEDIUM | P1 |
| Backtest-vs-paper reconciliation | HIGH | MEDIUM | P1 |
| Per-trade audit log | HIGH | LOW | P1 |
| Quarter-Kelly position sizing | HIGH | LOW | P1 |
| Hard stop-loss + trailing + time exit | HIGH | MEDIUM | P1 |
| Max concurrent positions | HIGH | LOW | P1 |
| Daily loss + max DD circuit breakers | HIGH | LOW | P1 |
| Per-symbol exposure limit | HIGH | LOW | P1 |
| Kill switch | HIGH | MEDIUM | P1 |
| Position reconciliation loop | HIGH | MEDIUM | P1 |
| MEXC order placement (paper mode) | HIGH | MEDIUM | P1 |
| Client order IDs + retries | HIGH | LOW | P1 |
| Slippage protection | HIGH | LOW | P1 |
| Order state machine | HIGH | MEDIUM | P1 |
| API key separation | HIGH | LOW | P1 |
| Graceful shutdown | HIGH | LOW | P1 |
| Grafana dashboard | HIGH | MEDIUM | P1 |
| Pipeline health monitoring | HIGH | LOW | P1 |
| Prometheus metrics | HIGH | LOW | P1 |
| Telegram alerts | HIGH | LOW | P1 |
| Structured JSON logs | HIGH | LOW | P1 |
| CI + protected branch | HIGH | LOW | P1 |
| Railway auto-deploy | HIGH | LOW | P1 |
| Secrets via env vars | HIGH | LOW | P1 |
| Hypothesis property-based tests for leakage | HIGH | MEDIUM | P1 |
| Strategy interface (multi-strategy framework) | MEDIUM | MEDIUM | P1 (designed) / P2 (proven) |
| Versioned strategy configs | HIGH | MEDIUM | P1 |
| Live MEXC execution | HIGH | LOW (incremental) | P2 |
| Signal-only / semi-auto / full-auto modes | HIGH | MEDIUM | P2 |
| Multi-source funding/OI stitched features | HIGH | MEDIUM | P2 |
| Liquidation cascade depth feature | MEDIUM | MEDIUM | P2 |
| BTC-decoupling regime classifier | MEDIUM | MEDIUM | P2 |
| Funding-window-conditioned features | MEDIUM | LOW | P2 |
| Listing-age feature | MEDIUM | LOW | P2 |
| Slippage model calibration from paper fills | HIGH | HIGH | P2 |
| Scheduled weekly walk-forward re-run | HIGH | MEDIUM | P2 |
| Model staleness monitoring | HIGH | MEDIUM | P2 |
| Adaptive position sizing by capital tier | HIGH | MEDIUM | P2 |
| Pump archaeology (versioned labels) | MEDIUM | MEDIUM | P2 |
| Trade journal export | MEDIUM | LOW | P2 |
| Meta-labeling layer | MEDIUM | MEDIUM | P3 |
| Backtest L2 replay | MEDIUM | HIGH | P3 |
| Second strategy | HIGH | MEDIUM | P3 |
| Coinglass Standard tier upgrade | MEDIUM | LOW | P3 |
| Sequence models (PyTorch) | LOW (until baseline proves out) | HIGH | P3 |
| Multi-exchange execution | LOW | HIGH | P3 |
| Prefect migration | LOW | MEDIUM | P3 |
| ClickHouse migration | LOW | HIGH | P3 |
| Twitter/NLP sentiment | LOW | HIGH | X |
| Multi-user / SaaS | NEGATIVE | HIGH | X |
| Spot trading | NEGATIVE | MEDIUM | X |
| Long setups in same model | NEGATIVE | MEDIUM | X |
| Mobile app | LOW | HIGH | X |
| DEX futures | LOW | HIGH | X |
| Real-time tick architecture | NEGATIVE | HIGH | X |
| Custom GUI from scratch | NEGATIVE | HIGH | X |
| HFT-style L3 features | LOW | HIGH | X |
| Reinforcement learning | LOW | HIGH | X |
| Online live parameter optimization | NEGATIVE | MEDIUM | X |
| L3 order book storage | LOW | HIGH | X |

## Competitor / Reference System Analysis

Reference systems (open-source crypto trading frameworks observed in 2024-2026):

| Feature | Hummingbot | Freqtrade | Jesse | NautilusTrader | Our Approach |
|---------|-----------|-----------|-------|----------------|--------------|
| Multi-exchange | Yes (50+) | Yes (~20 via ccxt) | Yes | Yes | **MEXC-only v1** (deliberate edge concentration) |
| Futures support | Yes (limited) | Yes (perpetuals) | Yes | Yes (best-in-class) | Yes (MEXC USDT-perp) |
| ML strategy support | Limited (custom strategies) | Yes (freqai add-on) | Custom | Custom event-driven | **First-class ML pipeline (XGBoost/LightGBM/MLflow/SHAP)** |
| Backtesting | Yes | Yes | Yes | Yes (production-grade) | **Custom event-driven matching paper/live code path** |
| Paper trading | Yes | Yes | Yes | Yes | Yes (same code path as live) |
| Walk-forward | Manual setup | Manual setup | Custom | Custom | **Built-in PurgedKFold + funding-window-aware** |
| SHAP explanations | No | Limited (freqai) | No | No | **Per-signal SHAP stored in DB, surfaced in Telegram** |
| Coinglass integration | No (community plugin) | No | No | No | **First-class** |
| Position reconciliation | Yes | Yes | Partial | Yes | Yes (mandatory before live) |
| Universe filter (dynamic) | Manual | Manual | Manual | Manual | **Built-in, daily refresh, persisted snapshots** |
| Liquidation cascade features | No | No | No | No (raw data only) | **First-class feature** |
| Hybrid autonomy escalation | No (binary on/off) | No (binary on/off) | No | No | **Three modes: signal-only / semi-auto / full-auto** |
| Telegram alerts | Limited | Yes (extensive) | Limited | No | Yes with severity tags and SHAP rendering |
| Kill switch | Limited | Limited | Limited | Limited | **Three triggers: Telegram + HTTP + auto-on-breach** |
| Strategy versioning (config in DB) | No | No | No | No | **First-class (versioned strategy configs, FK to every signal/trade)** |
| Open-source | Yes | Yes | Yes | Yes | **Closed (solo project)** |
| Maintenance status | Active | Active | Active | Active but 1.x with breaking changes | N/A |

**Reading of the table:** The open-source frameworks are excellent general-purpose trading bots, but none of them are a research-first ML pipeline. They treat ML as an afterthought add-on (Freqtrade's freqai is the closest, but lacks the SHAP/explainability/funding-window awareness this project needs). The competitive position is "purpose-built ML-research-platform-meets-MEXC-execution," which the open-source options do not fill — and which is why building this rather than configuring Freqtrade is justified.

**What to steal from each:**
- **Hummingbot:** Order management state machine patterns, multi-strategy isolation patterns.
- **Freqtrade:** Universe filtering UX, Telegram bot interaction patterns, freqai's approach to walk-forward feature engineering.
- **Jesse:** Cleaner backtester event loop than Freqtrade's; readable strategy interface.
- **NautilusTrader:** Production-grade event-driven engine semantics (use as a target when our custom backtester needs to grow up — but not yet, given 1.x instability).

## Sources

- **Lopez de Prado, "Advances in Financial Machine Learning"** — triple-barrier method, purging/embargo for walk-forward CV, meta-labeling, sample uniqueness. HIGH confidence (canonical reference; widely implemented).
- [The Triple Barrier Labeling of Marco Lopez de Prado](https://www.newsletter.quantreo.com/p/the-triple-barrier-labeling-of-marco) — HIGH (mechanics of triple-barrier confirmed)
- [Algorithmic crypto trading using information-driven bars, triple barrier labeling and deep learning (Springer 2025)](https://link.springer.com/article/10.1186/s40854-025-00866-w) — MEDIUM (academic paper; validates approach in crypto context)
- [Enhanced Triple Barrier Labeling for Crypto Pair Trading (MDPI 2024)](https://www.mdpi.com/2227-7390/12/5/780) — MEDIUM (academic validation in crypto)
- [Does Meta Labeling Add to Signal Efficacy? — Hudson & Thames](https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/) — HIGH (Hudson & Thames are the authoritative source on Lopez de Prado implementations)
- [Detecting Crypto Pump-and-Dump Schemes (arXiv 2503.08692, 2025)](https://arxiv.org/pdf/2503.08692) — HIGH (academic, recent; volume-spike thresholds and 1/3-of-month-in-event finding cited)
- [Microstructure and Manipulation: Quantifying Pump-and-Dump Dynamics (arXiv 2504.15790, 2025)](https://arxiv.org/pdf/2504.15790) — HIGH (academic microstructure approach for pump events)
- [Pump & Dump Detector — StratBase.ai](https://stratbase.ai/en/blog/pump-dump-detector-guide) — MEDIUM (industry-practitioner perspective)
- [MEXC Crypto Pulse — Understanding and Profiting from Short Squeezes](https://www.mexc.com/crypto-pulse/article/understanding-and-profiting-from-crypto-short-squeezes-52013) — HIGH (vendor-authoritative for MEXC-specific quirks: funding rate, OI, liquidation alerts UI)
- [MEXC — FAQ on Liquidation for Futures Trading](https://www.mexc.com/learn/article/faq-on-liquidation-for-futures-trading/1) — HIGH (vendor-authoritative on MEXC liquidation mechanics: cancel orders → match → laddered → bankruptcy takeover)
- [MEXC — Liquidation in Futures (blog)](https://blog.mexc.com/liquidation-in-futures/) — HIGH (vendor)
- [Bitcoin Futures Market Microstructure: Liquidation Cascades, Funding Regimes, and OI Signals (XT Exchange, 2026)](https://medium.com/@XT_com/bitcoin-futures-market-microstructure-liquidation-cascades-funding-regimes-and-open-interest-978b107b4889) — MEDIUM (industry analysis, recent)
- [Backtesting AI Crypto Trading Strategies Safely (Blockchain Council)](https://www.blockchain-council.org/cryptocurrency/backtesting-ai-crypto-trading-strategies-avoiding-overfitting-lookahead-bias-data-leakage/) — MEDIUM (industry guide; walk-forward + leakage prevention)
- [How to Backtest a Crypto Bot: Realistic Fees, Slippage, Paper Trading (Paybis)](https://paybis.com/blog/how-to-backtest-crypto-bot/) — MEDIUM (industry; signal-time vs execution-time separation explicitly called out)
- [Robust backtesting guide for crypto strategies](https://kitchentechy.com/market-analysis/robust-backtesting-guide-for-crypto-strategies-methods-pitfalls-and-best-practices/) — MEDIUM (industry; partial fills + queue modeling guidance)
- [How To Backtest Your Crypto Trading Strategy 2026 (Coin Bureau)](https://coinbureau.com/guides/how-to-backtest-your-crypto-trading-strategy) — MEDIUM
- [Cumulative Volume Delta Trading Strategy (Bookmap)](https://bookmap.com/blog/how-cumulative-volume-delta-transform-your-trading-strategy) — MEDIUM (CVD divergence mechanics)
- [CVD Guide (Chart Whisperer)](https://chartwhisperer.ca/blog/cumulative-volume-delta-cvd-crypto-trading-guide) — MEDIUM (CVD + funding rate combination)
- [Comprehensive Guide to Crypto Futures Indicators (CryptoCred via Medium)](https://medium.com/@cryptocreddy/comprehensive-guide-to-crypto-futures-indicators-f88d7da0c1b5) — MEDIUM (practitioner; standard derivatives indicators)
- [Decoding Market Dynamics: Price, CVD, OI, and Funding Rate](https://www.scribd.com/document/829499049/Decoding-Market-Dynamics-Price-CVD-OI-and-Funding-Rate) — MEDIUM (practitioner)
- [Trading Bot Risk Management 2026 (Cripton AI)](https://cripton.ai/en/guides/bot-risk-management) — MEDIUM (industry guide; kill switch + circuit breaker patterns confirmed)
- [Crypto Bot Pitfalls (Coin Bureau)](https://coinbureau.com/guides/crypto-trading-bot-mistakes-to-avoid) — MEDIUM (industry; circuit breaker on stale prices, daily loss limits)
- [Trading Bot Risk Management — Stop-Loss & Position Sizing (Nadcab)](https://www.nadcab.com/blog/trading-bot-risk-management-stop-loss-position-sizing-drawdown-control) — MEDIUM (industry; drawdown asymmetry math)
- [Crypto Trading Risk Checklist — 1-2% rule (Darkbot)](https://darkbot.io/en/blog/crypto-trading-risk-checklist-1-2percent-rule-for-safer-trades) — MEDIUM (industry)
- [Risk Management With Daily Loss Limit & Circuit Breaker (Binance Square)](https://www.binance.com/en/square/post/32732737991226) — MEDIUM (industry; 3% daily / 7% weekly heuristic)
- [Crypto Trading Bot Safety: API Keys, Permissions, and Risk (Vantixs 2026)](https://vantixs.com/blog/crypto-trading-bot-safety-guide-2026) — MEDIUM (industry; least-privilege API key separation)
- **PROJECT.md and STACK.md (this project)** — HIGH (project decisions and stack already validated)
- **ccxt MEXC issues #27253 and #28532** — HIGH (referenced from STACK.md; MEXC ccxt quirks)
- **Coinglass pricing page** — HIGH (referenced from STACK.md; tier limits)
- **STACK.md "Crypto-Trading-Specific Quirks" section** — HIGH (MEXC funding cadence, Coinglass source attribution, order book depth budget, slippage modeling, API key permission separation, UTC time zone discipline)

---
*Feature research for: MEXC futures ML short-after-pump trading system (solo, Railway, hybrid autonomy escalation)*
*Researched: 2026-05-21*
