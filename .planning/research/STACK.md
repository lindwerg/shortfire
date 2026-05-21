# Stack Research

**Domain:** Crypto futures ML trading system (MEXC perpetuals + Coinglass + CoinGecko) on Railway
**Researched:** 2026-05-21
**Confidence:** HIGH for core stack (Python/FastAPI/Postgres/TimescaleDB/ccxt/XGBoost/MLflow); MEDIUM for orchestration choice and MEXC websocket reliability; KNOWN-RISK on Coinglass tier requirements

## Executive Summary

This is a **solo, Python-only, Railway-deployed quant trading stack** built around four uncontroversial defaults that compress operational surface area to what one person can maintain:

1. **FastAPI + asyncio + httpx** for everything HTTP (REST clients, signal/control API, paper trading webhooks).
2. **PostgreSQL 16 + TimescaleDB 2.18+** on Railway as the single time-series + relational store. ClickHouse stays a Phase-3+ fallback if hypertable compression ratios stop being good enough.
3. **ccxt (REST + Pro websockets) 4.5.x** as the single exchange interface for MEXC — same client for ingest, paper, and live execution. Avoid hand-rolled MEXC SDKs.
4. **Polars 1.40+ for batch feature engineering and bulk reads; pandas 2.x for sklearn/XGBoost interop** (XGBoost still consumes pandas/numpy natively; convert at the boundary).

The expensive decisions are: paying **Coinglass Startup ($79/mo) minimum** to get usable 1m derivatives history, and accepting that **NautilusTrader is NOT v2-stable yet** — so backtesting starts with a custom event-driven simulator using ccxt's MEXC fee/precision model, and we evaluate Nautilus only after the strategy proves out.

For ML: **XGBoost 3.2 as primary, LightGBM 4.6 as secondary, Optuna 4.x for tuning, MLflow 3.x for tracking** — all self-hosted (MLflow against the same Postgres). PyTorch is explicitly Phase 3+, gated on baseline edge.

