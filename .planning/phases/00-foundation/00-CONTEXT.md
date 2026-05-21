# Phase 0: Foundation - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Project scaffolding exists end-to-end on Railway with TDD harness, CI/CD pipeline, secret hygiene, pure domain types, observability skeleton, and deterministic test fakes — so every subsequent commit can be tested, deployed, and verified in the real environment from the first line of production code.

**In scope for Phase 0:**
- Repo skeleton: `src/shortfire/` single Python package + `src/shortfire/entrypoints/{data_platform,strategy_engine,dashboard}.py`
- uv + ruff + pyright + pytest + Hypothesis + pytest-asyncio + freezegun + respx wired and green
- 8 pure-Pydantic domain types with Hypothesis property tests on invariants (Candle, OrderBook, Funding, Liquidation, Signal, Order, Position, RiskLimits)
- pydantic-settings per-service subclasses with SecretStr credentials and `safe_summary()` for startup logs
- structlog with correlation-id middleware + Prometheus `/metrics` + structured-JSON `/health`
- Alembic async env + TimescaleDB helper module + 2 migrations (extension init + `service_event` hypertable with compression policy)
- docker-compose for local Postgres+Timescale (`timescale/timescaledb:2.18.0-pg16`)
- 3 Railway services scaffolded: `data-platform` (always-on), `strategy-engine` and `dashboard` (sleep-when-idle)
- Railway TimescaleDB marketplace template provisioned; `DATABASE_URL=${{Postgres.DATABASE_URL}}` reference variable on all 3 services
- GitHub Actions CI: ruff → pyright → pytest → coverage; auto-deploy to Railway on green main
- 4-layer secret-scan defense (pre-commit gitleaks + CI gitleaks-action + GitHub Push Protection + GitHub Secret Scanning)
- `tests/fakes/` with `FakeMexcClient`, `FakeCoinglassClient`, `FakeCoinGeckoClient`, `InMemoryCandleRepo` (Protocols defined; bodies stubbed)
- Integration tests for Alembic rerun-safety + hypertable existence + compression policy existence (testcontainers)

**Out of scope (explicitly punted to later phases):**
- Real ingest from MEXC/Coinglass/CoinGecko (Phase 1)
- Continuous aggregates (Phase 1, STOR-05)
- Daily pg_dump backups to R2/B2 (Phase 1, STOR-10)
- ML feature engineering, training, MLflow (Phase 2)
- Strategy Protocol + Registry + backtester (Phase 3)
- Paper trading, kill switch, full risk module, Telegram alerts (Phase 4)
- Grafana dashboards, Sentry (Phase 5)
- `risk-guard` 4th Railway service (Phase 5)
- ROADMAP/REQUIREMENTS update for actual Coinglass/CoinGecko subscription tiers (do this BEFORE Phase 1 plan-phase — see Deferred)

</domain>

<decisions>
## Implementation Decisions

### Service Topology & Repo Layout
- **D-01:** Scaffold **3 Railway services in Phase 0** with final v1 names: `data-platform`, `strategy-engine`, `dashboard`. `risk-guard` added in Phase 5. The 3-service topology gets exercised on day 1 instead of mid-Phase-1.
- **D-02:** **Single Python package** `src/shortfire/` (no uv workspace). One `pyproject.toml`, one `uv.lock`, one `Dockerfile`, one `alembic/` dir.
- **D-03:** Each Railway service runs the **same container image** with a different `startCommand` pointing to a different entrypoint: `uvicorn shortfire.entrypoints.{data_platform|strategy_engine|dashboard}:app --host 0.0.0.0 --port $PORT`.
- **D-04:** **`sleepApplication: true`** on `strategy-engine` and `dashboard` placeholders (cold-start ~2-3s on healthcheck wake); `data-platform` always-on (Phase 1 needs ingest scheduler running).
- **D-05:** **No `watchPatterns` in Phase 0.** Every commit redeploys all 3 services — matches PROJECT.md "commit → push → deploy after every task". Revisit if cost or instability becomes an issue.
- **D-06:** Repo top-level layout:
  ```
  src/shortfire/
    domain/         # 8 Pydantic types (Phase 0)
    settings/       # per-service BaseAppSettings subclasses (Phase 0)
    observability/  # structlog + Prometheus + correlation-id middleware (Phase 0)
    db/             # SQLAlchemy DeclarativeBase + Timescale helpers + async engine (Phase 0)
    clients/        # Protocols for MexcClient, CoinglassClient, CoinGeckoClient (Phase 0)
    ingest/         # empty Phase 0; filled in Phase 1
    strategy/       # empty Phase 0; filled in Phase 2-3
    execution/      # empty Phase 0; filled in Phase 4
    risk/           # empty Phase 0; filled in Phase 4-5
    entrypoints/
      data_platform.py
      strategy_engine.py
      dashboard.py
  tests/
    fakes/          # FOUND-08 deterministic fakes
    unit/
    integration/    # testcontainers-based, pytest -m integration
  alembic/
  docker-compose.yml
  Dockerfile
  pyproject.toml
  uv.lock
  .pre-commit-config.yaml
  .github/workflows/ci.yml
  .gitignore
  .env.example
  ```

