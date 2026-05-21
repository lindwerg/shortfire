# Phase 1: Data Platform — Research

**Researched:** 2026-05-21
**Domain:** TimescaleDB-backed multi-source crypto data warehouse (MEXC + Coinglass + CoinGecko) on Railway
**Confidence:** HIGH overall (CONTEXT.md locked most decisions; this research operationalizes them with library-specific patterns and verified versions)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

D-35..D-96 in `.planning/phases/01-data-platform/01-CONTEXT.md` are binding. Highlights the planner MUST honor:

- **D-35:** Coinglass tier in production is HOBBYIST (~$35/mo). Rate limit **30 req/min** (not 80). 1m derivatives history window **~6 days**. ROADMAP.md / REQUIREMENTS.md (DATA-07, STOR-08) referencing "Startup ($79/mo)" MUST be patched in the same commit that lands the Phase 1 plan.
- **D-36:** CoinGecko tier ~$35/mo, default 30 req/min (Demo). Universe-metadata only, daily cadence.
- **D-37:** Coinglass Standard ($299/mo) upgrade stays deferred to Phase 2 EDA per V2-DATA-01.
- **D-38:** Backfill scope: ≥1 yr MEXC OHLCV (1m/5m/15m/1h/4h/1d) via paginated `fetch_ohlcv` 1000-candle pages; MEXC funding/OI full vendor depth; Coinglass 1m capped at 6 days (Hobbyist); L2 + trades + liquidations forward-capture only.
- **D-39:** L2 backfill impossible — accepted; slippage realism in Phase 3 constrained to forward-captured L2.
- **D-40..D-49:** ccxt-backed MEXC integration. Single async client per process, `defaultType='swap'`, symbol convention `BTC/USDT:USDT`; ccxt pinned `>=4.5.54,<4.6`; OHLCV REST backfill with `Semaphore(8)`; **live OHLCV is `watch_trades` → 1m client-side aggregation, NOT `watch_ohlcv` (ccxt#27253 ban)**; funding via REST + ws; OI REST-only; L2 via `watch_order_book(limit=20)` with tier-1 5s / rest 10s sampling under `asyncio.TaskGroup`; trades 1-min batched COPY; liquidations dual-source with `source` attribution; freshness contract per source/symbol.
- **D-50..D-54:** Coinglass via single `httpx.AsyncClient` HTTP/2; `aiolimiter(rate=28, period=60)` global; Pydantic v2 schemas per endpoint; validation failures → `dead_letter`; cadences locked per endpoint; 1m capped at 6 days.
- **D-55..D-57:** CoinGecko universe-metadata-only at 00:30 UTC; `aiolimiter(rate=28, period=60)`; schema `raw_coingecko_market` idempotent on `(symbol, ts, source)`.
- **D-58:** Typed-per-source hypertables. EAV explicitly rejected. Full table list in CONTEXT.md — see Section 1 below.
- **D-59:** `source TEXT NOT NULL` + Postgres `CHECK` constraint with enum `'mexc_native', 'coinglass_aggregate', 'coinglass_mexc_only', 'coingecko'`.
- **D-60:** `quality_flag TEXT NOT NULL DEFAULT 'ok'` on every raw table; enum `'ok','gap_detected','partial_candle','late_arrival','ws_rest_divergence','schema_warn','partial_capture'`.
- **D-61:** `ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()` on every raw table.
- **D-62:** Staging-table COPY → `INSERT … ON CONFLICT (symbol, ts, source) DO NOTHING` (first-write-wins, never `DO UPDATE`); staging is `CREATE UNLOGGED TABLE` per session.
- **D-63:** `symbols` relational lookup table with soft-delete via `delisted_at`. `ON DELETE CASCADE` banned project-wide (Phase 0 grep guard enforces).
- **D-64:** `universe_snapshots` hypertable PK `(snapshot_date, symbol)`, 90-day chunks, no compression (tiny), 24h-vol threshold $500K USD = `is_qualifying`. New-listing diff vs yesterday → Telegram + event.
- **D-65:** All time columns `TIMESTAMP(timezone=True)` (TIMESTAMPTZ). Phase 0 pre-commit guard forbids naive `TIMESTAMP[^(]` outside helpers.
- **D-66:** `enable_compression` + `add_compression_policy` per hypertable via Phase 0 `shortfire.db.timescale` helpers (D-27); NEVER raw `op.execute` for these.
- **D-67:** Continuous aggregates for 5m / 15m / 1h / 4h over `raw_mexc_candles_1m`. Per-aggregate `(start_offset, end_offset, schedule_interval)` locked. All start_offsets inside 7-day compression-after window.
- **D-68:** No retention policies in Phase 1.
- **D-69..D-71:** SQLAlchemy Core (NOT ORM) for hot-path writes; `asyncpg.copy_records_to_table` direct; single `copy_into_hypertable` helper in `src/shortfire/ingest/storage/copy.py`; per-timeframe `CandleRepo` impls delegate to it.
- **D-72..D-74:** Per-source tenacity policies in `src/shortfire/ingest/retry.py`. aiolimiter layered ABOVE tenacity. ccxt internal throttler kept ON (defense-in-depth). `dead_letter` schema locked.
- **D-75..D-79:** APScheduler 4.x `AsyncScheduler` + `SQLAlchemyDataStore(engine)` + `AsyncpgEventBroker.from_async_sqla_engine(engine)`. **`PostgresJobStore` (v3 nomenclature) is FORBIDDEN — REQUIREMENTS.md ORCH-01 refers to the concept, not the literal class name.** Scheduler runs inside `data-platform` FastAPI `lifespan`. Job graph locked (table in CONTEXT.md). Continuous ws tasks are NOT APScheduler jobs — they live in `asyncio.TaskGroup` under `lifespan`. Job callables are top-level module functions with primitive args only (no closures/instance methods).
- **D-80..D-83:** Daily `pg_dump --format=custom --compress=zstd:9` to Cloudflare R2 via boto3 S3-compatible; retention 7 daily + 4 weekly + 6 monthly + indefinite annual; restore drill in `docs/RESTORE.md`; secrets `R2__*` in Railway env, optional `R2BackupSettings | None`.
- **D-84..D-87:** New Prometheus metric families on existing custom `CollectorRegistry` (no new registry). Event taxonomy +13 names. Telegram via raw `httpx` to Bot API (NO `python-telegram-bot` framework dep until Phase 4). Severity routing `warn` / `crit`.
- **D-88..D-90:** 3 services unchanged (`data-platform`, `strategy-engine`, `dashboard`). Auto-deploy on green main. `data-platform` may need bump to 2 vCPU / 4 GB IF profiling shows OOM; default ship at Phase 0 resources.
- **D-91..D-94:** Coverage gate 80% project-wide. `src/shortfire/ingest/*` REMOVED from coverage `omit` in `pyproject.toml`. Unit/integration/contract/property layers. CI backfill test runs 6-day slice; full-year is operational not CI.
- **D-95..D-96:** Directory tree + Alembic migrations 0003 → 0014 locked.

### Claude's Discretion (from CONTEXT.md §Decisions §Claude's Discretion)

Plan-time resolution still needed on:

- Exact `wait_exponential_jitter(initial, max)` per source (CONTEXT.md gives shape; concrete numbers tuned during planning — see §Pitfalls).
- L2 JSONB internal structure: array of `[price, qty]` vs object `{price, qty}` (CONTEXT.md says array; this research confirms array is correct — narrower JSON, faster scan).
- SQLAlchemy table model class names for relational lookup tables (`Symbol`, `IngestRun`, `DeadLetter`) — naming is style, not architecture.
- Exact Prometheus Gauge label sets beyond what D-84 names (planner picks low-cardinality dimensions per metric).
- Migration 0014 strategy: add `create_continuous_aggregate(...)` helper to `shortfire.db.timescale` OR accept one raw `op.execute` per CA with inline justification — **this research recommends option (a)** since the pattern repeats 4×, see §3.5.
- Daily snapshot exact UTC time for new-listing diff (CONTEXT.md says 00:05 UTC — this research confirms; see §3 for rationale).

### Deferred Ideas (OUT OF SCOPE for Phase 1)

- Coinglass Standard ($299/mo) upgrade (Phase 2 EDA decision).
- Multi-exchange ingest (Binance / Bybit / OKX) — schema supports via `source` column, no code in Phase 1.
- Backtest-grade L2 reconstruction (V2-DATA-02).
- Prefect 3 / Dagster migration (V2-INFRA-01).
- ClickHouse migration (V2-INFRA-02).
- Retention policies on hypertables (deferred per D-68).
- `coinglass_mexc_only` source value — reserved in D-59 but ingest writes `coinglass_aggregate` by default in Phase 1.
- `python-telegram-bot` framework adoption (Phase 4 — `/halt` `/resume` `/status` commands).
- MEXC IP allowlist on `READ_KEY` (Phase 5 verifies Railway egress IP stability).
- Grafana dashboards, Sentry — Phase 5.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | MEXC OHLCV 1m/5m/15m/1h/4h/1d for qualifying universe | §2 ccxt patterns; §3 schema; §4 backfill recipe; §5 continuous aggregates for 5m+ |
| DATA-02 | MEXC funding history with `settlement_ts` + `published_ts` | §2 dual-timestamp pattern; §3 `raw_mexc_funding` schema |
| DATA-03 | MEXC OI hourly | §2 REST-only OI pattern (D-45) |
| DATA-04 | MEXC signed trades (REST + ws persistence) | §2 `watch_trades` + 1-min COPY batching |
| DATA-05 | MEXC L2 top-20 sampled 5–10s per symbol | §2 `watch_order_book(limit=20)` + tier-1 logic |
| DATA-06 | MEXC liquidations (ws or REST poll) | §2 D-48 dual-source pattern |
| DATA-07 | Coinglass funding / OI / LSR / liq within Hobbyist tier | §2 httpx + aiolimiter; §6 Coinglass quirks |
| DATA-08 | CoinGecko daily market metadata | §2 daily 00:30 UTC job |
| DATA-09 | Idempotent on `(symbol, ts, source)` | §3 staging COPY + ON CONFLICT DO NOTHING |
| DATA-10 | tenacity + aiolimiter per source | §2 retry policies; §7 layered limiter pattern |
| DATA-11 | Pydantic validation → `dead_letter` | §3 `dead_letter` schema; §7 writer pattern |
| DATA-12 | `source` column with CHECK | §3 schema + CI grep guard |
| STOR-01..05 | Typed hypertables, no EAV, TIMESTAMPTZ, compression, continuous aggregates | §3 full schema; §5 CA refresh policies |
| STOR-06 | Daily `universe_snapshots` | §4 universe snapshot job + point-in-time query |
| STOR-07 | Soft-delete via `delisted_at`; CASCADE banned | §3 `symbols` lookup table |
| STOR-08 | 1–2 yr backfill | §4 backfill recipe with paginated REST |
| STOR-09 | `quality_flag` flags gaps, no interpolation | §3 quality_flag enum + gap detector |
| STOR-10 | Daily pg_dump → R2 + restore drill | §8 backup recipe |
| UNIV-01..04 | $500K filter, daily refresh, point-in-time, new-listing 24h | §4 universe pipeline + Hypothesis property test |
| ORCH-01..04 | APScheduler 4 with Postgres jobstore, per-source cadence, freshness gauge, stale-data Telegram | §5 APScheduler v4 lifespan pattern; §7 freshness alerter |
| OPS-05 | commit→push→deploy after every task | §9 CI/CD pattern (carry from Phase 0) |
| OPS-06 | 3 Railway services live | §9 service topology (carry from Phase 0) |
</phase_requirements>

---

## Executive Summary

1. **Ground truth is CONTEXT.md, not training data.** 95% of architectural decisions for Phase 1 are already locked in D-35..D-96. This research's job is to make those decisions *executable*: verified library API surface, code-level patterns, gotchas, and an automated validation architecture. Nothing here contradicts CONTEXT.md; where research adds nuance it is flagged inline.

2. **The schema is the contract.** 14 Alembic migrations (0003 → 0014) ship a fully typed-per-source hypertable layout with a global `(symbol, ts, source)` idempotency key, a `source` `CHECK` constraint enforced both in Postgres and in the domain `Source` Literal, and continuous aggregates for 5m/15m/1h/4h sourced from `raw_mexc_candles_1m`. Compression policy uniform at 7 days. **Migration 0014 is the only carve-out from D-27** — we recommend adding `create_continuous_aggregate(...)` to `shortfire.db.timescale` to keep the discipline.

3. **Idempotency is structural, not behavioural.** Every write path goes through `copy_into_hypertable(target_table, records, columns, conflict_columns)` (`src/shortfire/ingest/storage/copy.py`), which does asyncpg `copy_records_to_table` into an UNLOGGED per-session staging table, then `INSERT … SELECT … ON CONFLICT DO NOTHING`. Re-ingest cannot produce duplicates by construction. Failed Pydantic validation writes to `dead_letter` instead of crashing the loop.

4. **Live data flow is `asyncio.TaskGroup` under FastAPI `lifespan`; cron is APScheduler 4 `AsyncScheduler`.** The two systems share one `AsyncEngine` but own different concerns: ws tasks (long-lived, reconnect-on-stale) vs. scheduled jobs (durable, restart-safe via `SQLAlchemyDataStore`). `watch_ohlcv` is banned per ccxt#27253 — live 1m candles come from `watch_trades` + client-side aggregation.

5. **Freshness is observed, not assumed.** Per-source-per-symbol Prometheus gauges (`shortfire_data_platform_source_freshness_seconds{source,dataset,symbol}`) update on every successful write; an APScheduler-cron `freshness.check` job scans them every minute and fires Telegram alerts when any exceeds 2× expected lag. Stale-data refusal at signal time (Pitfall 11 mitigation) is shipped *now* even though no signals fire until Phase 4 — the gauge is the seam.

**Primary recommendation:** Plan in 4 waves matching CONTEXT.md's natural seams — (Wave 1) schema migrations 0003–0014 + `copy_into_hypertable` helper + ingest infrastructure (retry/rate-limit/dead-letter/context); (Wave 2) per-source concrete clients (MEXC ccxt, Coinglass httpx, CoinGecko httpx) + their integration tests; (Wave 3) universe snapshot job + tier-1 logic + APScheduler bootstrap + ws TaskGroup; (Wave 4) freshness alerter + R2 backup + Telegram + observability extensions + the ROADMAP/REQUIREMENTS subscription-tier patch + CI/CD coverage-gate inclusion.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| MEXC REST OHLCV/funding/OI backfill | `data-platform` (Python ingest worker) | — | Only service with credentials + ccxt; bulk-batched. |
| MEXC ws live streams (trades/L2/funding/liquidations) | `data-platform` (`asyncio.TaskGroup` in lifespan) | — | Long-lived; reconnect logic = process-local. |
| Coinglass + CoinGecko HTTP polling | `data-platform` (APScheduler cron) | — | Same service; shared httpx client + aiolimiter. |
| Hypertable write hot path | `data-platform` → TimescaleDB (asyncpg COPY) | — | asyncpg bypasses SQLAlchemy ORM at row count > ~1k/s. |
| Continuous aggregate refresh | TimescaleDB internal scheduler | — | NOT in APScheduler — Timescale handles via `add_continuous_aggregate_policy`. |
| Universe snapshot daily | `data-platform` (APScheduler cron 00:05 UTC) | TimescaleDB (hypertable) | Job assembles MEXC `load_markets` + 24h volume, writes row-set. |
| Freshness gauge updates | `data-platform` (in-process after every write) | Prometheus `/metrics` (read by Grafana later) | Gauge writes ride on the same path as the data write. |
| Stale-data + dead-letter Telegram alerts | `data-platform` (APScheduler cron + raw httpx call) | Telegram Bot API | No `python-telegram-bot` framework dep until Phase 4. |
| Daily pg_dump → R2 | `data-platform` (APScheduler cron 01:00 UTC) | R2 (S3-compatible) | Single boto3 client; runs inside service. |
| Strategy-engine + dashboard services | `strategy-engine` / `dashboard` (placeholder, sleep-when-idle) | — | Required live for OPS-06 even though they do no Phase 1 work. |
| Migrations (Alembic) | `data-platform` `preDeployCommand` | — | Phase 0 wired `alembic upgrade head` in `railway.toml`. Phase 1 reuses. |

---

## 1. Standard Stack

### Core (already pinned in `pyproject.toml`)

| Library | Version | Verified | Purpose | Source provenance |
|---------|---------|----------|---------|---------------------|
| Python | 3.12.x | runtime (existing) | Runtime | [CITED: pyproject.toml `requires-python = ">=3.12"`] |
| FastAPI | >=0.128 | runtime (existing) | API layer in `data-platform` lifespan | [CITED: pyproject.toml] |
| ccxt | >=4.5.54, <4.6 | [CITED: CONTEXT.md D-41 + CLAUDE.md STACK matrix] | MEXC REST + ws unified | [VERIFIED: CLAUDE.md notes ccxt 4.5.54 confirmed latest May 15 2026; ccxt#28532 fix landed in 4.5 line] |
| httpx | >=0.28 | runtime (existing) | Coinglass + CoinGecko REST | [CITED: pyproject.toml] |
| Pydantic | >=2.13 | runtime (existing) | Schema validation at every API boundary | [CITED: pyproject.toml] |
| SQLAlchemy | >=2.0.49 | runtime (existing) | Engine + ORM for lookup tables | [CITED: pyproject.toml] |
| asyncpg | >=0.31 | runtime (existing) | Raw COPY hot path | [CITED: pyproject.toml] |
| Alembic | >=1.16 | runtime (existing) | Migrations 0003–0014 | [CITED: pyproject.toml] |
| tenacity | >=9.1 | runtime (existing) | Retry decorators per source | [CITED: pyproject.toml] |
| aiolimiter | >=1.2 | runtime (existing) | Per-source token bucket rate limiter | [CITED: pyproject.toml] |
| orjson | >=3.11 | runtime (existing) | Fast JSON for ws frame parsing | [CITED: pyproject.toml] |
| structlog | >=25.5 | runtime (existing) | JSON logging with correlation ID | [CITED: pyproject.toml + Phase 0 observability skeleton] |
| prometheus-client | >=0.25 | runtime (existing) | `/metrics` endpoint | [CITED: pyproject.toml; Phase 0 D-84 base 4 metrics] |
| pydantic-settings | >=2.11 | runtime (existing) | Env-var-driven settings | [CITED: pyproject.toml] |
| greenlet | >=3.5.1 | runtime (existing) | SQLAlchemy 2.x async runtime dep | [CITED: pyproject.toml; D-32 lesson learned in Phase 0] |

### New for Phase 1 (planner to add to `pyproject.toml`)

| Library | Recommended pin | Purpose | Source provenance |
|---------|-----------------|---------|---------------------|
| `apscheduler` | `>=4.0.0` (note: APScheduler 4 is the current line; 4.0+ has `AsyncScheduler`/`SQLAlchemyDataStore`/`AsyncpgEventBroker`) | Persistent cron + interval jobs | [VERIFIED: Context7 + CONTEXT.md D-75 + STACK.md APScheduler 4.x; **planner MUST `npm view`-equivalent on PyPI at install time** because v4 has minor API tweaks across releases — see Package Legitimacy Audit] |
| `boto3` | `>=1.35` | S3-compatible R2 client for pg_dump upload | [VERIFIED: pip index versions; widely deployed; CONTEXT.md D-80] |
| `pyarrow` | `>=17.0` | Polars↔pandas zero-copy AND Parquet for any offline analysis | [CITED: CLAUDE.md tech stack matrix — Polars ↔ Pydantic boundary] (Phase 1 does NOT yet need Polars per CONTEXT.md scope — asyncpg writes use plain tuples — so this is optional and may be deferred until Phase 2 §FEAT-01.) |
| `python-telegram-bot` | **DO NOT ADD** | Per D-86 explicit — Phase 1 uses raw `httpx` POSTs to `https://api.telegram.org/bot<TOKEN>/sendMessage`. | [CITED: CONTEXT.md D-86] |
| `cryptofeed` / `mexc-api` | **DO NOT ADD** | Per CONTEXT.md D-40 + CLAUDE.md anti-list — ccxt covers MEXC unified; single-vendor SDKs banned. | [CITED: CLAUDE.md "What NOT to Use"] |
| `mlflow` / `optuna` / `xgboost` | **NOT IN PHASE 1** | Phase 2 territory per ROADMAP. | [CITED: ROADMAP.md Phase 2 requirements] |
| `polars` | **NOT IN PHASE 1** | Defer until Phase 2 feature engineering. Phase 1 writes asyncpg COPY tuples — no DataFrame transforms needed. | [CITED: CONTEXT.md D-95 ingest tree has no polars import] |

### Already-Banned (carried from CLAUDE.md)

- `requests` (sync only — block event loop), `aiohttp` for new code (use httpx; aiohttp acceptable only as ccxt transport), `psycopg2` (legacy), `Black + isort + flake8` (ruff replaces), `Poetry` (uv replaces), `Pandas v1.x`, `time.sleep` inside async, `asyncio.create_task` without reference (Pitfall 27).

### Version verification (planner re-runs at install time)

```bash
pip index versions apscheduler   # Confirm 4.0+ on PyPI
pip index versions boto3         # Confirm >=1.35
# CONTEXT.md D-41 pins ccxt >=4.5.54,<4.6 — already in scope
```

[ASSUMED] APScheduler 4 is fully released and not in pre-release as of May 2026 — CONTEXT.md asserts this and Context7 confirms `AsyncScheduler` API, but planner must verify the latest minor at install time and lock it in `uv.lock`.

---

## 2. Architecture Patterns

### System Architecture Diagram

```
                       ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐
                       │ MEXC REST + ws  │  │ Coinglass REST  │  │ CoinGecko    │
                       │ (ccxt unified)  │  │ (httpx)         │  │ (httpx)      │
                       └────────┬────────┘  └────────┬────────┘  └──────┬───────┘
                                │                    │                  │
                                ▼                    ▼                  ▼
                       ┌──────────────────────────────────────────────────────────┐
                       │  per-source aiolimiter token buckets (D-51, D-56)         │
                       │  per-source tenacity retry decorators (D-72)              │
                       │  per-endpoint Pydantic v2 schemas (D-52)                  │
                       └──────────────────────────────────────────────────────────┘
                                │                    │                  │
                                ▼                    ▼                  ▼
                       ┌──────────────────────────────────────────────────────────┐
                       │  domain-type normalization (Candle / Funding / Liq / OB) │
                       │  + source attribution at construction time (D-12, D-59)  │
                       └──────────────────────────────────────────────────────────┘
                                │
                                ▼  failure ────────► ┌────────────────┐
                                │                    │  dead_letter   │
                                │  success           │  hypertable    │
                                │                    └────────────────┘
                                ▼
                       ┌──────────────────────────────────────────────────────────┐
                       │  copy_into_hypertable(target, records, cols, conflict)   │
                       │  (asyncpg COPY → UNLOGGED staging → INSERT ON CONFLICT)  │
                       └──────────────────────────────────────────────────────────┘
                                │
                                ▼
                       ┌──────────────────────────────────────────────────────────┐
                       │  TimescaleDB                                              │
                       │  ├── raw_mexc_candles_1m → CA 5m/15m/1h/4h (D-67)         │
                       │  ├── raw_mexc_candles_1d (independent — D-58 row)         │
                       │  ├── raw_mexc_funding (settlement_ts + published_ts)      │
                       │  ├── raw_mexc_oi, _trades, _l2_top20, _liquidations       │
                       │  ├── raw_coinglass_{funding_agg,oi,liq,lsr}               │
                       │  ├── raw_coingecko_market                                 │
                       │  ├── universe_snapshots (PK snapshot_date,symbol)         │
                       │  ├── symbols (relational, soft-delete)                    │
                       │  ├── dead_letter, ingest_runs                             │
                       │  └── 7-day compression policy on every hypertable         │
                       └──────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  data-platform FastAPI service (Railway, always-on)                           │
  │                                                                                │
  │  lifespan ──┬─► asyncio.TaskGroup (ws long-lived):                            │
  │             │     • mexc.candles.live.aggregator (watch_trades → 1m COPY)     │
  │             │     • mexc.funding.live (watch_funding_rate)                     │
  │             │     • mexc.l2.live (watch_order_book sampled per D-46)          │
  │             │     • mexc.trades.live (watch_trades persister)                  │
  │             │     • mexc.liquidations.live (watch_liquidations)                │
  │             │     • heartbeat loop per stream (D-49 reconnect protocol)        │
  │             │                                                                  │
  │             └─► APScheduler AsyncScheduler (cron + interval):                  │
  │                   • mexc.candles.backfill.1d, mexc.oi.poll                     │
  │                   • coinglass.* (5/10/15 min cadences)                         │
  │                   • coingecko.universe (00:30 UTC daily)                       │
  │                   • universe.snapshot (00:05 UTC daily)                        │
  │                   • backup.pg_dump (01:00 UTC daily → R2)                      │
  │                   • freshness.check (every 1 min)                              │
  │                   • dead_letter.alert (every 5 min)                            │
  │                                                                                │
  │  /metrics  ◄── Prometheus custom registry (D-84 + Phase 0 base 4)              │
  │  /health   ◄── structured-JSON health line                                     │
  └──────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure (locked in CONTEXT.md D-95)

```
src/shortfire/
├── ingest/                                # populated in Phase 1
│   ├── base.py                            # IngestClient base helpers
│   ├── retry.py                           # per-source tenacity policies (D-72)
│   ├── rate_limit.py                      # per-source aiolimiter wrappers (D-73)
│   ├── context.py                         # process-wide singletons (engine, settings, metrics)
│   ├── storage/copy.py                    # copy_into_hypertable helper (D-70)
│   ├── mexc/{client,backfill,live_candles,funding,oi,orderbook,trades,liquidations,schemas}.py
│   ├── coinglass/{client,funding_agg,oi,liq,lsr,schemas}.py
│   ├── coingecko/{client,universe,schemas}.py
│   ├── universe/{snapshot,tier1}.py
│   ├── backup/pg_dump_r2.py
│   ├── freshness/{gauges,alerter}.py
│   ├── dead_letter/{writer,alerter}.py
│   └── scheduler/{bootstrap,jobs}.py
├── db/
│   ├── models/                            # SQLAlchemy ORM for lookup tables only
│   │   ├── symbols.py
│   │   ├── ingest_runs.py
│   │   └── dead_letter.py
│   └── (existing: base.py, engine.py, timescale.py)
└── observability/
    ├── telegram.py                        # raw httpx Bot API client (D-86)
    └── (existing: events.py, logging.py, metrics.py, middleware.py)
```

### Pattern 1: Single-helper hypertable write path (D-70)

**What:** All hot-path writes route through one async function.
**When to use:** Every raw hypertable insert in Phase 1.
**Example:**

```python
# src/shortfire/ingest/storage/copy.py
from collections.abc import Iterable
from typing import Any

import asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine

# Staging tables are UNLOGGED — created per session in the same connection.
_STAGING_DDL = """
CREATE UNLOGGED TABLE IF NOT EXISTS {staging} (LIKE {target} INCLUDING DEFAULTS);
TRUNCATE TABLE {staging};
"""


async def copy_into_hypertable(
    engine: AsyncEngine,
    target_table: str,
    records: Iterable[tuple[Any, ...]],
    columns: tuple[str, ...],
    conflict_columns: tuple[str, ...],
) -> int:
    """COPY → UNLOGGED staging → INSERT … ON CONFLICT DO NOTHING. Returns row count.

    D-62/D-70: staging is per-session (UNLOGGED) for speed; conflict policy is
    DO NOTHING (first-write-wins) per D-62. Never DO UPDATE.
    """
    records_list = list(records)
    if not records_list:
        return 0

    staging = f"{target_table}_staging"
    conflict_cols = ", ".join(conflict_columns)
    col_list = ", ".join(columns)

    async with engine.connect() as conn:
        # asyncpg connection (raw) needed for copy_records_to_table
        raw_conn: asyncpg.Connection = await conn.get_raw_connection()  # SQLA escape hatch
        async with raw_conn.transaction():
            await raw_conn.execute(_STAGING_DDL.format(staging=staging, target=target_table))
            await raw_conn.copy_records_to_table(
                staging, records=records_list, columns=columns
            )
            row_count = await raw_conn.execute(
                f"""
                INSERT INTO {target_table} ({col_list})
                SELECT {col_list} FROM {staging}
                ON CONFLICT ({conflict_cols}) DO NOTHING
                """
            )
    return len(records_list)  # actual inserted count returned by ON CONFLICT is opaque; refine in Phase 2
```

**Source:** [VERIFIED: Context7 asyncpg docs `copy_records_to_table`; CONTEXT.md D-62 + D-70]
**Note for planner:** SQLAlchemy 2.x AsyncEngine ↔ raw asyncpg `Connection` access requires `conn.get_raw_connection()` (returns the connection wrapper) → `.driver_connection`. Exact escape-hatch API is version-sensitive; planner MUST test this against the actual SQLAlchemy 2.0.49 pinned in `pyproject.toml`. Alternative: keep a separate `asyncpg.create_pool()` for the COPY path only, sharing DSN with the SQLAlchemy engine. Both are valid; choose at planning time.

### Pattern 2: Layered rate-limit + retry decorator stack (D-72, D-73)

**What:** aiolimiter wraps every outbound call; tenacity wraps the limited callable.
**Example:**

```python
# src/shortfire/ingest/rate_limit.py
from aiolimiter import AsyncLimiter

# D-51: 5% headroom under 30 req/min Hobbyist
COINGLASS_LIMITER = AsyncLimiter(max_rate=28, time_period=60)
# D-56: same headroom shape
COINGECKO_LIMITER = AsyncLimiter(max_rate=28, time_period=60)
# MEXC: ccxt has its own throttler (D-73 defense-in-depth ON); project budget = 18 req/s under 20 req/s public quota
MEXC_LIMITER = AsyncLimiter(max_rate=18, time_period=1)

# src/shortfire/ingest/retry.py
import logging
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)

log = logging.getLogger(__name__)

# CONTEXT.md D-72 shape, concrete numbers below (Claude discretion)
coinglass_retry = retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    wait=wait_exponential_jitter(initial=1.0, max=60.0),
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)

