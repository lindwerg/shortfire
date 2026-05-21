# Architecture Research

**Domain:** Crypto futures ML trading system — strategy-agnostic data platform + multi-strategy framework (short-after-pump = strategy #1)
**Researched:** 2026-05-21
**Confidence:** HIGH on layered architecture, multi-strategy interface design, schema patterns, and Railway topology; MEDIUM on exact build order (depends on early EDA findings); KNOWN-TENSION on feature store pattern (full feature store is overkill for v1, but lightweight feature contract is mandatory)

## Executive Summary

This system has **two architectural concerns that must stay separated**: the **strategy-agnostic data platform** (a single source of truth for MEXC + Coinglass + CoinGecko timeseries) and the **strategy framework** (interfaces that any future hypothesis plugs into). They share one database (TimescaleDB) but not one code path.

Recommended shape:

1. **Layered architecture, single deployable, multi-process on Railway.** Five logical layers (Ingest, Storage, Feature, Strategy, Execution) — but exactly **three Railway services** at v1: `data-platform` (ingest + feature compute), `strategy-engine` (signals + paper trading + execution), `dashboard-api` (read-only FastAPI for monitoring). All sharing the same TimescaleDB. A fourth service appears (`risk-guard`) only when going live with real capital.
2. **Storage = typed-per-source hypertables, not the universal `(symbol, timestamp, metric, value)` model.** At MEXC universe scale (200-500 perps × multiple resolutions × derivatives), wide-typed tables compress 5-10× better, scan 3-10× faster, and avoid the JOIN tax of narrow EAV-style schemas. Curated/feature tables sit on top as continuous aggregates or materialized hypertables.
3. **Strategy framework = ABC + registry + config-driven.** Every strategy implements a `Strategy` protocol (`features_required`, `generate_signals`, `position_sizing_hint`). A `StrategyRegistry` discovers strategies at startup. **Strategy params live in Postgres** (versioned, per-instance), not in YAML/code, so paper→live promotion is a row update, not a deploy.
4. **Shared backtester, per-strategy feature pipelines.** The event-driven backtester is strategy-agnostic — it takes a `Strategy` instance and a time window. Each strategy owns its feature pipeline (a function `(raw_data, params) -> features`), discovered via the same registry.
5. **Execution + risk = separate processes from signal generation.** Signal generation can crash, restart, and reload state from DB. Execution holds open positions and **must not die unattended**. Risk guard is a thin process with one job: enforce hard limits via DB row-level locking and exchange-side kill switch.
6. **Event model = hybrid, but mostly synchronous batch for v1.** 1m candle close → 5-30s feature compute window → strategy evaluation. Async websocket trades stream into a bounded buffer, get aggregated to 1m candles, then trigger feature/signal recomputation. No Kafka, no NATS, no Redis Streams — just Postgres + APScheduler + `asyncio.Queue` for in-process plumbing. Latency budget for scalp horizon (5m-4h holds) is **seconds, not milliseconds**.
7. **TDD-friendly by construction.** Every boundary is an interface (`IngestClient`, `FeatureProvider`, `Strategy`, `OrderRouter`, `RiskGuard`) with a Pydantic-validated contract and at least one fake implementation in `tests/fakes/` for deterministic property-based tests.

The biggest mistake to avoid: building a "feature store" as a separate service. A `features` schema in the same Postgres with versioned materialized views is the right pattern at solo scale.

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL DATA SOURCES                                    │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐                                   │
│   │   MEXC   │    │ Coinglass│    │CoinGecko │                                   │
│   │ REST+WS  │    │   REST   │    │   REST   │                                   │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘                                   │
└────────┼───────────────┼───────────────┼──────────────────────────────────────────┘
         │               │               │
         ▼               ▼               ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          LAYER 1: INGEST                                          │
│   ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                     │
│   │  MexcIngest    │  │CoinglassIngest │  │CoinGeckoIngest │                     │
│   │  (ccxt+ws)     │  │   (httpx)      │  │   (httpx)      │                     │
│   └───────┬────────┘  └───────┬────────┘  └───────┬────────┘                     │
│           │                   │                   │                                │
│           └──── retries+rate limit+schema validate (Pydantic) ────┐               │
│                                                                    ▼               │
├──────────────────────────────────────────────────────────────────────────────────┤
│                          LAYER 2: STORAGE (TimescaleDB)                           │
│   ┌─────────────────────────────────────────────────────────────────────┐        │
│   │  raw_*  (hypertables, one per source/dataset, typed-per-source)     │        │
│   │  ├── raw_mexc_candles_1m, _5m, _15m, _1h, _4h, _1d                  │        │
│   │  ├── raw_mexc_trades       (compressed beyond 24h)                  │        │
│   │  ├── raw_mexc_orderbook_l2 (compressed beyond 12h, top-20 depth)    │        │
│   │  ├── raw_mexc_funding                                               │        │
│   │  ├── raw_coinglass_funding_agg, _oi, _liquidations, _lsr            │        │
│   │  └── raw_coingecko_universe (daily refresh)                         │        │
│   │                                                                      │        │
│   │  curated_*  (continuous aggregates + materialized hypertables)      │        │
│   │  ├── curated_universe_active   (today's tradable universe)          │        │
│   │  ├── curated_candles_5m_filled (gap-filled, validated)              │        │
│   │  └── curated_derivatives_joined (funding + OI + liq, per symbol)    │        │
│   │                                                                      │        │
│   │  features_*  (per-strategy feature snapshots, versioned by feature  │        │
│   │              spec hash)                                              │        │
│   │  └── features_short_after_pump_v1                                    │        │
│   └─────────────────────────────────────────────────────────────────────┘        │
├──────────────────────────────────────────────────────────────────────────────────┤
│                          LAYER 3: FEATURE COMPUTE                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐        │
│   │  FeatureProvider (strategy-agnostic primitives library)             │        │
│   │  ├── rsi(), divergence(), funding_zscore(), oi_roc(),               │        │
│   │  │   liquidation_cascade(), vwap_band(), btc_corr(), ...            │        │
│   │                                                                      │        │
│   │  Per-Strategy Feature Pipelines (compose primitives)                │        │
│   │  └── short_after_pump.compute_features(raw, params) -> DataFrame    │        │
│   └─────────────────────────────────────────────────────────────────────┘        │
├──────────────────────────────────────────────────────────────────────────────────┤
│                          LAYER 4: STRATEGY                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐        │
│   │  StrategyRegistry (discovers via entry points or decorator)         │        │
│   │  ├── Strategy (ABC: name, features_required, generate_signals,      │        │
│   │  │             position_sizing_hint, params_schema)                 │        │
│   │  └── ShortAfterPumpStrategy(Strategy)                                │        │
│   │                                                                      │        │
│   │  Strategy Instances (rows in `strategy_instances` table)            │        │
│   │  ├── instance_id, strategy_name, params_json, status (paper/live)   │        │
│   │  │                                                                   │        │
│   │  Backtester (strategy-agnostic event-driven simulator)              │        │
│   │  └── replay(strategy, window, fee_model, slippage_model) -> Trades  │        │
│   └─────────────────────────────────────────────────────────────────────┘        │
├──────────────────────────────────────────────────────────────────────────────────┤
│                          LAYER 5: EXECUTION + RISK                                │
│   ┌─────────────────────────────────────────────────────────────────────┐        │
│   │  OrderRouter (paper | mexc-live, behind same interface)             │        │
│   │  ├── submit_order(), cancel_order(), fetch_positions()              │        │
│   │                                                                      │        │
│   │  RiskGuard (gatekeeper between Strategy and OrderRouter)            │        │
│   │  ├── enforces quarter-Kelly, max concurrent, daily loss, hard SL    │        │
│   │  └── reads from `risk_limits` table (configurable without deploy)   │        │
│   │                                                                      │        │
│   │  PositionTracker (single source of truth for open exposure)         │        │
│   │  └── reconciles every N seconds with exchange-reported positions    │        │
│   └─────────────────────────────────────────────────────────────────────┘        │
├──────────────────────────────────────────────────────────────────────────────────┤
│                          LAYER 6: OBSERVABILITY + CONTROL                         │
│   ┌────────────────┐   ┌────────────────┐   ┌────────────────┐                  │
│   │  FastAPI       │   │  Prometheus    │   │  Telegram Bot  │                  │
│   │  /api (read)   │   │  /metrics      │   │  alerts + kill │                  │
│   │  dashboard     │   │  Grafana cloud │   │  switch        │                  │
│   └────────────────┘   └────────────────┘   └────────────────┘                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **Ingest Clients** | One per data source. Fetch, validate (Pydantic), retry (tenacity), rate-limit (aiolimiter), write to `raw_*` hypertables. Idempotent on `(symbol, timestamp, source)`. | `MexcIngest` wraps `ccxt.pro.mexc`; `CoinglassIngest` and `CoinGeckoIngest` use `httpx.AsyncClient`. |
| **Scheduler** | Triggers ingest jobs on cadence (1m candles every minute, funding every 8h, universe daily). Persists job state in Postgres jobstore. | `APScheduler 4.x` with `PostgresJobStore`. One scheduler process inside `data-platform` service. |
| **Storage (TimescaleDB)** | Persists raw timeseries + curated aggregates + features. Hypertables with native compression policies. Continuous aggregates for common rollups. | TimescaleDB 2.18 on Railway PG16. Alembic migrations with `op.execute()` for hypertable + compression policy DDL. |
| **FeatureProvider (library)** | Pure functions: `(input_df, params) -> output_df`. No I/O. No DB. No state. Testable with synthetic candles. | Module of polars/pandas functions. Each primitive is a unit-testable function with Hypothesis property tests. |
| **Feature Pipeline (per-strategy)** | Composes FeatureProvider primitives into the exact feature set a strategy needs. Cached output goes to `features_<strategy>_v<hash>` table. | Function `compute_features(raw_data, params)` per strategy. Hash of feature spec used as version tag. |
| **Strategy (ABC)** | Contract every strategy honors. Declares its required features, generates signals from a feature snapshot, hints position sizing. **Stateless** between calls; per-instance state lives in DB. | Python `Protocol` (preferred over ABC for duck-typing with pyright). |
| **StrategyRegistry** | Discovers all `Strategy` implementations at startup. Maps `strategy_name` → class. Looks up DB-stored `strategy_instances` rows to instantiate live configs. | Decorator-based registration (`@register_strategy`). |
| **Backtester** | Event-driven loop over historical bars. Calls `strategy.generate_signals()` per bar. Simulates fills via `FeeModel` + `SlippageModel`. Outputs `Trade` records. | Custom Python class; **NOT NautilusTrader v1** (still 1.x churn per STACK.md). Pure-function-style; deterministic given same data + seed. |
| **OrderRouter** | Abstraction over paper vs live. Same interface; different implementation. Paper writes simulated fills to `trades_paper` table; live calls `ccxt.mexc.create_order`. | Interface + two concrete impls. Live impl uses `ccxt 4.5.x` with the unified `mexc` swap client. |
| **RiskGuard** | Sits between strategy and OrderRouter. **Last gate before any order.** Reads current positions + daily P&L + configured limits; refuses orders that breach. Owns the kill switch. | Python class with synchronous critical path. State persisted in `risk_limits` + `risk_state` tables. Hard locks via `SELECT ... FOR UPDATE` for concurrent-write safety. |
| **PositionTracker** | Single source of truth for open positions. Reconciles N-second loop with exchange's reported positions. Alerts on drift. | Background task in `strategy-engine` process. Discrepancy → Telegram alert + halt new entries. |
| **Dashboard API** | Read-only FastAPI service. Serves equity curve, open positions, signal history, recent backtest results, data freshness. **No write endpoints.** | FastAPI app exposing `/api/*` and serving a small SPA (or just SSR HTML; solo doesn't need React). |
| **Observability** | Prometheus `/metrics` endpoint on each service. Structured JSON logs via structlog → Railway log drain → Grafana Cloud Loki. Telegram for ops alerts. | `prometheus-client`, `structlog`, `python-telegram-bot`. |

## Recommended Project Structure

```
shortfire/
├── pyproject.toml
├── alembic/
│   └── versions/          # TimescaleDB hypertable + compression DDL migrations
├── src/
│   └── shortfire/
│       ├── config/
│       │   ├── settings.py           # pydantic-settings, env-var driven
│       │   └── secrets.py            # API key loading + validation
│       │
│       ├── domain/                   # Pure dataclasses + value objects, no I/O
│       │   ├── candle.py             # OHLCV + invariants (high >= max(open,close), etc.)
│       │   ├── orderbook.py
│       │   ├── funding.py
│       │   ├── signal.py             # SignalIntent (immutable)
│       │   ├── order.py              # OrderRequest, Fill, Trade
│       │   ├── position.py
│       │   └── risk.py               # RiskLimits, RiskBreach
│       │
│       ├── ingest/                   # Layer 1
│       │   ├── base.py               # IngestClient protocol
│       │   ├── mexc.py               # ccxt-based MEXC client (REST + Pro ws)
│       │   ├── coinglass.py          # httpx-based Coinglass client
│       │   ├── coingecko.py          # httpx-based CoinGecko client
│       │   ├── rate_limit.py         # aiolimiter wrappers per source
│       │   ├── retry.py              # tenacity policies per source
│       │   └── schemas.py            # Pydantic models for each API response
│       │
│       ├── storage/                  # Layer 2
│       │   ├── engine.py             # SQLAlchemy async engine + asyncpg pool
│       │   ├── hypertables.py        # DDL builders (create_hypertable, add_compression_policy)
│       │   ├── repositories/
│       │   │   ├── candles.py        # CandleRepository (bulk upsert via COPY)
│       │   │   ├── orderbook.py
│       │   │   ├── funding.py
│       │   │   ├── trades.py         # closed-strategy trades (paper + live)
│       │   │   ├── signals.py
│       │   │   ├── positions.py
│       │   │   └── universe.py
│       │   └── views/                # Continuous aggregate definitions (SQL)
│       │
│       ├── features/                 # Layer 3 — pure functions
│       │   ├── primitives/
│       │   │   ├── price.py          # rsi, divergence, vwap, atr
│       │   │   ├── derivatives.py    # funding_zscore, oi_roc, liq_cascade
│       │   │   ├── microstructure.py # ob_imbalance, trade_flow
│       │   │   └── cross_asset.py    # btc_corr, regime_flag
│       │   ├── registry.py           # FeatureRegistry maps name → callable
│       │   └── pipeline.py           # FeaturePipeline (composes primitives)
│       │
│       ├── strategies/               # Layer 4
│       │   ├── base.py               # Strategy protocol + StrategyRegistry
│       │   ├── short_after_pump/
│       │   │   ├── strategy.py       # ShortAfterPumpStrategy(Strategy)
│       │   │   ├── features.py       # Feature pipeline for this strategy
│       │   │   ├── labeling.py       # Pump detector + label generator
│       │   │   └── params.py         # Pydantic params schema
│       │   └── _scaffold/            # Template for future strategies
│       │
│       ├── ml/                       # ML training pipeline (shared, called by strategies)
│       │   ├── splits.py             # walk_forward_splits (no leakage invariant)
│       │   ├── train.py              # generic train() with MLflow logging
│       │   ├── eval.py               # metrics, calibration, SHAP
│       │   └── registry.py           # MLflow model registry wrappers
│       │
│       ├── backtest/                 # Strategy-agnostic event-driven simulator
│       │   ├── engine.py             # BacktestEngine
│       │   ├── fee_model.py          # MexcFeeModel
│       │   ├── slippage_model.py     # SlippageModel (depth-aware)
│       │   ├── portfolio.py          # SimulatedPortfolio (cash, positions, equity)
│       │   └── reports.py            # tearsheet generation via quantstats
│       │
│       ├── execution/                # Layer 5
│       │   ├── router.py             # OrderRouter protocol
│       │   ├── paper.py              # PaperOrderRouter
│       │   ├── live_mexc.py          # MexcOrderRouter (ccxt)
│       │   ├── position_tracker.py
│       │   └── reconciler.py
│       │
│       ├── risk/                     # Cross-cutting concern, called by strategy-engine
│       │   ├── guard.py              # RiskGuard
│       │   ├── kelly.py              # quarter-Kelly sizing
│       │   ├── limits.py             # RiskLimits (DB-backed)
│       │   └── kill_switch.py        # Manual + automatic kill switch
│       │
│       ├── scheduler/                # Glue
│       │   ├── jobs.py               # Job definitions (ingest, feature compute, evaluate)
│       │   └── runner.py             # APScheduler bootstrap + Postgres jobstore
│       │
│       ├── api/                      # Dashboard FastAPI
│       │   ├── app.py
│       │   ├── routes/
│       │   │   ├── health.py
│       │   │   ├── equity.py
│       │   │   ├── signals.py
│       │   │   ├── positions.py
│       │   │   └── strategies.py     # list, params, status (read-only)
│       │   └── metrics.py            # prometheus_client wire-up
│       │
│       ├── observability/
│       │   ├── logging.py            # structlog config
│       │   ├── metrics.py            # Prometheus registry
│       │   └── alerts.py             # Telegram client + severity routing
│       │
│       └── entrypoints/              # Railway service entrypoints
│           ├── data_platform.py      # service: ingest + feature compute
│           ├── strategy_engine.py    # service: signals + execution
│           ├── risk_guard.py         # service: enabled only when going live
│           └── dashboard.py          # service: FastAPI read API
│
├── tests/
│   ├── unit/
│   │   ├── domain/                   # Hypothesis-heavy: invariants on candles, signals, orders
│   │   ├── features/                 # Property tests on each primitive (rsi, divergence, ...)
│   │   ├── strategies/               # Pure-function strategy tests with synthetic data
│   │   ├── risk/                     # Kelly bounds, limit-breach behavior
│   │   └── backtest/                 # Determinism, fee/slippage correctness
│   ├── integration/
│   │   ├── storage/                  # Real Postgres+Timescale (Docker)
│   │   ├── ingest/                   # respx/aioresponses-mocked APIs
│   │   └── pipeline/                 # End-to-end ingest → storage → feature → signal
│   ├── contract/                     # Schema drift detectors: hit real APIs in nightly job
│   │   ├── test_mexc_schema.py
│   │   ├── test_coinglass_schema.py
│   │   └── test_coingecko_schema.py
│   ├── fakes/                        # In-memory implementations of every interface
│   │   ├── fake_ingest.py
│   │   ├── fake_repository.py
│   │   ├── fake_router.py
│   │   └── fake_risk_guard.py
│   └── conftest.py
│
├── notebooks/                        # EDA only — production never imports from here
│   ├── 01_universe_exploration.ipynb
│   ├── 02_pump_detector_tuning.ipynb
│   ├── 03_feature_diagnostics.ipynb
│   └── 04_labeling_decisions.ipynb
│
├── scripts/                          # One-off operational scripts
│   ├── backfill_candles.py
│   ├── rebuild_features.py
│   └── promote_paper_to_live.py
│
└── railway/                          # Railway-specific config
    ├── data-platform.toml
    ├── strategy-engine.toml
    ├── risk-guard.toml
    └── dashboard.toml
```

### Structure Rationale

- **`domain/`:** Pure types with invariants. No I/O. Every other module can import from here without circular dependency risk. Hypothesis tests live here too — invariants are domain-level (e.g., `high >= max(open, close)` is a domain invariant, not a storage concern).
- **`ingest/` + `storage/` together = data platform.** They share no code with `strategies/` or `execution/`. This is the strategy-agnostic foundation.
- **`features/primitives/`:** Strategy-agnostic library. `rsi()`, `divergence()` are reusable. **Per-strategy pipelines live inside the strategy's folder** — keeps strategy code self-contained.
- **`strategies/<name>/` is a vertical slice.** Strategy, its features, its labeling, its params, all together. Adding a new strategy = new folder, no edits elsewhere.
- **`backtest/` is strategy-agnostic.** It takes a `Strategy` instance; it doesn't know what the strategy does.
- **`execution/` and `risk/` are separate** because of process boundary (see deployment topology).
- **`entrypoints/` per Railway service.** Each is a `__main__`-style script — wires the right pieces and starts the right scheduler/server. Easy to grep what each service does.
- **`tests/fakes/`:** First-class. Every external boundary gets a fake. Hypothesis + fakes = property tests for trading invariants without ever hitting a real exchange.
- **`notebooks/` is sandbox only.** Production code never imports from notebooks. If a notebook discovers something useful, that code gets ported to `features/` or `strategies/` with tests.
- **`scripts/` for operational tools.** Backfills, one-off rebuilds, promotion gates. Idempotent.

## Architectural Patterns

### Pattern 1: Layered with Plugin Strategy Registry

**What:** Five logical layers (Ingest → Storage → Feature → Strategy → Execution). Each layer talks only to the layer directly below via interfaces. Strategies plug into the Strategy layer via a registry pattern.

**When to use:** When you have one shared data substrate and N strategies that should compose without coupling. Standard pattern in `freqtrade`, `jesse`, and most multi-strategy quant systems.

**Trade-offs:**
- + New strategy = new folder + registry entry, no edits to data layer
- + Each layer testable in isolation with fakes
- + Backtester and live execution share the same Strategy interface (same code path)
- − Slight indirection cost (registry lookup, interface dispatch); negligible at trading latencies
- − Requires discipline: don't reach across layers (`strategy/` must not import from `ingest/`)

**Example:**

```python
# src/shortfire/strategies/base.py
from typing import Protocol, runtime_checkable
from pydantic import BaseModel
import polars as pl

class StrategyParams(BaseModel):
    """Base class — each strategy subclasses with its own fields."""
    pass

class SignalIntent(BaseModel):
    """Immutable signal output. Risk layer decides sizing & whether to act."""
    instance_id: str
    symbol: str
    timestamp_utc: datetime
    direction: Literal["short", "long", "flat"]
    confidence: float  # 0..1
    suggested_sl_pct: float
    suggested_tp_pct: float
    feature_snapshot_id: str  # for replayability

@runtime_checkable
class Strategy(Protocol):
    name: str
    params_schema: type[StrategyParams]

    def features_required(self) -> list[str]:
        """List of feature primitive names from FeatureRegistry."""
        ...

    def generate_signals(
        self,
        features: pl.DataFrame,
        params: StrategyParams,
    ) -> list[SignalIntent]:
        """Pure function: features in → signals out. No I/O."""
        ...

# src/shortfire/strategies/short_after_pump/strategy.py
from shortfire.strategies.base import Strategy, SignalIntent, register_strategy

@register_strategy
class ShortAfterPumpStrategy:
    name = "short_after_pump"
    params_schema = ShortAfterPumpParams

    def features_required(self) -> list[str]:
        return [
            "rsi_1m", "rsi_5m", "rsi_1h",
            "funding_zscore_8h",
            "oi_roc_1h",
            "liq_cascade_5m",
            "pump_magnitude_1h",
        ]

    def generate_signals(self, features, params):
        # Pure function. Model.predict_proba → threshold → SignalIntent
        ...
```

### Pattern 2: Wide-Typed Hypertables, Not Universal EAV

**What:** One hypertable per `(source, dataset)` combination with explicit typed columns (e.g., `raw_mexc_candles_1m(symbol, ts, open, high, low, close, volume, n_trades)`). NOT a universal `(symbol, ts, metric_name, value)` table.

**When to use:** When you know the schema of each source upfront (we do — APIs are fixed) and you care about compression ratio + scan speed. **Always** at >100M-row scale.

**Trade-offs:**
- + 5-10× better compression than narrow EAV (no `metric_name` text column repeated billions of times)
- + 3-10× faster scans for "give me OHLCV for symbol X in time range Y" (no `WHERE metric_name IN (...)` JOIN tax)
- + Schema is self-documenting; type checker catches errors
- − Adding a new metric requires migration (acceptable — we do this rarely)
- − One hypertable per source/dataset, so 8-12 hypertables in v1 (manageable)

The narrow `(symbol, ts, metric, value)` pattern is appealing for "future-proofing" but it's a known anti-pattern at this scale: you pay a 5-10× storage tax and JOIN-tax forever to defer one migration.

**Example DDL:**

```sql
-- raw_mexc_candles_1m
CREATE TABLE raw_mexc_candles_1m (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC(20, 10) NOT NULL,
    high NUMERIC(20, 10) NOT NULL,
    low NUMERIC(20, 10) NOT NULL,
    close NUMERIC(20, 10) NOT NULL,
    volume NUMERIC(28, 10) NOT NULL,
    n_trades INTEGER,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, ts)
);
SELECT create_hypertable('raw_mexc_candles_1m', 'ts', chunk_time_interval => INTERVAL '1 day');
ALTER TABLE raw_mexc_candles_1m SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');
SELECT add_compression_policy('raw_mexc_candles_1m', INTERVAL '7 days');

-- Continuous aggregate: 5m candles from 1m
CREATE MATERIALIZED VIEW curated_mexc_candles_5m
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('5 minutes', ts) AS ts,
    first(open, ts) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, ts) AS close,
    sum(volume) AS volume,
    sum(n_trades) AS n_trades
FROM raw_mexc_candles_1m
GROUP BY symbol, time_bucket('5 minutes', ts);
```

### Pattern 3: Strategy Params in DB, Not in Code

**What:** Strategy parameters live in a `strategy_instances` table, not in YAML or Python constants. Code defines the *schema* of params (Pydantic); DB stores *values*.

**When to use:** Always, for any strategy that has more than a couple of tunable knobs and where you want to A/B test or escalate paper→live without redeploying.

**Trade-offs:**
- + Promote paper → live = `UPDATE strategy_instances SET status='live' WHERE id=...`
- + Multiple instances of the same strategy with different param sets (e.g., aggressive vs conservative)
- + Audit trail of param changes (event-sourced via `strategy_instance_history`)
- − One more thing to migrate when schema changes (acceptable; Pydantic forward-compat helps)

**Example:**

```sql
CREATE TABLE strategy_instances (
    id UUID PRIMARY KEY,
    strategy_name TEXT NOT NULL,           -- maps to StrategyRegistry
    params JSONB NOT NULL,                 -- validated against strategy.params_schema at load
    status TEXT NOT NULL CHECK (status IN ('disabled', 'paper', 'live')),
    universe_filter JSONB,                 -- e.g., {"min_24h_volume_usd": 500000}
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE strategy_instance_history (
    id UUID PRIMARY KEY,
    instance_id UUID REFERENCES strategy_instances(id),
    changed_at TIMESTAMPTZ DEFAULT now(),
    old_params JSONB,
    new_params JSONB,
    changed_by TEXT  -- 'manual' | 'optuna' | 'autopromote'
);
```

### Pattern 4: Risk Guard as Process Boundary

**What:** RiskGuard is *not* a library called from inside the strategy engine. It's an interface that lives in the same process during paper trading but moves to its own Railway service once real capital is involved.

**When to use:** Always once going live. The kill switch must be enforced even if the strategy process is hung or crashed.

**Trade-offs:**
- + Risk limits are enforced even during a strategy-engine crash loop (separate process keeps DB rows consistent)
- + Independent deployability: tweak risk limits without redeploying strategy code
- − Adds one more service to operate (only when going live — paper trading keeps it in-process)
- − Cross-process state requires DB row-level locks (use `SELECT ... FOR UPDATE` on `risk_state`)

**Example:**

```python
# Same interface, two deployment topologies:

class RiskGuard(Protocol):
    def check(self, signal: SignalIntent, current_state: RiskState) -> RiskDecision: ...
    def record_fill(self, fill: Fill) -> None: ...

# Paper trading: in-process implementation
class InProcessRiskGuard:
    def check(self, signal, state):
        # Direct logic, fast path
        ...

# Live trading: HTTP client to risk-guard service
class RemoteRiskGuard:
    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=2.0)
    async def check(self, signal, state):
        # Network hop. If risk-guard is down → REFUSE order (fail closed).
        resp = await self._client.post("/check", json=...)
        return RiskDecision.parse_obj(resp.json())
```

### Pattern 5: Pure-Function Feature Primitives + Materialized Outputs

**What:** Feature primitives are pure functions of `(input_df, params)`. Strategy-specific feature pipelines compose primitives and write the result to `features_<strategy>_v<spechash>` tables. The spec hash invalidates stale features automatically.

**When to use:** When multiple strategies share primitives but each strategy needs its own feature set. Avoids both code duplication and the heavyweight "feature store as a service" trap.

**Trade-offs:**
- + Primitives are trivially unit-testable (synthetic candles in, expected output out)
- + Feature versioning is automatic via spec hash — never accidentally backtest with new features on old labels
- + No external feature store dependency (Feast/Tecton would be overkill at solo scale)
- − Spec hash discipline required: any change to a primitive's behavior must bump its version

**Example:**

```python
# src/shortfire/features/primitives/price.py

def rsi(
    candles: pl.DataFrame,
    period: int = 14,
    column: str = "close",
) -> pl.DataFrame:
    """Pure function. Synthetic test:
       rsi([1,2,3,...]) of monotonic series → 100 at convergence.
    """
    ...

# src/shortfire/strategies/short_after_pump/features.py

from shortfire.features.primitives import rsi, funding_zscore, oi_roc

FEATURE_SPEC_VERSION = "v1"  # bump on any logic change

def compute_features(raw: RawDataBundle, params: ShortAfterPumpParams) -> pl.DataFrame:
    df = raw.candles_1m
    df = df.with_columns([
        rsi(df, period=14).alias("rsi_14_1m"),
        funding_zscore(raw.funding, window="7d").alias("funding_z_7d"),
        oi_roc(raw.oi, window="1h").alias("oi_roc_1h"),
    ])
    return df

SPEC_HASH = hashlib.sha256(
    inspect.getsource(compute_features).encode()
).hexdigest()[:12]
```

### Pattern 6: Event-Driven Backtester, Shared Across Strategies

**What:** One backtester. It accepts any `Strategy` instance and replays bars in order, calling `strategy.generate_signals()` and simulating fills via `FeeModel` + `SlippageModel`. Same code as live execution loop (same `Strategy.generate_signals` contract).

**When to use:** Always. Per-strategy backtesters are a smell — they hide differences between backtest and live (the #1 source of "edge that disappears in production").

**Trade-offs:**
- + Backtest === paper === live (same Strategy code, same Order interface)
- + Add a new strategy = it gets a backtester for free
- + Single place to fix slippage model bugs
- − Generic backtesters can't optimize for strategy-specific fast paths (acceptable at solo scale)

## Data Flow

### Ingest → Storage Flow

```
[MEXC REST/WS]  [Coinglass REST]  [CoinGecko REST]
       ↓               ↓                  ↓
[Pydantic schema validation, fail-fast on drift]
       ↓               ↓                  ↓
[tenacity retries, aiolimiter rate caps]
       ↓               ↓                  ↓
[asyncpg COPY into raw_* hypertables]   ← idempotent on (symbol, ts, source)
       ↓
[TimescaleDB compression policy (>7d), continuous aggregates auto-refresh]
       ↓
[curated_* materialized views for common queries]
```

### Signal Generation Flow (per bar close)

```
[APScheduler: cron 1m]
       ↓
[FeaturePipeline.run(strategy, latest_bars)]
       ↓
[features_<strategy>_v<hash> table updated]
       ↓
[StrategyRegistry.get(name).generate_signals(features, params)]
       ↓
[list[SignalIntent] persisted to signals table]
       ↓
[RiskGuard.check(signal, current_state) → RiskDecision]
       ↓
[OrderRouter.submit(order)]  ← paper or live
       ↓
[Fill persisted to trades_paper or trades_live]
       ↓
[PositionTracker.update(fill)]
       ↓
[Telegram alert if signal/fill in observable categories]
```

### State Management

**State that exists in the system, and where it lives:**

| State | Location | Why |
|-------|----------|-----|
| Historical candles, funding, OI, liquidations | TimescaleDB `raw_*` hypertables | Append-only, immutable, compressed |
| Active universe (today's tradable symbols) | `curated_universe_active` table | Refreshed daily, small (100s of rows) |
| Strategy instances + params | `strategy_instances` table | Mutable, low-volume, audited |
| Open positions | `positions` table | Single source of truth; reconciled with exchange every N seconds |
| Pending orders | `orders_pending` table | Cleared on fill or timeout |
| Closed trades | `trades_paper`, `trades_live` | Append-only |
| Risk limits | `risk_limits` table | Mutable, audited via `risk_limit_history` |
| Risk state (daily P&L, position count, etc.) | `risk_state` table | Updated transactionally on every fill |
| ML model artifacts | MLflow (backed by same Postgres + Railway volume for binaries) | Versioned, immutable per version |
| Feature snapshots | `features_<strategy>_v<hash>` hypertables | Versioned per spec hash; old versions kept for replayability |
| APScheduler jobs | `apscheduler_jobs` table (Postgres jobstore) | Survives process restart |

**Stateless components (can crash + restart freely):** Ingest workers, FeatureProvider, Strategy (signal generation), Dashboard API. All state is in Postgres.

**Stateful components (need careful restart):** PositionTracker (reconciles on startup), RiskGuard (reloads from `risk_state`), OrderRouter (resumes in-flight orders from `orders_pending`).

**Backup:** Railway PG automated backups (daily). Additionally: `pg_dump` to S3 weekly via scheduled script for offsite copy. MLflow artifacts on Railway volume → mirror to S3 with periodic sync.

## Deployment Topology on Railway

**Recommendation: 3 services at v1, 4 services at live launch.**

```
┌────────────────────────────────────────────────────────────────┐
│                       Railway Project                           │
│                                                                 │
│   ┌──────────────────────────────────────────────────┐         │
│   │  Service: data-platform                          │         │
│   │  Entry: entrypoints/data_platform.py             │         │
│   │  Process: APScheduler + ingest workers +         │         │
│   │           feature compute jobs                    │         │
│   │  Resources: 1 vCPU, 2GB RAM baseline             │         │
│   └─────────────────┬────────────────────────────────┘         │
│                     │                                            │
│                     ▼                                            │
│   ┌──────────────────────────────────────────────────┐         │
│   │  Service: postgres (TimescaleDB 2.18 on PG16)    │         │
│   │  Railway template + Timescale extension          │         │
│   │  Storage: starts ~10GB, grows                    │         │
│   │  Backups: daily automatic                        │         │
│   └─────────────────┬────────────────────────────────┘         │
│                     │  (via Railway private network             │
│                     │   *.railway.internal)                     │
│                     ▼                                            │
│   ┌──────────────────────────────────────────────────┐         │
│   │  Service: strategy-engine                        │         │
│   │  Entry: entrypoints/strategy_engine.py           │         │
│   │  Process: Signal generation loop + paper/live    │         │
│   │           OrderRouter + PositionTracker          │         │
│   │           + InProcessRiskGuard (until going live)│         │
│   │  Resources: 1 vCPU, 2GB RAM baseline             │         │
│   └─────────────────┬────────────────────────────────┘         │
│                     │                                            │
│                     ▼                                            │
│   ┌──────────────────────────────────────────────────┐         │
│   │  Service: dashboard                              │         │
│   │  Entry: entrypoints/dashboard.py                 │         │
│   │  Process: FastAPI + uvicorn, read-only           │         │
│   │  Resources: 0.5 vCPU, 512MB RAM                  │         │
│   │  Public domain: dashboard.yourproject.up.railway.app        │
│   └──────────────────────────────────────────────────┘         │
│                                                                 │
│   --- Added at live launch only: ---                            │
│                                                                 │
│   ┌──────────────────────────────────────────────────┐         │
│   │  Service: risk-guard                             │         │
│   │  Entry: entrypoints/risk_guard.py                │         │
│   │  Process: FastAPI exposing /check, /halt,        │         │
│   │           /resume; owns kill switch              │         │
│   │  Resources: 0.5 vCPU, 512MB RAM                  │         │
│   │  Reachable only via private network              │         │
│   └──────────────────────────────────────────────────┘         │
└────────────────────────────────────────────────────────────────┘
```

**Rationale for 3-service split (not monolith, not microservices):**

| Service | Why separate? | Why not split further? |
|---------|---------------|------------------------|
| `data-platform` | Ingest crashes or schedule misses can't take down execution. Different release cadence (ingest changes often; execution rarely). | Splitting per-source (MEXC vs Coinglass vs CoinGecko) would triple Railway billing for no isolation benefit. |
| `strategy-engine` | Holds open positions; needs stable uptime. Different memory profile (loads ML models). | At v1, signal + paper-execution + position-tracking all share state; splitting adds coordination overhead without isolation benefit. |
| `dashboard` | Public-facing; serves traffic. Different scaling profile. Bug here shouldn't crash trading. | One dashboard is plenty for a solo tool. |
| `risk-guard` (live only) | Must remain available even if strategy-engine crashes. Kill switch must be enforceable independently. | Splitting kill switch from risk check duplicates DB lock concerns. |

**Why not monolith (all-in-one process):** A crash in feature computation must not kill open-position monitoring. Memory leak in MLflow logging must not cause OOM on the position-reconciler. **Process boundaries enforce blast-radius limits.**

**Why not full microservices:** Each Railway service has fixed baseline cost. Solo budget says 3-4 services is the ceiling; deeper splits buy nothing operationally.

**Inter-service communication:**

- All services read/write via TimescaleDB on Railway's private network (`postgres.railway.internal`).
- `risk-guard` (when live) exposes HTTP on internal network only (`risk-guard.railway.internal`).
- No Kafka, no Redis Streams, no message bus. The DB is the message bus at this scale.
- For high-frequency in-process plumbing (websocket frames → candle aggregator), use `asyncio.Queue` with bounded size — back-pressure into ingest if storage falls behind.

**Why Postgres is the message bus and that's fine:**
- Trading happens at second-to-minute cadence; Postgres LISTEN/NOTIFY + polling is more than enough.
- One less service to run, one less failure mode.
- Migrate to a real broker only if event volume > 10k/sec — won't happen.

## Multi-Strategy Framework — Concrete Design

**The contract every strategy honors:**

```python
class Strategy(Protocol):
    name: str                            # unique, lowercase_snake_case
    params_schema: type[StrategyParams]  # Pydantic class for params validation

    def features_required(self) -> list[FeatureSpec]:
        """Declares which feature primitives this strategy needs.
        Returned specs are validated against FeatureRegistry at startup."""

    def generate_signals(
        self,
        features: pl.DataFrame,
        params: StrategyParams,
        context: StrategyContext,  # current positions, capital tier, regime
    ) -> list[SignalIntent]:
        """PURE function. No I/O. No DB. No randomness without seeded RNG.
        Deterministic given same inputs."""

    def position_sizing_hint(
        self,
        signal: SignalIntent,
        params: StrategyParams,
        context: StrategyContext,
    ) -> PositionSizingHint:
        """Optional override of default quarter-Kelly sizing."""
```

**Strategy lifecycle (5 stages):**

1. **Registered** — class exists and is decorated with `@register_strategy`. Discovered at startup.
2. **Configured** — at least one row exists in `strategy_instances` with `status='disabled'` and validated params.
3. **Paper** — `status='paper'`. Generates signals; orders go to `PaperOrderRouter` and `trades_paper`. Equity tracked but no real capital.
4. **Live (signal-only)** — `status='live'`, `autonomy='signal_only'`. Generates signals; Telegram alerts; no orders submitted.
5. **Live (semi-auto)** — `status='live'`, `autonomy='semi_auto'`. Telegram confirm-button before order submission.
6. **Live (full-auto)** — `status='live'`, `autonomy='full_auto'`. Direct submission.

**Adding a new strategy = 4 things, in this order:**

```
1. New folder:   src/shortfire/strategies/<new_strategy>/
                 ├── strategy.py    (class with @register_strategy)
                 ├── features.py    (compute_features function)
                 ├── labeling.py    (if ML-based)
                 └── params.py      (Pydantic params schema)

2. New tests:    tests/unit/strategies/<new_strategy>/
                 + property tests with synthetic data
                 + signal determinism test

3. New row:      INSERT INTO strategy_instances (...) VALUES (..., 'disabled')

4. Promote:      Disabled → paper → live, gated on TDD + backtest + paper trading metrics
```

**No changes required to:** ingest layer, storage layer, FeatureProvider primitives (unless new primitive needed), backtester, OrderRouter, RiskGuard, dashboard.

## Build Order

The build order is shaped by **TDD discipline + dependency chain + Phase 0 = data first**.

```
Phase 0: Foundation
─────────────────────────────────────────────────────────────
  1. Repo + uv + ruff + pyright + pytest scaffold
  2. Railway project + Postgres+Timescale service
  3. Alembic + hypertable DDL migration tooling
  4. CI/CD: GitHub Actions → push → Railway auto-deploy
  5. Domain types (Candle, OrderBook, Funding, Signal, Order, Position)
     + Hypothesis property tests on every invariant
  6. Observability skeleton (structlog, prometheus_client, /metrics endpoint)

Phase 1: Data Platform (strategy-agnostic, ship this fully)
─────────────────────────────────────────────────────────────
  7. IngestClient interface + Pydantic schemas for all 3 sources
  8. Fakes for all 3 ingest clients (tests/fakes/)
  9. Storage repositories (CandleRepo, FundingRepo, ...) with COPY-based bulk insert
 10. MexcIngest concrete impl (ccxt REST first, websocket later)
 11. CoinglassIngest concrete impl
 12. CoinGeckoIngest concrete impl (universe filter)
 13. APScheduler bootstrapped in data-platform service
 14. Backfill scripts (idempotent, resumable)
 15. Continuous aggregates for 5m/15m/1h/4h candles
 16. Data freshness monitoring + Telegram alerts on stale data
 17. data-platform service deploys to Railway

Phase 2: Feature Layer + EDA (strategy-agnostic + strategy-specific)
─────────────────────────────────────────────────────────────
 18. FeatureProvider primitives library (rsi, divergence, funding_z, oi_roc,
     liq_cascade, vwap, btc_corr) — each with property tests
 19. Jupyter notebooks for EDA (pump distributions, feature diagnostics)
 20. Pump detector + labeling decision (Phase 2 deliverable per PROJECT.md)
 21. Short-after-pump feature pipeline (compute_features function)

Phase 3: Strategy + Backtester (strategy framework + first strategy)
─────────────────────────────────────────────────────────────
 22. Strategy protocol + StrategyRegistry
 23. strategy_instances + signals + trades_paper schema
 24. Generic event-driven backtester (FeeModel, SlippageModel, Portfolio)
 25. ShortAfterPumpStrategy implementation
 26. ML training pipeline (walk_forward_splits, train, eval, MLflow logging)
 27. SHAP + feature importance reports
 28. Backtest results dashboard (equity curve, drawdown, win rate, EV)

Phase 4: Paper Trading
─────────────────────────────────────────────────────────────
 29. PaperOrderRouter + InProcessRiskGuard + PositionTracker
 30. strategy-engine service deploys to Railway
 31. Dashboard service: read-only API + simple SSR HTML or minimal SPA
 32. Telegram bot: signal alerts, daily equity summary
 33. 1-2 months paper trading (PROJECT.md hard gate)

Phase 5: Live Trading (gated on paper performance)
─────────────────────────────────────────────────────────────
 34. RemoteRiskGuard impl + risk-guard service
 35. MexcOrderRouter (live) with reconciler
 36. Kill switch (manual via Telegram + automatic on limit breach)
 37. Capital-tier-aware position sizing (adapt to current balance)
 38. Staged autonomy: signal_only → semi_auto → full_auto

Phase 6+: Additional Strategies
─────────────────────────────────────────────────────────────
 Future strategies plug into Phase 3 framework with the 4-step recipe above.
```

**Hard dependencies (must build in this order):**
- Foundation → Data Platform (need DB + CI before ingest)
- Data Platform → Feature Layer (no features without raw data)
- Feature Layer → Strategy + Backtester (strategy needs features)
- Strategy + Backtester → Paper Trading (paper trading is backtester + live data)
- Paper Trading → Live Trading (PROJECT.md gate)

**Soft dependencies (can parallelize):**
- Observability can grow alongside any phase
- Dashboard can start as a stub in Phase 1 and expand each phase
- ML primitives library can be developed alongside features layer

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| **v1 (solo, 200-500 symbols, 1m candles + funding + OI)** | All 3 services on Railway with 1-2GB RAM each. TimescaleDB single instance. Native compression on chunks >7 days. Continuous aggregates for 5m/15m/1h/4h. Expected: ~50-200M rows/year, ~10-50GB on disk compressed. |
| **2-5× scale (full L2 orderbook, 1s trades archive)** | Move L2 orderbook to its own hypertable with aggressive compression (`segmentby=symbol, orderby=ts DESC`). Drop trades after 30 days into archive table on cold storage. Add a second `data-platform` service for orderbook-only ingest. |
| **10× scale (multiple exchanges, multi-strategy production)** | Migrate to Timescale Cloud tiered storage to S3 (Phase 3+ in STACK.md). Split `strategy-engine` per strategy if memory profiles diverge (e.g., heavy PyTorch model in one strategy). Add Redis for cross-process pub/sub. |
| **100× scale (institutional)** | Out of scope per PROJECT.md (solo tool). Would require: ClickHouse for analytics layer, Kafka for ingest, separate model-serving service, multi-exchange execution router. |

### Scaling Priorities (what breaks first)

1. **CoinGecko free tier rate limit** — 30 req/min becomes the bottleneck on daily universe refresh as the universe grows. Fix: aggressive caching + paid Demo tier upgrade.
2. **Coinglass historical depth** — STACK.md notes no tier gives >180 days of 1m. Fix: accept rolling-window features OR upgrade to Standard.
3. **TimescaleDB write throughput on 1s orderbook snapshots** — if you start storing full L2 every second. Fix: sample less often (every 5s for active universe), use `asyncpg.copy_records_to_table` (already in stack).
4. **MLflow artifact storage on Railway volume** — grows with every backtest run. Fix: prune old runs, or mirror to S3.
5. **Backtest wall-clock time** — once feature set + universe grows. Fix: parallelize per-symbol backtests with `joblib.Parallel(n_jobs=-1)`; consider polars-native backtester rewrite.

## Anti-Patterns

### Anti-Pattern 1: Universal `(symbol, ts, metric_name, value)` EAV Schema

**What people do:** "Future-proof" their time-series schema by storing every value as a row with a `metric_name` column.

**Why it's wrong:** 5-10× storage tax (the string `metric_name` repeated billions of times, even with TimescaleDB compression). Every query needs `WHERE metric_name IN (...)` or self-joins to assemble OHLCV. Slow scans, slow aggregates, slow features. Becomes catastrophic at 500+ symbols × 1m × multiple metrics.

**Do this instead:** Typed-per-source hypertables (one per `(source, dataset)`). Add new columns with Alembic migrations when new metrics arrive — happens rarely enough that it's fine.

### Anti-Pattern 2: Feature Store as a Separate Service

**What people do:** Adopt Feast / Tecton / Hopsworks for a single-developer trading bot.

**Why it's wrong:** Feature stores solve a problem (online + offline parity across many teams) that doesn't exist for a solo developer. Adds an entire ops surface, a separate read path, and another DB. The benefit (offline/online consistency) is trivially solved by writing features to a Postgres table and reading from the same table in backtest and live.

**Do this instead:** `features_<strategy>_v<hash>` Postgres tables. Spec-hash-versioned. Same query path for backtest and live. Reconsider only if you're running 10+ strategies sharing 50+ features.

### Anti-Pattern 3: Strategy Code That Reaches Into Storage Directly

**What people do:** `from shortfire.storage.repositories.candles import CandleRepo` inside strategy code.

**Why it's wrong:** Couples strategy logic to DB layout. Backtester and live must read from the same source (the `features_*` table). Strategy code that reaches into `raw_*` tables is reading the wrong thing and will silently use unfiltered/un-curated data.

**Do this instead:** Strategy code receives a `pl.DataFrame` of features (passed by the orchestrator). It never knows where the features came from.

### Anti-Pattern 4: Mixing Backtest and Live Code Paths

**What people do:** Separate `backtest_strategy()` and `live_strategy()` functions. Or worse: a `if live: ... else: ...` branch inside the signal generator.

**Why it's wrong:** Edge that exists in backtest disappears in live (or worse, edge that doesn't exist in backtest seems to exist in live = lucky live trades). The whole point of backtesting is to predict live behavior. **Different code paths break that contract.**

**Do this instead:** Strategy.generate_signals is called identically in backtest and live. Only the `OrderRouter` and the data source (historical vs streaming) differ. Both feed into the same `Strategy` interface.

### Anti-Pattern 5: Risk Logic Inside Strategy Logic

**What people do:** Strategy.generate_signals checks "do I already have a position in this symbol?" and short-circuits.

**Why it's wrong:** Strategy logic gets tangled with position state. Hard to test (strategy now has I/O dependency). Risk limits change → strategy code must change.

**Do this instead:** Strategy emits `SignalIntent` regardless of current state. RiskGuard, called between Strategy and OrderRouter, decides what to do given current state and limits. Strategy stays pure.

### Anti-Pattern 6: Fire-and-Forget asyncio Tasks

**What people do:** `asyncio.create_task(do_something())` and never hold a reference.

**Why it's wrong:** Python may GC the task mid-flight. Silent failures destroy bots overnight. STACK.md flagged this.

**Do this instead:** `asyncio.TaskGroup` (Python 3.11+) for structured concurrency. Hold task references. Use `done_callback` to log exceptions.

### Anti-Pattern 7: Notebooks Imported by Production Code

**What people do:** Promote a notebook function by importing it directly.

**Why it's wrong:** Notebooks have no tests, no versioning, and Jupyter's `%run` magic. Production code depending on `notebooks/eda.ipynb` is undebuggable.

**Do this instead:** Notebooks are sandbox. Useful code gets ported to `src/shortfire/features/` or `src/shortfire/strategies/` with tests. Notebook is then dead — delete or archive.

### Anti-Pattern 8: Single API Key with Withdraw Permission

**What people do:** One MEXC API key with all permissions, used for ingest and execution.

**Why it's wrong:** A compromised ingest service (perhaps via a logging bug) leaks the withdraw permission. STACK.md flagged this.

**Do this instead:** Three keys: read-only (ingest), trade-no-withdraw (execution), no key in dashboard. Different env vars per Railway service.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| MEXC REST + WS | `ccxt 4.5.x` unified API; pin minor version | Use `watch_trades()` + client-side OHLCV build, not `watch_ohlcv()` (STACK.md). Three separate API keys. |
| Coinglass REST | `httpx.AsyncClient` + `aiolimiter` (80 req/min Startup) | Pydantic schema validation on every response; alert on schema drift. Cache funding data with TTL = funding interval. |
| CoinGecko REST | `httpx.AsyncClient` + `aiolimiter` (30 req/min Demo) | Used only for daily universe refresh; cache hard. |
| Railway PostgreSQL+Timescale | `asyncpg` for hot-path COPY, `psycopg` v3 + SQLAlchemy 2.x for everything else | Connection pool size: 5 per service. Use `pgbouncer`-style pooling if connection count grows. |
| MLflow | Self-hosted, same Postgres backend | Artifacts on Railway volume; periodic sync to S3. |
| Grafana Cloud | Prometheus scrape from `/metrics` endpoint on each Railway service | Free tier sufficient. Loki for log aggregation via Railway log drain. |
| Telegram Bot API | `python-telegram-bot` 21.x | Single bot, multiple channels: `#signals`, `#alerts`, `#kill-switch`. Polling mode (no webhook needed). |
| Sentry | Auto-init at process start; captures uncaught exceptions | Free tier (5k errors/mo). |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| ingest → storage | Direct: `Repository.bulk_insert(records)` via asyncpg | Synchronous within data-platform process |
| storage → feature compute | Direct: query `raw_*` via SQLAlchemy | Synchronous; results in `pl.DataFrame` |
| feature compute → strategy | Direct: pass `pl.DataFrame` to `strategy.generate_signals()` | Pure function; no I/O across this boundary |
| strategy → risk guard (paper) | In-process: `InProcessRiskGuard.check(...)` | Synchronous, microseconds |
| strategy → risk guard (live) | HTTP: `httpx.post("risk-guard.railway.internal/check")` | Synchronous, 1-10ms; fail-closed on timeout |
| risk guard → order router | Direct (paper) or HTTP (live, if router is its own service later) | Always synchronous; orders are not deferred |
| All services ↔ Postgres | `asyncpg` / `psycopg` v3 via Railway private network | TLS in production |
| Services → Prometheus | Pull: each service exposes `/metrics` on its public port (or private if dashboard) | Grafana Cloud scrapes |
| Services → Telegram | Push: `python-telegram-bot` async client | Bounded queue with overflow alert |

## TDD-Friendly Boundaries

Every external boundary has an interface + a fake. Strategy and risk logic is pure-function. Hypothesis property tests on every invariant.

| Interface | Fake (tests) | Real impl | Property tests |
|-----------|--------------|-----------|----------------|
| `IngestClient` | `FakeMexcClient` (returns canned candles) | `MexcIngest` (ccxt) | "every candle has high >= max(open, close)" |
| `Repository[Candle]` | `InMemoryCandleRepo` | `PostgresCandleRepo` | "bulk_insert is idempotent on (symbol, ts)" |
| `FeatureProvider.rsi` | (no fake; pure function) | the function itself | "rsi of monotonic series → 100" |
| `Strategy` | (no fake; protocol) | `ShortAfterPumpStrategy` | "same input → same signals (deterministic)" |
| `OrderRouter` | `FakeOrderRouter` (records orders) | `PaperOrderRouter`, `MexcOrderRouter` | "submitted size never exceeds risk-approved size" |
| `RiskGuard` | `FakeRiskGuard` (configurable allow/deny) | `InProcessRiskGuard`, `RemoteRiskGuard` | "concurrent daily losses can't exceed limit" |
| `PositionTracker` | `InMemoryPositionTracker` | `PostgresPositionTracker` | "sum of fills equals current position" |
| `FeeModel` | (no fake; pure function) | `MexcFeeModel` | "fee is monotonic in size" |
| `SlippageModel` | (no fake; pure function) | `DepthAwareSlippageModel` | "slippage is non-negative and monotonic in size" |

Backtester tests: replay the same window twice → bit-identical results. Property test on `BacktestEngine(strategy, window) == BacktestEngine(strategy, window)`.

## Sources

- [Tiger Data — Best Practices for Time-Series Data Modeling (narrow vs wide)](https://www.tigerdata.com/learn/best-practices-time-series-data-modeling-single-or-multiple-partitioned-tables-aka-hypertables) — HIGH (vendor docs)
- [Timescale Docs — Narrow data model tradeoffs](https://docs.timescale.com/timescaledb/latest/overview/data-model-flexibility/narrow-data-model/) — HIGH
- [Tiger Data — Best Practices for Metadata Tables](https://www.tigerdata.com/learn/best-practices-for-time-series-metadata-tables) — HIGH
- [TimescaleDB issue #1616 — One huge table or many smaller hypertables?](https://github.com/timescale/timescaledb/issues/1616) — HIGH (maintainer guidance)
- [Railway Docs — Deploying a Monorepo](https://docs.railway.com/guides/monorepo) — HIGH
- [Railway Docs — Deploy a FastAPI App](https://docs.railway.com/guides/fastapi) — HIGH
- [Railway Docs — Pricing](https://docs.railway.com/pricing) — HIGH
- [Railway Docs — Services](https://docs.railway.com/services) — HIGH
- [freqtrade — Free, open source crypto trading bot (architecture reference)](https://github.com/freqtrade/freqtrade) — HIGH (community-validated)
- [Jesse — Crypto trading bot framework (multi-strategy pattern)](https://github.com/jesse-ai/jesse) — HIGH
- [Medium — Multi-layer architecture to backtest a trading strategy](https://eveince.medium.com/the-backtesting-platform-the-architecture-and-its-requirements-6d710dded956) — MEDIUM (third-party tutorial)
- [Medium — Data Pipeline Design in an Algorithmic Trading System](https://medium.com/@edwinsalguero/data-pipeline-design-in-an-algorithmic-trading-system-ac0d8109c4b9) — MEDIUM
- [Medium — Designing a Production-Style Algorithmic Trading Platform](https://medium.com/@kaur.exe/designing-a-production-style-algorithmic-trading-platform-5dc326faacc8) — MEDIUM
- [QuantStart — Best Programming Language for Algorithmic Trading Systems (separation of concerns)](https://www.quantstart.com/articles/Best-Programming-Language-for-Algorithmic-Trading-Systems/) — MEDIUM
- [.planning/research/STACK.md (this project)](.planning/research/STACK.md) — HIGH (already-decided stack constraints)
- [.planning/PROJECT.md (this project)](.planning/PROJECT.md) — HIGH (project context, gates, autonomy escalation)

---
*Architecture research for: crypto futures ML trading on Railway (solo, TDD-first, multi-strategy)*
*Researched: 2026-05-21*