### Domain Types Modeling
- **D-07:** **Pure Pydantic v2 BaseModel for ALL 8 domain types.** No msgspec, no frozen dataclasses, no SQLAlchemy ORM in domain layer.
- **D-08:** **`model_config = ConfigDict(frozen=True, strict=True)`** for Candle, OrderBook, OrderBookLevel, Funding, Liquidation, Signal, Order, RiskLimits. **Position has `frozen=False`** (mutates as fills land — event-sourced refactor deferred to Phase 3).
- **D-09:** **`Decimal` everywhere for money** (prices, quantities, PnL, notional). NUMERIC(38,18) in Postgres. **Lint rule** (pre-commit grep) bans `: float` annotations under `src/shortfire/domain/`. Cast to `float64` only at the polars/numpy ML-feature boundary.
- **D-10:** **`Literal[...]` for all enum-like fields** (Timeframe, Source, SignalSide, SignalKind, OrderIntent, OrderType). Behavior dispatch goes in module-level functions, NOT StrEnum methods. Uniform pattern across the codebase.
- **D-11:** **`tuple[X, ...]` (not `list[X]`) in frozen models** for collections (OrderBook.bids/asks, Signal.shap_top).
- **D-12:** **Timestamps: `datetime` with mandatory tz-aware UTC.** `@model_validator(mode='after')` rejects naive. Mirrors STOR-03 (TIMESTAMPTZ-only) — invariant established at domain layer.
- **D-13:** **Invariants enforced at construction** (not at boundaries):
  - Candle: `low ≤ open,close ≤ high`
  - OrderBook: bids descending by price, asks ascending, not crossed
  - Funding: `published_ts ≤ settlement_ts`
  - **Order: `intent='close' ⇒ reduce_only=True`** (EXEC-01/02 enforced mechanically — cannot construct a close order with reduce_only=False)
  - RiskLimits: `max_per_trade_pct ≤ 0.05`, `max_gross_exposure_pct ≤ 0.15`, `kelly_fraction ≤ 0.25` (RISK-02 hard caps as field constraints via `Field(le=...)`)
- **D-14:** **File layout:**
  - `src/shortfire/domain/market.py` — Candle, OrderBookLevel, OrderBook, Funding, Liquidation
  - `src/shortfire/domain/trading.py` — Signal, Order, Position
  - `src/shortfire/domain/risk.py` — RiskLimits
- **D-15:** **Hypothesis property tests required at Phase 0** for every invariant:
  - "Violation builds raise ValidationError" per invariant
  - "Round-trip `model_dump` / `model_validate` preserves all fields"
  - "Naive datetime rejected"
  - "Order(intent='close', reduce_only=False) raises ValidationError"
  - "RiskLimits(max_per_trade_pct=0.06) raises ValidationError" (RISK-02 hard cap)

### Settings & Local-Dev Secrets
- **D-16:** **Per-service `BaseAppSettings` subclasses** (not one big shared class):
  - `BaseAppSettings(BaseSettings)` — shared common fields (`service_name`, `port`, `db`, `common`)
  - `DataPlatformSettings` — Phase 1+ adds `mexc: MexcReadSettings`, `coinglass`, `coingecko`
  - `StrategyEngineSettings` — Phase 2+ adds `mlflow_tracking_uri`; Phase 5+ adds `mexc_trade: MexcTradeSettings`
  - `DashboardSettings` — minimal; Phase 5+ may add Telegram bot creds
  - `RiskGuardSettings` — Phase 5 only; no external API keys
  - Each entrypoint instantiates ITS specific class → pydantic-native fail-fast on missing required fields.
  - **Anti-leak guarantee:** `DataPlatformSettings` has NO `mexc_trade` field → even if `MEXC_TRADE__SECRET` env var is somehow visible to data-platform, pydantic-settings won't load it. Plus startup assertion: `assert "MEXC_TRADE__SECRET" not in os.environ` on data-platform.