mexc_retry = retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError, TimeoutError)),
    wait=wait_exponential_jitter(initial=2.0, max=120.0),  # MEXC tolerates longer backoff
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)

coingecko_retry = retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    wait=wait_exponential_jitter(initial=1.0, max=60.0),
    stop=stop_after_attempt(4),  # CoinGecko fails fast; less retry budget
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
```

Critical: **Do NOT retry on 4xx-non-429** — those signal bad input (auth, malformed symbol, schema drift) and should land in `dead_letter` immediately. The `retry_if_exception_type` above triggers on transport errors and `HTTPStatusError`, but tenacity sees only the exception type. Inside the call site, check status code before re-raising:

```python
async def _call_coinglass(client: httpx.AsyncClient, url: str, **kwargs):
    async with COINGLASS_LIMITER:
        r = await client.get(url, **kwargs)
        if r.status_code in (429, 500, 502, 503, 504):
            r.raise_for_status()  # tenacity will retry
        if r.status_code >= 400:
            # Permanent — route to dead_letter, do NOT raise for retry
            await write_to_dead_letter(source="coinglass", endpoint=url, payload=r.text,
                                        error_type="HTTPStatusError", error_msg=f"HTTP {r.status_code}")
            return None
        return r.json()

@coinglass_retry
async def fetch_funding_list(client):
    return await _call_coinglass(client, "...")