For orchestration: **APScheduler 4.x inside the FastAPI app for v1** (solo simplicity, no extra service). Migrate to **Prefect 3.x self-hosted on Railway** only if/when retries, async dependencies, and observability outgrow a single scheduler process.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12.x | Runtime | 3.13 has free-threaded mode but library ecosystem (pandas, polars, xgboost wheels) is still tested primarily on 3.12. Switching to 3.13 buys nothing for our workload. Hard-floor: 3.11 (FastAPI 0.130+ dropped 3.9, ccxt async drops 3.10 cleanly). |
| FastAPI | 0.115+ | API layer (signals, control, healthcheck) | Async-native, Pydantic v2 validation (50x faster than v1), best-in-class OpenAPI. Standard for new Python APIs in 2026. |
| uvicorn | 0.42+ | ASGI server | Production-ready standalone in 2026 — Gunicorn wrapper no longer required for single-instance Railway deploys. Use `uvicorn main:app --workers $(nproc)` directly. |
| Pydantic | 2.7+ | Schema validation at all system boundaries | Mandatory for FastAPI; also use for API response models (MEXC/Coinglass/CoinGecko) to fail-fast on schema drift. |
| PostgreSQL | 16.x | Primary relational store (trades, strategy state, MLflow backend, run metadata) | Railway's managed offering; rock-solid; ACID for execution state. |
| TimescaleDB | 2.18+ (PG16) | Hypertables for candles, funding, OI, liquidations, order book snapshots | Single managed database covers both relational AND time-series. Hypercore hybrid row/columnar compression reaches 10-20x on candle data. **56x faster small-batch insert throughput than ClickHouse at typical ingest sizes** — critical for streaming MEXC trades. Native PG = no separate ops surface. |
| ccxt | 4.5.54+ | MEXC REST + websocket (unified API) | Industry standard; same client works for spot/swap/futures/historical/live/paper. MEXC is "supported" tier (not "certified") — see Pitfalls. Pay attention to recent MEXC swap order endpoint fix (#28532, May 2026). |
| httpx | 0.27+ | Direct REST client for Coinglass + CoinGecko (no good unified library exists) | Async-native, HTTP/2, identical sync/async API. Avoid `requests` (sync-only) and `aiohttp` (more surface area, no sync). |
| Polars | 1.40+ | Batch feature engineering, bulk historical reads, Parquet I/O | 5-30x faster than pandas on >1GB workloads. Streaming engine for backfill. Lazy API for feature pipelines. |
| pandas | 2.2.x | sklearn/XGBoost/MLflow interop boundary; small ad-hoc analysis | XGBoost.DMatrix/sklearn still expect pandas/numpy. PyArrow backend closes most performance gaps for sub-GB work. Convert Polars→pandas only at the model boundary. |
| NumPy | 2.x | Underlying numerics | Polars + pandas 2.x + XGBoost 3.2 + scikit-learn 1.5+ all NumPy 2.x compatible as of 2026. |
| XGBoost | 3.2.0 | Primary baseline gradient booster | More forgiving defaults than LightGBM near tuned ceiling; level-wise growth is stable for walk-forward. Best documented for finance use cases. SHAP integration excellent. |
| LightGBM | 4.6.x | Secondary baseline for ensembling and speed comparison | Faster leaf-wise growth on large feature matrices. Use when XGBoost wall-clock becomes a bottleneck during hyperparam sweeps. |
| scikit-learn | 1.5+ | LogisticRegression baseline, pipelines, metrics, TimeSeriesSplit | LogisticRegression baseline is non-negotiable — must beat it before trusting boosters. |
| Optuna | 4.x | Hyperparameter optimization | Beats Hyperopt: ~35% faster on LightGBM tuning; better pruning, better study persistence (SQLite/Postgres). Native walk-forward via `TimeSeriesSplit` callbacks. |
| MLflow | 3.x | Experiment tracking, model registry, run lineage | Self-hosted against same Postgres. 100% free. Better than W&B for solo because no SaaS dependency. Has model registry built-in. |
| APScheduler | 4.x | In-process cron + interval scheduling for v1 ingest | Single process, no extra service, persistent jobs via Postgres jobstore. Sufficient until DAG dependencies emerge. |
| SQLAlchemy | 2.x | ORM for relational tables (strategy runs, positions, signals); raw SQL for hypertable writes | 2.x async support is mature. **Use Core (not ORM) for hot-path hypertable inserts** — ORM overhead matters at 1k+ rows/sec. |
| Alembic | 1.13+ | Schema migrations | TimescaleDB-aware (use `op.execute()` for `create_hypertable`, continuous aggregates, compression policies). |
| pytest | 8.x | Test framework | Industry standard; auto-async via pytest-asyncio. |
| pytest-asyncio | 0.24+ | Async test support | Use auto mode in `pyproject.toml` to drop per-test markers. |
| Hypothesis | 6.x | Property-based testing for invariants | Mandatory for trading code: balance invariants, no-data-leakage assertions, slippage bounds, order sizing invariants. |
| Ruff | 0.6+ | Linter + formatter (replaces Black + isort + flake8) | Single tool, 100x faster, zero config debates. |
| mypy or pyright | latest | Type checking | Strict mode in CI; pyright if you want speed, mypy if you want maturity. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tenacity` | 9.x | Retry decorators (exponential backoff, jitter) | Wrap every external API call (MEXC, Coinglass, CoinGecko). Stateful retries persist via Postgres for long-lived ingest jobs. |
| `aiolimiter` | 1.2+ | Async rate limiting (token bucket) | Coinglass Startup = 80 req/min, CoinGecko free = 30/min → must rate-limit client-side. ccxt has its own throttler for MEXC. |
| `orjson` | 3.10+ | Fast JSON parsing | MEXC websocket frames are large; orjson is 2-5x faster than stdlib `json` and used by FastAPI internally. |
| `structlog` | 24.x | Structured JSON logging | Required for parsable logs in Grafana/Loki; trading bugs need replayable context. |
| `pydantic-settings` | 2.x | Environment-variable config | Validate all Railway env vars at startup; fail-fast on missing API keys. |
| `python-dotenv` | 1.x | Local dev only | Loaded conditionally — Railway injects env vars directly in production. |
| `pandas-ta` or `ta-lib` (python) | latest | TA indicators (RSI, MACD, BB, ATR) | `pandas-ta` is pure Python (easy install, slower); TA-Lib is C-based (fast, install pain). Default `pandas-ta` for v1 — speed isn't bottleneck on 1m candles. |
| `pyarrow` | 17.x | Parquet I/O, Polars/pandas backend | Mandatory for fast Polars↔pandas conversion (`use_pyarrow=True`); Parquet for offline feature snapshots. |
| `python-telegram-bot` | 21.x | Telegram alerts for signals + fatal errors | Async-native; uses asyncio. Phase-1 critical channel for solo operator. |
| `shap` | 0.45+ | Feature importance + per-trade attribution | After model trains, MUST be able to explain why each signal fired. Critical for trust before going live. |
| `quantstats` | 0.0.6x | Tearsheets (Sharpe, Calmar, drawdowns, exposure) | Use for paper-trading and backtest reports. Pairs with custom event-driven backtester. |
| `freezegun` | 1.5+ | Time mocking in tests | Time-zone bugs and funding-window bugs are everywhere in crypto. Wrap every time-sensitive test. |
| `respx` | 0.21+ | httpx mocking (not `responses`, which is for `requests`) | Mock Coinglass + CoinGecko in tests deterministically. |
| `aioresponses` | 0.7+ | aiohttp mocking (ccxt's underlying transport) | Mock MEXC API responses in tests. |
| `psycopg` (v3) | 3.2+ | Postgres driver | v3 is async-native; v2 (`psycopg2`) is legacy. SQLAlchemy 2.x speaks both. |
| `asyncpg` | 0.30+ | Alternative Postgres driver (faster, lower-level) | Use for raw COPY-based hypertable bulk inserts when SQLAlchemy overhead matters. |
| `loguru` *(alternative to structlog)* | 0.7+ | Simpler logging API | Pick ONE of structlog vs loguru and stick with it. structlog is more standard for structured-JSON-first shops. |
| `prometheus-client` | 0.21+ | `/metrics` endpoint for Grafana | Expose: API call counts, latency histograms, signal counts, paper-trading P&L, model staleness. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Ruff | Lint + format | `tool.ruff` in `pyproject.toml`; rules: E, F, I, B, UP, SIM, ASYNC, PERF. |
| pyright (or mypy --strict) | Type checking | CI gate; `reportMissingTypeStubs = "warning"`. |
| pytest + pytest-asyncio + pytest-cov + hypothesis | Test stack | 80%+ coverage gate; `pytest --asyncio-mode=auto`. |
| pre-commit | Git hooks | Ruff + pyright + pytest-fast subset before each commit. |
| `uv` | Package manager + venv | 10-100x faster than pip + virtualenv; lockfile-based (`uv.lock`); replaces poetry/pip-tools combo. **Recommended over poetry in 2026.** |
| GitHub Actions | CI/CD | `python -m uv sync` → ruff → pyright → pytest → push to Railway. Railway auto-deploys on `main`. |
| Railway CLI | Deploy + secrets management | `railway run` for local execution with prod env; `railway logs` for streaming. |
| Grafana Cloud (free tier) | Dashboards + alerts | 10K series / 50GB logs / 14-day retention is enough for a solo bot. Scrapes Prometheus endpoint from Railway-exposed service. |
| Sentry (free tier) | Error tracking | Catches unhandled exceptions in async tasks that Railway logs alone miss. |
| Jupyter Lab | EDA only | Notebooks live in `notebooks/` — production code never imports from there. |

## Installation

```bash
# Project bootstrap (uv replaces pip+poetry in 2026)
uv init --python 3.12
uv add fastapi uvicorn[standard] pydantic pydantic-settings httpx orjson \
       sqlalchemy[asyncio] psycopg[binary,pool] alembic asyncpg \
       ccxt aiolimiter tenacity \
       polars pandas pyarrow numpy \
       xgboost lightgbm scikit-learn optuna mlflow shap \
       pandas-ta quantstats \
       apscheduler structlog prometheus-client \
       python-telegram-bot

# Dev dependencies
uv add --dev pytest pytest-asyncio pytest-cov hypothesis freezegun \
             respx aioresponses \
             ruff pyright pre-commit \
             jupyterlab ipykernel
```

**Pinned constraints to add to `pyproject.toml`:**
```toml
[project]
requires-python = ">=3.12,<3.13"

[tool.uv]
constraint-dependencies = [
    "numpy>=2.0",
    "pandas>=2.2",
    "polars>=1.40",
    "ccxt>=4.5.54",
    "xgboost>=3.2",
    "lightgbm>=4.6",
]
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| TimescaleDB on Railway | **ClickHouse on Railway** | If row count crosses ~500M and query latency on 1m candle aggregates > 1s on TimescaleDB even after compression + continuous aggregates. ClickHouse gives 3-10x query speedup on heavy aggregates. Operational cost: separate service, separate ingest path, separate query language. Defer this migration to Phase 3+ if it happens. |
| TimescaleDB on Railway | **TigerData (Timescale Cloud)** | If you outgrow Railway's PG instance sizes or want managed PITR backups, continuous aggregates dashboard, and tiered storage to S3. ~$20-50/mo minimum. Not required for v1. |
| TimescaleDB on Railway | **DuckDB + Parquet on Railway volume** | If ingest pipeline is purely batch (no real-time websocket needs) and you want zero database ops. DuckDB queries Parquet directly; great for backtest-only mode. **Bad fit here** — we need real-time funding rate writes for live signals. |
| ccxt | **python-mexc-sdk** (community, e.g., `mexc-api`) | Never preferred — single-exchange SDKs are inconsistently maintained, and you lose paper/live symmetry. Acceptable only if you hit a specific MEXC contract endpoint that ccxt's `mexc` class doesn't unify. Even then, prefer **ccxt's `mexc.private_*` implicit methods** before bringing in a second SDK. |
| ccxt | **Raw `httpx` against MEXC** | Only for endpoints ccxt doesn't expose AND ccxt's implicit API can't reach. Costs you signing, rate-limiting, and reconnect logic that ccxt provides. |
| ccxt Pro (websockets) | **`cryptofeed`** | If you need >5 exchanges simultaneously with normalized output. For MEXC-only, ccxt Pro is simpler and shares config with REST client. cryptofeed's MEXC futures support has historically lagged. |
| ccxt Pro (websockets) | **Raw `websockets` library** | Only if ccxt Pro proves unreliable on MEXC futures streams. Then you write your own reconnect + ping-pong + replay-from-snapshot logic — substantial work; avoid. |
| Polars (batch) | **DuckDB (in-process)** | DuckDB is excellent for SQL-based feature engineering on Parquet. Use it for ad-hoc EDA queries; keep Polars for the production pipeline (single API, no SQL surface). |
| pandas (model boundary) | **All-Polars pipeline** | When XGBoost adds first-class Polars support (in progress 2026). Today, `polars.DataFrame.to_pandas(use_pyarrow_extension_array=True)` is fine. |
| XGBoost | **LightGBM** | When training time becomes the bottleneck on >1M-row feature matrices. LightGBM's leaf-wise growth is faster but easier to overfit; needs `num_leaves` and `min_data_in_leaf` discipline. |
| XGBoost | **CatBoost** | If categorical features (symbol, hour-of-day, weekday) start dominating feature importance. CatBoost handles them natively without one-hot blowup. Acceptable Phase 2 ensemble member. |
| Optuna | **scikit-learn's HalvingGridSearchCV** | For quick sanity checks. Optuna's TPE sampler + median pruner is the production default. |
| MLflow (self-hosted) | **Weights & Biases free tier** | If you want better UI for sweeps and don't care about data residency. W&B's free tier (5 GB) is fine for a solo project but adds a SaaS dependency. MLflow keeps everything on Railway. |
| APScheduler (v1) | **Prefect 3 self-hosted** | When you need: (a) per-asset retries with backoff state, (b) DAG dependencies between ingest stages, (c) UI for run inspection. Prefect 3 is Python-native, decorator-based, low ceremony — preferred over Dagster for solo. |
| APScheduler (v1) | **Dagster** | Dagster forces software-defined-assets model and per-asset materialization billing on cloud. Heavy for solo. Pick Dagster only if you want strict asset lineage from day 1 — overkill here. |
| APScheduler (v1) | **Airflow** | Don't. Heavyweight, Python-2-era operator model, awful local dev story. No solo developer in 2026 should pick Airflow over Prefect/Dagster. |
| Custom event-driven backtester | **NautilusTrader** | Once strategy proves out in paper trading. Nautilus is still **1.x (1.227 as of May 2026), breaking changes between releases**. Production-grade event-driven engine with realistic crypto-futures simulation. Pin a version and only upgrade deliberately. |
| Custom event-driven backtester | **vectorbt (open-source)** | Use vectorbt for fast parameter sweeps and idea-screening on closed-form rules. Bad for path-dependent ML signals (stop-loss interactions, position sizing rules). **vectorbt-pro is paid** ($500+/yr). Stick with open-source `vectorbt`. |
| Custom event-driven backtester | **backtesting.py** | Slowing maintenance; no native futures/leverage support. Skip. |
| Grafana Cloud free | **SigNoz (self-hosted)** | If Grafana Cloud's 14-day retention or 10K-series cap bites. SigNoz on Railway works but adds operational surface area. |
| Grafana Cloud free | **Railway's built-in metrics** | Sufficient for system metrics (CPU/RAM/network) but no business-metric custom dashboards. Always pair Railway metrics + Grafana for app metrics. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Zipline / Zipline-Reloaded** | Equities-first, US market hours baked in, no native crypto futures support, sparse maintenance. Crypto perps don't fit the data bundle model. | Custom event-driven backtester → NautilusTrader once proven. |
| **PyAlgoTrade / bt** | Effectively unmaintained. | Same as above. |
| **Backtrader** | Last meaningful release pre-2023. Active forks exist but ecosystem is dying. No crypto-futures specifics. | Same as above. |
| **vectorbt-pro for v1** | $500+/yr for marginal features over open-source vectorbt at this scale. | Open-source `vectorbt` for sweeps; custom event-driven for execution-realism. |
| **TA-Lib (C library) on Railway** | C extension build pain in Docker; install flakiness; alternative `pandas-ta` is pure Python and adequate for 1m-and-up timeframes. | `pandas-ta` for v1; revisit TA-Lib only if profiling proves indicator computation is bottleneck. |
| **Pandas v1.x** | EOL; no NumPy 2.x support. | pandas 2.2+. |
| **`requests` library for async code paths** | Sync-only, blocks event loop, will silently nuke throughput. | `httpx` (sync + async unified API). |
| **`aiohttp` for new code** | Bigger surface area, sync/async API mismatch, less ergonomic than `httpx`. Only acceptable as ccxt's internal transport (it uses aiohttp). | `httpx`. |
| **psycopg2** | Legacy, no async. | `psycopg` v3 (and `asyncpg` for hot-path COPY). |
| **Black + isort + flake8 + pylint stack** | Slow, fragmented, redundant. | Ruff (single tool, 100x faster). |
| **Poetry** | Slower than `uv`; flaky lockfile updates; complex resolver edge cases. | `uv` (10-100x faster, simpler `uv.lock`). Poetry is still fine, but `uv` won in 2026. |
| **PyMongo / MongoDB for time-series** | Schemaless makes time-series schema drift silent killers; no native compression for crypto candle workloads matching TimescaleDB. | TimescaleDB. |
| **InfluxDB** | Flux language adoption stalled; v2/v3 split caused ecosystem fragmentation; community-edition rate-limited. | TimescaleDB. |
| **Custom MEXC SDKs from random GitHub repos** | Inconsistent maintenance, no paper/live symmetry, abandoned mid-2024 in several cases. | ccxt (and contribute fixes upstream if MEXC support has gaps). |
| **Pandas `df.iterrows()` / `df.apply(axis=1)` in feature engineering hot path** | 100-1000x slower than vectorized. | Polars expressions, or pandas vectorized ops + numpy. |
| **`asyncio.create_task` without tracking** | Fire-and-forget tasks get GC'd mid-flight; silent failures destroy bots overnight. | Hold task references; use `asyncio.TaskGroup` (Python 3.11+) for structured concurrency. |
| **`time.sleep` inside async coroutines** | Blocks event loop. | `await asyncio.sleep(...)`. |
| **CoinGecko free tier for production ingest** | 30 calls/min is brutally low; you will get throttled on any nontrivial universe scan. | **CoinGecko Demo API ($0)** is the free tier (was rebranded); **CoinGecko Analyst tier ($129/mo)** for production. Or: cache aggressively + run discovery hourly, not per-tick. |
| **Coinglass Hobbyist tier for backtesting** | 1m candles capped at 6 days, 30 req/min — useless for 1-2 year backfill. | **Coinglass Startup ($79/mo)** minimum for 12 days of 1m + 80 req/min. Realistically **Standard ($299/mo)** if you want 720 days of hourly derivatives. **No tier offers >180 days of 1m candles — accept that 1m derivatives features will use a rolling window only.** |

## Stack Patterns by Variant

**If Coinglass budget is hard-capped at $30/mo:**
- Use Coinglass Hobbyist only for live signals (latest funding/OI snapshots).
- Backfill historical derivatives features from **MEXC's own funding/OI endpoints** (lower quality, exchange-specific, but free).
- Accept reduced feature set for backtests (no aggregated multi-exchange funding/OI).

**If MEXC adds restrictions / KYC issues / API outages become frequent:**
- ccxt unified API makes Binance/Bybit/OKX a config swap, BUT:
  - Their memecoin/low-cap listings are thinner — strategy edge is partially MEXC-listing-specific.
  - Migration would invalidate historical backfill (different symbols, different funding cadences).
- Plan: capture this as a "data layer must support symbol-source attribution" architecture decision.

**If row counts cross 500M (Phase 3+):**
- Keep TimescaleDB for last-30-days hot data with continuous aggregates.
- Tier older chunks to **Timescale Cloud's tiered storage to S3** OR migrate cold history to ClickHouse / DuckDB-on-Parquet.
- Do NOT do a full ClickHouse migration without proving TimescaleDB compression + continuous aggregates are inadequate first.

**If walk-forward training time crosses 30 minutes:**
- LightGBM-only sweep (drop XGBoost from hyperparam search; keep for final model).
- Optuna with median pruner cuts hyperparam search ~50%.
- Consider GPU XGBoost (`tree_method='hist'`, `device='cuda'`) on a temporary Railway GPU service — but expensive; defer.

**If paper trading proves edge and you go live:**
- Add `python-binance` or stick with ccxt for execution? **Stick with ccxt** — keeps paper/live identical.
- Promote risk management module from "library" to "process boundary" — separate Railway service with its own kill switch endpoint.
- Add **redundant deployment** (one ingest service + one execution service + one signal service) so deploys don't kill open positions.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Python 3.12 | Polars 1.40, pandas 2.2, XGBoost 3.2, LightGBM 4.6, ccxt 4.5 | Sweet spot; 3.13 lacks tested wheels for some niche libs (`pandas-ta`, older deps). |
| pandas 2.2 | NumPy 2.x, PyArrow 17 | NumPy 2.x requires pandas ≥2.2.2; older pandas will segfault. |
| Polars 1.40 | PyArrow 17, pandas 2.2 | `polars.from_pandas` / `polars.to_pandas` requires PyArrow for zero-copy. |
| FastAPI 0.115 | Pydantic ≥2.7, Starlette 0.40+ | Drops Pydantic v1 entirely. Migrate any legacy `BaseModel.dict()` → `model_dump()`. |
| SQLAlchemy 2.x | psycopg 3.2 OR asyncpg 0.30 | Async engine requires async driver; mixing sync engine + asyncpg silently breaks. |
| TimescaleDB 2.18 | PostgreSQL 14, 15, 16, 17 | Railway template defaults to PG16. **PG18 + Timescale exists** but is brand-new — stick with PG16 for v1. |
| ccxt 4.5 | Python 3.10+, aiohttp 3.10+ | Pin ccxt to a specific minor version; behavior changes between minors are common. |
| MLflow 3.x | SQLAlchemy 2.x, Postgres 12+ | MLflow 3 dropped Python 3.8; use Postgres backend (not SQLite) for concurrent runs. |
| Optuna 4.x | SQLAlchemy 2.x | Optuna's RDB storage uses SQLAlchemy; share the same Postgres as MLflow. |
| pytest-asyncio 0.24 | pytest 8.x | Set `asyncio_mode = "auto"` in `pyproject.toml`. |
| Pydantic 2.7 | pydantic-settings 2.x, pydantic-extra-types 2.x | All three usually move together; pin as a set. |
| XGBoost 3.2 | NumPy 2.x, pandas 2.2, scikit-learn 1.5+ | `XGBClassifier` accepts `categorical_feature` natively as of 3.x. |
| ccxt Pro websockets | aiohttp transport | ccxt Pro is included in `pip install ccxt` since 4.x (no separate paid package for Python — JS/TS Pro is separate licensing, but Python is unified and MIT). |

## Paid Services Summary

| Service | Tier | Cost | Why Required | Phase |
|---------|------|------|--------------|-------|
| Railway | Hobby / Pro | $5-20/mo baseline + usage | Hosting + managed Postgres+Timescale | v1 |
| Coinglass API | **Startup** | **$79/mo** | 1m derivatives history (12 days), 80 req/min — minimum viable for live signals + short backfill window | v1 |
| Coinglass API | Standard | $299/mo | 720 days of hourly derivatives, 300 req/min — required for proper backtest of derivatives features | Phase 2 if backtest signals need >12 days of 1m |
| CoinGecko API | Demo (free) | $0 | 30 calls/min — adequate for daily universe filter refresh; cache aggressively | v1 |
| CoinGecko API | Analyst | $129/mo | 500 req/min — only if intraday market-cap/category signals matter | Phase 2 (likely skip) |
| MEXC API | Free | $0 | Public + signed API access; rate limits adequate for solo bot | v1 |
| Grafana Cloud | Free | $0 | 10K series, 50GB logs, 14-day retention | v1 |
| Sentry | Free | $0 | 5K errors/mo | v1 |
| MLflow | Self-hosted on Railway | $0 (uses existing Postgres) | Experiment tracking | v1 |

**Total external API cost floor: ~$84/mo** (Railway $5 + Coinglass Startup $79). Plan for **$300+/mo** if Coinglass Standard becomes necessary in Phase 2.

## Crypto-Trading-Specific Quirks Called Out

1. **MEXC websocket OHLCV in ccxt Pro has had hangs and missing-data issues** — see ccxt#27253. Default to **`watch_trades()` and recompute candles client-side via `build_ohlcvc()`** rather than `watch_ohlcv()` directly. This is documented ccxt guidance for MEXC and several other Tier-2 exchanges.

2. **MEXC contract endpoints occasionally drift between ccxt minor versions** — see ccxt#28532 (May 2026, swap order create endpoint fix). Pin ccxt to a known-working minor version; gate ccxt upgrades behind a paper-trading smoke test.

3. **Funding rate cadence is exchange-specific.** MEXC settles every 8 hours; some pairs differ. Schema must store funding interval per symbol, not assume a global constant.

4. **Coinglass aggregates funding across exchanges** — these are NOT the same as MEXC's own funding rates for the same pair. Tag every funding row with `source` (`mexc` vs `coinglass_aggregate`) at the schema level or you will compare apples to oranges in features.

5. **MEXC listing/delisting churn is high** — memecoin perps come and go in weeks. Universe filter must run daily AND your schema must handle symbols disappearing (no ON DELETE CASCADE traps, no foreign-key blowups on retroactive backfill).

6. **Walk-forward validation must respect funding boundaries** — labeling and feature lookahead windows must end strictly before the next funding tick or you'll leak funding-rate information into features. Hypothesis property-based tests should encode this invariant.

7. **Order book snapshots at MEXC universe scale (200-500 perp pairs)** are expensive — full L2 snapshots every minute is ~10-50 MB/min. Pick a depth (top 20 levels) and a sampling rate (every 5-10s for active universe, every 1m for full universe). TimescaleDB compression will work well on these.

8. **Slippage on MEXC memecoin perps is non-trivial** — backtests must model: maker/taker fee (default taker 0.05% on USDT-M perps), slippage as % of top-of-book depth, and partial fills. Don't trust any backtest that uses a flat 0.05% slippage assumption on a $500K-volume coin.

9. **MEXC API key permissions are coarse** — read vs trade vs withdraw. Always create read-only keys for ingest and a separate trade-permission key (no withdraw) for execution. Never use a single super-key.

10. **Time zones bite hard in crypto.** Everything must be UTC in storage; only convert at display. Funding windows are UTC. Hypothesis tests with `freezegun` should explicitly assert behavior crossing day boundaries.

## Sources

- ccxt PyPI — 4.5.54 confirmed as latest May 15 2026 — HIGH
- nautilus_trader PyPI — 1.227.0 confirmed May 18 2026, still 1.x — HIGH
- Polars releases — 1.40.1 (Apr 22 2026), production/stable — HIGH
- XGBoost releases — 3.2.0 (Feb 10 2026) — HIGH
- LightGBM — 4.6.x current — HIGH
- Coinglass official pricing page — Hobbyist $29/Startup $79/Standard $299/Pro $699 — HIGH (fetched May 2026 from coinglass.com/pricing)
- Coinglass API docs — funding rate / OI / liquidation endpoints — MEDIUM (vendor-provided, verified)
- Railway TimescaleDB templates — `timescale/timescaledb:2.18.0-pg16` confirmed available — HIGH
- ccxt MEXC issues #27253 (watch_ohlcv hang) and #28532 (swap order endpoint, May 2026) — HIGH (GitHub issues)
- FastAPI release notes — Pydantic v1 dropped, min Python 3.10+ — HIGH
- TimescaleDB vs ClickHouse benchmarks (sanj.dev 2026, tigerdata.com, dev.to AWS Builders) — MEDIUM (third-party benchmarks, cross-verified)
- Prefect vs Dagster comparisons (2026) — MEDIUM (vendor-adjacent)
- Polars vs pandas benchmarks (KDnuggets, pythonalchemist 2026) — MEDIUM
- Optuna vs Hyperopt (druce.ai benchmark) — MEDIUM (single benchmark, directionally consistent with community wisdom)
- MLflow vs W&B comparison (zenml, modern-datatools 2026) — MEDIUM
- General Python testing practices (pytest 9.x, hypothesis 6.152, pytest-asyncio auto-mode) — HIGH
- NumPy 2.x ecosystem compatibility — HIGH (vendor docs)

---
*Stack research for: crypto futures ML trading on Railway (solo)*
*Researched: 2026-05-21*