- **D-17:** **`SettingsConfigDict`** for `BaseAppSettings`:
  ```python
  SettingsConfigDict(
      env_file=".env.local" if env != "production" else None,
      env_file_encoding="utf-8",
      env_nested_delimiter="__",
      case_sensitive=False,
  )
  ```
  No `env_prefix` — use ALL_CAPS conventional names where Railway already injects them (`DATABASE_URL`, `PORT`, `LOG_LEVEL`).
- **D-18:** **Env-var naming convention:**
  - Top-level: `DATABASE_URL`, `LOG_LEVEL`, `ENV`, `SERVICE_NAME`, `PORT`
  - Nested via `__`: `MEXC__READ_KEY`, `MEXC__READ_SECRET`, `COINGLASS__API_KEY`, `COINGECKO__API_KEY`, `TELEGRAM__BOT_TOKEN`, `MEXC_TRADE__TRADE_KEY` (Phase 5), `MEXC_TRADE__TRADE_SECRET` (Phase 5)
- **D-19:** **`SecretStr` for every credential field.** Never plain `str` for API keys, tokens, DSNs that embed passwords. `.get_secret_value()` is called only at ccxt/client init — confined to client init code.
- **D-20:** **Local-dev story:**
  - `.env.example` (committed, template, no real values)
  - `.env.local` (gitignored, developer fills with local Postgres URL and dev API keys if any)
  - Production: `ENV=production` set on Railway; pydantic-settings skips `env_file`; Railway injects env vars directly
  - **Phase 4+ real trade keys: `railway run` to test locally — NEVER in `.env.local`.**