```

**Source:** [CITED: Context7 tenacity docs — `wait_exponential_jitter`, `before_sleep_log`; aiolimiter docs — `AsyncLimiter(max_rate, time_period)`]

### Pattern 3: `asyncio.TaskGroup` for ws long-lived streams (D-46, D-78, Pitfall 27)

**What:** Every ws stream is a TaskGroup member, never a fire-and-forget `create_task`.
**When to use:** All `watch_*` methods on the ccxt MEXC swap client.

```python
# src/shortfire/ingest/mexc/live_candles.py (skeleton)
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

@asynccontextmanager
async def mexc_ws_streams(client, symbols: list[str]) -> AsyncIterator[None]:
    """All MEXC ws streams under one TaskGroup; cancellation propagates."""
    async with asyncio.TaskGroup() as tg:
        tg.create_task(_trades_aggregator_loop(client, symbols), name="mexc.candles.live.aggregator")
        tg.create_task(_funding_live_loop(client, symbols), name="mexc.funding.live")
        tg.create_task(_l2_sampling_loop(client, symbols), name="mexc.l2.live")
        tg.create_task(_trades_persist_loop(client, symbols), name="mexc.trades.live")
        tg.create_task(_liquidations_loop(client, symbols), name="mexc.liquidations.live")
        tg.create_task(_heartbeat_watchdog(client), name="mexc.heartbeat")
        yield
        # On context exit, TaskGroup cancels all children; exceptions surfaced via ExceptionGroup.
```

**Reconnect contract (D-49):** Each loop catches its own transport exceptions, increments `ws_reconnects_total{source,stream}`, and `await asyncio.sleep(backoff)` before resuming. If a loop raises an *unhandled* exception, the TaskGroup propagates → lifespan exits → Railway restarts the service. This is intentional: a hung ws is worse than a restart.

**Heartbeat (D-49 step 3):** A separate `_heartbeat_watchdog` polls each stream's `last_received` timestamp every 30s; if any stream has > 60s silence, it cancels that stream's task and respawns it via a `dict[str, asyncio.Task]` registry held in the watchdog scope. **The watchdog itself runs under the same TaskGroup** so it can't go fire-and-forget.

**Source:** [CITED: Python 3.11+ `asyncio.TaskGroup` docs; CONTEXT.md D-46/D-49/D-78; PITFALLS.md Pitfall 27]

### Pattern 4: APScheduler 4 `AsyncScheduler` in FastAPI `lifespan` (D-75, D-76)

```python
# src/shortfire/ingest/scheduler/bootstrap.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler import AsyncScheduler
from apscheduler.datastores.sqlalchemy import SQLAlchemyDataStore
from apscheduler.eventbrokers.asyncpg import AsyncpgEventBroker

from shortfire.db.engine import create_engine_from_env
from shortfire.ingest.scheduler.jobs import register_all_jobs
from shortfire.ingest.mexc.live_candles import mexc_ws_streams


@asynccontextmanager
async def data_platform_lifespan(app: FastAPI):
    engine = create_engine_from_env()
    data_store = SQLAlchemyDataStore(engine)
    event_broker = AsyncpgEventBroker.from_async_sqla_engine(engine)

    # Construct concrete MEXC client + the symbol set from universe (latest snapshot)
    mexc_client = ...  # ccxt swap client, see §2.1
    symbols = await _load_qualifying_symbols(engine)  # reads universe_snapshots latest row

    async with AsyncScheduler(data_store, event_broker) as scheduler:
        await register_all_jobs(scheduler)            # idempotent — adds by stable job_id
        await scheduler.start_in_background()

        async with mexc_ws_streams(mexc_client, symbols):
            yield  # FastAPI serves while ws tasks + scheduler run
        # On exit: TaskGroup cancels ws; `async with scheduler` shuts scheduler down
```

**Key v4 nomenclature corrections (D-75):**
- `AsyncScheduler` (NOT `AsyncIOScheduler` — that was v3)
- `SQLAlchemyDataStore(engine)` (NOT `SQLAlchemyJobStore` from v3)
- `AsyncpgEventBroker.from_async_sqla_engine(engine)` — required to wake the scheduler on cross-process job adds (irrelevant in single-process Phase 1 but harmless to include).
- `start_in_background()` returns immediately; `async with scheduler` handles graceful shutdown via `stop()` + `wait_until_stopped()`.

**Source:** [VERIFIED via Context7 APScheduler docs + CONTEXT.md D-75 anchoring the v4 API names; CONTEXT.md `<canonical_refs>` notes "APScheduler 4 Docs verified May 2026"]

### Pattern 5: Idempotent job registration by `job_id` (D-76, D-77, D-79)

```python
# src/shortfire/ingest/scheduler/jobs.py
from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


# D-79: top-level functions, primitive args only.
async def coinglass_funding_agg_job() -> None:
    """Cron-target: refresh Coinglass funding aggregate for all symbols (one batch call)."""
    from shortfire.ingest.context import get_engine, get_settings, get_metrics
    engine, settings, metrics = get_engine(), get_settings(), get_metrics()
    # ... implementation ...


async def register_all_jobs(scheduler: AsyncScheduler) -> None:
    """Idempotent job registration. Re-adding a job with the same id replaces config (APScheduler 4 semantics)."""
    await scheduler.add_schedule(
        coinglass_funding_agg_job,
        trigger=IntervalTrigger(minutes=5),
        id="coinglass.funding_agg",
        misfire_grace_time=300,  # tolerate up to 5 min of latency before considering a run missed
        max_running_jobs=1,       # prevent overlap
    )
    await scheduler.add_schedule(
        universe_snapshot_job,
        trigger=CronTrigger(hour=0, minute=5, timezone="UTC"),
        id="universe.snapshot",
        coalesce=True,            # if scheduler was down across multiple firings, only run once
        misfire_grace_time=3600,
    )
    # ... rest of D-77 job graph ...
```

**Why `coalesce=True` matters:** Without it, after a deploy that takes 30 minutes, APScheduler will fire every missed interval immediately on startup — *bursting* the rate limiter and potentially triggering 429s. CONTEXT.md D-77 doesn't specify this; **this research adds it as a hard requirement** for every cron job that polls an external API.

**Source:** [VERIFIED via Context7 APScheduler 4 docs — `Schedule(coalesce, misfire_grace_time, max_running_jobs)`]

### Anti-Patterns to Avoid

- **Single global `ON CONFLICT (symbol, ts) DO NOTHING`** — must include `source` per D-59 + Pitfall 16. The presence of `source` in PK is non-negotiable for derivative tables.
- **`asyncio.create_task(...)` without holding a reference** — Python's GC will collect the task and silently kill it (Pitfall 27).
- **`watch_ohlcv` for live 1m candles** — banned by ccxt#27253. Use `watch_trades` + client aggregation.
- **Raw `op.execute("SELECT create_hypertable(...)")` in migrations** — D-27 forbids; helpers always. Migration 0014 (continuous aggregates) is the lone carve-out and must justify inline.
- **Single global APScheduler `PostgresJobStore`** — that's v3 nomenclature. Use `SQLAlchemyDataStore` (v4).
- **`ON DELETE CASCADE` anywhere in migrations** — Phase 0 pre-commit grep guard blocks the commit.
- **Tracking ws task completion via `task.done()` polling** — TaskGroup handles cancellation correctly; manual polling races with the watchdog.
- **Pydantic `.dict()` / `.json()`** — v1 API; use `.model_dump()` / `.model_dump_json()` on v2.
- **Storing L2 levels as one row per (symbol, ts, level_idx)** — D-58 specifies JSONB arrays (`bids JSONB`, `asks JSONB`). One row per snapshot is correct; multi-row blows up storage 20× and makes the Phase 3 book-walk worse.

---

## 3. Storage Schema (STOR-01..10, DATA-12)

### 3.1 Hypertable inventory (canonical — from D-58)

This table is the contract for migrations 0003 → 0014. Every row is a deliverable for the planner.

| Table | Hypertable | PK / dedup key | `chunk_interval` | `compress_segmentby` | `compress_after` | Special notes |
|-------|-----------|------|-------|------|------|---------------|
| `raw_mexc_candles_1m` | yes | `(symbol, ts)` | 1 day | `symbol` | 7 days | base for all CAs (D-67) |
| `raw_mexc_candles_5m/15m/1h/4h` | **NO — continuous aggregate** view over 1m | (sym, time_bucket) | — | — | — | D-67 CA pattern; refresh policy locked |
| `raw_mexc_candles_1d` | yes | `(symbol, ts)` | 90 days | `symbol` | 30 days | independent from 1m; cross-validate via SUM |
| `raw_mexc_funding` | yes | `(symbol, settlement_ts)` | 30 days | `symbol` | 7 days | both `settlement_ts` + `published_ts`; Pitfall 2 |
| `raw_mexc_oi` | yes | `(symbol, ts)` | 7 days | `symbol` | 7 days | hourly cadence |
| `raw_mexc_trades` | yes | `(symbol, exchange_trade_id)` w/ fallback `(symbol, ts, side, price, qty)` | 1 day | `symbol` | 2 days | aggressive compression |
| `raw_mexc_l2_top20` | yes | `(symbol, ts)` | 1 day | `symbol` | 2 days | `bids JSONB`, `asks JSONB` (arrays of `[price, qty]`); **top-20, not top-10** |
| `raw_mexc_liquidations` | yes | `(symbol, ts, side, qty, price)` | 7 days | `symbol` | 7 days | dedup by tuple; vendor often lacks stable id |
| `raw_coinglass_funding_agg` | yes | `(symbol, ts, source)` | 30 days | `symbol` | 7 days | `source='coinglass_aggregate'` |
| `raw_coinglass_oi` | yes | `(symbol, ts, source)` | 30 days | `symbol` | 7 days | may split per-exchange in future |
| `raw_coinglass_liq` | yes | `(symbol, ts, source)` | 7 days | `symbol` | 7 days | aggregate |
| `raw_coinglass_lsr` | yes | `(symbol, ts, source)` | 30 days | `symbol` | 7 days | long/short ratio |
| `raw_coingecko_market` | yes | `(symbol, ts, source)` | 90 days | `source` | 30 days | daily cadence |
| `universe_snapshots` | yes | `(snapshot_date, symbol)` | 90 days | NONE (tiny) | — | one row per (date, sym) qualifying |
| `symbols` | **NO (relational)** | `(symbol)` PK | — | — | — | soft-delete via `delisted_at` |
| `dead_letter` | yes | `(id UUID)` | 30 days | `source` | 30 days | DATA-11 |
| `ingest_runs` | yes | `(id UUID)` | 30 days | `source` | 30 days | per-job run telemetry |

### 3.2 Source CHECK constraint (D-59)

Every derivatives row carries `source TEXT NOT NULL` with:

```sql
ALTER TABLE raw_mexc_funding ADD CONSTRAINT ck_raw_mexc_funding_source
    CHECK (source IN ('mexc_native', 'coinglass_aggregate', 'coinglass_mexc_only', 'coingecko'));
```

For MEXC-native tables, the value is *always* `'mexc_native'`. The CHECK is still added per-table (consistency + cheap insurance against future code paths writing wrong source). A CI grep test asserts every `raw_*` migration contains `CHECK (source IN`.

**Domain alignment:** The `Source` Literal in `src/shortfire/domain/market.py` currently is `Literal["mexc", "coinglass", "coingecko"]`. **Phase 1 Wave 1 must update this to**:

```python
Source = Literal["mexc_native", "coinglass_aggregate", "coinglass_mexc_only", "coingecko"]
```

This is a deliberate domain-type change flagged in CONTEXT.md `<code_context>`. The Phase 0 Hypothesis tests on `Candle` will need to be updated in the same commit (replace `source='mexc'` → `source='mexc_native'`).

### 3.3 `quality_flag` enum (D-60)

```sql
ALTER TABLE raw_mexc_candles_1m ADD CONSTRAINT ck_raw_mexc_candles_1m_quality
    CHECK (quality_flag IN (
        'ok', 'gap_detected', 'partial_candle', 'late_arrival',
        'ws_rest_divergence', 'schema_warn', 'partial_capture'
    ));
```

Meaning per value:

| Value | When set | Effect downstream |
|-------|----------|-------------------|
| `ok` | Default; no anomaly | Use normally |
| `gap_detected` | Gap detector found a missing bar before/after | Phase 2 feature pipeline filters or fills explicitly (no implicit bfill) |
| `partial_candle` | Live aggregation captured incomplete minute (current minute) | Exclude from feature compute until rolled |
| `late_arrival` | Row inserted after the next interval started | Tag for forensics |
| `ws_rest_divergence` | Periodic REST cross-check showed >0.5% mismatch | Investigate; consider quarantine |
| `schema_warn` | Pydantic validator emitted a non-fatal warning | Forensic only |
| `partial_capture` | Liquidations REST-poll fallback active (D-48) | Phase 2 must know fidelity is degraded |

**Critical:** `bfill` / `interpolate` are banned in Phase 2 (FEAT-14); Phase 1 doesn't need to enforce yet, but writing the `quality_flag` correctly NOW is what makes the future ban work — features can branch on flag values rather than blindly interpolating.

### 3.4 `universe_snapshots` schema + point-in-time query (D-64, UNIV-01..04)

```sql
CREATE TABLE universe_snapshots (
    snapshot_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    volume_24h_usd NUMERIC(28, 10) NOT NULL,
    price_usd NUMERIC(20, 10),
    is_qualifying BOOLEAN NOT NULL,           -- 24h volume > $500K (UNIV-01)
    source TEXT NOT NULL DEFAULT 'mexc_native',
    quality_flag TEXT NOT NULL DEFAULT 'ok',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, symbol),
    CONSTRAINT ck_universe_snapshots_source CHECK (source IN ('mexc_native','coinglass_aggregate','coinglass_mexc_only','coingecko'))
);
SELECT create_hypertable('universe_snapshots', 'snapshot_date', chunk_time_interval => INTERVAL '90 days');
```

**Point-in-time query (the canonical UNIV-03 invariant):**

```sql
-- Symbols qualifying AT date T (NOT "currently qualifying"):
SELECT symbol
FROM universe_snapshots
WHERE snapshot_date = $1::DATE
  AND is_qualifying = TRUE;
