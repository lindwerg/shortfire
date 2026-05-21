# Phase 1: Data Platform - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** `--auto --all` (autonomous, all gray areas resolved in one pass; user delegated full enumeration)

<domain>
## Phase Boundary

A strategy-agnostic, leak-aware historical and live data warehouse exists in TimescaleDB with **daily universe snapshots, L2 capture, source attribution, and 1–2 years of MEXC-native backfill** — so research and backtesting in later phases can never be invalidated by retrofitted schema decisions.

This phase builds the *foundation under everything else*: every Phase 2 feature, every Phase 3 backtest, every Phase 4 paper-trade, every Phase 5 live-trade reads from the hypertables shipped here. Schema mistakes here are unfixable later; survivorship, slippage realism, and timestamp correctness all originate in Phase 1.

**In scope for Phase 1:**

- Concrete `ccxt`-backed `MexcClient` and `httpx`-backed `CoinglassClient` / `CoinGeckoClient` implementations satisfying the Phase 0 Protocols (FOUND-08 seam already laid down)
- Typed-per-source hypertables for MEXC OHLCV (1m/5m/15m/1h/4h/1d via continuous aggregates from the 1m base), funding, OI, signed trades, L2 top-20 orderbook, liquidations (DATA-01..06, STOR-01..05)
- Typed-per-source hypertables for Coinglass funding-aggregate, OI, liquidations, long/short ratio (DATA-07, STOR-01)
- CoinGecko daily-cadence market metadata hypertable (DATA-08)
- Explicit `source` column on every derivatives row with CHECK constraint (DATA-12, STOR-01, Pitfall 16 mitigation)
- Idempotent ingest via asyncpg COPY-to-staging + `INSERT … ON CONFLICT (symbol, ts, source) DO NOTHING` (DATA-09)
- tenacity retries + per-source aiolimiter rate limits (DATA-10)
- Pydantic v2 schema validation on every API response; validation failures land in `dead_letter` hypertable (DATA-11)
- `universe_snapshots` daily hypertable with point-in-time correctness; new-listing detection within 24h (UNIV-01..04, Pitfall 1 mitigation)
- `symbols` relational lookup with soft-delete via `delisted_at` (STOR-07, Pitfall 1)
- 7-day-aged compression policies on every hypertable (STOR-04)
- TimescaleDB continuous aggregates for 5m/15m/1h/4h rollups of 1m OHLCV (STOR-05)
- `quality_flag` column on raw tables; gap detection flags, NEVER interpolation (STOR-09, Pitfall 21 mitigation)
- TIMESTAMPTZ-only column type, `ON DELETE CASCADE` banned project-wide (STOR-03, STOR-07 — pre-commit grep guards already shipped in Phase 0)
- Backfill of ≥1 year of MEXC-native OHLCV + funding + OI; Coinglass 1m derivatives backfill accepted at the user's Hobbyist-tier 6-day window (STOR-08 — see §Subscription Reconciliation below)
- APScheduler 4.x `AsyncScheduler` with `SQLAlchemyDataStore` running inside `data-platform` Railway service (ORCH-01..02)
- Per-source `freshness_seconds` Prometheus gauges (ORCH-03)
- Telegram stale-data alerts via raw `httpx`-call to the Bot API — no `python-telegram-bot` framework dep until Phase 4 (ORCH-04)
- Daily `pg_dump --format=custom --compress=zstd:9` to Cloudflare R2 (S3-compatible) with documented restore drill (STOR-10)
- All three Phase 0 Railway services (`data-platform`, `strategy-engine`, `dashboard`) remain live; only `data-platform` is doing real work in Phase 1 — every push to `main` still auto-deploys all three (OPS-05..06)
- `data-platform` exposes per-source freshness gauges, ingest-rows-total counters, dead-letter counter, universe-symbols gauge, backup-age gauge on `/metrics`
- Extension of Phase 0 event taxonomy with ~13 new event names for ingest/universe/backup lifecycle (UI-SPEC contract continued)

**Out of scope (explicitly punted):**

- Feature engineering, primitive library (`rsi`, `funding_zscore`, `oi_roc`, …) → Phase 2
- Pump detector, labeling, ML training, MLflow → Phase 2
- Strategy Protocol, StrategyRegistry, backtester, `strategy_instances` table → Phase 3
- Paper trading, kill switch, full risk module, signal-quality Telegram alerts with SHAP → Phase 4
- Live order execution, two-key MEXC auth, `risk-guard` 4th Railway service → Phase 5
- Grafana dashboards, Sentry — deliberately deferred to Phase 5 per ROADMAP (avoid dashboard-before-edge anti-pattern, Pitfall 30)
- Coinglass Standard tier ($79–$299) upgrade decision — kept open until Phase 2 EDA quantifies whether >6 days of 1m derivatives data unlocks edge
- Multi-exchange ingest (Binance/Bybit/OKX) — schema is exchange-agnostic via `source` column, but Phase 1 ships MEXC + Coinglass + CoinGecko only
- ClickHouse migration — V2-INFRA per REQUIREMENTS.md, not Phase 1
- Prefect 3 migration — V2-INFRA; APScheduler 4 carries Phase 1 fine

</domain>

<decisions>
## Implementation Decisions

> Numbering continues from Phase 0 — Phase 0 ended at D-34, Phase 1 starts at D-35.

### Source-of-Truth & Subscription Reconciliation (precondition lock — affects every downstream ingest decision)

- **D-35:** **Coinglass tier in production is HOBBYIST (~$35/mo), not Startup ($79/mo).** ROADMAP.md, REQUIREMENTS.md (DATA-07, STOR-08), and PROJECT.md still reference Startup; Phase 0 deferred this reconciliation to Phase 1 plan-phase. **CONTEXT.md hereby overrides:** Coinglass quota for Phase 1 is **30 req/min**, 1m derivatives history window is **~6 days**, 5m/15m/1h history is much longer (months). Phase 1 plans and rate-limiters MUST use these numbers. ROADMAP.md and REQUIREMENTS.md will be patched in the same commit that lands the Phase 1 plan (research and planner agents to flag this if not yet done).
- **D-36:** **CoinGecko tier ≈ $35/mo, treat as 30 req/min by default** (Demo tier). Planner verifies actual rate limit against the active API key at planning time and adjusts the aiolimiter accordingly. CoinGecko is used for **daily universe metadata refresh only** — no minute-cadence calls.
- **D-37:** **Coinglass Standard ($299/mo) upgrade decision stays deferred to Phase 2 EDA**, exactly as REQUIREMENTS.md V2-DATA-01 mandates. No upgrade pressure in Phase 1.
- **D-38:** **Backfill scope explicitly:**
    - MEXC-native OHLCV (1m, 5m, 15m, 1h, 4h, 1d): **1 year minimum, 2 years aspirational** — paginated via ccxt `fetch_ohlcv` with `since` walking forward in 1000-candle pages, rate-limited per MEXC's public throttle
    - MEXC-native funding history: full available depth via `fetch_funding_rate_history`
    - MEXC-native OI: hourly granularity, full available depth via `fetch_open_interest_history`
    - Coinglass aggregates: **1m history limited to ~6 days** (Hobbyist constraint), 5m/15m/1h/4h history up to vendor's exposed depth, daily granularity full
    - L2 top-20 orderbook: forward-capture only (no backfill possible — vendor does not expose historical L2)
    - Signed trades: forward-capture only (limited historical depth via REST `fetch_trades`, sampling acceptable)
    - Liquidations: forward-capture only (MEXC ws) + Coinglass historical aggregate
- **D-39:** **L2 backfill is fundamentally impossible — accept and document.** Slippage realism in Phase 3 backtester is constrained to forward-captured L2 from Phase 1 commit-zero forward. This makes the Phase 1 → Phase 2 → Phase 3 timing matter: more days of forward L2 = more backtest fidelity. ROADMAP.md is fine with this.

### Ingest: ccxt MEXC Integration (DATA-01..06)