- **D-21:** **`safe_summary()` method** on every Settings class returns a sanitized dict for startup logs. `repr(settings)` is NEVER called; `log.info("settings.loaded", **settings.safe_summary())` is the canonical pattern.
- **D-22:** **4-layer secret-scan defense:**
  1. **gitleaks** in `.pre-commit-config.yaml` (developer's machine)
  2. **gitleaks-action** in GitHub Actions CI (every PR + push to main)
  3. **GitHub Push Protection** (server-side, free for known providers — enabled in repo settings)
  4. **GitHub Secret Scanning** (server-side history scan — enabled in repo settings)
- **D-23:** **`.gitignore` coverage:** `.env`, `.env.local`, `.env.*.local`, `*.env.bak`, `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/`, `coverage.xml`, `dist/`, `build/`, `*.egg-info/`, `.DS_Store`, `.vscode/`, `.idea/`.

### TimescaleDB & Migrations
- **D-24:** **Railway marketplace TimescaleDB template** for the shared database service (image `timescale/timescaledb:2.18.0-pg16`). All 3 app services link via `DATABASE_URL=${{Postgres.DATABASE_URL}}` reference variable. Private network: `postgres.railway.internal:5432`.
- **D-25:** **Local dev: docker-compose** with the same Timescale image:
  ```yaml
  services:
    postgres:
      image: timescale/timescaledb:2.18.0-pg16
      environment:
        POSTGRES_USER: shortfire
        POSTGRES_PASSWORD: shortfire
        POSTGRES_DB: shortfire_dev
        TIMESCALEDB_TELEMETRY: 'off'
      ports: ["5432:5432"]
      volumes: ["shortfire-pg:/var/lib/postgresql/data"]
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U shortfire"]
  volumes:
    shortfire-pg: {}
  ```
- **D-26:** **Alembic async template** (`alembic init -t async`). `alembic/env.py` reads `DATABASE_URL` from env, rewrites `postgres://` → `postgresql+asyncpg://`, sets `transaction_per_migration=True`, `compare_type=True`, `compare_server_default=True`, naming convention from `Base.metadata`.
- **D-27:** **TimescaleDB DDL helper module** `src/shortfire/db/timescale.py` with idempotent wrappers (NEVER raw `op.execute("SELECT create_hypertable(...)")` in migrations):
  - `create_hypertable(table, time_column='ts', chunk_interval='7 days', if_not_exists=True)`
  - `enable_compression(table, segment_by, order_by='ts DESC')`
  - `add_compression_policy(table, after_age='7 days', if_not_exists=True)`
  - `add_retention_policy(table, drop_after, if_not_exists=True)`
- **D-28:** **Phase 0 migrations (2 files):**
  - `alembic/versions/0001_init_timescaledb.py`: `CREATE EXTENSION IF NOT EXISTS timescaledb`
  - `alembic/versions/0002_service_event_hypertable.py`: creates `service_event(ts TIMESTAMPTZ, service_name TEXT, event_type TEXT, payload JSONB)` + `create_hypertable` + `enable_compression` + `add_compression_policy`. **This is a real long-term observability table, NOT a throwaway smoke object.**
- **D-29:** **DeclarativeBase + naming convention** in `src/shortfire/db/base.py`:
  ```python
  NAMING_CONVENTION = {
      "ix": "ix_%(column_0_label)s",
      "uq": "uq_%(table_name)s_%(column_0_name)s",
      "ck": "ck_%(table_name)s_%(constraint_name)s",
      "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
      "pk": "pk_%(table_name)s",
  }
  class Base(DeclarativeBase):
      metadata = MetaData(naming_convention=NAMING_CONVENTION)
  ```
- **D-30:** **asyncpg 0.30+ everywhere** (Alembic env + SQLAlchemy AsyncEngine + future hot-path ingest with `COPY BIN`). No psycopg in v1.
- **D-31:** **Integration tests use testcontainers-python** with `PostgresContainer("timescale/timescaledb:2.18.0-pg16")`. Marked `@pytest.mark.integration`. Tests required at Phase 0:
  - `test_alembic_upgrade_is_idempotent` — run `upgrade head` twice, assert no error
  - `test_service_event_is_hypertable` — query `timescaledb_information.hypertables`
  - `test_service_event_has_compression_policy` — query `timescaledb_information.compression_settings` / `jobs`
- **D-32:** **STOR-03 / STOR-07 enforcement starts at Phase 0:**
  - Pre-commit grep-check: forbid `TIMESTAMP[^(]` (must be `TIMESTAMP(timezone=True)`) anywhere under `alembic/versions/` and `src/`
  - Pre-commit grep-check: forbid `ON DELETE CASCADE` anywhere under `alembic/versions/`

### CI/CD & Coverage
- **D-33:** **GitHub Actions CI workflow** (`.github/workflows/ci.yml`):
  - Trigger: every push + every PR
  - Steps: `uv sync` → `uv run ruff format --check` → `uv run ruff check` → `uv run pyright` → `uv run pytest --cov` → gitleaks-action
  - Coverage gate: 80% project-wide at Phase 0. The 95% rule for `risk/` and `execution/` (TEST-04) lives in Phase 2 and ramps in when those modules ship.
  - Pre-Phase-1 the directories `src/shortfire/{risk,execution}/` exist with just `__init__.py`. No tests required, no coverage rule required until those modules contain real code.
- **D-34:** **Railway auto-deploy on green main.** Failing CI blocks merge (branch protection). Pre-deploy assertion in each entrypoint's `main()` sanity-checks env vars (via Settings subclass — fail-fast).

### Claude's Discretion
The user did not say "you decide" on anything. All decisions above came from explicit user selections. Claude has discretion ONLY on second-order details not surfaced by the discussion, e.g., the exact JSON schema of `service_event.payload`, the Dockerfile multistage layering, the precise structlog processor stack, the choice of pytest fixtures naming, etc. — these will be resolved at planning time.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents (gsd-phase-researcher, gsd-planner) MUST read these before planning or implementing.**

### Project-level
- `.planning/PROJECT.md` — Core value, constraints, key decisions, Russian-language strategy rationale
- `.planning/ROADMAP.md` — 6 phases, success criteria, hard gates, sequencing rationale
- `.planning/REQUIREMENTS.md` — 152 v1 REQ-IDs with traceability table; Phase 0 owns: FOUND-01..08, OPS-01..04, OPS-07, OPS-08, TEST-01, TEST-02, TEST-05, TEST-06
- `CLAUDE.md` — Tech stack matrix (Python 3.12, FastAPI, uv, Pydantic v2, TimescaleDB 2.18 on PG16, SQLAlchemy 2.x, asyncpg, ccxt 4.5, XGBoost 3.2, LightGBM 4.6, MLflow 3.x, Optuna 4.x, Ruff, pyright, pytest 8.x with Hypothesis); explicit "Use SQLAlchemy Core (not ORM) for hot-path hypertable inserts"

### Phase 0 success criteria anchors (from ROADMAP.md §Phase 0)
- ROADMAP.md success #1 — `git clone` + `uv sync` produces green `pytest` with Hypothesis on the 8 domain types
- ROADMAP.md success #2 — green CI auto-deploys to Railway; service answers `/metrics` (Prometheus) and `/health` (structured JSON with correlation ID)
- ROADMAP.md success #3 — pydantic-settings rejects startup on missing env var; secret-scan blocks committed secrets
- ROADMAP.md success #4 — `alembic upgrade head` applies TimescaleDB-aware migration (hypertable + compression policy); rerun-safe
- ROADMAP.md success #5 — `tests/fakes/` exposes 4 fake clients for downstream phases

### Memory-tracked project context
- `/Users/mishanikhinkirtill/.claude/projects/-Users-mishanikhinkirtill-Desktop-ShortFIRE/memory/project_data_tier_subscriptions.md` — User's actual Coinglass and CoinGecko subscriptions are ~$35/mo each (minimum tiers), NOT the $79 Startup tier assumed in PROJECT.md / REQUIREMENTS.md. **Phase 0 unaffected** (no real ingest yet) but Phase 1 plan-phase MUST reconcile.

### No external specs yet
No ADRs, design docs, or third-party specs are referenced for Phase 0. PROJECT.md + ROADMAP.md + REQUIREMENTS.md + CLAUDE.md are the only canonical sources.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
**None — this is a greenfield repo.** Only `.git/`, `.planning/`, `.claude/`, and `CLAUDE.md` exist before Phase 0 ships. Every file Phase 0 produces is net-new.

### Established Patterns
- **TDD discipline** (TEST-02): every module starts with a failing test. Documented in `CONTRIBUTING.md` or `AGENTS.md` (decide which during planning).
- **Commit → push → Railway auto-deploy** (PROJECT.md DevOps requirement): branch protection on `main`; CI gates merges; Railway deploys green main.
- **No external code to mimic.** Patterns are established BY Phase 0, not derived from existing code.

### Integration Points
- All 3 Railway services link to the Timescale Postgres service via `DATABASE_URL=${{Postgres.DATABASE_URL}}` reference variable
- All 3 services share `src/shortfire/{domain,settings,observability,db,clients}/` — these are the import boundaries that compounding code will respect
- `tests/fakes/` is the seam between Phase 0 (defines Protocols + fake bodies) and Phase 1 (implements real bodies satisfying the same Protocols)

</code_context>

<specifics>
## Specific Ideas

- **`service_event` table is a real long-term asset**, not a smoke placeholder. Every service writes heartbeat / restart / scheduled-task-run events here. Survives into Phase 1+ and powers ad-hoc observability queries.
- **`safe_summary()` pattern on Settings.** When the service starts, structlog emits a single `settings.loaded` event with sanitized fields — never a `repr(settings)` dump. This is the canonical "what config did this process boot with" log line.
- **EXEC-02 invariant baked into domain layer at construction.** `Order(intent="close", reduce_only=False)` raises `ValidationError`. The expensive runtime invariant (Hypothesis property test in Phase 4) becomes a STRUCTURAL invariant from Phase 0. No one can build a close-order without reduce_only because the type system says no.
- **RISK-02 hard caps as field constraints.** `Field(le=Decimal("0.05"))` on `max_per_trade_pct` — if a config row tries to set per-trade to 6%, RiskLimits construction fails at startup. The hard cap is structural, not a check that can be skipped.
- **Anti-leak architecture from Phase 0**, before any keys exist. `DataPlatformSettings` doesn't have a `mexc_trade` field at all; Phase 5 `TRADE_KEY` env var is structurally inert on the data-platform service.

</specifics>

<deferred>
## Deferred Ideas

### To revisit in later phases
- **Event-sourced Position** (immutable Position + Fill events) — revisit in Phase 3 backtester if BACK-10 deterministic reproducibility demands it. For Phase 0–2, mutable Position is acceptable.
- **msgspec for hot-path domain types** — revisit only if Phase 1+ profiling identifies Pydantic construction in the top-3 ingest hot spots. asyncpg COPY bypasses Pydantic on hot-path writes already, so this is unlikely to be the bottleneck.
- **watchPatterns per Railway service** — add later if Railway redeploy cost or instability becomes a concern.

### Must-do before Phase 1 plan-phase
- **ROADMAP.md / REQUIREMENTS.md update for actual subscription tiers.** User has Coinglass ~$35/mo and CoinGecko ~$35/mo (minimum tiers), not the Coinglass Startup ($79) referenced in DATA-07 / STOR-08 / V2-DATA-01 cost calculations. Either update those docs directly OR override in Phase 1 CONTEXT.md.
- **Coinglass Hobbyist limits empirical check.** 1m derivatives history window is ~6 days (vs Startup's 12) and rate limit is 30 req/min (vs Startup's 80). Phase 1 backfill strategy + ingest cadence must reckon with this.

### Out of scope discussion notes
- No scope creep redirected during this discussion — the user stayed within Phase 0 boundaries on all 4 areas.

</deferred>

---

*Phase: 0-Foundation*
*Context gathered: 2026-05-21*