```

**Hypothesis property test (UNIV-03):** Seed two synthetic snapshots T0 and T1 with a known symbol disappearing between them. Assert `universe_at(T0)` contains the symbol; `universe_at(T1)` doesn't. Assert deletes to live `symbols` table don't change historical query results (proof of immutability of snapshots).

**New-listing detection (UNIV-04):** At the tail of the daily snapshot job, `set_today = set(today's symbols)`, `set_yesterday = set(yesterday's symbols)`, `new = set_today - set_yesterday`. For each new symbol: write `universe.symbol.new` structlog event + Telegram alert + lookup/upsert into `symbols` table with `first_seen_at = now()`.

### 3.5 Continuous aggregates (D-67) — recommended helper

CONTEXT.md gives the choice between (a) adding `create_continuous_aggregate(...)` to `shortfire.db.timescale` and (b) inline `op.execute` per CA. **This research recommends (a)** because:

1. Pattern repeats 4× (5m/15m/1h/4h) → DRY benefit.
2. Phase 0 D-27 spirit is "no raw `op.execute` for TimescaleDB DDL" — keeping the discipline.
3. CA helper is testable in isolation against testcontainers (Phase 0 harness).

Suggested signature:

```python
def create_continuous_aggregate(
    view_name: str,
    source_table: str,
    bucket: str,                     # e.g. '5 minutes'
    select_columns: str,             # full SELECT clause expression
    group_by: str = "symbol, time_bucket(:bucket, ts)",
    start_offset: str = "2 hours",
    end_offset: str = "5 minutes",
    schedule_interval: str = "5 minutes",
) -> None:
    """Create a TimescaleDB continuous aggregate + refresh policy.

    Used in migration 0014 for 5m/15m/1h/4h OHLCV rollups (D-67).
    """
    op.execute(text(f"""
        CREATE MATERIALIZED VIEW {view_name}
        WITH (timescaledb.continuous) AS
        SELECT {select_columns}
        FROM {source_table}
        GROUP BY {group_by};

        SELECT add_continuous_aggregate_policy(
            '{view_name}',
            start_offset => INTERVAL '{start_offset}',
            end_offset   => INTERVAL '{end_offset}',
            schedule_interval => INTERVAL '{schedule_interval}'
        );
    """))
```

**Refresh policies per D-67:**

| View | `bucket` | `start_offset` | `end_offset` | `schedule_interval` |
|------|----------|----------------|--------------|---------------------|
| `raw_mexc_candles_5m` | 5 minutes | 2 hours | 5 minutes | 5 minutes |
| `raw_mexc_candles_15m` | 15 minutes | 4 hours | 15 minutes | 15 minutes |
| `raw_mexc_candles_1h` | 1 hour | 12 hours | 1 hour | 1 hour |
| `raw_mexc_candles_4h` | 4 hours | 2 days | 4 hours | 4 hours |

All `start_offset` < 7 days (the compression-after window on 1m), so refreshes never touch compressed chunks.

**SELECT clause for `raw_mexc_candles_5m`** (mirrors D-67):

```sql
SELECT
    symbol,
    time_bucket('5 minutes', ts) AS ts,
    first(open, ts) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, ts) AS close,
    sum(volume) AS volume,
    max(quality_flag) AS quality_flag,   -- propagate worst flag in bucket via string ORDER (planner must verify the ORDER is meaningful — alphabetical is not by severity; this needs a CASE WHEN or a separate severity column. See Open Questions.)
    'mexc_native'::TEXT AS source
FROM raw_mexc_candles_1m
GROUP BY symbol, time_bucket('5 minutes', ts);
```

**[ASSUMED] gotcha flagged for planner:** `max(quality_flag)` ranks alphabetically — `'partial_candle' > 'ok'` so worst flag wins by coincidence for the current enum. Planner should consider replacing with `CASE` mapping or a numeric `quality_severity SMALLINT` column to guarantee monotonicity. Lower-risk decision: ship `max(quality_flag)` in Phase 1 and add the severity column in Phase 2 if the alphabetical accident breaks down.

### 3.6 `symbols` lookup + tier-1 designation (D-63, D-46, specifics §3)

CONTEXT.md specifies the table; CONTEXT.md §Specifics §3 extends it with `tier INTEGER`:

```sql
CREATE TABLE symbols (
    symbol TEXT PRIMARY KEY,                  -- ccxt unified 'BTC/USDT:USDT'
    exchange TEXT NOT NULL DEFAULT 'mexc',
    market_type TEXT NOT NULL DEFAULT 'swap',
    mexc_native_symbol TEXT NOT NULL,         -- 'BTC_USDT' (D-40)
    coinglass_symbol TEXT,                    -- 'BTC'
    coingecko_id TEXT,                        -- 'bitcoin'
    tier INTEGER NOT NULL DEFAULT 2,          -- 1 = top-50 by 7d vol (5s L2), 2 = rest (10s L2)
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delisted_at TIMESTAMPTZ,                  -- NULL = live; soft delete
    listed_at TIMESTAMPTZ
);
```

`tier` is rewritten daily by the universe snapshot job after sorting last-7d volume; only top-50 get tier=1.

---

## 4. Multi-source ingest patterns (DATA-01..12)

### 4.1 ccxt MEXC client setup (D-40, D-41)

```python
# src/shortfire/ingest/mexc/client.py
import ccxt.pro as ccxtpro
from shortfire.settings.data_platform import DataPlatformSettings


def build_mexc_swap_client(settings: DataPlatformSettings) -> ccxtpro.mexc:
    if settings.mexc is None:
        raise RuntimeError("DataPlatformSettings.mexc must be configured for live ingest")
    return ccxtpro.mexc({
        "apiKey": settings.mexc.read_api_key.get_secret_value(),
        "secret": settings.mexc.read_api_secret.get_secret_value(),
        "enableRateLimit": True,         # D-73 defense-in-depth ON
        "options": {
            "defaultType": "swap",        # D-40: USDT-perp futures
            "recvWindow": 10000,          # 10s instead of default 5s — buffer for Railway egress jitter
        },
        # exchange.verbose = False — Pitfall 8 (never log signing material)
    })
```

**Symbol convention:** ccxt unified format `BTC/USDT:USDT` everywhere; only `symbols.mexc_native_symbol` stores `BTC_USDT` for the eventual Phase 5 trade-send path.

### 4.2 Backfill recipe: paginated OHLCV (D-42, STOR-08)

```python
# src/shortfire/ingest/mexc/backfill.py
from datetime import datetime, timedelta, timezone
import asyncio

TIMEFRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
                "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

async def backfill_ohlcv(
    client, symbol: str, timeframe: str,
    since: datetime, until: datetime,
    semaphore: asyncio.Semaphore,
) -> int:
    """Paginated REST backfill — 1000 candles per page; idempotent via copy_into_hypertable."""
    ms_step = TIMEFRAME_MS[timeframe] * 1000  # 1000-candle page
    cursor = int(since.timestamp() * 1000)
    end_ms = int(until.timestamp() * 1000)
    total = 0
    async with semaphore:
        while cursor < end_ms:
            data = await client.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
            if not data:
                break
            records = [
                (symbol, datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                 row[1], row[2], row[3], row[4], row[5],
                 'mexc_native', 'ok')
                for row in data
            ]
            n = await copy_into_hypertable(
                engine, "raw_mexc_candles_1m" if timeframe == "1m" else f"raw_mexc_candles_{timeframe}",
                records,
                columns=("symbol","ts","open","high","low","close","volume","source","quality_flag"),
                conflict_columns=("symbol","ts"),
            )
            total += n
            # Advance cursor by the highest ts seen + one bar
            cursor = data[-1][0] + TIMEFRAME_MS[timeframe]
    return total


async def backfill_universe(client, symbols: list[str], timeframes: list[str], since: datetime):
    sem = asyncio.Semaphore(8)  # D-42 bounded concurrency
    until = datetime.now(timezone.utc)
    async with asyncio.TaskGroup() as tg:
        for sym in symbols:
            for tf in timeframes:
                tg.create_task(backfill_ohlcv(client, sym, tf, since, until, sem))
```

**Note:** for 1m timeframe, write to `raw_mexc_candles_1m` (CONTEXT.md D-58); for 1d, write to `raw_mexc_candles_1d`. 5m/15m/1h/4h are continuous aggregates and need NO backfill — they materialize from the 1m base automatically on first refresh after the 1m backfill completes.

### 4.3 Live OHLCV: trades→1m client-side aggregator (D-43)

`watch_ohlcv` is BANNED (ccxt#27253). Implementation:

```python
# src/shortfire/ingest/mexc/live_candles.py — sketch
from collections import defaultdict
from datetime import datetime, timezone

class MinuteAggregator:
    def __init__(self) -> None:
        self.partial: dict[str, dict] = {}   # symbol → {ts, o, h, l, c, v}

    def on_trade(self, symbol: str, ts: datetime, price: Decimal, qty: Decimal) -> dict | None:
        """Returns a finalized 1m candle dict when the minute rolls over."""
        bucket_ts = ts.replace(second=0, microsecond=0)
        if symbol not in self.partial:
            self.partial[symbol] = {"ts": bucket_ts, "o": price, "h": price, "l": price, "c": price, "v": qty}
            return None
        cur = self.partial[symbol]
        if bucket_ts != cur["ts"]:
            # Roll: emit the previous bucket and start a new one
            finalized = cur
            self.partial[symbol] = {"ts": bucket_ts, "o": price, "h": price, "l": price, "c": price, "v": qty}
            return finalized
        # Update partial
        cur["h"] = max(cur["h"], price)
        cur["l"] = min(cur["l"], price)
        cur["c"] = price
        cur["v"] += qty
        return None


async def trades_aggregator_loop(client, symbols: list[str]):
    agg = MinuteAggregator()
    buffer: list[tuple] = []
    while True:
        try:
            trades = await client.watch_trades_for_symbols(symbols)  # ccxt Pro batch ws
            for t in trades:
                fin = agg.on_trade(t["symbol"], _ts_from_ms(t["timestamp"]), Decimal(str(t["price"])), Decimal(str(t["amount"])))
                if fin:
                    buffer.append((t["symbol"], fin["ts"], fin["o"], fin["h"], fin["l"], fin["c"], fin["v"], "mexc_native", "ok"))
            if buffer:
                await copy_into_hypertable(engine, "raw_mexc_candles_1m", buffer,
                    columns=("symbol","ts","open","high","low","close","volume","source","quality_flag"),
                    conflict_columns=("symbol","ts"))
                update_freshness_gauge("mexc_native", "candles_1m", buffer)
                buffer.clear()
        except Exception as e:
            METRICS["ws_reconnects_total"].labels(source="mexc_native", stream="trades").inc()
            log.warning("trades_aggregator: reconnecting", exc_info=e)
            await asyncio.sleep(2.0)
```

**Tradeoff flagged:** Client-side aggregation means a deploy mid-minute loses the partial bucket (the in-memory state isn't persisted). The next bucket from REST backfill (`mexc.candles.backfill.1d` cron) repairs it within 24h. This is acceptable per CONTEXT.md scope; the gap arrives flagged `partial_candle` via the cross-REST check (D-49 step 4).

### 4.4 L2 sampling (D-46, DATA-05)

```python
# src/shortfire/ingest/mexc/orderbook.py — sketch
async def l2_sample_loop(client, symbol: str, sample_seconds: float):
    """Tier-1 symbols pass sample_seconds=5.0; rest pass 10.0 (D-46)."""
    last_emit = 0.0
    while True:
        try:
            book = await client.watch_order_book(symbol, limit=20)
            now = time.monotonic()
            if now - last_emit < sample_seconds:
                continue
            last_emit = now
            record = (
                symbol,
                _ts_from_ms(book["timestamp"]),
                json.dumps([[bid[0], bid[1]] for bid in book["bids"][:20]]),
                json.dumps([[ask[0], ask[1]] for ask in book["asks"][:20]]),
                "mexc_native", "ok",
            )
            await copy_into_hypertable(engine, "raw_mexc_l2_top20", [record],
                columns=("symbol","ts","bids","asks","source","quality_flag"),
                conflict_columns=("symbol","ts"))
            update_freshness_gauge("mexc_native", "l2_top20", [record])
        except Exception:
            METRICS["ws_reconnects_total"].labels(source="mexc_native", stream="l2").inc()
            await asyncio.sleep(2.0)
```

**Storage budget sanity check** (from CONTEXT.md Specifics §2): 200 symbols × 17,280 snapshots/day (5s tier-1) × 365 days = 1.26B rows if narrow; 600M with JSONB wide. JSONB wide wins. After 2-day compression policy (D-58), per-snapshot row should compress to ~1–2 KB, giving ~700 GB uncompressed → ~70 GB compressed at 10× ratio. Railway storage cost driver — flag for Phase 2 retention review.

### 4.5 Funding ingest with dual timestamps (D-44, Pitfall 2)

```python
# src/shortfire/ingest/mexc/funding.py — sketch
async def funding_live_loop(client, symbols: list[str]):
    while True:
        try:
            for sym in symbols:
                f = await client.watch_funding_rate(sym)
                # MEXC ccxt returns 'fundingTimestamp' (settlement) and 'datetime' (published-when-received)
                record = (
                    sym,
                    _ts_from_ms(f["fundingTimestamp"]),   # settlement_ts
                    _ts_from_ms(f["timestamp"]),          # published_ts
                    f["fundingRate"],
                    "mexc_native", "ok",
                )
                await copy_into_hypertable(engine, "raw_mexc_funding", [record],
                    columns=("symbol","settlement_ts","published_ts","funding_rate","source","quality_flag"),
                    conflict_columns=("symbol","settlement_ts"))
                update_freshness_gauge("mexc_native", "funding", [record])
        except Exception:
            METRICS["ws_reconnects_total"].labels(source="mexc_native", stream="funding").inc()
            await asyncio.sleep(2.0)