- **D-40:** **Single ccxt async client instance per process** with `options={'defaultType': 'swap'}` for perpetual futures. Symbol convention is **ccxt-unified `BTC/USDT:USDT`** stored everywhere except `symbols.mexc_native_symbol` which mirrors the exchange's native `BTC_USDT` (used only at live-trade send time in Phase 5). Storing unified lets us swap exchanges later without column rewrites.
- **D-41:** **ccxt version pinned to `>=4.5.54,<4.6`.** Minor-version drift between ccxt 4.5/4.6 has broken MEXC swap endpoints historically (#28532 referenced in STACK.md). `uv.lock` is the truth; the pin lives in `pyproject.toml`.
- **D-42:** **OHLCV backfill uses REST `fetch_ohlcv(symbol, timeframe, since_ms, limit=1000)`** paginated by stepping `since_ms` forward by `limit * timeframe_ms`. Worker pool size: **bounded `asyncio.Semaphore(8)`** per symbol-timeframe pair to avoid bursting MEXC public quota (20 req/s). Returns array `[ts_ms, o, h, l, c, v]`; Pydantic `Candle` model validates each row.
- **D-43:** **Live OHLCV is NOT done via `watch_ohlcv` — confirmed banned by Pitfall 11 + ccxt#27253.** Instead: **`watch_trades` stream → client-side aggregation into 1m candles → COPY into `raw_mexc_candles_1m`**. The 1m table is the source of truth; 5m/15m/1h/4h/1d are continuous aggregates (D-50). Trade tape itself is persisted to `raw_mexc_trades`.
- **D-44:** **Funding ingest uses BOTH `fetch_funding_rate_history` (REST, historical)** AND **`watch_funding_rate` (ws, live)**. Schema captures both `settlement_ts` and `published_ts` per Pitfall 2/16. Live ws ensures Phase 4 paper-trade always has the freshest funding rate without REST polling per symbol.
- **D-45:** **OI ingest is REST-only** (`fetch_open_interest_history` hourly, `fetch_open_interest` for current). MEXC does not stream OI reliably on ccxt 4.5.x. Refresh every 5 min for the live snapshot, hourly for the historical row.
- **D-46:** **L2 top-20 capture uses `watch_order_book(symbol, limit=20)` ccxt Pro** with **per-symbol async tasks managed by `asyncio.TaskGroup`** (Python 3.11+ structured concurrency — banned `asyncio.create_task` without reference, Pitfall 27). Sampling cadence: **10s for full universe, 5s for "tier-1" subset = top 50 symbols by 7-day rolling volume**. Tier-1 designation refreshed daily by the universe snapshot job.
- **D-47:** **Signed-trades stream via `watch_trades(symbol)`** — Phase 1 persists with **1-minute batching** (collect trades in memory, COPY batch every minute) to keep write throughput sane. Per-batch COPY uses asyncpg `copy_records_to_table` into a `raw_mexc_trades_staging` temp table, then `INSERT … SELECT … ON CONFLICT DO NOTHING` into `raw_mexc_trades` keyed on `(symbol, exchange_trade_id)`. If MEXC's `id` is unstable, fallback key is `(symbol, ts_ms, side, price, qty)` deduped at staging.
- **D-48:** **Liquidations** captured TWO ways with explicit `source`:
    - `source='mexc_native'` — `watch_liquidations` if available in ccxt 4.5.54's MEXC swap class; otherwise REST poll every minute for liquidation orders (degraded fidelity flagged via `quality_flag='partial_capture'`)
    - `source='coinglass_aggregate'` — Coinglass historical liquidation endpoint, 5-min refresh
- **D-49:** **Reconnect + freshness contract per source/symbol:**
    1. Per-symbol Prometheus gauge `shortfire_data_platform_source_freshness_seconds{source, dataset, symbol}` updated on every successful row write
    2. Before any consumer reads a feed, asserts `now() - gauge < 2 × expected_lag` — refuses to proceed otherwise (this is the Pitfall 11 "freshness check at signal time" applied to ingest itself)
    3. Heartbeat task every 30s pings ccxt's `last_received` timestamp; if no update for > 60s on an active stream → cancel TaskGroup branch and respawn (kills the silent-hang failure mode)
    4. Cross-REST check every 60s for the lowest-volume symbol in tier-1: fetch latest candle via REST, compare to ws-derived row, flag `quality_flag='ws_rest_divergence'` if > 0.5% mismatch

### Ingest: Coinglass v4 Integration (DATA-07)

- **D-50:** **Single `httpx.AsyncClient` instance per process** with HTTP/2 enabled, `timeout=10.0`, `limits=httpx.Limits(max_connections=20, max_keepalive_connections=10)`. All four Coinglass endpoints called from the same client.
- **D-51:** **`aiolimiter.AsyncLimiter(rate=28, period=60)`** for Coinglass (5% headroom under the 30 req/min Hobbyist cap, per D-35). Single global bucket — Coinglass does not document per-endpoint sub-limits.
- **D-52:** **Pydantic v2 response schemas per endpoint** in `src/shortfire/ingest/coinglass/schemas.py`:
    - `FundingRateListResponse`, `OpenInterestHistoryResponse`, `LiquidationCoinHistoryResponse`, `LongShortAccountRatioResponse`
    - Every schema enforces TIMESTAMPTZ via `datetime` field validators identical to Phase 0 domain types
    - Validation failure → write to `dead_letter` (D-67) with full raw JSON payload, do NOT crash the ingest loop
- **D-53:** **Refresh cadences:**
    - Funding rate list (batch endpoint, all symbols in one call): every 5 min
    - OI history (per-symbol): every 5 min, round-robin through universe — at 200 symbols + 28 req/min budget, full sweep takes ~7.2 min in steady state, acceptable
    - Liquidation history (per-symbol): every 10 min
    - Long/short ratio (per-symbol): every 15 min
- **D-54:** **Coinglass derivatives backfill (1m): explicitly capped at 6 days** (Hobbyist). Older history pulled at 5m/15m/1h aggregate only. Schema records `granularity_seconds` so feature engineering in Phase 2 can join the right resolution.

### Ingest: CoinGecko Integration (DATA-08)

- **D-55:** **CoinGecko is universe-metadata-only, daily cadence.** Endpoints used: `/coins/markets` (paginated, 250 per page) and `/coins/{id}` for category + initial-listing-date enrichment of new MEXC listings.
- **D-56:** **`aiolimiter.AsyncLimiter(rate=28, period=60)`** matching Coinglass headroom. Refresh once daily at 00:30 UTC (after the universe-snapshot job at 00:05).
- **D-57:** **Schema = `raw_coingecko_market(symbol, ts, source='coingecko', price_usd, volume_24h_usd, market_cap_usd, category TEXT, listing_date DATE, raw_payload JSONB)`**. Idempotent on `(symbol, ts, source)` like everything else.

### Storage: Schema (STOR-01..05, DATA-12, UNIV-01..04)

- **D-58:** **Typed-per-source hypertables — the universal narrow `(symbol, ts, metric, value)` EAV is STILL EXPLICITLY REJECTED.** STOR-02 + ARCHITECTURE.md Pattern 2 confirmed. Complete table list:

    | Table | Hypertable | PK / dedup key | chunk_interval | compress segment_by | compress after | Notes |
    |---|---|---|---|---|---|---|
    | `raw_mexc_candles_1m` | yes | `(symbol, ts)` | 1 day | `symbol` | 7 days | base for all continuous aggregates |
    | `raw_mexc_candles_5m` | NO (continuous aggregate) | view over 1m | — | — | — | D-67 below |
    | `raw_mexc_candles_15m` | NO (continuous aggregate) | view over 1m | — | — | — | D-67 |
    | `raw_mexc_candles_1h` | NO (continuous aggregate) | view over 1m | — | — | — | D-67 |
    | `raw_mexc_candles_4h` | NO (continuous aggregate) | view over 1m | — | — | — | D-67 |
    | `raw_mexc_candles_1d` | yes (NOT a cagg — sourced directly from ccxt 1d endpoint) | `(symbol, ts)` | 90 days | `symbol` | 30 days | independent capture; cross-validate against 1m sum |
    | `raw_mexc_funding` | yes | `(symbol, settlement_ts)` | 30 days | `symbol` | 7 days | both `settlement_ts` + `published_ts` |
    | `raw_mexc_oi` | yes | `(symbol, ts)` | 7 days | `symbol` | 7 days | hourly cadence |
    | `raw_mexc_trades` | yes | `(symbol, exchange_trade_id)` w/ fallback `(symbol, ts, side, price, qty)` | 1 day | `symbol` | 2 days | aggressive compression |
    | `raw_mexc_l2_top20` | yes | `(symbol, ts)` | 1 day | `symbol` | 2 days | `bids JSONB`, `asks JSONB` (arrays of `[price, qty]`); top-20 not top-10 |
    | `raw_mexc_liquidations` | yes | `(symbol, ts, side, qty, price)` | 7 days | `symbol` | 7 days | dedup by tuple; vendor often lacks stable id |
    | `raw_coinglass_funding_agg` | yes | `(symbol, ts, source)` | 30 days | `symbol` | 7 days | `source='coinglass_aggregate'` always |
    | `raw_coinglass_oi` | yes | `(symbol, ts, source)` | 30 days | `symbol` | 7 days | aggregate; can be split per-exchange if Coinglass returns the breakdown |
    | `raw_coinglass_liq` | yes | `(symbol, ts, source)` | 7 days | `symbol` | 7 days | aggregate |
    | `raw_coinglass_lsr` | yes | `(symbol, ts, source)` | 30 days | `symbol` | 7 days | long/short ratio |
    | `raw_coingecko_market` | yes | `(symbol, ts, source)` | 90 days | `source` | 30 days | daily cadence |
    | `universe_snapshots` | yes | `(snapshot_date, symbol)` | 90 days | NONE (tiny) | — | one row per (date, symbol) qualifying that day |
    | `symbols` | NO (relational) | `(symbol)` PK | — | — | — | lifecycle table, see D-63 |
    | `dead_letter` | yes | `(id UUID)` | 30 days | `source` | 30 days | DATA-11 |
    | `ingest_runs` | yes | `(id UUID)` | 30 days | `source` | 30 days | per-job run telemetry |

- **D-59:** **Every derivatives row carries a `source TEXT NOT NULL` column** with a Postgres CHECK constraint restricting values to a fixed enum: `'mexc_native', 'coinglass_aggregate', 'coinglass_mexc_only', 'coingecko'`. DATA-12 + STOR-01 + Pitfall 16. The CHECK constraint is created in the migration; an additional CI test grep-asserts every raw_* migration includes the `source` column and the CHECK.
- **D-60:** **`quality_flag TEXT` column on every raw table** with enum `'ok', 'gap_detected', 'partial_candle', 'late_arrival', 'ws_rest_divergence', 'schema_warn', 'partial_capture'`. Default `'ok'`. STOR-09 + Pitfall 21. `bfill` and forward-looking interpolation REMAIN BANNED (Phase 2 lint rule shipped here as forward placeholder — actually adding the lint rule is Phase 2 per FEAT-14).
- **D-61:** **`ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()` column on every raw table** — operational hygiene; used by freshness gauges and for forensic backtracking.
- **D-62:** **Idempotency strategy — staging-table COPY-then-merge:**
    ```python
    async with conn.transaction():
        await conn.copy_records_to_table('raw_mexc_candles_1m_staging', records=...)
        await conn.execute("""
            INSERT INTO raw_mexc_candles_1m
            SELECT * FROM raw_mexc_candles_1m_staging
            ON CONFLICT (symbol, ts) DO NOTHING
        """)
        await conn.execute("TRUNCATE raw_mexc_candles_1m_staging")
    ```
    `ON CONFLICT DO NOTHING` (NOT `DO UPDATE`) — first write wins, re-ingest never overwrites. Staging table is a `CREATE UNLOGGED TABLE` per session for speed.
- **D-63:** **`symbols` lookup table (relational, NOT a hypertable):**
    ```sql
    CREATE TABLE symbols (
        symbol TEXT PRIMARY KEY,                  -- ccxt unified e.g. 'BTC/USDT:USDT'
        exchange TEXT NOT NULL DEFAULT 'mexc',
        market_type TEXT NOT NULL DEFAULT 'swap',
        mexc_native_symbol TEXT NOT NULL,         -- e.g. 'BTC_USDT'
        coinglass_symbol TEXT,                    -- e.g. 'BTC'
        coingecko_id TEXT,                        -- e.g. 'bitcoin'
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        delisted_at TIMESTAMPTZ,                  -- NULL = currently listed; soft delete
        listed_at TIMESTAMPTZ,                    -- if known from CoinGecko
        CONSTRAINT ck_symbols_no_self_cascade CHECK (true)  -- placeholder; CASCADE banned project-wide
    );
    ```
    Soft delete (`delisted_at = now()`) — never `DELETE` rows. `ON DELETE CASCADE` is structurally inert because the existing pre-commit grep guard refuses to commit migrations containing the substring.
- **D-64:** **`universe_snapshots` hypertable for point-in-time universe (Pitfall 1, UNIV-01..04):**
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
        PRIMARY KEY (snapshot_date, symbol)
    );
    SELECT create_hypertable('universe_snapshots', 'snapshot_date', chunk_time_interval => INTERVAL '90 days');
    ```
    Point-in-time query: `SELECT symbol FROM universe_snapshots WHERE snapshot_date = $T::DATE AND is_qualifying`. New-listing detection runs at the end of the snapshot job by diffing today's symbol set with yesterday's; new symbols emit `universe.symbol.new` event and Telegram alert.
- **D-65:** **All timestamps use `TIMESTAMP(timezone=True)` (PostgreSQL TIMESTAMPTZ).** STOR-03 + Pitfall 17. The Phase 0 pre-commit grep guard (forbidding `TIMESTAMP[^(]` outside helpers) carries forward — Phase 1 migrations must clear it.
- **D-66:** **`add_compression_policy` after `enable_compression` for every hypertable**, using the Phase 0 `shortfire.db.timescale` helpers (D-27). Phase 1 migrations call `create_hypertable` + `enable_compression` + `add_compression_policy` per the table from D-58.
- **D-67:** **Continuous aggregates for 5m / 15m / 1h / 4h** sourced from `raw_mexc_candles_1m`. Pattern:
    ```sql
    CREATE MATERIALIZED VIEW raw_mexc_candles_5m
    WITH (timescaledb.continuous) AS
    SELECT
        symbol,
        time_bucket('5 minutes', ts) AS ts,
        first(open, ts) AS open,
        max(high) AS high,
        min(low) AS low,
        last(close, ts) AS close,
        sum(volume) AS volume,
        max(quality_flag) AS quality_flag,           -- propagate worst flag in bucket
        'mexc_native'::TEXT AS source
    FROM raw_mexc_candles_1m
    GROUP BY symbol, time_bucket('5 minutes', ts);

    SELECT add_continuous_aggregate_policy('raw_mexc_candles_5m',
        start_offset => INTERVAL '2 hours',
        end_offset   => INTERVAL '5 minutes',
        schedule_interval => INTERVAL '5 minutes');
    ```
    Per-aggregate (start_offset, end_offset, schedule_interval, bucket):
    - 5m: (`2 hours`, `5 minutes`, `5 minutes`)
    - 15m: (`4 hours`, `15 minutes`, `15 minutes`)
    - 1h: (`12 hours`, `1 hour`, `1 hour`)
    - 4h: (`2 days`, `4 hours`, `4 hours`)

    All `start_offset` values are well inside the 7-day compression-after window on `raw_mexc_candles_1m`, so refreshes never touch compressed chunks (TimescaleDB 2.18 supports refreshing over compressed chunks, but staying inside the uncompressed window keeps the operational story simple).
- **D-68:** **No retention policies in Phase 1.** Goal is 1–2yr backfill — pruning is premature. Retention decision deferred to Phase 5 or whenever Railway storage cost forces it. Compression + continuous aggregates are sufficient for v1 budget.

### Storage: Repositories & Hot-Path Inserts (DATA-09, DATA-12)

- **D-69:** **SQLAlchemy 2.x Core (NOT ORM) for hot-path hypertable writes** — confirmed by CLAUDE.md tech stack matrix. SQLAlchemy ORM is acceptable for low-volume relational tables (`symbols`, `ingest_runs`, `dead_letter` metadata) but the per-row overhead matters at 1k+ rows/sec.
- **D-70:** **Hot-path writes use `asyncpg.Connection.copy_records_to_table` directly** (bypass SQLAlchemy entirely) into the per-session staging table from D-62. Concrete repo layer:
    ```python
    # src/shortfire/ingest/storage/copy.py
    async def copy_into_hypertable(
        engine: AsyncEngine,
        target_table: str,
        records: Iterable[tuple[Any, ...]],
        columns: tuple[str, ...],
        conflict_columns: tuple[str, ...],
    ) -> int:
        """COPY → staging → INSERT…ON CONFLICT DO NOTHING. Returns row count."""
    ```
    All `CandleRepo`-like Protocol implementations route through this single helper for write hot path. Reads use SQLAlchemy.
- **D-71:** **One `CandleRepo` implementation per timeframe**, all delegating to the same `copy_into_hypertable` helper, parameterized by target table — keeps the Protocol stable while accommodating per-timeframe chunk-interval/compression tuning.

### Ingest: Retry, Rate-Limit, Dead-Letter (DATA-10, DATA-11)

- **D-72:** **tenacity policies per-source, declared once in `src/shortfire/ingest/retry.py`:**
    ```python
    coinglass_retry = retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        wait=wait_exponential_jitter(initial=1, max=60),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(log, logging.WARNING),
    )
    ```
    Same shape for MEXC (with longer max=120) and CoinGecko. Retry on 5xx + 429 + network errors. Do NOT retry on 4xx/auth — fail fast and write to `dead_letter`.
- **D-73:** **aiolimiter is layered ABOVE tenacity** — limiter acquires before request, releases after response. ccxt's internal throttler is left ON (`enableRateLimit=True`) for defense-in-depth; aiolimiter is the project-level budget.
- **D-74:** **dead_letter schema:**
    ```sql
    CREATE TABLE dead_letter (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
        source TEXT NOT NULL,                     -- mexc/coinglass/coingecko/etc.
        endpoint TEXT NOT NULL,                   -- e.g. 'fetch_ohlcv'
        symbol TEXT,                              -- nullable; not every error is per-symbol
        raw_payload JSONB NOT NULL,
        error_type TEXT NOT NULL,                 -- exception class name
        error_msg TEXT NOT NULL,                  -- truncated to 2KB
        retries_attempted INTEGER NOT NULL DEFAULT 0,
        quality_flag TEXT NOT NULL DEFAULT 'schema_warn'
    );
    SELECT create_hypertable('dead_letter', 'ts', chunk_time_interval => INTERVAL '30 days');
    ```
    Every Pydantic `ValidationError` AND every exhausted-retry exception lands here. Telegram alert if `dead_letter` row count per source / hour exceeds threshold (10 by default).

### Orchestration: APScheduler 4 (ORCH-01..04)

- **D-75:** **APScheduler 4.x using `AsyncScheduler` + `SQLAlchemyDataStore(engine)` + `AsyncpgEventBroker.from_async_sqla_engine(engine)`** — note this is APScheduler 4 nomenclature; the older `PostgresJobStore` term in REQUIREMENTS.md ORCH-01 refers to the persistent-store concept, not the literal class name (`PostgresJobStore` is APScheduler 3.x). Planner must use the v4 API names exactly.
- **D-76:** **The scheduler runs INSIDE the `data-platform` FastAPI service via `lifespan` context manager:**
    ```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_engine_from_env()
        data_store = SQLAlchemyDataStore(engine)
        event_broker = AsyncpgEventBroker.from_async_sqla_engine(engine)
        scheduler = AsyncScheduler(data_store, event_broker)
        async with scheduler:
            await _register_all_jobs(scheduler)
            await scheduler.start_in_background()
            yield
    ```
    `_register_all_jobs` adds every cron/interval trigger idempotently by `id`. Re-deploys are safe.
- **D-77:** **Job graph (Phase 1):**

    | Job ID | Trigger | Description |
    |---|---|---|
    | `mexc.candles.live.aggregator` | continuous (async task launched in lifespan, not a scheduler job) | watch_trades → 1m candle build → COPY |
    | `mexc.candles.backfill.1d` | `IntervalTrigger(hours=24)` | sweep universe, fill any missing 1m gaps via REST |
    | `mexc.funding.live` | continuous (ws task) | watch_funding_rate |
    | `mexc.funding.backfill` | `CronTrigger(minute=2)` after each funding window (00:00/08:00/16:00 UTC) | REST `fetch_funding_rate_history` for last window |
    | `mexc.oi.poll` | `IntervalTrigger(minutes=5)` | round-robin tier-1 first, full universe sweep on the hour |
    | `mexc.l2.live` | continuous (ws task) | watch_order_book sampled per D-46 |
    | `mexc.trades.live` | continuous (ws task) | watch_trades persisted per D-47 |
    | `mexc.liquidations.live` | continuous (ws task) | watch_liquidations |
    | `coinglass.funding_agg` | `IntervalTrigger(minutes=5)` | batch endpoint, all symbols one call |
    | `coinglass.oi` | `IntervalTrigger(minutes=5)` | round-robin |
    | `coinglass.liq` | `IntervalTrigger(minutes=10)` | round-robin |
    | `coinglass.lsr` | `IntervalTrigger(minutes=15)` | round-robin |
    | `coingecko.universe` | `CronTrigger(hour=0, minute=30)` UTC | daily |
    | `universe.snapshot` | `CronTrigger(hour=0, minute=5)` UTC | daily snapshot + new-listing diff |
    | `backup.pg_dump` | `CronTrigger(hour=1, minute=0)` UTC | daily pg_dump → R2 |
    | `freshness.check` | `IntervalTrigger(minutes=1)` | scan all freshness gauges, fire alert if stale |
    | `dead_letter.alert` | `IntervalTrigger(minutes=5)` | aggregate dead_letter rows by source, alert if threshold |
    | `compaction.refresh.recent` | TimescaleDB internal (continuous aggregate policy) | NOT in APScheduler — Timescale handles |

- **D-78:** **Continuous ws tasks are NOT APScheduler jobs** — they are long-lived `asyncio.TaskGroup` members owned by the FastAPI lifespan. APScheduler manages the cron/interval jobs only. This separation matters: APScheduler retries delayed jobs, but a hung ws task needs the reconnect protocol from D-49, not a retry policy.
- **D-79:** **All scheduler job functions are top-level module functions accepting only primitive arguments** (no closures, no instance methods) so they can be serialized into `SQLAlchemyDataStore`. Internal dependencies are looked up lazily via a tiny `shortfire.ingest.context.get_engine()` accessor (engine is a module-level singleton inside `data-platform`).

### Backup & Restore (STOR-10)

- **D-80:** **Daily `pg_dump --format=custom --compress=zstd:9` → Cloudflare R2** via boto3 S3-compatible client. R2 chosen over Backblaze B2 because R2 charges $0 egress on restores (B2 charges egress). Bucket policy: object-lock enabled to prevent accidental deletion; lifecycle rule moves > 30-day-old dumps to colder storage tier.
- **D-81:** **Retention policy: 7 daily + 4 weekly + 6 monthly + indefinite annual.** ~17 dumps retained at steady state; at expected ~10 GB compressed each, ~170 GB R2 storage = ~$2.55/mo.
- **D-82:** **Restore drill documented in `docs/RESTORE.md`** — checklist runs through pulling the latest dump from R2, restoring into a fresh Postgres+Timescale instance via testcontainers, asserting hypertable count and row counts within expected bounds. Drill is **not automated as a cron in Phase 1** but the steps are committed; first manual drill executed during Phase 1 verification.
- **D-83:** **Backup secrets** stored as Railway env vars `R2__ACCOUNT_ID`, `R2__ACCESS_KEY_ID` (SecretStr), `R2__SECRET_ACCESS_KEY` (SecretStr), `R2__BUCKET_NAME`. Added to `DataPlatformSettings` as an optional `R2BackupSettings | None` block (matches D-16 pattern). `assert_no_trade_env_leaked` is unaffected — R2 is read-only-ish credentials.

### Observability Extensions (FOUND-05 carries forward; ORCH-03..04)

- **D-84:** **New Prometheus metric families on `data-platform` (extending the 4 base metrics from Phase 0):**
    - `shortfire_data_platform_ingest_rows_total{source, dataset}` — Counter
    - `shortfire_data_platform_ingest_duration_seconds{source, dataset}` — Histogram
    - `shortfire_data_platform_source_freshness_seconds{source, dataset, symbol}` — Gauge
    - `shortfire_data_platform_dead_letter_total{source, error_type}` — Counter
    - `shortfire_data_platform_universe_symbols_count{status}` — Gauge (status = 'qualifying' | 'non_qualifying' | 'delisted')
    - `shortfire_data_platform_backup_age_seconds` — Gauge (age of latest successful R2 upload)
    - `shortfire_data_platform_ws_reconnects_total{source, stream}` — Counter
    - `shortfire_data_platform_rate_limit_remaining{source}` — Gauge
    All registered in the existing custom `CollectorRegistry` from Phase 0 — no new registry.
- **D-85:** **Event taxonomy extensions** (added to `EVENTS` frozenset in `src/shortfire/observability/events.py`):
    - `ingest.started`, `ingest.completed`, `ingest.failed`, `ingest.rate_limited`, `ingest.dead_letter`
    - `universe.snapshot.created`, `universe.symbol.new`, `universe.symbol.delisted`
    - `freshness.degraded`, `freshness.recovered`
    - `backup.started`, `backup.completed`, `backup.failed`
    - `ws.connected`, `ws.disconnected`, `ws.reconnect`, `ws.stale`
    Phase 1 commits adding these BEFORE first use (the `assert_event_registered` guard from Phase 0 enforces this — fresh-deploy Phase 1 code crashes loudly if anyone forgets to register a new event).
- **D-86:** **Telegram bot integration MINIMAL for Phase 1** — only stale-data + dead-letter alerts. No commands, no inline keyboards. Implementation: `httpx`-call to `https://api.telegram.org/bot<TOKEN>/sendMessage` with `chat_id` from settings. NO `python-telegram-bot` framework dep — that lands in Phase 4 alongside `/halt` `/resume` `/status`. Settings additions on `DataPlatformSettings`:
    ```python
    class TelegramSettings(BaseModel):
        bot_token: SecretStr
        operator_chat_id: str
    telegram: TelegramSettings | None = None  # None = alerts logged only
    ```