```

Note: ccxt's funding-rate response field names are not perfectly stable across exchanges; planner must verify against actual ccxt 4.5.x response shape for MEXC swap during the planning fixture-capture step.

### 4.6 Coinglass: batch funding endpoint over per-symbol polling (D-53, Pitfall 12)

```python
# src/shortfire/ingest/coinglass/funding_agg.py — sketch
async def fetch_coinglass_funding_batch(client: httpx.AsyncClient, settings) -> list[dict]:
    """One call returns all symbols — cheaper than per-symbol polling."""
    async with COINGLASS_LIMITER:
        r = await client.get(
            "https://open-api-v4.coinglass.com/api/futures/funding-rate-list",
            headers={"CG-API-KEY": settings.coinglass.api_key.get_secret_value()},
        )
        if r.status_code >= 400:
            await write_to_dead_letter("coinglass", "funding-rate-list", r.text,
                                       "HTTPStatusError", f"HTTP {r.status_code}")
            return []
        try:
            payload = FundingRateListResponse.model_validate_json(r.content)
        except ValidationError as e:
            await write_to_dead_letter("coinglass", "funding-rate-list", r.text,
                                       "ValidationError", str(e)[:2000])
            return []
        return payload.to_records()
```

**Round-robin per-symbol endpoints** (OI, Liquidations, LSR — D-53): at 28 req/min budget and 200 symbols, full sweep takes ~7.2 minutes. The scheduler runs the job every 5 minutes (D-77); on tick N+1, resume from `state.last_symbol_index` so each symbol gets coverage roughly every 7 min. Persist `last_symbol_index` in `ingest_runs` table or a small `kv_state` table (planner picks; `ingest_runs` is the simpler home).

---

## 5. Continuous aggregates + scheduling (STOR-05, ORCH-01..02)

See §3.5 for the CA SQL pattern. Scheduler-side, **continuous aggregates are NOT APScheduler jobs** — TimescaleDB's own background worker runs them per `add_continuous_aggregate_policy`. The only Phase 1 cron interaction is:

- **`mexc.candles.backfill.1d`** (`IntervalTrigger(hours=24)`): sweeps the universe and runs the gap-repair backfill so the 1m base table has the data the CAs depend on.
- No need to manually refresh CAs from APScheduler — Timescale's policy handles it.

**Optional but recommended:** A `compaction.refresh.audit` job that queries `timescaledb_information.continuous_aggregates` once a day and exports refresh-lag metrics to Prometheus. Surfaces silent CA staleness. Not in CONTEXT.md D-77; **this research recommends adding it** as a Phase 1 add-on if the Wave 4 budget allows.

---

## 6. Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token-bucket rate limiter | Hand-rolled `asyncio.Semaphore + sleep` | `aiolimiter.AsyncLimiter` | Battle-tested; correct under cancellation; CONTEXT.md D-51/D-56 |
| Exponential backoff with jitter | `for attempt in range(5): try ... except: time.sleep(2**attempt)` | `tenacity` decorators | Jitter algorithm matters for thundering herd; CONTEXT.md D-72 |
| MEXC ws reconnect protocol | Raw `websockets` library + manual JSON | `ccxt.pro.mexc.watch_*` | ccxt Pro is included free in `pip install ccxt`; handles ping/pong, resync, error recovery; PITFALLS.md Pitfall 11 + CLAUDE.md anti-list |
| Cron / interval scheduler with restart-safety | `while True: await sleep(60)` loops | APScheduler 4 `AsyncScheduler` + `SQLAlchemyDataStore` | Restart-safe via Postgres; misfire handling; coalesce on burst; CONTEXT.md D-75 |
| TimescaleDB hypertable DDL | Raw `op.execute("SELECT create_hypertable(…)")` | Phase 0 `shortfire.db.timescale.create_hypertable` | D-27 mandate; centralizes if-not-exists semantics |
| Hot-path Postgres COPY | `INSERT … VALUES (…), (…), (…)` loops | `asyncpg.Connection.copy_records_to_table` | 50–100× faster on 1k+ row batches; CONTEXT.md D-70 |
| Continuous aggregate refresh | Cron job that materializes views | TimescaleDB `add_continuous_aggregate_policy` | Native to engine; respects compressed chunks; CONTEXT.md D-67 |
| Time-zone handling | Naive datetimes + offset arithmetic | `datetime.now(timezone.utc)` + Pydantic `@model_validator` rejecting naive | Pitfall 17; Phase 0 enforces via guard |
| S3-compatible upload | `requests.put` to R2 | `boto3` S3 client pointed at R2 endpoint | R2 advertises full S3 API compatibility; lifecycle + object-lock requires boto3-shape calls |
| Telegram bot framework | Lightweight commands needed → bring in `python-telegram-bot` | **In Phase 1, raw `httpx.AsyncClient.post`** to Bot API `/sendMessage` | D-86: 4 message types; ~50 LOC; no async framework dep until Phase 4 |
| Dedup logic on (symbol, ts, source) | App-side hash set / pre-INSERT SELECT | Postgres `ON CONFLICT (…) DO NOTHING` on the hypertable PK | DB-level dedup is race-free and idempotent on retry |
| Per-tier L2 sampling state machine | Closures + global dicts | `dict[symbol, asyncio.Task]` registry inside watchdog scope under TaskGroup | Avoids GC fire-and-forget; Pitfall 27 |
| Universe filter ($500K volume threshold) | Hand-roll loop over ticker dicts | `await mexc_client.fetch_tickers()` → filter `.quoteVolume > 500_000` → write rows | ccxt unifies the ticker volume field across exchanges; single line of filter |

**Key insight:** Phase 1 is mostly about *gluing together libraries correctly*, not building algorithms. The areas where hand-rolling is unavoidable are (a) the 1m candle aggregator (no library does this for MEXC with sufficient quality control), (b) the universe snapshot job (project-specific business rule), (c) the dead-letter routing logic (specific to our schema). Everything else has a battle-tested library.

---

## 7. Common Pitfalls

> Cross-referenced to `.planning/research/PITFALLS.md`. Phase 1 explicitly addresses Pitfalls 1, 4, 11, 16, 17, 21, 26, 27.

### Pitfall 1: Survivorship-biased universe
**Mitigation:** `universe_snapshots` hypertable, point-in-time query (UNIV-03 invariant), `symbols.delisted_at` soft delete (D-63). **Verification:** Hypothesis property test — see §10.

### Pitfall 4: Unrealistic slippage from missing L2 capture
**Mitigation:** L2 top-20 sampled 5–10s starting Phase 1 commit-zero (D-46). **Acceptance:** no backfill — Phase 3 backtester slippage is constrained to forward-captured snapshots (D-39).

### Pitfall 11: Stale websocket / silent data starvation
**Mitigation:** Per-symbol-per-stream freshness gauge updated on every successful row; APScheduler `freshness.check` cron every 1 min compares `now - gauge` to expected lag thresholds (D-49, D-77, D-84, D-87). Heartbeat watchdog in TaskGroup respawns hung streams (D-49 step 3). Cross-REST check every 60s for one tier-1 symbol (D-49 step 4).

### Pitfall 16: Confusing Coinglass aggregate with MEXC-native funding/OI
**Mitigation:** `source` CHECK constraint on every derivatives row, value `'mexc_native'` vs `'coinglass_aggregate'` (D-59). Strategy / feature pipelines in Phase 2 join on `source` explicitly.

### Pitfall 17: Time zone bugs
**Mitigation:** TIMESTAMPTZ enforced at three layers (Pydantic validator → asyncpg/Postgres TIMESTAMPTZ → pre-commit grep guard); `funding_rate` uses both `settlement_ts` + `published_ts` per Pitfall 2; APScheduler crons specify `timezone="UTC"`.

### Pitfall 21: Backfill gaps without interpolation
**Mitigation:** `quality_flag = 'gap_detected'` instead of `bfill` (D-60). Gap detector: after backfill completes for a (symbol, timeframe), compute `count(*) per day` vs expected; for missing buckets, INSERT a synthetic row with NULL OHLC and `quality_flag='gap_detected'` so feature pipelines see explicit gap markers. **NOT YET in scope per CONTEXT.md** — flagged for planner: gap-injection helper is small (~30 LOC) and pays off in Phase 2; recommend including as part of the Wave 2 backfill task.

### Pitfall 26 (Phase 1 specific): Coinglass aggregate ≠ Coinglass-mexc-only
**Mitigation:** Schema reserves `coinglass_mexc_only` source value in D-59; Phase 1 writes `coinglass_aggregate` by default. Per-exchange split deferred to Phase 2 EDA decision.

### Pitfall 27: Fire-and-forget asyncio
**Mitigation:** Every long-lived task under `asyncio.TaskGroup` (D-46, D-78). Explicit watchdog respawn loop. No bare `asyncio.create_task(...)` in Phase 1 code.

### Phase-1-specific pitfalls NOT in PITFALLS.md

**P1-A: APScheduler 4 misfire burst on deploy.**
After a 30-min deploy gap, APScheduler will fire every missed run immediately. **Mitigation:** every poll-based job uses `coalesce=True` + `misfire_grace_time` per Pattern 5. CONTEXT.md doesn't specify; this research mandates it.

**P1-B: Compression locks during inserts.**
TimescaleDB compression on a chunk takes a lock that blocks INSERT into that chunk briefly. Our 7-day age window means compression only ever touches week-old chunks — concurrent live ingest writes to today's chunk. Safe by construction *as long as* backfill never targets chunks older than 7 days while live ingest is running. Backfill is one-shot operational task, so this is fine.

**P1-C: Continuous aggregate refresh on compressed chunks.**
TimescaleDB 2.18+ supports CA refresh over compressed chunks, but it's slower. CONTEXT.md D-67 sets all `start_offset < 7 days` to keep refresh inside uncompressed window. **Don't change these values** without re-verifying performance.

**P1-D: asyncpg + SQLAlchemy async engine connection sharing.**
The `copy_into_hypertable` helper needs the raw asyncpg connection. SQLAlchemy 2.0.x `engine.connect()` returns an `AsyncConnection`; getting at the raw `asyncpg.Connection` requires `.driver_connection` (works) or `(await conn.get_raw_connection()).driver_connection` (more robust). **Test this against the actual pinned version during Wave 1 of the plan.**

**P1-E: ccxt symbol convention drift.**
ccxt `BTC/USDT:USDT` is unified swap futures; MEXC native is `BTC_USDT`. The `symbols` table maps both. ANY code path that calls MEXC private API in Phase 5 must read `mexc_native_symbol`; Phase 1 only uses unified. **Lint rule deferred to Phase 5**, but make sure Phase 1 ingest stays on the unified form throughout.

**P1-F: `fetch_tickers()` returns currently-listed only.**
For the daily universe snapshot, `await mexc.fetch_tickers()` returns the live set. To detect delistings, compare today's set against `symbols.delisted_at IS NULL`. Symbols present yesterday but absent today get `UPDATE symbols SET delisted_at = now() WHERE symbol = ?`. This is the only place "delistings" are inferred — Phase 1 has no other detection mechanism, and it's sufficient.

**P1-G: Coinglass response schema drift.**
Coinglass occasionally renames JSON fields without breaking changes notice. Mitigation: Pydantic `model_config = ConfigDict(extra='allow')` on Coinglass schemas so unknown fields don't fail validation; `quality_flag='schema_warn'` set if validation emits a warning hook (planner adds a Pydantic warning collector if Phase 1 budget allows; otherwise schema drift surfaces in `dead_letter` and that's acceptable).

---

## 8. Backup & Restore (STOR-10)

### 8.1 Daily pg_dump job

```python
# src/shortfire/ingest/backup/pg_dump_r2.py — sketch
import subprocess
from datetime import datetime, timezone
import boto3
from botocore.config import Config

async def daily_pg_dump_to_r2(settings) -> None:
    """Run pg_dump, stream stdout into R2 (multipart upload)."""
    if settings.r2_backup is None:
        log.warning("backup.skipped — r2_backup not configured")
        return

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"daily/{ts}.dump.zst"

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_backup.account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_backup.access_key_id.get_secret_value(),
        aws_secret_access_key=settings.r2_backup.secret_access_key.get_secret_value(),
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "adaptive"}),
    )

    # D-80: --format=custom --compress=zstd:9
    proc = subprocess.Popen(
        ["pg_dump", "--format=custom", "--compress=zstd:9", "--no-owner", "--no-acl",
         settings.database_url.replace("postgresql+asyncpg://", "postgresql://")],
        stdout=subprocess.PIPE,
    )
    try:
        s3.upload_fileobj(proc.stdout, settings.r2_backup.bucket_name, key)
        proc.wait(timeout=3600)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump exited with code {proc.returncode}")
    finally:
        if proc.poll() is None:
            proc.kill()

    METRICS["backup_age_seconds"].set(0)  # fresh upload — age = 0
    log.info("backup.completed", key=key, bucket=settings.r2_backup.bucket_name)
```

**Caveats for planner:**
- `pg_dump` uses synchronous stdio pipes; running it inside an async job is fine because the upload is the bottleneck. If memory pressure becomes an issue, switch to `aioboto3` for streaming multipart upload.
- Railway containers do not include `pg_dump` in the base Python image; the **Dockerfile must `apt-get install postgresql-client-16`** (must match Postgres 16 server version to avoid `pg_dump: aborting because of server version mismatch`).
- `--no-owner --no-acl` recommended so restore into a fresh server doesn't fail on missing roles.
- `compress=zstd:9` requires `pg_dump` 16+; the postgresql-client-16 package satisfies this.

### 8.2 Retention (D-81)

`7 daily + 4 weekly + 6 monthly + indefinite annual = ~17 dumps`. Implementation can use either:

1. R2 **lifecycle rules** (preferred — no code): "delete objects with prefix `daily/` older than 7 days" + analogous rules for `weekly/`/`monthly/`. Requires moving objects between prefixes — adds complexity.
2. **Sundown sweep job** (simpler): the same `daily_pg_dump_to_r2` job, after success, lists existing dumps and deletes those outside retention. ~40 LOC.

**This research recommends option 2** for Phase 1 (single language, testable, no external lifecycle config). Move to option 1 in Phase 5 when ops surface is closer.

### 8.3 Restore drill (D-82)

`docs/RESTORE.md` checklist (planner writes this — content sketch):

1. Spin up local `postgres:16` + `timescaledb:2.18.0-pg16` via docker-compose (Phase 0 already has this).
2. `aws s3 cp s3://shortfire-backups/daily/<ts>.dump.zst restore.dump --endpoint-url=...`
3. `pg_restore --verbose --no-owner --no-acl --dbname=shortfire restore.dump`
4. `psql -c "SELECT count(*) FROM timescaledb_information.hypertables"` → expect ≥ N hypertables (where N is locked at Phase 1 ship).
5. Sample row count per hypertable within ±10% of production.
6. Run smoke pytest (`pytest tests/integration/db/test_alembic_and_hypertables.py -v`) against the restored DB.

Drill manually first time, document in markdown, automate later (Phase 5).

---

## 9. Service Topology + CI/CD (OPS-05, OPS-06)

Already locked in Phase 0:
- `railway.toml` + `railway.strategy-engine.toml` + `railway.dashboard.toml` ship 3 services from one Docker image.
- `preDeployCommand = ["alembic upgrade head"]` runs migrations before traffic on `data-platform`.
- GitHub Actions CI: ruff + pyright + pytest + gitleaks → blocks merge.
- Auto-deploy on push to `main`.

**Phase 1 deltas:**
1. Dockerfile must install `postgresql-client-16` (for `pg_dump` in the backup job). One line: `RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 && rm -rf /var/lib/apt/lists/*`.
2. `pyproject.toml [tool.coverage.run] omit` removes `"src/shortfire/ingest/*"` (D-91) — coverage gate now sees Phase 1 code.
3. New Railway env vars to wire (planner adds to `.env.example` placeholders): `MEXC__READ_API_KEY`, `MEXC__READ_API_SECRET`, `COINGLASS__API_KEY`, `COINGECKO__API_KEY`, `TELEGRAM__BOT_TOKEN`, `TELEGRAM__OPERATOR_CHAT_ID`, `R2__ACCOUNT_ID`, `R2__ACCESS_KEY_ID`, `R2__SECRET_ACCESS_KEY`, `R2__BUCKET_NAME`. Real values in Railway dashboard only — never in git.
4. `data-platform` resource bump from 1 vCPU / 2 GB → 2 vCPU / 4 GB **conditional on observed OOM** (D-90); ship at Phase 0 resources first.

---

## 10. Project Constraints (from CLAUDE.md)

Constraints from CLAUDE.md the planner must honor (extracted as directives — same authority as locked decisions):

| Directive | Source | Implication for Phase 1 |
|-----------|--------|-------------------------|
| Tech stack = Python 3.12 + FastAPI + pandas/polars + ccxt + httpx | CLAUDE.md Recommended Stack | Already in `pyproject.toml`; no changes |
| PostgreSQL 16 + TimescaleDB on Railway | CLAUDE.md | Phase 0 provisioned; Phase 1 ships 12 migrations on top |
| XGBoost/LightGBM as ML baseline, PyTorch only after edge | CLAUDE.md | **Not Phase 1** — defer per ROADMAP |
| Railway deploy + GitHub Actions CI | CLAUDE.md | Phase 0 wired; Phase 1 reuses |
| **TDD with first commit — every module starts with tests** | CLAUDE.md | Every Phase 1 module ships test-first. See §11 Validation Architecture |
| **Walk-forward only — никаких random split** | CLAUDE.md | Not directly Phase 1, but Phase 1 schema enables it: `universe_snapshots` + `source` + `quality_flag` are the substrate |
| Risk = quarter-Kelly + hard stops + max concurrent | CLAUDE.md | Phase 4+, not Phase 1 |
| Live trading gated on ≥1-2 months positive paper | CLAUDE.md | Phase 5 gate |
| **Solo only, audience-wise** | CLAUDE.md | No multi-user infra; auth simple; Telegram = solo operator chat |
| Universe = $500K+ 24h volume dynamic filter | CLAUDE.md | D-64 + UNIV-01 enforces |
| Use SQLAlchemy Core (not ORM) for hot-path inserts | CLAUDE.md Recommended Stack | D-69 + D-70 enforce via `copy_into_hypertable` |
| `respx` for httpx mocks; `aioresponses` for aiohttp / ccxt; `freezegun` for time | CLAUDE.md Supporting Libraries | §11 sec covers test patterns |
| Hypothesis 6.x mandatory for trading-code invariants | CLAUDE.md | UNIV-03 point-in-time test + DATA-09 idempotency test are Hypothesis |
| Ruff (not Black+isort+flake8); pyright strict in CI | CLAUDE.md | Already configured in `pyproject.toml`; Phase 1 just adds files |
| **GSD workflow enforcement** — start work via `/gsd-*` command | CLAUDE.md | Planning agents already comply |
| **Language: respond to user in Russian** (from MEMORY) | global user memory | Plan output may include Russian-language commit messages or comments; canonical artifacts in English (REQUIREMENTS, ROADMAP, STATE) stay English |

---

## Validation Architecture

<!-- Section 11 of RESEARCH.md — header normalized to match plan-phase workflow grep ("## Validation Architecture"). -->


> Required because `workflow.nyquist_validation` is not explicitly disabled in `.planning/config.json` (defaults to enabled).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.4 + pytest-asyncio (auto mode) + Hypothesis 6.x |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (existing) |
| Quick run command | `uv run pytest tests/unit/ingest -x -q` |
| Full suite command | `uv run pytest --cov=src/shortfire --cov-report=term-missing -m "not integration or integration"` |
| Integration-only | `uv run pytest -m integration` (requires Docker + testcontainers; Phase 0 baseline lives at `tests/integration/db/test_alembic_and_hypertables.py`) |
| Coverage gate | 80% project-wide (D-91); `src/shortfire/ingest/*` REMOVED from `omit` in Phase 1 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit -x -q` (~30 sec)
- **Per wave merge:** Full suite incl. integration (`pytest -m "integration or not integration"`) — ~5 min target with the 6-day CI backfill slice per D-94
- **Phase gate:** Full suite green + coverage ≥80% + `pytest tests/integration -v` shows backfill idempotency, universe point-in-time, dead_letter routing all green

### Phase Requirements → Test Map

| Req ID | Behavior | Test type | Automated command | Wave |
|--------|----------|-----------|-------------------|------|
| DATA-01 | MEXC OHLCV ingest produces correct rows | unit (FakeMexcClient fixture) + integration | `pytest tests/integration/ingest/test_mexc_ohlcv.py -v` | Wave 2 |
| DATA-02 | Funding row has both settlement_ts + published_ts | unit (schema) + Hypothesis invariant `published_ts <= settlement_ts + 1h` | `pytest tests/unit/ingest/test_mexc_funding_schema.py` | Wave 2 |
| DATA-03 | OI hourly cadence | unit (round-robin scheduler test) | `pytest tests/unit/ingest/test_oi_round_robin.py` | Wave 3 |
| DATA-04 | Signed trades persisted in 1-min batches | unit (aggregator state machine) + integration | `pytest tests/unit/ingest/test_minute_aggregator.py` | Wave 2 |
| DATA-05 | L2 top-20 sampled per tier | unit (sampling cadence under freezegun) | `pytest tests/unit/ingest/test_l2_sampling.py` | Wave 3 |
| DATA-06 | Liquidations dual-source | unit (both code paths exercised) | `pytest tests/unit/ingest/test_liquidations.py` | Wave 3 |
| DATA-07 | Coinglass ingest under rate limit | integration via respx + aiolimiter | `pytest tests/integration/ingest/test_coinglass.py` | Wave 2 |
| DATA-08 | CoinGecko daily refresh | integration via respx | `pytest tests/integration/ingest/test_coingecko.py` | Wave 2 |
| DATA-09 | **Idempotent on (symbol, ts, source)** — re-run yields no dupes | **Hypothesis property test**: random record order, double-run, assert row count unchanged | `pytest tests/integration/ingest/test_idempotency.py -v` | Wave 1 |
| DATA-10 | Retry + rate limit | unit (tenacity policy on synthetic 5xx) + freezegun | `pytest tests/unit/ingest/test_retry_policies.py` | Wave 1 |
| DATA-11 | Pydantic failures → dead_letter | integration with intentionally malformed fixture | `pytest tests/integration/ingest/test_dead_letter.py` | Wave 1 |
| DATA-12 | source column + CHECK constraint | integration: attempt INSERT with bad source, expect rollback | `pytest tests/integration/db/test_source_check.py` | Wave 1 |
| STOR-01..04 | Hypertables exist; compression policy attached | integration extending `test_alembic_and_hypertables.py` | `pytest tests/integration/db/test_phase1_schema.py` | Wave 1 |
| STOR-05 | Continuous aggregates 5m/15m/1h/4h refresh and match SQL hand-roll | integration: seed 1m data, refresh CA, compare aggregated SUM/MAX/MIN | `pytest tests/integration/db/test_continuous_aggregates.py` | Wave 1 |
| STOR-06 | universe_snapshots hypertable + point-in-time row set | integration + Hypothesis | `pytest tests/integration/ingest/test_universe_point_in_time.py` | Wave 3 |
| STOR-07 | symbols soft-delete; CASCADE banned in DDL | grep guard (already in pre-commit) + integration | (pre-commit) + `pytest tests/integration/db/test_symbols_soft_delete.py` | Wave 1 |
| STOR-08 | 1-yr backfill idempotent (CI runs 6-day slice per D-94) | integration | `pytest tests/integration/ingest/test_backfill_6d.py -v` | Wave 2 |
| STOR-09 | quality_flag flags gaps, no interpolation | unit + integration | `pytest tests/integration/ingest/test_gap_quality_flag.py` | Wave 2 |
| STOR-10 | pg_dump → R2 succeeds; restore drill smoke-tests | manual restore drill + integration (mock R2 via `moto`) | `pytest tests/integration/backup/test_pg_dump_r2.py` (mock) + `docs/RESTORE.md` drill (manual) | Wave 4 |
| UNIV-01 | $500K filter logic | unit | `pytest tests/unit/ingest/test_universe_filter.py` | Wave 3 |
| UNIV-02 | Daily refresh writes new row set | integration | `pytest tests/integration/ingest/test_universe_daily_refresh.py` | Wave 3 |
| UNIV-03 | **Point-in-time correctness** | **Hypothesis property test** — seed N synthetic snapshots, assert `universe_at(T)` returns exactly the set qualifying at T regardless of subsequent universe changes | `pytest tests/integration/ingest/test_universe_point_in_time.py::test_point_in_time_property` | Wave 3 |
| UNIV-04 | New-listing detected within 24h | unit (diff logic) + integration (job fires Telegram alert path) | `pytest tests/integration/ingest/test_new_listing_detection.py` | Wave 3 |
| ORCH-01 | APScheduler AsyncScheduler boots with SQLAlchemyDataStore | integration (lifespan smoke test) | `pytest tests/integration/scheduler/test_scheduler_lifespan.py` | Wave 3 |
| ORCH-02 | Per-source cadence respected | unit (freezegun + scheduler.add_schedule introspection) | `pytest tests/unit/scheduler/test_job_graph.py` | Wave 3 |
| ORCH-03 | Freshness gauge updates on every write | unit (assert gauge before/after `copy_into_hypertable`) | `pytest tests/unit/ingest/test_freshness_gauges.py` | Wave 3 |
| ORCH-04 | Stale-data Telegram alert fires when gauge > 2× expected lag | integration (mock Telegram endpoint via respx, freezegun-shift time) | `pytest tests/integration/freshness/test_stale_alert.py` | Wave 4 |
| OPS-05 | commit → push → deploy works | manual smoke: push small change, verify Railway redeploys all 3 | (manual, post-deploy) | Wave 4 |
| OPS-06 | 3 Railway services live | manual smoke + `curl /health` on all 3 | (manual, post-deploy) | Wave 4 |

### Hypothesis property tests (the leakage-prevention seeds)

These are the keystone tests of Phase 1 — they catch entire classes of bugs at once.

```python
# tests/integration/ingest/test_idempotency.py
import pytest
from hypothesis import given, strategies as st, settings
from hypothesis.strategies import composite

@composite
def candle_record(draw):
    return (
        draw(st.sampled_from(["BTC/USDT:USDT", "ETH/USDT:USDT", "XYZ/USDT:USDT"])),
        draw(st.datetimes(timezones=st.just(timezone.utc))),
        # ...
        "mexc_native", "ok",
    )

@settings(max_examples=50, deadline=10_000)
@given(records=st.lists(candle_record(), min_size=0, max_size=200))
@pytest.mark.integration
@pytest.mark.asyncio
async def test_reingest_is_idempotent(timescale_db, records):
    # Run 1: insert all
    n1 = await copy_into_hypertable(timescale_db, "raw_mexc_candles_1m", records,
            columns=COLS, conflict_columns=("symbol","ts"))
    count_after_1 = await timescale_db.scalar(text("SELECT count(*) FROM raw_mexc_candles_1m"))
    # Run 2: same records, shuffled
    import random; random.shuffle(records)
    n2 = await copy_into_hypertable(timescale_db, "raw_mexc_candles_1m", records,
            columns=COLS, conflict_columns=("symbol","ts"))
    count_after_2 = await timescale_db.scalar(text("SELECT count(*) FROM raw_mexc_candles_1m"))
    assert count_after_1 == count_after_2, "Re-ingest produced duplicates"
```

```python
# tests/integration/ingest/test_universe_point_in_time.py
@given(
    early_symbols=st.sets(st.sampled_from(["A","B","C","D"]), min_size=1, max_size=4),
    late_symbols=st.sets(st.sampled_from(["A","B","C","D"]), min_size=1, max_size=4),
)
@pytest.mark.integration
async def test_universe_point_in_time_correctness(timescale_db, early_symbols, late_symbols):
    # Seed two snapshots at T-30 and T-1
    await _seed_snapshot(timescale_db, date(2025, 4, 1), early_symbols)
    await _seed_snapshot(timescale_db, date(2025, 5, 1), late_symbols)
    # Add a third snapshot at T0 with arbitrary content — must not affect historical
    await _seed_snapshot(timescale_db, date(2025, 6, 1), {"X","Y"})
    # Assert point-in-time correctness
    universe_at_t30 = await _query_universe(timescale_db, date(2025, 4, 1))
    universe_at_t1  = await _query_universe(timescale_db, date(2025, 5, 1))
    assert universe_at_t30 == early_symbols
    assert universe_at_t1 == late_symbols