- **D-87:** **Alert severity routing (UI-SPEC continuation):** `severity='warn'` for stale freshness, dead-letter > threshold, ws reconnect storms; `severity='crit'` for backup failure 24h, complete ws starvation > 15min, universe job failure. Severity is a Telegram message prefix + structlog `severity` field.

### Service Topology & Deploy (OPS-05..06)

- **D-88:** **No change to the 3-service topology from Phase 0.** `data-platform` (always-on, runs all of Phase 1's work) + `strategy-engine` (sleep-when-idle placeholder) + `dashboard` (sleep-when-idle placeholder). Phase 5 adds `risk-guard`.
- **D-89:** **Phase 0's `commit → push → Railway auto-deploy on green main`** rule continues unchanged. Phase 1 plans add Alembic migrations 0003 onwards; `preDeployCommand` in `railway.toml` already runs `alembic upgrade head` per Phase 0 plan 00-07.
- **D-90:** **`data-platform` resources may need bumping** to handle ws task fan-out (200 symbols × multiple streams). Phase 0 budgeted 1 vCPU / 2 GB RAM. Phase 1 plan-time profile dictates whether to bump to 2 vCPU / 4 GB. Default: ship at Phase 0 resources, scale only on observed OOM/throttle.

### Test Strategy (extends TEST-01..06 from Phase 0)

- **D-91:** **Coverage gate remains 80% project-wide.** `ingest/` directory entered the coverage scope per `pyproject.toml` `[tool.coverage.run] omit`; the existing `omit = ["src/shortfire/ingest/*"]` is REMOVED in Phase 1's pyproject edit. `risk/`, `execution/`, `strategy/` stay omitted until later phases populate them.
- **D-92:** **Phase 1 testing layers:**
    - **Unit (`tests/unit/ingest/...`)**: Pydantic schema validation against captured fixture payloads (mexc/coinglass/coingecko canned JSON); copy_into_hypertable contract tests via in-memory fakes; tenacity policy behavior tests; aiolimiter throttle tests via `freezegun`
    - **Integration (`tests/integration/ingest/...`)** using testcontainers Postgres+Timescale (already wired in Phase 0):
        - Re-ingest same fixture twice → row count unchanged (DATA-09 invariant)
        - Universe snapshot point-in-time correctness (UNIV-03 — Hypothesis property test)
        - Continuous aggregate refresh produces matching values vs hand-rolled SQL aggregate over the same 1m source
        - Source CHECK constraint rejects unknown source value
        - dead_letter receives row when fixture is malformed
    - **Contract (`tests/contract/...`)**: hit real APIs from a nightly CI job (gated, never on PR) with read-only keys; schema drift catches.
    - **Property (Hypothesis)**:
        - "Re-running ingest with re-ordered records produces identical hypertable state"
        - "universe_snapshots(T) returns exactly the symbols that were qualifying at T" (deterministic synthetic fixture)
        - "Funding row's published_ts <= settlement_ts" (already enforced at domain level — reinforced here)
- **D-93:** **API mocking pattern:** `respx` for Coinglass + CoinGecko (httpx); `aioresponses` for MEXC if ccxt's aiohttp transport is hit directly; otherwise inject a `FakeMexcClient` (already shipped in Phase 0 `tests/fakes/`) for high-level ingest tests.
- **D-94:** **Backfill integration test runs in CI but with the 6-day universe slice** (≤200 symbols × 1m × 6 days ≈ 1.7M rows) to keep CI under 5 min. Full-year backfill is a one-off operational task, not a CI gate.

### Code Organization (extends Phase 0 layout, follows ARCHITECTURE.md §Recommended Project Structure)

- **D-95:** New directory tree under `src/shortfire/`:
    ```
    src/shortfire/
      ingest/                                  # was empty in Phase 0; populated here
        __init__.py
        base.py                                # IngestClient base helpers
        retry.py                               # per-source tenacity policies (D-72)
        rate_limit.py                          # per-source aiolimiter wrappers (D-73)
        context.py                             # process-wide singletons (engine, settings)
        storage/
          __init__.py
          copy.py                              # copy_into_hypertable (D-70)
        mexc/
          __init__.py
          client.py                            # concrete MexcClient impl
          backfill.py                          # paginated fetch_ohlcv (D-42)
          live_candles.py                      # watch_trades → 1m aggregator (D-43)
          funding.py
          oi.py
          orderbook.py                         # watch_order_book sampler (D-46)
          trades.py                            # watch_trades persister (D-47)
          liquidations.py
          schemas.py                           # response Pydantic models
        coinglass/
          __init__.py
          client.py                            # httpx-backed CoinglassClient impl
          funding_agg.py
          oi.py
          liq.py
          lsr.py
          schemas.py
        coingecko/
          __init__.py
          client.py
          universe.py
          schemas.py
        universe/
          __init__.py
          snapshot.py                          # daily universe snapshot + diff (D-64, D-77)
          tier1.py                             # top-50 by 7d volume designation (D-46)
        backup/
          __init__.py
          pg_dump_r2.py                        # daily backup job (D-80)
        freshness/
          __init__.py
          gauges.py                            # per-source freshness gauge updaters
          alerter.py                           # stale-data Telegram alerts
        dead_letter/
          __init__.py
          writer.py                            # write_to_dead_letter() (D-74)
          alerter.py                           # threshold-based DLQ Telegram alerts
        scheduler/
          __init__.py
          bootstrap.py                         # AsyncScheduler + DataStore wiring (D-75/D-76)
          jobs.py                              # _register_all_jobs (D-77)

      db/
        models/                                # NEW: SQLAlchemy models for lookup tables only
          __init__.py
          symbols.py                           # symbols (relational, D-63)
          ingest_runs.py
          dead_letter.py
        # Existing Phase 0 files preserved: base.py, engine.py, timescale.py

      observability/
        telegram.py                            # NEW: minimal httpx-based bot client (D-86)
        # Existing Phase 0 files preserved: events.py, logging.py, metrics.py, middleware.py
        # events.py extended with new entries from D-85

      settings/
        # Existing files preserved; data_platform.py extended with TelegramSettings + R2BackupSettings
    ```

- **D-96:** **Alembic migrations 0003 → 0014** (one logical schema unit each — keeps blame and review small):
    ```
    0003_raw_mexc_candles_1m_1d.py     # 1m hypertable + 1d hypertable + compression
    0004_raw_mexc_funding.py
    0005_raw_mexc_oi.py
    0006_raw_mexc_trades.py
    0007_raw_mexc_l2_top20.py
    0008_raw_mexc_liquidations.py
    0009_raw_coinglass.py              # funding_agg + oi + liq + lsr in one migration
    0010_raw_coingecko_market.py
    0011_universe_snapshots.py
    0012_symbols_lookup.py             # relational, not hypertable
    0013_dead_letter_and_ingest_runs.py
    0014_continuous_aggregates_5m_15m_1h_4h.py
    ```
    Each migration: `op.create_table` + `create_hypertable` + `enable_compression` + `add_compression_policy` via the Phase 0 helpers (D-27). Migration 0014 uses raw `op.execute` for the `CREATE MATERIALIZED VIEW … WITH (timescaledb.continuous)` + `SELECT add_continuous_aggregate_policy(...)` (continuous aggregates do not have Alembic helpers; this is the one place raw `op.execute` lives, with an inline comment justifying the carve-out from D-27).

### Claude's Discretion

The user said "сам все области собери и пройдись по ним максимально детально" — explicitly delegating ALL gray-area choices to Claude under `--auto --all`. The decisions above are Claude's recommendations using the Context7-verified APIs (ccxt 4.5, TimescaleDB 2.18 continuous aggregates, APScheduler 4 `AsyncScheduler` + `SQLAlchemyDataStore`) and the established Phase 0 patterns. Implementation-level details NOT in this list (exact SQLAlchemy table model class names, exact JSONB structure of L2 `bids`/`asks` arrays, the precise prometheus-client Gauge labels beyond what D-84 names, the precise tenacity `wait_exponential_jitter` initial/max for MEXC vs Coinglass vs CoinGecko) are intentionally left to planning-time resolution by `gsd-phase-researcher` and `gsd-planner`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents (gsd-phase-researcher, gsd-planner) MUST read these before planning or implementing.**

### Project-level (canonical sources of truth)
- `.planning/PROJECT.md` — Core value, gates, autonomy escalation, deferred decisions (Russian-language strategy rationale)
- `.planning/ROADMAP.md` — 6 phases, hard gates table, sequencing rationale; Phase 1 success criteria
- `.planning/REQUIREMENTS.md` — 152 v1 REQ-IDs; Phase 1 owns DATA-01..12, STOR-01..10, UNIV-01..04, ORCH-01..04, OPS-05, OPS-06 (32 reqs)
- `CLAUDE.md` — Tech stack matrix; "Use SQLAlchemy Core (not ORM) for hot-path hypertable inserts"; library version pins

### Phase 0 carry-forward (locks that Phase 1 BUILDS ON, does not redo)
- `.planning/phases/00-foundation/00-CONTEXT.md` — All Phase 0 decisions D-01 through D-34 (numbering continues at D-35 here)
- `.planning/phases/00-foundation/00-VERIFICATION.md` — verified Phase 0 success criteria (TimescaleDB helper module, asyncpg engine, 3 services live, secret-scan defense, fakes shipped)
- `.planning/phases/00-foundation/00-UI-SPEC.md` — `/metrics` and `/health` contracts that Phase 1 extends (metric naming convention, event taxonomy registry rules, severity routing)
- `src/shortfire/db/timescale.py` — `create_hypertable`, `enable_compression`, `add_compression_policy`, `add_retention_policy` helpers (D-27); Phase 1 migrations call these (NEVER raw `op.execute`)
- `src/shortfire/db/engine.py` — `create_engine_from_env()` returns the AsyncEngine that APScheduler `SQLAlchemyDataStore` and `AsyncpgEventBroker` will share
- `src/shortfire/db/base.py` — `Base` DeclarativeBase + NAMING_CONVENTION for new lookup-table models
- `src/shortfire/clients/{mexc,coinglass,coingecko,repos}.py` — Protocol definitions Phase 1 must satisfy with concrete implementations
- `src/shortfire/domain/{market,trading,risk}.py` — `Candle`, `OrderBook`, `Funding`, `Liquidation` types with TIMESTAMPTZ + Decimal invariants; Phase 1 ingest converts every API response THROUGH these types
- `src/shortfire/settings/data_platform.py` — `DataPlatformSettings` already exposes `mexc`, `coinglass`, `coingecko` optional blocks; Phase 1 wires the real keys and adds `telegram` + `r2_backup`
- `src/shortfire/observability/{metrics,events,logging,middleware}.py` — extended by Phase 1 (D-84, D-85)
- `tests/fakes/{mexc,coinglass,coingecko,repos}.py` — Phase 0 fake implementations; Phase 1 expands them with deterministic OHLCV/funding/OI/orderbook generators for integration tests
- `tests/integration/db/test_alembic_and_hypertables.py` — Phase 0 baseline; Phase 1 adds per-table tests for hypertable existence, compression policy, continuous aggregate refresh, source CHECK constraint, idempotency

### Project research (single source of truth for "why these choices")
- `.planning/research/SUMMARY.md` — Executive summary, hard gates, research flags, cross-research-tensions
- `.planning/research/ARCHITECTURE.md` — 6 logical layers, Pattern 2 (typed-per-source hypertables, EAV REJECTED), Pattern 5 (pure-function feature primitives), §State Management table, §Anti-Pattern 1 (Universal EAV) §Anti-Pattern 6 (fire-and-forget asyncio)
- `.planning/research/PITFALLS.md` — Phase 1 is the addressing-phase for Pitfalls 1, 4, 11, 16, 17, 21, 26, 27 — every Phase 1 design decision must explicitly cite which pitfall it mitigates
- `.planning/research/STACK.md` — version pins (ccxt 4.5.54, TimescaleDB 2.18 PG16, APScheduler 4, asyncpg 0.30+, Polars 1.40, Pydantic 2.7+), Coinglass tier comparison table
- `.planning/research/FEATURES.md` — Phase 1 "must have" data platform features cross-referenced

### Memory-tracked overrides (critical — override docs above)
- `/Users/mishanikhinkirtill/.claude/projects/-Users-mishanikhinkirtill-Desktop-ShortFIRE/memory/project_data_tier_subscriptions.md` — User's actual Coinglass + CoinGecko subscriptions ARE ~$35/mo each, NOT the $79 Startup that ROADMAP.md / REQUIREMENTS.md still reference. **D-35..D-37 lock the override.** Planner must use these numbers and patch ROADMAP/REQUIREMENTS in the same commit that lands the Phase 1 plan.

### External docs (verified via Context7 during this discussion)
- **ccxt 4.5 Manual** — `fetchOHLCV(symbol, timeframe, since, limit, params)`, `fetchFundingRateHistory`, `fetchTrades`, `watchTrades`, `watchOrderBook`, swap default-type pattern, MEXC swap class quirks (ccxt#27253 `watch_ohlcv` hang, ccxt#28532 May-2026 swap order endpoint fix)
- **TimescaleDB 2.18 Docs** — `CREATE MATERIALIZED VIEW … WITH (timescaledb.continuous)` + `add_continuous_aggregate_policy(start_offset, end_offset, schedule_interval)` pattern (verified May 2026)
- **APScheduler 4 Docs** — `AsyncScheduler` + `SQLAlchemyDataStore(engine)` + `AsyncpgEventBroker.from_async_sqla_engine(engine)`; `IntervalTrigger`, `CronTrigger`; `start_in_background()` inside FastAPI lifespan. **`PostgresJobStore` is APScheduler 3.x — DO NOT USE that class name in Phase 1 code; REQUIREMENTS.md ORCH-01 refers to the persistent-store concept, not the literal class.**

### Vendor pricing & rate-limit pages (planner re-verifies at plan time)
- Coinglass v4 docs + pricing page (Hobbyist tier: 30 req/min, 1m derivatives history ~6 days, 5m+ history months-deep)
- CoinGecko Demo / Analyst tier docs (rate limits + endpoint coverage)
- MEXC futures API docs (public 20 req/s, signed `recv_window` defaults, futures swap endpoint set)
- Cloudflare R2 S3-compatible API docs (`boto3` client config, lifecycle rules, object-lock)

### Phase 1 success criteria anchors (from ROADMAP.md §Phase 1)
- ROADMAP.md success #1 — ≥1 year backfill complete on Coinglass Startup tier WITHOUT duplicates, every derivatives row has explicit `source` (D-35 overrides "Startup" → "Hobbyist"; otherwise unchanged)
- ROADMAP.md success #2 — `universe_snapshots(T)` returns symbols qualifying AT T (point-in-time); Hypothesis property test enforces (D-64)
- ROADMAP.md success #3 — re-ingest idempotent on `(symbol, ts, source)`; failed validations → `dead_letter`; `quality_flag` flags gaps (D-58/D-60/D-62/D-74)
- ROADMAP.md success #4 — 3 Railway services live; auto-deploy on push; freshness gauges + Telegram stale-data alerts (D-84/D-86/D-87/D-88/D-89)
- ROADMAP.md success #5 — daily off-Railway `pg_dump` to R2; restore drill documented; continuous aggregates for 5m/15m/1h/4h; all TIMESTAMPTZ; ON DELETE CASCADE banned (D-80/D-82/D-67/D-65; CASCADE ban already enforced by Phase 0 grep guard)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (shipped in Phase 0 — Phase 1 must reuse, not rebuild)

- **`shortfire.db.timescale`** — `create_hypertable`, `enable_compression`, `add_compression_policy`, `add_retention_policy` helpers. **D-27 prohibits any raw `op.execute("SELECT create_hypertable…")` in migrations** — every Phase 1 migration goes through these helpers. The lone carve-out is migration 0014 (continuous aggregates — no helper exists for them yet; plan adds a `create_continuous_aggregate` helper IF the pattern repeats).
- **`shortfire.db.engine.create_engine_from_env()`** — returns the shared `AsyncEngine`. APScheduler `SQLAlchemyDataStore` and every ingest worker reuse this single engine. Pool size 5 is fine for Phase 1.
- **`shortfire.db.base.Base`** — `DeclarativeBase` + NAMING_CONVENTION (`pk_/uq_/ix_/ck_/fk_`). Required base class for every new lookup-table model (`symbols`, `ingest_runs`, `dead_letter` metadata if modeled as ORM). Hypertables themselves are migration-only — they do NOT need ORM models for the hot-path write side.
- **`shortfire.clients.MexcClient` / `CoinglassClient` / `CoinGeckoClient` / `CandleRepo`** Protocols — Phase 1 ships the concrete `MexcClient` (ccxt), `CoinglassClient` (httpx), `CoinGeckoClient` (httpx), and per-timeframe `CandleRepo` implementations. The Protocols are STABLE — if Phase 1 needs to add a method, it adds it to the Protocol AND every fake in `tests/fakes/`.
- **`shortfire.domain.market.{Candle, OrderBook, OrderBookLevel, Funding, Liquidation}`** — every API response is normalized to one of these types before any persistence. `source: Source` already exists on `Candle` (Literal `'mexc' | 'coinglass' | 'coingecko'`) — Phase 1 extends the literal alias to include explicit `'mexc_native'`, `'coinglass_aggregate'`, `'coinglass_mexc_only'`, `'coingecko'` to match the storage layer's CHECK constraint. **This is a deliberate domain-type change** flagged for planner: bump types and update Phase 0 property tests in one of the early Phase 1 plans.
- **`shortfire.observability.metrics.build_metrics_for_service` + custom `CollectorRegistry`** — Phase 1 registers new metric families on the same registry, no fresh `CollectorRegistry`. D-84 lists the new families.
- **`shortfire.observability.events.EVENTS` frozenset + `assert_event_registered`** — Phase 1 extends `EVENTS` (D-85). The structural guard fires loudly if anyone forgets.
- **`shortfire.settings.data_platform.DataPlatformSettings`** — already has `mexc`, `coinglass`, `coingecko` as `… | None` blocks; Phase 1 (a) makes them non-None at startup by wiring Railway env vars, and (b) adds `telegram: TelegramSettings | None` + `r2_backup: R2BackupSettings | None` blocks. The anti-leak guard `assert_no_trade_env_leaked()` is untouched (still no `mexc_trade` field on data-platform).
- **`alembic/`** infrastructure — `env.py` reads `DATABASE_URL` and rewrites to `postgresql+asyncpg://`; `transaction_per_migration=True`; naming convention from `Base.metadata`. Phase 1 migrations 0003+ just write the actual schema; the harness is done.
- **`tests/fakes/{mexc,coinglass,coingecko,repos}.py`** — Phase 0 stubs. Phase 1 expands them with synthetic Candle/Funding/OI/Liquidation/OrderBook generators (Hypothesis-friendly) so integration tests never hit a real API.
- **`tests/integration/db/test_alembic_and_hypertables.py`** — the existing testcontainers harness is the template for every new Phase 1 integration test.
- **Pre-commit grep guards** — already block `TIMESTAMP[^(]` outside helpers and `ON DELETE CASCADE` anywhere under `alembic/versions/`. Phase 1 migrations pass through them automatically.
- **GitHub Actions CI** — ruff + pyright + pytest + gitleaks-action; coverage gate at 80%. Phase 1 removes `src/shortfire/ingest/*` from the coverage `omit` list in `pyproject.toml`, exposing the new code to the 80% gate (D-91).

### Established Patterns

- **Protocol-first boundaries with fakes** (FOUND-08 / D-06): Every external client is a Protocol; every Protocol has a Fake in `tests/fakes/`. Phase 1 shipping a concrete `MexcClient` does NOT delete `FakeMexcClient` — it expands it.
- **`source` column attribution from the schema up** (D-12, Pitfall 16): the domain `Source` literal, the DB `source` column with CHECK, the Pydantic schema, and the API normalizer are all in lockstep. Adding a new source = update all four in one commit.
- **TIMESTAMPTZ-only timestamps** (D-12, STOR-03): Pydantic rejects naive at construction; Postgres rejects naive at insert; the pre-commit grep guard rejects naive in DDL. Three lines of defense.
- **Idempotency-by-construction** (DATA-09): every raw table has `(symbol, ts, source)` as the dedup key; every COPY routes through staging-then-merge; every retry is idempotent by virtue of the same dedup key.
- **No fire-and-forget `asyncio.create_task`** (Pitfall 27): `asyncio.TaskGroup` for any task that must outlive a single request.
- **No raw `op.execute` for TimescaleDB DDL** (D-27): helpers always. The single carve-out for continuous aggregates is justified inline.
- **`safe_summary()` on Settings** (D-21): every new Settings block adds a boolean-flag entry (not the SecretStr value) to `safe_summary()`.
- **commit → push → Railway auto-deploy** (PROJECT.md DevOps): branch protection on `main`; CI gates merges; Railway redeploys all 3 services on green.

### Integration Points

- The shared `AsyncEngine` is the bus between APScheduler's `SQLAlchemyDataStore` + `AsyncpgEventBroker` and every ingest worker's `copy_into_hypertable` helper.
- `data-platform`'s FastAPI `lifespan` is where every long-lived ws task is spawned via `asyncio.TaskGroup` AND where APScheduler is started in background — both end when lifespan exits.
- New `src/shortfire/ingest/context.py` exposes process-wide singletons (engine, settings, metrics) so APScheduler job callables (which must be picklable / importable, see D-79) can look them up without closures.
- `tests/fakes/repos.py` is the seam that lets Phase 2 feature engineering use the same `CandleRepo` Protocol that Phase 1 implements over Postgres+Timescale — no Phase 2 code touches asyncpg directly.

</code_context>

<specifics>
## Specific Ideas

- **The "tier-1" universe concept (D-46)** — top-50 by 7-day rolling volume gets 5s L2 sampling; the rest gets 10s. This sets up Phase 2 feature engineering to have higher-fidelity L2-derived features on the symbols that actually generate signals (memecoin pumps mostly happen in the tier-1 cohort once 7-day volume builds). Tier-1 designation is a DAILY recomputation, persisted to `symbols.tier` (extend D-63 with `tier INTEGER` column) — so Phase 2 features can join on this without recomputing.
- **L2 wide schema (JSONB `bids`/`asks` arrays) over narrow rows (D-58)** — 600M rows vs 1.26B rows at 200 symbols × 17K snapshots/day × 365 days. The wide JSONB schema also keeps the slippage book-walk logic in Phase 3 trivial (one row per snapshot, walk JSONB array, no GROUP BY).
- **Continuous aggregates for 5m / 15m / 1h / 4h, but a SEPARATE 1d hypertable (D-67)** — the daily candle is cross-validated against `SUM(volume)` from the 1m hypertable; mismatches surface as a Phase 1 health-check signal. (Cheap insurance against forgotten 1m candles.)
- **Backup retention = 7 daily + 4 weekly + 6 monthly + indefinite annual (D-81)** — gives 6 months of point-in-time-ish recovery with bounded R2 cost ($2.55/mo at expected size). The "indefinite annual" leg matters because if Phase 2 EDA discovers something interesting about old market structure, we'll want the raw data, not just the aggregates.
- **Telegram Phase 1 is httpx-direct, NOT python-telegram-bot (D-86)** — Phase 1 needs at most 4 message types (stale-data, dead-letter, backup-failure, new-listing). 1 file, ~50 LOC, no async framework dep. python-telegram-bot enters in Phase 4 when /halt /resume /status need command handling.
- **Migration 0014 is the lone carve-out from D-27** — TimescaleDB continuous aggregates have no Alembic helper yet. Plan-time decision: either (a) add `create_continuous_aggregate(name, source_table, bucket, columns, ...)` to `shortfire.db.timescale` and call from migration 0014, OR (b) accept one raw `op.execute` block per CA with inline justification. (a) is more disciplined; (b) is faster. Defer to planner judgment — both are acceptable.
- **`watch_funding_rate` for live funding (D-44)** — ccxt 4.5 exposes this on the MEXC swap class. The Phase 1 implementation captures BOTH `settlement_ts` and `published_ts` to harden the Pitfall 2/16 mitigation for Phase 2 features.

</specifics>

<deferred>
## Deferred Ideas

### To revisit in later phases

- **Coinglass Standard tier ($299/mo) upgrade** — explicitly deferred to Phase 2 EDA per REQUIREMENTS.md V2-DATA-01 + ROADMAP.md hard-gates table. Trigger condition: Phase 2 EDA shows that 1m derivatives features beyond 6 days unlock edge that 5m/15m/1h aggregates cannot. If EDA does not show this, stay on Hobbyist forever.
- **Multi-exchange ingest (Binance/Bybit/OKX)** — schema already supports it via `source` column; new ingest clients just plug in. V2-EXCH-01 per REQUIREMENTS.md. Trigger: live MEXC-only edge holds for ≥3 months, AND a specific cross-venue signal emerges.
- **Backtest-grade L2 reconstruction** (V2-DATA-02) — Phase 1 captures forward L2 from commit-zero; deeper historical reconstruction (e.g. replaying trade tape against initial book snapshot) is a Phase 3+ enhancement IF the Phase 3 backtester finds the current top-20 5–10s sampling insufficient.
- **Prefect 3 migration** (V2-INFRA-01) — Phase 1 ships APScheduler 4. Migration trigger: DAG dependencies between ingest jobs become non-trivial (e.g. universe-snapshot blocks tier-1 designation blocks L2 sampler reconfiguration).
- **ClickHouse migration** (V2-INFRA-02) — only if TimescaleDB compression + continuous aggregates prove inadequate at scale. Trigger: hypertable scan latency on multi-month feature compute crosses 30s on the production instance.
- **Retention policies on hypertables** (deferred per D-68) — Phase 1 keeps everything. Retention enters when Railway storage cost or Phase 5+ scaling forces it.
- **Per-Coinglass-source attribution** — Coinglass exposes per-exchange breakdowns on some endpoints (`coinglass_mexc_only` source value is reserved in D-59). Phase 1 ships with `coinglass_aggregate` as the default; per-exchange split is a Phase 2 EDA decision IF it adds signal.
- **`python-telegram-bot` framework adoption** — Phase 4. Phase 1 stays on raw `httpx` calls to the Bot HTTP API (D-86).
- **MEXC IP allowlist on `READ_KEY`** — even the read-only key COULD be IP-allowlisted, but Railway egress IP stability is unverified. Phase 1 leaves the allowlist OFF for `READ_KEY` (low blast radius — read-only); Phase 5 verifies stability for `TRADE_KEY`.

### Must-do at Phase 1 plan-phase entry

- **Patch ROADMAP.md and REQUIREMENTS.md** in the same plan-phase commit that opens Phase 1: update DATA-07 / STOR-08 / V2-DATA-01 / Hard Gates / ROADMAP §Phase 1 success #1 from "Coinglass Startup ($79/mo)" → "Coinglass Hobbyist (~$35/mo)" with the reduced 1m derivatives window. Memory `project_data_tier_subscriptions.md` is the authoritative override; CONTEXT.md just locks the implementation around it.
- **Verify CoinGecko actual tier** at plan-phase entry. If the active key supports more than 30 req/min, relax D-56's aiolimiter. If exactly Demo (30/min), proceed as designed.

### Out of scope discussion notes

- **No scope creep redirected** — the user delegated full enumeration under `--auto --all`. Everything captured above is within Phase 1's boundary (Data Platform: ingest + storage + universe + orchestration + backup + Phase-1-appropriate observability + 3-service deploy). Items that LOOKED like creep candidates (kill switch, /halt commands, signal alerts, SHAP, Grafana, real-time backtest dashboard) are all correctly already-deferred by REQUIREMENTS.md / ROADMAP.md to Phases 4–5.

</deferred>

---

*Phase: 1-Data Platform*
*Context gathered: 2026-05-21*