```

### Wave 0 gaps

The Phase 0 test harness covers a lot. New artifacts Phase 1 needs:

- [ ] `tests/integration/ingest/test_idempotency.py` — covers DATA-09 (Hypothesis property)
- [ ] `tests/integration/ingest/test_universe_point_in_time.py` — covers UNIV-03 (Hypothesis property)
- [ ] `tests/integration/db/test_phase1_schema.py` — covers STOR-01..04 (hypertable existence + compression)
- [ ] `tests/integration/db/test_continuous_aggregates.py` — covers STOR-05
- [ ] `tests/integration/db/test_source_check.py` — covers DATA-12
- [ ] `tests/integration/ingest/test_dead_letter.py` — covers DATA-11
- [ ] `tests/integration/backup/test_pg_dump_r2.py` — covers STOR-10 (mock R2 via `moto`)
- [ ] `tests/integration/freshness/test_stale_alert.py` — covers ORCH-04
- [ ] `tests/integration/scheduler/test_scheduler_lifespan.py` — covers ORCH-01
- [ ] `tests/fakes/repos.py` — expand `InMemoryCandleRepo` with synthetic OHLCV generators (Hypothesis-friendly) per D-93
- [ ] `tests/fakes/coinglass.py` — expand with response fixtures captured from real Coinglass (read-only API key, contract test)
- [ ] `tests/fakes/mexc.py` — expand to emit synthetic trades for the minute aggregator test
- [ ] `moto` package install for R2 mocking (`pip index versions moto` to confirm; add to dev deps)

### Why these tests in particular

- **Idempotency property test** (DATA-09) catches the entire class of "re-ingest broke something" bugs — schema drift, off-by-one in cursor advance, missing `ON CONFLICT`, etc.
- **Point-in-time property test** (UNIV-03) catches the entire class of "survivorship bias snuck in" bugs — Pitfall 1 mitigation is structural.
- **CA-vs-SQL property test** (STOR-05) catches CA refresh-policy misconfiguration (e.g., wrong `bucket` or `start_offset`).
- **Dead-letter integration test** (DATA-11) confirms the entire failure-routing path: malformed Coinglass response → Pydantic ValidationError → `dead_letter` row → ingest loop unblocked.

---

## 12. Code Examples (verified patterns)

### Telegram alert via raw httpx (D-86)

```python
# src/shortfire/observability/telegram.py
import httpx
from shortfire.settings.data_platform import DataPlatformSettings

async def send_telegram_alert(settings: DataPlatformSettings, severity: str, body: str) -> None:
    """Phase 1: raw httpx — no python-telegram-bot framework dep (D-86)."""
    if settings.telegram is None:
        log.warning("telegram.skipped", severity=severity, body=body)
        return

    prefix = {"warn": "⚠️ WARN", "crit": "🚨 CRIT"}.get(severity, "ℹ️ INFO")
    msg = f"{prefix} | {body}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        url = f"https://api.telegram.org/bot{settings.telegram.bot_token.get_secret_value()}/sendMessage"
        try:
            r = await client.post(url, json={
                "chat_id": settings.telegram.operator_chat_id,
                "text": msg[:4000],  # Telegram per-msg limit 4096; leave headroom
            })
            r.raise_for_status()
        except Exception as e:
            log.error("telegram.send.failed", exc_info=e)  # don't crash the caller
```

### Freshness gauge update (D-49, D-84)

```python
# src/shortfire/ingest/freshness/gauges.py
from prometheus_client import Gauge
from datetime import datetime, timezone

SOURCE_FRESHNESS = Gauge(
    "shortfire_data_platform_source_freshness_seconds",
    "Seconds since last successful row write per (source, dataset, symbol)",
    labelnames=("source", "dataset", "symbol"),
    registry=PHASE_0_REGISTRY,  # custom CollectorRegistry from Phase 0 D-84
)

def update_freshness_gauge(source: str, dataset: str, records: list[tuple]) -> None:
    """Reset freshness to 0 for each (source, dataset, symbol) that just got fresh rows."""
    seen_symbols = {r[0] for r in records}  # records tuple position 0 = symbol per our convention
    for sym in seen_symbols:
        SOURCE_FRESHNESS.labels(source=source, dataset=dataset, symbol=sym).set(0.0)
```

**Note on cardinality:** label `symbol` across 200 symbols × 3 sources × ~10 datasets = ~6000 series. Within Grafana free-tier 10K-series budget. **If cardinality is a concern**, drop `symbol` from the gauge labels and emit per-source-per-dataset only; planner picks (recommendation: include symbol for now, audit cardinality in Wave 4).

### Stale-data alerter job (ORCH-04)

```python
# src/shortfire/ingest/freshness/alerter.py
EXPECTED_LAG = {
    ("mexc_native", "candles_1m"): 90,           # seconds
    ("mexc_native", "funding"): 8 * 3600,        # 8h MEXC funding cycle
    ("mexc_native", "oi"): 5 * 60,
    ("mexc_native", "l2_top20"): 30,
    ("mexc_native", "trades"): 90,
    ("mexc_native", "liquidations"): 5 * 60,
    ("coinglass_aggregate", "funding_agg"): 6 * 60,
    ("coinglass_aggregate", "oi"): 6 * 60,
    ("coinglass_aggregate", "liq"): 12 * 60,
    ("coinglass_aggregate", "lsr"): 18 * 60,
    ("coingecko", "market"): 25 * 3600,           # daily
}

async def freshness_check_job() -> None:
    """Cron every 1 min. Compares Prometheus gauges to expected lag and alerts."""
    from shortfire.ingest.context import get_settings, get_metrics
    settings, metrics = get_settings(), get_metrics()
    now = datetime.now(timezone.utc)

    # Iterate Prometheus gauge family — collect samples
    for sample in SOURCE_FRESHNESS.collect()[0].samples:
        if sample.name != "shortfire_data_platform_source_freshness_seconds":
            continue
        source = sample.labels["source"]
        dataset = sample.labels["dataset"]
        symbol = sample.labels["symbol"]
        # Gauge is the timestamp of last write (we set it to 0 on write — see note below)
        # ACTUALLY: switch the gauge semantics — store last_write_ts as Gauge, compute lag here
        # (see Open Questions #2)
        lag_seconds = sample.value
        expected = EXPECTED_LAG.get((source, dataset), 600)
        if lag_seconds > 2 * expected:
            await send_telegram_alert(settings, "warn",
                f"stale: {source}/{dataset}/{symbol} lag={lag_seconds:.0f}s threshold={2*expected}s")
```

**Flagged Open Question:** The gauge semantics. CONTEXT.md D-49 says "updated on every successful row write" — does the gauge store *seconds since last write* (must be recomputed continuously by some other process) or *unix timestamp of last write* (the freshness check computes the lag)? The latter is simpler — a Gauge holding `time.time()` doesn't decay, and the freshness check computes `now - gauge` each tick. Recommend latter; planner confirms.

### Dead-letter writer (D-74)

```python
# src/shortfire/ingest/dead_letter/writer.py
async def write_to_dead_letter(
    source: str,
    endpoint: str,
    symbol: str | None,
    raw_payload: str | bytes,
    error_type: str,
    error_msg: str,
    retries_attempted: int = 0,
) -> None:
    """Land a failed validation or exhausted retry into the dead_letter hypertable."""
    record = (
        uuid.uuid4(),
        datetime.now(timezone.utc),
        source,
        endpoint,
        symbol,
        raw_payload if isinstance(raw_payload, str) else raw_payload.decode("utf-8", errors="replace"),
        error_type,
        error_msg[:2000],
        retries_attempted,
        "schema_warn",
    )
    await copy_into_hypertable(
        engine,
        "dead_letter",
        [record],
        columns=("id","ts","source","endpoint","symbol","raw_payload","error_type","error_msg","retries_attempted","quality_flag"),
        conflict_columns=("id",),  # UUID PK; effectively never conflicts
    )
    METRICS["dead_letter_total"].labels(source=source, error_type=error_type).inc()
```

---

## 13. State of the Art

| Old approach | Current (Phase 1 ships this) | When changed | Impact |
|--------------|-----------------------------|--------------|--------|
| Universal narrow EAV `(symbol, ts, metric, value)` | Typed-per-source hypertables (STOR-02 explicit reject) | Phase 1 ARCHITECTURE.md Pattern 2 | 5–10× compression; 3–10× scan speed; idempotency by construction |
| APScheduler 3 `PostgresJobStore` | APScheduler 4 `SQLAlchemyDataStore` + `AsyncpgEventBroker` | v4 GA | Native async; v3 nomenclature in REQUIREMENTS.md ORCH-01 must NOT propagate into code |
| ccxt `watch_ohlcv` | `watch_trades` + client-side 1m aggregator | ccxt#27253 confirmed MEXC hang | Reliable live candles; no silent stall |
| Coinglass Startup ($79/mo) | Coinglass Hobbyist (~$35/mo) | Memory override `project_data_tier_subscriptions.md` | 30 req/min (not 80); 1m capped at 6 days (not 12) |
| `psycopg2` | `asyncpg` + `psycopg` v3 | Phase 0 D-30 | Async-native COPY path |
| `Black + isort + flake8` | Ruff | Phase 0 | 100× faster; single tool |
| `python-telegram-bot` for any Telegram use | Raw `httpx.post` for Phase 1 alerts; framework only when commands needed (Phase 4) | D-86 | ~50 LOC vs ~500 LOC dep |

**Deprecated / outdated:**
- `APScheduler.jobstores.PostgresJobStore` (v3) — replaced by `apscheduler.datastores.sqlalchemy.SQLAlchemyDataStore` (v4)
- `ccxt watch_ohlcv` for MEXC — known-bad per #27253, banned in CONTEXT.md
- `Coinglass Startup tier` references in REQUIREMENTS.md DATA-07 / STOR-08 / V2-DATA-01 — must be patched in the same commit that lands the Phase 1 plan
- `psycopg2` driver — Phase 0 already migrated to async stack

---

## 14. Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|----------------|
| A1 | APScheduler 4.0+ released and stable on PyPI as of May 2026; `AsyncScheduler`/`SQLAlchemyDataStore`/`AsyncpgEventBroker` are GA. | §1 Standard Stack / §5 Pattern 4 | Planner must `pip index versions apscheduler` at install time. If still pre-release, fall back to v3 `AsyncIOScheduler` + `SQLAlchemyJobStore` — code changes needed across `bootstrap.py` + `jobs.py`. |
| A2 | `max(quality_flag)` in continuous aggregate SELECT is alphabetically monotonic to severity for the current enum values | §3.5 | If wrong, `quality_flag` propagates the WRONG bucket aggregate. Fix: replace with `CASE WHEN ... END` or numeric severity column. |
| A3 | ccxt 4.5.54 + reports MEXC `watch_funding_rate` with both `fundingTimestamp` AND `timestamp` fields per response | §4.5 | Code path captures only one ts — Pitfall 2 mitigation degraded. Verify against actual ccxt response shape during Wave 2 fixture capture. |
| A4 | `coalesce=True` + `misfire_grace_time` are supported on APScheduler 4 `add_schedule` | §5 Pattern 5 | If API renamed in v4, the burst-on-deploy mitigation needs different syntax. |
| A5 | `SQLAlchemy 2.0.49 + asyncpg 0.31` allows `await (await engine.connect()).get_raw_connection()` to yield an asyncpg `Connection` with `.copy_records_to_table` | §2 Pattern 1 | If escape-hatch API changed, planner uses separate `asyncpg.create_pool()` for COPY path (alternative shipped). |
| A6 | R2 supports `pg_dump`-compatible multipart upload via boto3 with `Config(signature_version='s3v4')` | §8.1 | If signature mismatch, switch endpoint URL format or use `s3v2`. R2 docs documented compatible. |
| A7 | Railway's PostgreSQL service is reachable by hostname from the `data-platform` service container — exact `DATABASE_URL` format known from Phase 0 | §8.1 | Phase 0 already wired this; concrete DSN format already in `.env.example`. No risk. |
| A8 | `moto` library covers enough of S3 API surface to test the R2 backup path without hitting real R2 | §11 Validation | If `moto` doesn't cover the specific multipart upload + signature mode boto3 uses, fall back to a small wiremock server or skip integration test for R2 (manual-only). |
| A9 | Coinglass Hobbyist tier endpoints `funding-rate-list`, OI history, liquidation history, long-short ratio are all available (CONTEXT.md asserts) | §4.6, §11 | If Hobbyist tier doesn't expose one of these endpoints (rare for Coinglass), the corresponding ingest job becomes a no-op until Standard tier — degraded scope. |
| A10 | `pg_dump` from `postgresql-client-16` correctly handles TimescaleDB extensions and hypertables on restore (no special `--exclude-extension` needed; `pg_restore` recreates hypertables correctly) | §8 | If `pg_restore` doesn't recreate hypertables, restore drill fails — fallback: include `timescaledb-extras pg_dump_with_hypertable` step or use the `timescaledb-backup` tool. |
| A11 | Sources table CHECK constraint values `('mexc_native','coinglass_aggregate','coinglass_mexc_only','coingecko')` is the complete set; no other source is added in Phase 1 | §3.2 | If multi-exchange ingest (V2-EXCH) is bumped forward, schema needs ALTER. |

**Recommended planner actions:** Convert each `[ASSUMED]` claim above into a Wave-1 verification step (one small spike per ASSUMED claim, ≤30 minutes each) before locking the plan's implementation tasks.

---

## 15. Runtime State Inventory

Phase 1 is greenfield code additions, not rename/refactor — but Phase 0 already produced production state worth inventorying:

| Category | Items found | Action required |
|----------|-------------|------------------|
| Stored data | None: Phase 0 created `service_event` hypertable + the two Alembic versions 0001/0002; Phase 1 adds 12 more migrations on top. | Forward-only schema additions; no data migration. |
| Live service config | Railway services (`data-platform`, `strategy-engine`, `dashboard`) live with Phase 0 config; per-service `railway.*.toml` files in git. | Phase 1 only adds **env vars** (MEXC/Coinglass/CoinGecko/Telegram/R2 secrets) — done via Railway dashboard, NOT git. Document the required set in `.env.example` placeholders. |
| OS-registered state | None — Railway containers are stateless; no Task Scheduler / systemd / launchd state outside the deploy. | None. |
| Secrets/env vars | Phase 0 wired `DATABASE_URL` reference + per-service settings. Phase 1 adds new env-var blocks for MEXC, Coinglass, CoinGecko, Telegram, R2 — all `SecretStr`. | Planner adds `.env.example` placeholders + `safe_summary()` boolean flags + Railway dashboard population. Never commit real values. |
| Build artifacts | `/app/.venv/bin/alembic` (from Dockerfile uv sync). | None; reused. **NEW: Dockerfile needs `postgresql-client-16` apt-installed for pg_dump in backup job.** Plan an early Wave-1 spike to verify the install fits within Railway image-size limits. |

---

## 16. Common Pitfalls (See §7 above)

(Section number reserved to match output_format checklist; content is in §7 to keep narrative flow.)

---

## 17. Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Runtime | ✓ (Phase 0) | 3.12.x | — |
| PostgreSQL 16 + TimescaleDB 2.18 | Storage layer | ✓ (Railway Phase 0) | PG 16 + TS 2.18 | — |
| ccxt 4.5.54+ | MEXC unified client | ✓ (already in `pyproject.toml`) | per pin | — |
| httpx 0.28+ | Coinglass / CoinGecko / Telegram | ✓ | per pin | — |
| asyncpg 0.31+ | COPY hot path | ✓ | per pin | — |
| APScheduler 4.x | Scheduler | ✗ (not yet in deps) | TBD | If 4.x not GA, use v3 `AsyncIOScheduler` + `SQLAlchemyJobStore` — API shape close enough for code reuse |
| boto3 | R2 backup | ✗ (not yet in deps) | TBD | None — backup is core Phase 1 deliverable |
| postgresql-client-16 (apt) | pg_dump in backup job | ✗ (Dockerfile change needed) | 16.x | None — `pg_dump` is the canonical TS-aware dump tool |
| pg_dump-compatible TS extension | Restore drill | ✓ via postgresql-client-16 | 16.x | If a TS-specific tool is needed (`timescaledb-backup`), pivot in Wave 4 |
| Telegram Bot API access | Stale-data alerts | ✓ (user has Bot token per CONTEXT.md `<deferred>`) | — | If unavailable: log-only alerts |
| Cloudflare R2 account + bucket | Daily backup | ✓ (CONTEXT.md D-80 assumes provisioned) | — | If unavailable: Backblaze B2 (boto3-compatible) or local-only retention until R2 set up |
| MEXC futures API READ key | Live ingest | ✓ (user has — per `.env.example` and Phase 5 plans imply existing keys) | — | Phase 1 cannot ship without — block at start |
| Coinglass Hobbyist API key | Coinglass ingest | ✓ (memory override D-35) | — | If missing: ingest jobs skip with `coinglass.skipped` log entry; degraded scope |
| CoinGecko Demo API key | Daily universe metadata | ✓ (memory override D-36) | — | If missing: fall back to MEXC `fetch_tickers` only for universe (no CoinGecko enrichment) |

**Missing dependencies with fallback:** APScheduler 4 (v3 fallback), CoinGecko (MEXC-only fallback).
**Missing dependencies with no fallback:** boto3 (must install), postgresql-client-16 (must apt-install in Dockerfile), MEXC READ key (must provision).

---

## 18. Security Domain

`security_enforcement` is not explicitly set to `false` — include this section.

### Applicable ASVS categories

| ASVS category | Applies | Standard control |
|---------------|---------|-----------------|
| V2 Authentication | yes (Telegram bot token, MEXC/Coinglass/CoinGecko/R2 API keys) | All as `SecretStr` in pydantic-settings; `safe_summary()` exposes only boolean flags; Phase 0 secret-scan defense-in-depth carries forward |
| V3 Session Management | no | No user sessions in Phase 1 |
| V4 Access Control | partial | `data-platform` service uses `READ_KEY` only; `assert_no_trade_env_leaked()` guard prevents trade-key leak |
| V5 Input Validation | **yes — central concern** | Pydantic v2 schemas on every API response (MEXC/Coinglass/CoinGecko); CHECK constraints on `source` + `quality_flag` in DB; idempotency PK on (symbol, ts, source) |
| V6 Cryptography | yes | Never hand-roll; `SecretStr` + `.get_secret_value()` only at call site; structlog redactor strips credentials in log lines (already Phase 0) |
| V7 Error Handling | yes | Pydantic ValidationError → `dead_letter` (don't crash ingest loop); never log raw API key in exception traces |
| V9 Communications | yes | All external HTTP via httpx (HTTPS only); ccxt enforces HTTPS for MEXC; boto3 to R2 uses HTTPS endpoint |
| V12 Files & Resources | partial | pg_dump output streamed direct to R2 — never written to local disk (avoids accidental persistent leak); `subprocess.Popen(pg_dump, …)` does not log credentials (DSN in argv is acceptable for short-lived process, but **flag for review**: prefer passing DSN via env or `.pgpass` to avoid argv exposure) |

### Known threat patterns for this stack

| Pattern | STRIDE | Standard mitigation |
|---------|--------|---------------------|
| API key leakage in logs / ccxt verbose mode | Information Disclosure | `exchange.verbose = False`; structlog redactor pattern from Phase 0; pre-commit gitleaks |
| MEXC API key with withdraw permission | Spoofing / Elevation | `READ_KEY` is read-only and trade-key isn't even introduced until Phase 5; `assert_no_trade_env_leaked()` runtime guard |
| Source-mixed funding/OI causing Pitfall 16 | Tampering (data integrity) | CHECK constraint on `source`; CI grep test on migrations |
| Naive datetime sneaking past validation | Tampering (data integrity, time-zone) | Pydantic `@model_validator(mode='after')` reject naive; Postgres TIMESTAMPTZ + pre-commit guard |
| pg_dump credentials in process argv visible via `/proc` | Information Disclosure | Pass DSN via `PGPASSWORD` env or `.pgpass` — flagged for planner |
| R2 backup public-read accidentally | Information Disclosure | bucket policy default-private; object-lock enabled per D-80 |
| Coinglass API key in URL query string | Information Disclosure | Use header `CG-API-KEY` not URL param (Coinglass v4 supports both — use header) |
| Telegram bot token in error stack trace | Information Disclosure | `try/except` around the httpx call swallows exceptions and logs without re-raising token-bearing URLs |

---

## 19. Package Legitimacy Audit

Phase 1 adds new external packages. Per the Package Legitimacy Gate protocol:

```
slopcheck install apscheduler boto3 moto python-telegram-bot --json
```

Slopcheck was not run in this research session (no tool surface available in this researcher). **Per protocol fallback rule, all entries below are tagged `[ASSUMED]` and the planner must gate each install behind a `checkpoint:human-verify` task.**

| Package | Registry | Age (approx) | Downloads | Source repo | slopcheck | Disposition |
|---------|----------|--------------|-----------|-------------|-----------|-------------|
| `apscheduler` | PyPI | 10+ yrs | tens of M/mo | github.com/agronholm/apscheduler | not run | [ASSUMED] — verify with `pip index versions apscheduler` + open repo at install time |
| `boto3` | PyPI | 10+ yrs | hundreds of M/mo | github.com/boto/boto3 | not run | [ASSUMED] — AWS-owned; very low risk; verify version |
| `moto` (dev only — for R2 mock in tests) | PyPI | 10+ yrs | tens of M/mo | github.com/getmoto/moto | not run | [ASSUMED] — verify |
| `python-telegram-bot` | PyPI | 10+ yrs | M/mo | github.com/python-telegram-bot/python-telegram-bot | not run | **REMOVED FROM PHASE 1** per D-86; raw httpx instead |

**Packages removed due to slopcheck [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none identified.
**Cross-ecosystem confusion check:** Planner runs `pip index versions <pkg>` (PyPI) NOT `npm view` — these are Python packages.

**Post-install verification step (planner adds as Wave 1 task):**
- For each new package, open the GitHub repo, verify ≥1000 stars + recent commit activity, AND `pip show <pkg>` after install to confirm origin metadata matches GitHub URL. Both checks together approximate manual slopcheck for high-trust packages.

---

## 20. Open Questions for Planner

> Things research couldn't fully resolve. Planner should pick a direction and document the choice in PLAN.md.

1. **Freshness gauge semantics — lag-seconds vs unix-timestamp.**
   - Option A: Gauge holds *seconds since last write*. Requires a background updater that decreases over time. Simpler at read time.
   - Option B (recommended): Gauge holds *unix timestamp of last write*. Freshness check computes `now - gauge`. No background updater needed.
   - **Pick:** B (simpler; CONTEXT.md D-49 wording is compatible with either).

2. **Migration 0014 strategy — helper vs inline `op.execute`.**
   - Option A: Add `create_continuous_aggregate(...)` to `shortfire.db.timescale` (DRY, testable; recommended per §3.5).
   - Option B: One raw `op.execute` per CA with inline comment.
   - **Pick:** A.

3. **L2 storage cardinality budget.**
   - With JSONB wide, ~600M rows over 1 year. At 7-day chunks, 52 chunks/yr × 200 symbols × ~17,280 snapshots/day for tier-1 = ~1.8M rows/symbol/yr; ~30GB uncompressed per symbol; ~3GB compressed at 10×. Aggregate ≈ 600GB compressed — high.
   - **Action for planner:** During Wave 3, run a back-of-envelope: actual row size after 2-day compression for the first chunk. If compression < 5×, reduce L2 sampling cadence for tier-2 from 10s → 30s, OR drop tier-2 L2 entirely (only tier-1 captured).

4. **CoinGecko fallback if rate limit lower than Demo (30 req/min) is observed.**
   - **Action for planner at Wave 1:** with the actual key, run a smoke check: `aiolimiter` set to 28 req/min, fire 30 requests in 60 seconds, observe 429 rate. If true Demo (30/min) → proceed; if reduced → relax aiolimiter to whatever empirical headroom is.

5. **APScheduler 4 release status verification.**
   - **Action for planner at Wave 1:** `pip install apscheduler && python -c "from apscheduler import AsyncScheduler"`. If import succeeds and version is 4.x, proceed. If not, fall back to v3 (`AsyncIOScheduler` + `SQLAlchemyJobStore`) — CODE CHANGES across `bootstrap.py` + `jobs.py` are roughly +50/-40 LOC; not a blocker.

6. **`compaction.refresh.audit` job add-on (§5).**
   - Not in CONTEXT.md D-77. Recommended add — exposes silent CA staleness via Prometheus. Planner picks: include in Wave 4 if budget allows; otherwise defer to Phase 2.

7. **Gap-injection helper (§7 Pitfall 21).**
   - CONTEXT.md doesn't explicitly require Phase 1 to insert gap-marker rows; the `quality_flag` enum reserves the value. **Recommendation:** include the helper in Wave 2 backfill task. ~30 LOC. Phase 2 feature pipelines benefit immediately.

8. **`pg_dump` credential passing — argv vs env.**
   - argv exposes the DSN to `/proc/<pid>/cmdline`. **Recommendation:** pass DSN via `PGPASSWORD` env or use a `.pgpass` file in `/root/`. Trivial code change.

9. **Backup retention — R2 lifecycle rules vs sundown sweep job.**
   - Recommended option 2 (sundown sweep). CONTEXT.md D-81 specifies retention shape but not implementation. Confirm during Wave 4.

10. **Domain `Source` literal change**: extending `Literal["mexc","coinglass","coingecko"]` → `Literal["mexc_native","coinglass_aggregate","coinglass_mexc_only","coingecko"]` per D-59. Phase 0 Hypothesis tests on `Candle` reference the old values.
    - **Action for planner:** include this change in Wave 1 as part of "domain alignment with new source enum"; update the ~5 Phase 0 tests in the same commit.

---

## 21. Sources

### Primary (HIGH confidence)
- `.planning/phases/01-data-platform/01-CONTEXT.md` — D-35..D-96 (locked decisions; the bulk of architectural authority for this research)
- `.planning/REQUIREMENTS.md` — DATA-01..12, STOR-01..10, UNIV-01..04, ORCH-01..04, OPS-05..06 (exact requirement text)
- `.planning/ROADMAP.md` — Phase 1 §Success Criteria
- `CLAUDE.md` — Tech stack matrix (Python 3.12, ccxt 4.5.54+, TimescaleDB 2.18, APScheduler 4, asyncpg 0.30+), anti-list, paid services
- `.planning/research/ARCHITECTURE.md` — Pattern 2 (typed-per-source hypertables, EAV REJECTED), §State Management
- `.planning/research/PITFALLS.md` — Pitfalls 1, 2, 4, 11, 16, 17, 21, 27 directly mitigated in Phase 1
- `.planning/research/STACK.md` — Coinglass tier comparison, version pins
- `.planning/phases/00-foundation/00-CONTEXT.md` — D-01..D-34 carry-forward (TimescaleDB helpers, engine.py, settings pattern, secret-scan defense, observability skeleton)
- `pyproject.toml` (actual file in repo) — version pins for ccxt-less stack, ruff/pyright/coverage config
- `src/shortfire/db/timescale.py` — `create_hypertable`, `enable_compression`, `add_compression_policy`, `add_retention_policy` (read in this session)
- `src/shortfire/clients/{mexc,coinglass,coingecko,repos}.py` — Protocol contracts that Phase 1 implements
- `src/shortfire/domain/market.py` — `Source` literal that needs widening per D-59
- `railway.toml` — preDeployCommand + startCommand pattern that Phase 1 reuses

### Secondary (MEDIUM confidence — verified against authoritative sources noted in CONTEXT.md)
- **ccxt 4.5 Manual** (Context7 verified per CONTEXT.md `<canonical_refs>`): `fetchOHLCV`, `fetchFundingRateHistory`, `watchTrades`, `watchOrderBook`, swap `defaultType`
- **TimescaleDB 2.18 docs** (Context7 verified per CONTEXT.md): `CREATE MATERIALIZED VIEW … WITH (timescaledb.continuous)` + `add_continuous_aggregate_policy`; compression locks; refresh-on-compressed-chunk semantics
- **APScheduler 4 docs** (Context7 verified per CONTEXT.md): `AsyncScheduler` + `SQLAlchemyDataStore` + `AsyncpgEventBroker`; `start_in_background`; `add_schedule(coalesce, misfire_grace_time, max_running_jobs)`
- **Coinglass v4 API + pricing page**: Hobbyist tier (30 req/min, 1m derivatives ~6 days) — memory override `project_data_tier_subscriptions.md` overrides STACK.md text
- **MEXC futures API docs**: public 20 req/s, signed `recvWindow`, swap endpoints
- **Cloudflare R2 S3-compatible docs**: boto3 endpoint URL format, lifecycle rules, object-lock
- **GitHub issues ccxt#27253 (watch_ohlcv MEXC hang)** + **ccxt#28532 (swap order endpoint fix May 2026)**: cited in CLAUDE.md and CONTEXT.md D-41

### Tertiary (LOW — knowledge from training, flagged for planner verification)
- The exact rate-limit headers MEXC returns on futures endpoints (training: `X-MBX-Used-Weight-1m`-style; verify at install time during Wave 1)
- moto coverage of R2 / S3 multipart upload signatures (planner verifies during Wave 4 test scaffolding)
- pg_dump 16 → TimescaleDB 2.18 hypertable round-trip restore behavior (planner verifies during Wave 4 restore-drill spike)

---

## Metadata

**Confidence breakdown:**
- Standard stack (existing pinned + new APScheduler/boto3): HIGH — `pyproject.toml` already lists most; new packages are mainstream
- Architecture: HIGH — CONTEXT.md locked D-35..D-96 in deep detail; this research operationalizes without contradiction
- Pitfalls: HIGH — PITFALLS.md is the project canon; Pitfalls 1/4/11/16/17/21/27 cross-mapped
- Validation architecture: HIGH — Phase 0 test harness + Hypothesis fixtures are the proven seam
- Open questions: MEDIUM — 10 listed; all are resolvable in Wave-1 verification spikes (≤30 min each)

**Research date:** 2026-05-21
**Valid until:** 2026-06-20 (30 days — TimescaleDB compression / ccxt MEXC behavior is stable; refresh if APScheduler 4 makes a breaking minor release)
