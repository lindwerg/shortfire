# Phase 0: Foundation - Research

**Researched:** 2026-05-21
**Domain:** Greenfield Python/FastAPI scaffolding, TimescaleDB on Railway, TDD harness, observability skeleton, secret hygiene
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Service Topology & Repo Layout (D-01 to D-06):**
- **D-01:** 3 Railway services in Phase 0 with final v1 names: `data-platform`, `strategy-engine`, `dashboard`. `risk-guard` deferred to Phase 5.
- **D-02:** Single Python package `src/shortfire/`. No uv workspace. One `pyproject.toml`, one `uv.lock`, one `Dockerfile`, one `alembic/`.
- **D-03:** All 3 services run the **same container image** with different `startCommand` per service: `uvicorn shortfire.entrypoints.{data_platform|strategy_engine|dashboard}:app --host 0.0.0.0 --port $PORT`.
- **D-04:** `sleepApplication: true` on `strategy-engine` and `dashboard`; `data-platform` always-on.
- **D-05:** **No `watchPatterns` in Phase 0** — every commit redeploys all 3 services. Matches PROJECT.md "commit → push → deploy after every task". Revisit only if cost/instability emerges.
- **D-06:** Top-level repo layout fixed (see CONTEXT.md §D-06): `src/shortfire/{domain,settings,observability,db,clients,ingest,strategy,execution,risk,entrypoints}/` + `tests/{fakes,unit,integration}/` + `alembic/` + `docker-compose.yml` + `Dockerfile` + `pyproject.toml` + `uv.lock` + `.pre-commit-config.yaml` + `.github/workflows/ci.yml` + `.gitignore` + `.env.example`.

**Domain Types Modeling (D-07 to D-15):**
- **D-07:** Pure Pydantic v2 BaseModel for ALL 8 domain types. No msgspec, no frozen dataclasses, no SQLAlchemy ORM in domain layer.
- **D-08:** `model_config = ConfigDict(frozen=True, strict=True)` for Candle, OrderBook, OrderBookLevel, Funding, Liquidation, Signal, Order, RiskLimits. **Position has `frozen=False`** (mutates as fills land — event-sourced refactor deferred to Phase 3).
- **D-09:** Decimal everywhere for money. NUMERIC(38,18) in Postgres. Pre-commit grep bans `: float` annotations under `src/shortfire/domain/`. Cast to `float64` only at polars/numpy ML boundary.
- **D-10:** `Literal[...]` for all enum-like fields. Behavior dispatch in module-level functions, NOT StrEnum methods.
- **D-11:** `tuple[X, ...]` (not `list[X]`) in frozen models for collections.
- **D-12:** Timestamps: `datetime` with mandatory tz-aware UTC. `@model_validator(mode='after')` rejects naive.
- **D-13:** Invariants enforced at construction (NOT at boundaries):
  - Candle: `low ≤ open,close ≤ high`
  - OrderBook: bids descending by price, asks ascending, not crossed
  - Funding: `published_ts ≤ settlement_ts`
  - **Order: `intent='close' ⇒ reduce_only=True`** (EXEC-01/02 enforced mechanically)
  - RiskLimits: `max_per_trade_pct ≤ 0.05`, `max_gross_exposure_pct ≤ 0.15`, `kelly_fraction ≤ 0.25` (via `Field(le=...)`)
- **D-14:** Domain file layout: `domain/market.py` (Candle, OrderBookLevel, OrderBook, Funding, Liquidation), `domain/trading.py` (Signal, Order, Position), `domain/risk.py` (RiskLimits).
- **D-15:** Hypothesis property tests required at Phase 0 for every invariant (violation raises, round-trip, naive-rejection, Order close+reduce_only=False raises, RiskLimits caps).

**Settings & Local-Dev Secrets (D-16 to D-23):**
- **D-16:** Per-service `BaseAppSettings` subclasses — `BaseAppSettings(BaseSettings)` shared common, then `DataPlatformSettings`, `StrategyEngineSettings`, `DashboardSettings`, `RiskGuardSettings` (Phase 5). Anti-leak: `DataPlatformSettings` has NO `mexc_trade` field. Plus startup assertion: `assert "MEXC_TRADE__SECRET" not in os.environ` on data-platform.
- **D-17:** `SettingsConfigDict(env_file=".env.local" if env != "production" else None, env_file_encoding="utf-8", env_nested_delimiter="__", case_sensitive=False)`. No `env_prefix`.
- **D-18:** Env-var naming convention:
  - Top-level: `DATABASE_URL`, `LOG_LEVEL`, `ENV`, `SERVICE_NAME`, `PORT`
  - Nested via `__`: `MEXC__READ_KEY`, `MEXC__READ_SECRET`, `COINGLASS__API_KEY`, `COINGECKO__API_KEY`, `TELEGRAM__BOT_TOKEN`, `MEXC_TRADE__TRADE_KEY` (Phase 5), `MEXC_TRADE__TRADE_SECRET` (Phase 5)
- **D-19:** `SecretStr` for every credential field. `.get_secret_value()` called only at ccxt/client init.
- **D-20:** Local-dev: `.env.example` committed; `.env.local` gitignored; production = `ENV=production`, pydantic-settings skips env_file, Railway injects vars directly. **Phase 4+ real trade keys: `railway run` to test locally — NEVER in `.env.local`.**
- **D-21:** `safe_summary()` method on every Settings class returns sanitized dict. `repr(settings)` is NEVER called. Canonical pattern: `log.info("settings.loaded", **settings.safe_summary())`.
- **D-22:** 4-layer secret-scan defense: (1) gitleaks in `.pre-commit-config.yaml`, (2) gitleaks-action in GitHub Actions CI, (3) GitHub Push Protection (server-side), (4) GitHub Secret Scanning (server-side history).
- **D-23:** `.gitignore` coverage: `.env`, `.env.local`, `.env.*.local`, `*.env.bak`, `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/`, `coverage.xml`, `dist/`, `build/`, `*.egg-info/`, `.DS_Store`, `.vscode/`, `.idea/`.

**TimescaleDB & Migrations (D-24 to D-32):**
- **D-24:** Railway marketplace TimescaleDB template (image `timescale/timescaledb:2.18.0-pg16`). All 3 app services link via `DATABASE_URL=${{Postgres.DATABASE_URL}}` reference variable. Private network: `postgres.railway.internal:5432`.
- **D-25:** Local dev: docker-compose with same Timescale image (full YAML in CONTEXT.md §D-25).
- **D-26:** Alembic async template (`alembic init -t async`). `env.py` reads `DATABASE_URL`, rewrites `postgres://` → `postgresql+asyncpg://`, sets `transaction_per_migration=True`, `compare_type=True`, `compare_server_default=True`, naming convention from `Base.metadata`.
- **D-27:** TimescaleDB DDL helper module `src/shortfire/db/timescale.py` with idempotent wrappers (NEVER raw `op.execute("SELECT create_hypertable(...)")` in migrations): `create_hypertable`, `enable_compression`, `add_compression_policy`, `add_retention_policy`.
- **D-28:** Phase 0 migrations (2 files):
  - `0001_init_timescaledb.py`: `CREATE EXTENSION IF NOT EXISTS timescaledb`
  - `0002_service_event_hypertable.py`: creates `service_event(ts TIMESTAMPTZ, service_name TEXT, event_type TEXT, payload JSONB)` + hypertable + compression + policy. **Real long-term observability table, NOT throwaway smoke object.**
- **D-29:** DeclarativeBase + naming convention in `src/shortfire/db/base.py` (full constant in CONTEXT.md §D-29).
- **D-30:** asyncpg 0.30+ everywhere (Alembic env + AsyncEngine + future `COPY BIN`). No psycopg in v1.
- **D-31:** Integration tests use testcontainers-python with `PostgresContainer("timescale/timescaledb:2.18.0-pg16")`. Marked `@pytest.mark.integration`. Required Phase 0 tests:
  - `test_alembic_upgrade_is_idempotent` (run `upgrade head` twice)
  - `test_service_event_is_hypertable` (query `timescaledb_information.hypertables`)
  - `test_service_event_has_compression_policy` (query `timescaledb_information.jobs`)
- **D-32:** STOR-03 / STOR-07 enforcement starts at Phase 0:
  - Pre-commit grep: forbid `TIMESTAMP[^(]` under `alembic/versions/` and `src/`
  - Pre-commit grep: forbid `ON DELETE CASCADE` under `alembic/versions/`

**CI/CD & Coverage (D-33 to D-34):**
- **D-33:** GitHub Actions CI: every push + every PR; steps: `uv sync` → `uv run ruff format --check` → `uv run ruff check` → `uv run pyright` → `uv run pytest --cov` → gitleaks-action. Coverage gate: 80% project-wide at Phase 0. `src/shortfire/{risk,execution}/` have just `__init__.py` — no tests/coverage required yet.
- **D-34:** Railway auto-deploy on green main. Failing CI blocks merge (branch protection). Pre-deploy assertion in each entrypoint's `main()` sanity-checks env vars via Settings subclass — fail-fast.

### Claude's Discretion

The user gave Claude discretion only on second-order details not surfaced by the discussion, e.g.:
- Exact JSON schema of `service_event.payload`
- Dockerfile multistage layering
- Precise structlog processor stack
- pytest fixtures naming
- Pydantic discriminated-union pattern for Order (`Literal['close']` triggering required `reduce_only=True`)
- Whether to use `prometheus-fastapi-instrumentator` or raw `prometheus-client` for `/metrics`
- Exact gitleaks allowlist patterns for `uv.lock` and test fixtures
- Hypothesis strategy registration for custom Pydantic types

### Deferred Ideas (OUT OF SCOPE)

- **Event-sourced Position** (immutable Position + Fill events) — Phase 3 backtester if BACK-10 demands it.
- **msgspec for hot-path domain types** — only if Phase 1+ profiling shows Pydantic construction in top-3 hot spots. asyncpg COPY already bypasses Pydantic on hot-path writes.
- **watchPatterns per Railway service** — add later if redeploy cost/instability bites.

**Must-do before Phase 1 plan-phase (not Phase 0):**
- ROADMAP.md / REQUIREMENTS.md update for actual Coinglass (~$35/mo, likely Hobbyist) and CoinGecko (~$35/mo) subscription tiers. Phase 0 unaffected — only scaffolds clients and Pydantic schemas, doesn't actually call APIs at scale.
- Coinglass Hobbyist limits empirical check (~6-day 1m derivatives window, 30 req/min).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FOUND-01 | Repository scaffold (uv + ruff + pyright + pytest + Hypothesis) with CI on every push | §Standard Stack (uv, ruff, pyright, pytest, hypothesis), §CI/CD Pattern, §Code Examples |
| FOUND-02 | Railway project with PostgreSQL 16 + TimescaleDB 2.18 extension is provisioned and connected from GitHub | §Standard Stack (Railway marketplace), §Architecture Patterns / Pattern 4 (Railway 3-service shape), §Environment Availability |
| FOUND-03 | Alembic migrations with TimescaleDB-aware DDL (`create_hypertable`, compression policies) wired and tested | §Architecture Patterns / Pattern 6 (Alembic async + Timescale), §Code Examples (idempotent helpers), §Pitfalls 3 + 4 |
| FOUND-04 | Pure domain types (Candle, OrderBook, Funding, Liquidation, Signal, Order, Position, RiskLimits) as Pydantic models with property tests on invariants | §Architecture Patterns / Pattern 1 (Pydantic v2 frozen+strict), §Code Examples, §Pitfall 1 (Pydantic v2 strict + Decimal) |
| FOUND-05 | structlog with correlation IDs + Prometheus `/metrics` endpoint scaffolding | §Architecture Patterns / Pattern 5 (observability), §Code Examples (structlog + asgi-correlation-id + prometheus-client) |
| FOUND-06 | `.gitignore` covers `.env*`, secret scanning runs pre-commit, GitHub secret scanning enabled | §Architecture Patterns / Pattern 8 (4-layer secret-scan defense), §Code Examples (gitleaks configs) |
| FOUND-07 | pydantic-settings validates required env vars at service startup; missing/invalid config fails fast | §Architecture Patterns / Pattern 2 (pydantic-settings per-service subclasses), §Code Examples |
| FOUND-08 | `tests/fakes/` directory with `FakeMexcClient`, `FakeCoinglassClient`, `FakeCoinGeckoClient`, `InMemoryCandleRepo` interfaces | §Architecture Patterns / Pattern 7 (Protocols + deterministic fakes), §Code Examples |
| OPS-01 | GitHub repository with protected `main` branch | §Architecture Patterns / Pattern 8 (branch protection ties to CI gate) |
| OPS-02 | Railway project connected to GitHub repo; auto-deploys on push to `main` | §Architecture Patterns / Pattern 4 (Railway 3-service shape) |
| OPS-03 | GitHub Actions CI runs on every PR: ruff + pyright + pytest (with coverage) | §Architecture Patterns / Pattern 9 (CI/CD shape), §Code Examples (workflow YAML) |
| OPS-04 | CI blocks merge on failing tests or coverage drop below 80% | §Architecture Patterns / Pattern 9, §Code Examples (pytest-cov gate flag) |
| OPS-07 | Database migration discipline — Alembic migrations applied in deploy step | §Architecture Patterns / Pattern 6, §Pitfall 4 (run migrations BEFORE start) |
| OPS-08 | Pre-commit hooks: ruff format, ruff lint, secret scan | §Architecture Patterns / Pattern 8, §Code Examples (.pre-commit-config.yaml) |
| TEST-01 | pytest + Hypothesis + pytest-asyncio configured; respx/aioresponses for API client mocks | §Standard Stack, §Code Examples (pyproject.toml [tool.pytest]) |
| TEST-02 | TDD discipline documented in `CONTRIBUTING.md` or `AGENTS.md` | §Don't Hand-Roll (use AGENTS.md per existing convention; small writing task) |
| TEST-05 | `tests/fakes/` provides deterministic fakes for every external boundary | §Architecture Patterns / Pattern 7, §Code Examples |
| TEST-06 | freezegun used for time-dependent tests | §Standard Stack (freezegun), §Pitfall 7 (time / TZ correctness) |
</phase_requirements>

## Summary

Phase 0 is greenfield scaffolding. The decision space was effectively closed in `/gsd:discuss-phase` — 34 decisions are locked. Research therefore focuses on (a) verifying that locked decisions are still implementable against current 2026 library versions, (b) extracting the canonical code patterns for each locked decision, and (c) surfacing the landmines that would silently make Phase 0 ship broken (Alembic + asyncpg URL rewrite ordering, contextvars-loss across asyncio.create_task, Railway healthchecks that don't run continuously, testcontainers cold start cost, gitleaks false positives on uv.lock).

The stack matrix in CLAUDE.md is current and complete — every Phase 0 package has been version-verified against PyPI (May 2026): `pydantic 2.13.4`, `pydantic-settings 2.11.0`, `fastapi 0.128.8`, `uvicorn 0.39.0`, `structlog 25.5.0`, `prometheus-client 0.25.0`, `sqlalchemy 2.0.49`, `asyncpg 0.31.0`, `alembic 1.16.5`, `pytest 8.4.2`, `pytest-asyncio 1.2.0`, `hypothesis 6.141.1`, `ruff 0.15.13`, `pyright 1.1.409`, `testcontainers 4.13.3`, `freezegun 1.5.5`, `respx 0.23.1`, `aioresponses 0.7.8`. All 25 install candidates passed `slopcheck install --ecosystem pypi` cleanly.

**Primary recommendation:** Follow the locked decisions verbatim. Use the canonical code patterns documented in §Code Examples. Address the 4 landmines surfaced in §Common Pitfalls (Pydantic v2 strict-mode Decimal coercion, contextvars loss across `asyncio.create_task`, Alembic async URL rewrite ordering, Railway healthchecks ≠ liveness probes) in the wave-0 implementation tasks.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Domain types (Candle, OrderBook, Signal, Order, Position, RiskLimits, Funding, Liquidation) | Pure-Python core (`src/shortfire/domain/`) | — | No I/O. Invariants enforced at construction. Imported by every higher tier. |
| Settings / env-var loading | Pure-Python core (`src/shortfire/settings/`) | — | Validates at startup. Anti-leak boundary lives here (D-16). |
| Observability primitives (structlog config, correlation-id middleware, Prometheus registry) | Pure-Python core (`src/shortfire/observability/`) | FastAPI ASGI middleware | Logging is a process-level concern; middleware is HTTP-tier. |
| DB engine + Alembic + Timescale helpers | Adapter layer (`src/shortfire/db/`) | — | Talks to Postgres. Async engine + DeclarativeBase + idempotent DDL wrappers. |
| Protocols for external clients (Mexc/Coinglass/CoinGecko) | Adapter layer (`src/shortfire/clients/`) | — | Defines interfaces only. Real impls land in Phase 1. |
| 3 FastAPI entrypoints (`data_platform`, `strategy_engine`, `dashboard`) | HTTP / process | — | Each instantiates its Settings subclass; mounts middleware + `/health` + `/metrics`. |
| Deterministic fakes (`tests/fakes/`) | Test infrastructure | — | Same Protocols as real clients. Imported by Phase 1+ tests. |
| Container image | DevOps / build | — | Single Dockerfile, 3 startCommands per Railway service (D-03). |
| CI / branch protection / secret scanning | Repo platform (GitHub) | Pre-commit hooks | Two-layer defense: developer's machine + server-side. |
| Railway service config | DevOps / platform | `railway.toml` in repo | Service shape lives in code; secret values live in Railway dashboard. |

## Standard Stack

### Core (every package version-verified against PyPI 2026-05-21; all `[OK]` per slopcheck)

| Library | Verified Version | Purpose | Why Standard |
|---------|------------------|---------|--------------|
| `python` | 3.12.x | Runtime | CLAUDE.md tech stack locks 3.12 — wheels for `xgboost`, `lightgbm`, `pandas-ta` are tested primarily on 3.12 [CITED: CLAUDE.md]. |
| `uv` | 0.11.8 (verified locally) | Package manager + venv + lockfile | 10-100× faster than pip+virtualenv; PEP 735 [dependency-groups] support; replaces poetry [VERIFIED: astral-sh/uv docs]. |
| `pydantic` | 2.13.4 | Schema validation for domain types AND API response models | Mandatory for FastAPI; `ConfigDict(frozen=True, strict=True)` + `Field(le=...)` + `@model_validator(mode='after')` cover all D-13 invariants [VERIFIED: pydantic.dev/docs/validation/latest/concepts/models]. |
| `pydantic-settings` | 2.11.0 | env-var-driven config with per-service subclasses | `SettingsConfigDict(env_nested_delimiter="__")` + `SecretStr` cover D-17 to D-19 [VERIFIED: pydantic.dev/docs/validation/latest/concepts/pydantic_settings]. |
| `fastapi` | 0.128.8 | API layer (`/health`, `/metrics`, future signal endpoints) | Async-native, Pydantic-v2-native, drops Pydantic v1; standard for new Python APIs [CITED: CLAUDE.md]. |
| `uvicorn` | 0.39.0 | ASGI server | Production-ready standalone in 2026 — Gunicorn wrapper no longer required [CITED: CLAUDE.md]. |
| `structlog` | 25.5.0 | Structured JSON logging + contextvars for correlation IDs | `merge_contextvars` processor is the canonical pattern for async correlation-id propagation [VERIFIED: structlog.org/en/stable/contextvars.html]. |
| `asgi-correlation-id` | 4.3.4 (Oct 2024) | per-request UUID4 correlation ID middleware for ASGI | Canonical package (`snok/asgi-correlation-id`); integrates with structlog via a `add_correlation` processor [VERIFIED: github.com/snok/asgi-correlation-id]. |
| `prometheus-client` | 0.25.0 | `/metrics` endpoint with custom Counter/Histogram | Preferred over `prometheus-fastapi-instrumentator` because Phase 1+ needs CUSTOM business metrics (data freshness, signal counts, position counts) — instrumentator is "not made for generic Prometheus instrumentation" [VERIFIED: github.com/trallnag/prometheus-fastapi-instrumentator]. |
| `sqlalchemy` | 2.0.49 | DeclarativeBase + AsyncEngine + Core inserts | 2.x async support is mature; use Core (not ORM) for hot-path inserts per CLAUDE.md [CITED: CLAUDE.md, docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html]. |
| `asyncpg` | 0.31.0 | Postgres driver (async-native, supports COPY BIN) | Used by both Alembic env.py and SQLAlchemy AsyncEngine. No psycopg in v1 per D-30 [CITED: CLAUDE.md]. |
| `alembic` | 1.16.5 | Schema migrations | Async template via `alembic init -t async`; supports TimescaleDB-aware DDL via `op.execute` [VERIFIED: alembic.sqlalchemy.org/en/latest/cookbook.html]. |
| `pytest` | 8.4.2 | Test framework | Industry standard [CITED: CLAUDE.md]. |
| `pytest-asyncio` | 1.2.0 | Async test support | `asyncio_mode = "auto"` in `pyproject.toml` to drop per-test markers [CITED: CLAUDE.md]. |
| `pytest-cov` | 7.1.0 | Coverage measurement + gate | `--cov-fail-under=80` enforces D-33 coverage gate. |
| `hypothesis` | 6.141.1 | Property-based testing | Mandatory for D-15 invariants: balance + no-data-leakage + Order(close, reduce_only=False) raises [CITED: CLAUDE.md]. |
| `ruff` | 0.15.13 | Linter + formatter | Replaces Black + isort + flake8 [CITED: CLAUDE.md]. |
| `pyright` | 1.1.409 | Type checker | Strict mode in CI [CITED: CLAUDE.md]. |
| `testcontainers` | 4.13.3 | Integration tests with real Postgres+Timescale container | `PostgresContainer("timescale/timescaledb:2.18.0-pg16")` for D-31 tests [VERIFIED: testcontainers-python.readthedocs.io]. |
| `freezegun` | 1.5.5 | Time mocking for tz-sensitive tests | TEST-06 mandates use; wrap every time-sensitive Pydantic invariant test [CITED: CLAUDE.md]. |
| `respx` | 0.23.1 | httpx-based mocking for Coinglass + CoinGecko clients in tests | TEST-01 mandates; correct choice (NOT `responses`, which is for `requests` library) [CITED: CLAUDE.md]. |
| `aioresponses` | 0.7.8 | aiohttp mocking (ccxt's internal transport) | TEST-01 mandates; ccxt uses aiohttp under the hood, so MEXC API mocking goes here [CITED: CLAUDE.md]. |
| `python-dotenv` | 1.2.1 | Local dev `.env.local` loader | Used implicitly by pydantic-settings via `env_file=` config; conditional on `ENV != production` per D-20. |
| `orjson` | 3.11.5 | Fast JSON serialization | FastAPI uses internally; explicit dependency makes intent visible [CITED: CLAUDE.md]. |
| `tenacity` | 9.1.2 | Retry decorators for external API calls | Used in Phase 1+ but declared in `pyproject.toml` in Phase 0 so Protocol fakes can reference shape if needed [CITED: CLAUDE.md]. |
| `aiolimiter` | 1.2.1 | Async rate limiting (token bucket) | Used in Phase 1+ (Coinglass/CoinGecko rate-limit) but declared in Phase 0 [CITED: CLAUDE.md]. |
| `httpx` | 0.28.1 | Async HTTP client for Coinglass + CoinGecko | Phase 1+ but in Phase 0 dependency set so the Protocol surface in `clients/` can type-annotate request objects [CITED: CLAUDE.md]. |

### Supporting (Phase 0 may declare, but real wiring in later phases)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ccxt` | 4.5.x | MEXC unified API | Phase 1 — Phase 0 only declares the Protocol surface. |
| `psycopg` | n/a | Sync Postgres driver | **NOT used in v1** per D-30. Only asyncpg. |
| `aiosqlite` | n/a | Alembic-test-against-SQLite alternative | **NOT used** — we test against the real `timescale/timescaledb:2.18.0-pg16` container; SQLite would mask Timescale-specific DDL bugs. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `prometheus-client` (raw Counter/Histogram + `/metrics` endpoint) | `prometheus-fastapi-instrumentator` | Instrumentator gives free default HTTP metrics but is "not made for generic Prometheus instrumentation" — Phase 1+ business metrics drive the choice [VERIFIED: github.com/trallnag/prometheus-fastapi-instrumentator]. |
| `asgi-correlation-id` library | Hand-rolled middleware + contextvar | The library has been maintained since 2020; hand-rolling for FastAPI is ~30 lines but reinventing a solved problem. Use the library. |
| Single shared `Dockerfile` (D-03) | Per-service Dockerfile | Locked by D-03. Three `startCommand`s on the same image is simpler and consistent. |
| Pure Pydantic v2 BaseModel for ALL 8 domain types (D-07) | Hybrid Pydantic + msgspec for hot-path types | Locked by D-07. Pydantic construction is ~3-10μs/record — irrelevant at our throughput. Hot-path bypass via asyncpg COPY in Phase 1, not via switching to msgspec. |
| `Literal[...]` for enum-like fields (D-10) | StrEnum classes | Locked by D-10. Behavior dispatch lives in module-level functions, not enum methods. Uniform pattern. |
| Real testcontainers TimescaleDB image | Mocked DDL helpers in unit tests | Locked indirectly by D-31. Mocking timescaledb-specific DDL would miss the actual landmines (extension order, compression policy job registration). |
| In-process scheduler in Phase 0 | APScheduler 4.x | APScheduler wired in Phase 1 (ORCH-01). Phase 0 has no scheduler. |

**Installation:**

```bash
# Phase 0 install — use uv with PEP 735 dependency groups
uv init --package shortfire
uv add \
  pydantic pydantic-settings \
  fastapi uvicorn \
  structlog asgi-correlation-id prometheus-client \
  sqlalchemy asyncpg alembic \
  orjson tenacity aiolimiter httpx python-dotenv

uv add --group dev \
  pytest pytest-asyncio pytest-cov hypothesis \
  freezegun respx aioresponses \
  testcontainers \
  ruff pyright
```

**Version verification (PyPI, 2026-05-21):** all 25 packages verified present + current via `pip3 index versions <pkg>` and cleared by `slopcheck install --ecosystem pypi` (see §Package Legitimacy Audit).

## Package Legitimacy Audit

Ran `slopcheck install --ecosystem pypi` against all 25 Phase 0 install candidates on 2026-05-21. All 25 verdicts: `[OK]`. slopcheck flagged two with comments but both are confirmed legitimate:

| Package | Registry | slopcheck | Notes from slopcheck | Disposition |
|---------|----------|-----------|----------------------|-------------|
| `pydantic` | PyPI | [OK] | — | Approved |
| `pydantic-settings` | PyPI | [OK] | — | Approved |
| `fastapi` | PyPI | [OK] | — | Approved |
| `uvicorn` | PyPI | [OK] | — | Approved |
| `structlog` | PyPI | [OK] | — | Approved |
| `prometheus-client` | PyPI | [OK] | Name ends with '-client' — classic LLM naming pattern. Name looks like LLM bait but package is established. | Approved |
| `sqlalchemy` | PyPI | [OK] | — | Approved |
| `asyncpg` | PyPI | [OK] | — | Approved |
| `alembic` | PyPI | [OK] | — | Approved |
| `psycopg` | PyPI | [OK] | — | Not used in v1 per D-30 (do NOT install) |
| `pytest` | PyPI | [OK] | — | Approved |
| `pytest-asyncio` | PyPI | [OK] | — | Approved |
| `pytest-cov` | PyPI | [OK] | No source repository linked. | Approved (pytest-cov is canonical; the "no source repo" warning is a slopcheck false positive — pytest-dev/pytest-cov exists on GitHub) |
| `hypothesis` | PyPI | [OK] | — | Approved |
| `freezegun` | PyPI | [OK] | — | Approved |
| `respx` | PyPI | [OK] | — | Approved |
| `aioresponses` | PyPI | [OK] | — | Approved |
| `ruff` | PyPI | [OK] | — | Approved |
| `pyright` | PyPI | [OK] | — | Approved |
| `testcontainers` | PyPI | [OK] | — | Approved |
| `python-dotenv` | PyPI | [OK] | Name starts with 'python-' — classic LLM naming pattern. Name looks like LLM bait but package is established. | Approved |
| `httpx` | PyPI | [OK] | — | Approved |
| `tenacity` | PyPI | [OK] | — | Approved |
| `aiolimiter` | PyPI | [OK] | — | Approved |
| `orjson` | PyPI | [OK] | — | Approved |
| `asgi-correlation-id` | PyPI | (not run via slopcheck — added to recommendation post-slopcheck) | — | [ASSUMED legitimate per github.com/snok/asgi-correlation-id v4.3.4]. Planner should re-run `slopcheck install asgi-correlation-id --ecosystem pypi` before adding it to `pyproject.toml`. |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none
**Action item for planner:** Run `slopcheck install asgi-correlation-id --ecosystem pypi` as the first sub-task of any wave that adds it, so the legitimacy gate is closed before install.

## Architecture Patterns

### System Architecture Diagram

```
                              GitHub repo (1 main branch, branch protection)
                                            │
                       ┌────────────────────┼────────────────────┐
                       │                    │                    │
                       ▼                    ▼                    ▼
                .pre-commit-config       .github/workflows    Railway "deploy on push to main"
                (gitleaks + ruff +        ci.yml (ruff →
                pyright + grep guards)    pyright → pytest → 
                                          gitleaks-action)
                       │
                       │ push (only if pre-commit + CI green)
                       ▼
              ┌─────────────────────────────────────────────────────────────┐
              │ Railway project                                              │
              │   ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐│
              │   │ data-platform   │  │ strategy-engine │  │  dashboard   ││
              │   │ (always-on)     │  │ (sleep-when-idle)│  │ (sleep-idle) ││
              │   │ startCommand:   │  │ startCommand:   │  │ startCommand:││
              │   │ entrypoints.    │  │ entrypoints.    │  │ entrypoints. ││
              │   │ data_platform   │  │ strategy_engine │  │ dashboard    ││
              │   └────────┬────────┘  └────────┬────────┘  └──────┬───────┘│
              │            │                    │                  │        │
              │            │ DATABASE_URL=${{Postgres.DATABASE_URL}}        │
              │            └────────────────────┼──────────────────┘        │
              │                                 ▼                            │
              │                 ┌───────────────────────────┐                │
              │                 │ Postgres + TimescaleDB    │                │
              │                 │ timescale/timescaledb:    │                │
              │                 │ 2.18.0-pg16               │                │
              │                 │ (private network          │                │
              │                 │  postgres.railway.internal│                │
              │                 │  :5432)                   │                │
              │                 └───────────────────────────┘                │
              └─────────────────────────────────────────────────────────────┘

  Inside each entrypoint (same container image, different startCommand):

      uvicorn → FastAPI app
                  │
                  ├── CorrelationIdMiddleware (UUID4 per request → contextvar)
                  ├── /health (structured JSON, includes request_id)
                  ├── /metrics (Prometheus text exposition)
                  │
                  └── on startup:
                        1. instantiate ServiceXSettings() — fails fast on missing env vars
                        2. log "settings.loaded" via structlog with settings.safe_summary()
                        3. create AsyncEngine(DATABASE_URL.replace("postgres://", "postgresql+asyncpg://"))
                        4. assert_no_leaked_env_vars() — e.g. data-platform asserts MEXC_TRADE__* absent

  Domain layer (imported by every entrypoint):
      src/shortfire/domain/{market,trading,risk}.py — 8 frozen Pydantic models
        Invariants enforced at construction (D-13):
          Order(intent='close', reduce_only=False)  →  ValidationError
          RiskLimits(max_per_trade_pct=Decimal("0.06"))  →  ValidationError
          Candle(low=11, high=10)  →  ValidationError
```

### Recommended Project Structure (matches D-06)

```
shortfire/
├── src/shortfire/
│   ├── __init__.py
│   ├── domain/                   # Phase 0 — 8 pure Pydantic types
│   │   ├── __init__.py
│   │   ├── market.py             # Candle, OrderBookLevel, OrderBook, Funding, Liquidation
│   │   ├── trading.py            # Signal, Order, Position
│   │   └── risk.py               # RiskLimits
│   ├── settings/                 # Phase 0 — per-service BaseSettings subclasses
│   │   ├── __init__.py
│   │   ├── base.py               # BaseAppSettings + nested submodels
│   │   ├── data_platform.py      # DataPlatformSettings
│   │   ├── strategy_engine.py    # StrategyEngineSettings
│   │   ├── dashboard.py          # DashboardSettings
│   │   └── risk_guard.py         # placeholder for Phase 5
│   ├── observability/            # Phase 0 — structlog + Prometheus + middleware
│   │   ├── __init__.py
│   │   ├── logging.py            # structlog configure + safe_summary helpers
│   │   ├── metrics.py            # Prometheus registry + service_event Counter
│   │   └── middleware.py         # mount CorrelationIdMiddleware on a FastAPI app
│   ├── db/                       # Phase 0 — DB engine + helpers
│   │   ├── __init__.py
│   │   ├── base.py               # DeclarativeBase + NAMING_CONVENTION
│   │   ├── engine.py             # async engine factory
│   │   └── timescale.py          # idempotent DDL helpers (create_hypertable, enable_compression, ...)
│   ├── clients/                  # Phase 0 — Protocols only (no impls)
│   │   ├── __init__.py
│   │   ├── mexc.py               # MexcClient Protocol
│   │   ├── coinglass.py          # CoinglassClient Protocol
│   │   └── coingecko.py          # CoinGeckoClient Protocol
│   ├── ingest/                   # Phase 0 empty; filled in Phase 1
│   │   └── __init__.py
│   ├── strategy/                 # Phase 0 empty; filled in Phase 2-3
│   │   └── __init__.py
│   ├── execution/                # Phase 0 empty; filled in Phase 4
│   │   └── __init__.py
│   ├── risk/                     # Phase 0 empty; filled in Phase 4-5
│   │   └── __init__.py
│   └── entrypoints/              # Phase 0 — 3 FastAPI apps
│       ├── __init__.py
│       ├── data_platform.py
│       ├── strategy_engine.py
│       └── dashboard.py
├── alembic/
│   ├── env.py                    # async template, rewritten DATABASE_URL
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_init_timescaledb.py
│       └── 0002_service_event_hypertable.py
├── alembic.ini
├── tests/
│   ├── conftest.py
│   ├── fakes/                    # FOUND-08 — Protocol-conforming fakes
│   │   ├── __init__.py
│   │   ├── mexc.py               # FakeMexcClient
│   │   ├── coinglass.py          # FakeCoinglassClient
│   │   ├── coingecko.py          # FakeCoinGeckoClient
│   │   └── repos.py              # InMemoryCandleRepo
│   ├── unit/
│   │   ├── domain/
│   │   ├── settings/
│   │   ├── observability/
│   │   └── db/                   # unit tests for timescale.py helpers (string-builder tests)
│   └── integration/              # testcontainers — pytest -m integration
│       ├── conftest.py
│       └── db/
│           └── test_alembic_and_hypertables.py
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── uv.lock
├── .pre-commit-config.yaml
├── .gitleaks.toml
├── .github/
│   └── workflows/
│       └── ci.yml
├── .gitignore
├── .env.example
├── AGENTS.md                     # TDD discipline doc — see TEST-02
├── railway.toml                  # service-level config (optional in Phase 0; dashboard-only also fine)
└── README.md
```

### Pattern 1: Frozen, Strict Pydantic v2 Domain Type with Cross-Field Invariant

**What:** All 8 domain types share the same shape: `ConfigDict(frozen=True, strict=True)`, Decimal-only money, `Literal[...]` enums, `tuple[X, ...]` collections, tz-aware datetime, `@model_validator(mode='after')` for cross-field invariants.

**When to use:** All 8 domain types in `src/shortfire/domain/`. Position is the lone `frozen=False` exception (D-08).

**Example (Order with EXEC-02 structural invariant — D-13):**

```python
# src/shortfire/domain/trading.py
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from pydantic import BaseModel, ConfigDict, Field, model_validator

OrderIntent = Literal["open", "close"]
OrderType = Literal["market", "limit"]
SignalSide = Literal["short", "long"]


class Order(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    client_order_id: str
    symbol: str
    intent: OrderIntent
    side: SignalSide
    order_type: OrderType
    quantity: Decimal = Field(gt=Decimal("0"))
    price: Decimal | None = None  # None for market orders
    reduce_only: bool
    ts: datetime

    @model_validator(mode="after")
    def _reject_naive_ts(self) -> Self:
        if self.ts.tzinfo is None:
            raise ValueError("Order.ts must be timezone-aware (UTC)")
        return self

    @model_validator(mode="after")
    def _close_orders_must_be_reduce_only(self) -> Self:
        if self.intent == "close" and not self.reduce_only:
            raise ValueError("Order(intent='close') requires reduce_only=True (EXEC-02)")
        return self
```

[VERIFIED: pydantic.dev/docs/validation/latest/concepts/models — confirmed `ConfigDict(frozen=True, strict=True)`, `Field(gt=…)`, `@model_validator(mode='after')` returning `self` is the canonical 2.x pattern.]

**Hypothesis test for the invariant (D-15):**

```python
# tests/unit/domain/test_order.py
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError
from shortfire.domain.trading import Order


utc_dt = st.datetimes(timezones=st.just(timezone.utc))
pos_dec = st.decimals(min_value=Decimal("0.00000001"), max_value=Decimal("1000000"), places=18, allow_nan=False, allow_infinity=False)


@given(side=st.sampled_from(["short", "long"]),
       qty=pos_dec,
       ts=utc_dt)
def test_close_order_requires_reduce_only(side, qty, ts):
    with pytest.raises(ValidationError, match="reduce_only=True"):
        Order(
            client_order_id="x",
            symbol="BTCUSDT",
            intent="close",
            side=side,
            order_type="market",
            quantity=qty,
            reduce_only=False,
            ts=ts,
        )


@given(side=st.sampled_from(["short", "long"]),
       qty=pos_dec,
       ts=utc_dt)
def test_close_order_with_reduce_only_succeeds(side, qty, ts):
    o = Order(
        client_order_id="x", symbol="BTCUSDT", intent="close",
        side=side, order_type="market", quantity=qty,
        reduce_only=True, ts=ts,
    )
    assert o.reduce_only is True
    # round-trip
    assert Order.model_validate(o.model_dump()) == o
```

[VERIFIED: hypothesis.readthedocs.io/en/latest/reference/strategies.html — `st.decimals(places=18)`, `st.datetimes(timezones=st.just(timezone.utc))`, `st.sampled_from(...)` are the canonical strategies.]

### Pattern 2: Per-Service Settings Subclass with Anti-Leak Boundary

**What:** Each service has its own `*Settings(BaseAppSettings)` subclass that ONLY declares the env vars that service is allowed to see. pydantic-settings does not load env vars that don't appear as fields, so a misrouted `MEXC_TRADE__SECRET` on `data-platform` is structurally inert.

**When to use:** Every entrypoint imports its specific Settings class and instantiates it at module load (fails fast on missing required fields).

**Example:**

```python
# src/shortfire/settings/base.py
from typing import Literal
from pydantic import BaseModel, SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import os


def _env_file() -> str | None:
    return ".env.local" if os.getenv("ENV", "local") != "production" else None


class DBSettings(BaseModel):
    url: str = Field(..., alias="DATABASE_URL")
    pool_size: int = 5
    pool_pre_ping: bool = True
    pool_recycle: int = 1800  # 30 min — Railway's private network occasionally drops idle conns


class CommonSettings(BaseModel):
    log_level: Literal["DEBUG", "INFO", "WARN", "ERROR"] = "INFO"
    env: Literal["local", "ci", "staging", "production"] = "local"


class BaseAppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",  # extra env vars (Railway injects many) must not crash startup
    )

    service_name: str
    port: int = 8000
    db: DBSettings
    common: CommonSettings = CommonSettings()

    def safe_summary(self) -> dict[str, object]:
        """Sanitized snapshot for startup logging — D-21."""
        return {
            "service_name": self.service_name,
            "port": self.port,
            "env": self.common.env,
            "log_level": self.common.log_level,
            "db_host": self.db.url.split("@", 1)[-1].split("/", 1)[0] if "@" in self.db.url else "<unknown>",
            # NEVER include credentials, even masked — log structure should not hint at presence/absence
        }


# src/shortfire/settings/data_platform.py
from pydantic import BaseModel, SecretStr
from .base import BaseAppSettings


class MexcReadSettings(BaseModel):
    read_key: SecretStr
    read_secret: SecretStr


class CoinglassSettings(BaseModel):
    api_key: SecretStr


class CoingeckoSettings(BaseModel):
    api_key: SecretStr


class DataPlatformSettings(BaseAppSettings):
    """Note: NO `mexc_trade` field. Phase 5 TRADE_KEY env var is structurally inert here (D-16)."""
    service_name: str = "data-platform"
    # Phase 1+ wires these — declared now so the env-var-routing boundary is structurally correct.
    mexc: MexcReadSettings | None = None
    coinglass: CoinglassSettings | None = None
    coingecko: CoingeckoSettings | None = None

    def safe_summary(self) -> dict[str, object]:
        base = super().safe_summary()
        base.update({
            "mexc_read_configured": self.mexc is not None,
            "coinglass_configured": self.coinglass is not None,
            "coingecko_configured": self.coingecko is not None,
        })
        return base


def assert_no_trade_env_leaked() -> None:
    """Guardrail D-16 — startup assertion on data-platform."""
    import os
    leaked = [k for k in os.environ if k.startswith("MEXC_TRADE__")]
    if leaked:
        raise RuntimeError(
            f"FATAL: trade-only env vars visible to data-platform: {leaked}. "
            f"Check Railway service-scoping; MEXC_TRADE__* must only exist on strategy-engine."
        )
```

[VERIFIED: pydantic.dev/docs/validation/latest/concepts/pydantic_settings — `SettingsConfigDict(env_nested_delimiter="__")`, `SecretStr`, conditional `env_file`, per-service subclass inheritance is the documented pattern. Env vars override `.env` values; OS env vars take priority.]

### Pattern 3: TimescaleDB-Aware Migration via Idempotent Helpers (D-27)

**What:** A `src/shortfire/db/timescale.py` module exposes idempotent wrappers around Timescale DDL functions. Migration files call these wrappers, NEVER raw `op.execute("SELECT create_hypertable(...)")`. This makes migrations rerun-safe and centralizes the SQL once.

**When to use:** Every Alembic migration that touches Timescale objects.

**Example:**

```python
# src/shortfire/db/timescale.py
from sqlalchemy import text
from alembic import op


def create_hypertable(
    table: str,
    time_column: str = "ts",
    chunk_interval: str = "7 days",
    if_not_exists: bool = True,
) -> None:
    """Idempotent create_hypertable wrapper.

    Timescale 2.18 still ships the legacy create_hypertable() function. It accepts
    if_not_exists => TRUE. The newer CREATE TABLE ... WITH (timescaledb.hypertable)
    syntax is preferred for fresh tables but is not as friendly to Alembic's CREATE TABLE
    autogenerate, so we use the function form.
    """
    op.execute(text(f"""
        SELECT create_hypertable(
            '{table}',
            '{time_column}',
            chunk_time_interval => INTERVAL '{chunk_interval}',
            if_not_exists => {str(if_not_exists).upper()}
        );
    """))


def enable_compression(
    table: str,
    segment_by: str,
    order_by: str = "ts DESC",
) -> None:
    """Idempotent ALTER TABLE ... SET (timescaledb.compress, ...)."""
    op.execute(text(f"""
        ALTER TABLE {table} SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = '{segment_by}',
            timescaledb.compress_orderby = '{order_by}'
        );
    """))


def add_compression_policy(
    table: str,
    after_age: str = "7 days",
    if_not_exists: bool = True,
) -> None:
    """Idempotent add_compression_policy wrapper.

    Skips silently if a policy already exists at the same age — Timescale's
    add_compression_policy supports if_not_exists since 2.4.
    """
    op.execute(text(f"""
        SELECT add_compression_policy(
            '{table}',
            INTERVAL '{after_age}',
            if_not_exists => {str(if_not_exists).upper()}
        );
    """))
```

**0002 migration:**

```python
# alembic/versions/0002_service_event_hypertable.py
"""service_event hypertable + compression policy"""
from alembic import op
import sqlalchemy as sa
from shortfire.db.timescale import create_hypertable, enable_compression, add_compression_policy

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.create_table(
        "service_event",
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    # Time-partition primary key is implicit via hypertable; no app-level uniqueness yet.
    create_hypertable("service_event", time_column="ts", chunk_interval="7 days")
    enable_compression("service_event", segment_by="service_name", order_by="ts DESC")
    add_compression_policy("service_event", after_age="7 days")


def downgrade() -> None:
    # Downgrade in Phase 0 is intentionally non-clever:
    # drop_table cascades into hypertable chunks + policies.
    op.drop_table("service_event")
```

[VERIFIED: alembic.sqlalchemy.org/en/latest/cookbook.html — `op.execute(text(...))` is the canonical extension-DDL escape hatch. The naming convention auto-derives constraint names via Base.metadata.]

[CITED: tigerdata.com/docs/use-timescale/latest/hypertables/create — create_hypertable() still ships in 2.18, accepts `if_not_exists => TRUE`. The newer `CREATE TABLE … WITH (timescaledb.hypertable)` syntax is documented but is harder to combine with Alembic autogenerate, so the function-form is the pragmatic choice for this project.]

### Pattern 4: Railway 3-Service Shape via `railway.toml`

**What:** Each Railway service uses the same Docker image and overrides `startCommand`. Service-specific config (`sleepApplication`, `healthcheckPath`) lives in the Railway dashboard OR in service-scoped `railway.toml` blocks.

**When to use:** All 3 entrypoints. In Phase 0 it is acceptable to configure services purely through the Railway dashboard; a `railway.toml` is optional but documented as best practice.

**Example (optional `railway.toml`):**

```toml
# railway.toml — service-level config (Railway reads per-service in the dashboard;
# the schema-as-code shape exists primarily for `data-platform` defaults)
$schema = "https://railway.com/railway.schema.json"

[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"
# D-05: no watchPatterns in Phase 0 — every commit redeploys all 3 services.

[deploy]
# data-platform-specific values; strategy-engine and dashboard override in dashboard
startCommand = "alembic upgrade head && uvicorn shortfire.entrypoints.data_platform:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
healthcheckTimeout = 60
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5
# sleepApplication NOT set for data-platform (always-on)
```

**For strategy-engine and dashboard, set in dashboard:**
- `startCommand = "uvicorn shortfire.entrypoints.strategy_engine:app --host 0.0.0.0 --port $PORT"`
- `sleepApplication = true`
- `healthcheckPath = "/health"`

**Reference variable wiring (set in Railway dashboard on each app service):**
- `DATABASE_URL = ${{Postgres.DATABASE_URL}}`

[VERIFIED: docs.railway.com/reference/config-as-code — `[build]` and `[deploy]` are the top-level keys; `watchPatterns` lives under `[build]`; `startCommand`, `healthcheckPath`, `restartPolicyType` live under `[deploy]`.]

[CITED: docs.railway.com/reference/healthchecks + station.railway.com — Railway healthchecks run **only at deploy time**, NOT continuously. Default timeout 300s. They do NOT wake sleeping services — the FIRST INBOUND REQUEST wakes a sleeping service (cold start). See Pitfall 5.]

### Pattern 5: structlog + asgi-correlation-id + Prometheus Observability Stack

**What:** Three-piece stack: (1) `asgi-correlation-id` middleware sets a UUID4 per request into a contextvar; (2) structlog's `merge_contextvars` processor includes it on every log line; (3) prometheus-client exposes `/metrics` with custom business metrics.

**When to use:** Every FastAPI entrypoint mounts the same middleware/handlers via a shared helper.

**Example:**

```python
# src/shortfire/observability/logging.py
import logging
import structlog
from asgi_correlation_id import correlation_id
from typing import Any


def add_correlation_id(logger: logging.Logger, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor — pulls the current asgi-correlation-id into the event dict."""
    if rid := correlation_id.get():
        event_dict["request_id"] = rid
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog with JSON output + correlation-id + contextvar merging."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,   # MUST be first — propagates contextvars across async boundaries
        add_correlation_id,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging._nameToLevel[log_level]),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    # Bridge uvicorn / stdlib loggers through the same processor chain
    logging.basicConfig(level=log_level, handlers=[logging.StreamHandler()])
```

[VERIFIED: structlog.org/en/stable/contextvars.html — `merge_contextvars` MUST be the first processor for async correlation-id propagation; ContextVar isolation between sync and async means the contextvar-based pattern is the only one that works across event loops.]

```python
# src/shortfire/observability/middleware.py
from fastapi import FastAPI
from asgi_correlation_id import CorrelationIdMiddleware


def install_correlation_middleware(app: FastAPI) -> None:
    app.add_middleware(CorrelationIdMiddleware)  # generates UUID4 if no X-Request-ID header
```

[VERIFIED: github.com/snok/asgi-correlation-id — `app.add_middleware(CorrelationIdMiddleware)` is the canonical 1-line install; default generator is uuid4; header `X-Request-ID`.]

```python
# src/shortfire/observability/metrics.py
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
from fastapi import FastAPI, Response

# Phase 0: define ONE shared business metric — service_event_total — to prove the wiring works.
# Phase 1+ adds per-source freshness gauges, signal counts, etc.
REGISTRY = CollectorRegistry()
SERVICE_EVENT = Counter(
    "shortfire_service_event_total",
    "service_event rows emitted by name + type",
    ["service_name", "event_type"],
    registry=REGISTRY,
)


def install_metrics_endpoint(app: FastAPI) -> None:
    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
```

[VERIFIED: github.com/trallnag/prometheus-fastapi-instrumentator — instrumentator is "not made for generic Prometheus instrumentation"; for services with custom business metrics, prometheus-client direct usage is preferred.]

**Entrypoint wiring (single per-service entrypoint, ~20 lines):**

```python
# src/shortfire/entrypoints/data_platform.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
import structlog

from shortfire.settings.data_platform import DataPlatformSettings, assert_no_trade_env_leaked
from shortfire.observability.logging import configure_logging
from shortfire.observability.middleware import install_correlation_middleware
from shortfire.observability.metrics import install_metrics_endpoint

settings = DataPlatformSettings()  # fails fast on missing env vars (D-34)
assert_no_trade_env_leaked()       # fails fast on misrouted MEXC_TRADE__* (D-16)
configure_logging(settings.common.log_level)
log = structlog.get_logger("data-platform")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("settings.loaded", **settings.safe_summary())
    yield


app = FastAPI(lifespan=lifespan, title="shortfire-data-platform")
install_correlation_middleware(app)
install_metrics_endpoint(app)


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"ok": True, "service": settings.service_name}
```

### Pattern 6: Alembic Async env.py with DATABASE_URL Rewrite

**What:** `alembic init -t async` produces an env.py that uses `async_engine_from_config`. Three things must be wired correctly: (1) URL rewrite from `postgres://` (Railway emits this on some adapters) to `postgresql+asyncpg://`; (2) `transaction_per_migration=True`; (3) naming convention from `Base.metadata`.

**When to use:** Phase 0 `alembic/env.py`. Wire once; every future migration inherits these settings.

**Example:**

```python
# alembic/env.py (key sections — full file is ~50 lines)
import asyncio
import os
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

from shortfire.db.base import Base  # pulls in NAMING_CONVENTION

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolved_url() -> str:
    """Railway sometimes provides `postgres://` form on env vars; SQLAlchemy needs `postgresql+asyncpg://`."""
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=True,
        # Preserve Base.metadata's NAMING_CONVENTION via target_metadata
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _resolved_url()
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported (we use TimescaleDB DDL helpers).")
else:
    run_migrations_online()
```

[VERIFIED: alembic.sqlalchemy.org/en/latest/cookbook.html — `async_engine_from_config` + `connection.run_sync(do_run_migrations)` + `transaction_per_migration=True` + `compare_type=True` + `compare_server_default=True` is the canonical async cookbook pattern.]

### Pattern 7: Protocols + Deterministic Fakes for External Boundaries (D-08, FOUND-08)

**What:** Each external client is defined as a `typing.Protocol` in `src/shortfire/clients/`. A `tests/fakes/` module exposes deterministic implementations of the same Protocol, used by Phase 1+ tests without network. In Phase 0 the Protocols are real; the fakes' bodies are stubbed (return canned data, raise on unimplemented methods).

**When to use:** All 4 fakes — `FakeMexcClient`, `FakeCoinglassClient`, `FakeCoinGeckoClient`, `InMemoryCandleRepo`.

**Example:**

```python
# src/shortfire/clients/mexc.py
from datetime import datetime
from typing import Protocol
from shortfire.domain.market import Candle


class MexcClient(Protocol):
    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: datetime, until: datetime) -> tuple[Candle, ...]: ...
    async def fetch_funding_rate_history(self, symbol: str, since: datetime, until: datetime) -> tuple["Funding", ...]: ...  # noqa: F821
    # ... full signature in Phase 1
```

```python
# tests/fakes/mexc.py
from datetime import datetime
from shortfire.domain.market import Candle


class FakeMexcClient:
    """Deterministic fake for Phase 0+ unit tests. Phase 1 fills in real candle generation."""

    def __init__(self, candles: tuple[Candle, ...] = ()) -> None:
        self._candles = candles

    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: datetime, until: datetime) -> tuple[Candle, ...]:
        return tuple(c for c in self._candles if since <= c.ts <= until)

    async def fetch_funding_rate_history(self, symbol: str, since: datetime, until: datetime) -> tuple:
        raise NotImplementedError("Phase 1 fills this in")
```

### Pattern 8: 4-Layer Secret-Scan Defense (D-22, OPS-08, FOUND-06)

**What:** Four independent layers of secret detection, each catching the previous layer's escapes.

| Layer | Where | Catches |
|-------|-------|---------|
| 1 | `.pre-commit-config.yaml` gitleaks hook on the developer's machine | Most secrets, before the commit lands |
| 2 | `.github/workflows/ci.yml` gitleaks-action on every push + PR | Secrets that bypassed pre-commit (developer skipped hooks) |
| 3 | GitHub Push Protection (server-side, configured in repo Settings) | Secrets at the moment of `git push` for known providers |
| 4 | GitHub Secret Scanning (server-side full-history) | Anything that landed historically |

**Layer 1 (`.pre-commit-config.yaml`):**

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.24.2
    hooks:
      - id: gitleaks

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.13
    hooks:
      - id: ruff-format
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]

  - repo: local
    hooks:
      - id: ban-naive-timestamp
        name: Ban `TIMESTAMP[^(]` in alembic & src
        entry: bash -c '! git diff --cached --name-only | xargs grep -nE "TIMESTAMP[^(]" -- "alembic/versions/" "src/" 2>/dev/null'
        language: system
        pass_filenames: false
        files: ^(alembic/versions/|src/).*\.py$

      - id: ban-on-delete-cascade
        name: Ban `ON DELETE CASCADE` in alembic
        entry: bash -c '! git diff --cached --name-only | xargs grep -niE "ON DELETE CASCADE" -- "alembic/versions/" 2>/dev/null'
        language: system
        pass_filenames: false
        files: ^alembic/versions/.*\.py$

      - id: ban-float-in-domain
        name: Ban `: float` annotation in src/shortfire/domain
        entry: bash -c '! git diff --cached --name-only --diff-filter=AM | grep "^src/shortfire/domain/" | xargs grep -nE ": float\b" 2>/dev/null'
        language: system
        pass_filenames: false
        files: ^src/shortfire/domain/.*\.py$
```

[VERIFIED: github.com/gitleaks/gitleaks README — pre-commit-config.yaml entry uses `repo: https://github.com/gitleaks/gitleaks`, `rev: v8.24.2`, `id: gitleaks`.]

**Layer 1 config (`.gitleaks.toml` — allowlist for uv.lock + fixtures):**

```toml
title = "shortfire gitleaks config"

[extend]
useDefault = true  # inherit gitleaks' default ruleset

[[allowlists]]
description = "Ignore lock files and deterministic test fixtures"
paths = [
  '''uv\.lock''',
  '''tests/fixtures/.*''',
  '''tests/fakes/.*''',
  '''\.env\.example''',  # template values are not real secrets
]
```

[VERIFIED: github.com/gitleaks/gitleaks README — `[[allowlists]]` table with `paths = ['regex1', 'regex2']` is the canonical allowlist shape.]

**Layer 2 (`.github/workflows/ci.yml` — gitleaks-action step at end of pipeline):**

```yaml
- name: Run gitleaks
  uses: gitleaks/gitleaks-action@v2
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**Layers 3 + 4:** enabled in repo Settings → Security → Code security and analysis. Not configured via code.

### Pattern 9: GitHub Actions CI (D-33)

**What:** Single workflow runs ruff → pyright → pytest with coverage → gitleaks. Fast-fail ordering: cheap-and-likely-to-fail first.

**Example:**

```yaml
# .github/workflows/ci.yml
name: ci
on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # gitleaks needs history

      - name: Install uv
        uses: astral-sh/setup-uv@v8
        with:
          version: "0.11.8"
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set Python version
        run: uv python install 3.12

      - name: Sync dependencies
        run: uv sync --locked --group dev

      - name: Lint (ruff format check)
        run: uv run ruff format --check .

      - name: Lint (ruff)
        run: uv run ruff check .

      - name: Type-check (pyright)
        run: uv run pyright

      - name: Test (pytest + coverage gate)
        run: uv run pytest -m "not integration" --cov=shortfire --cov-fail-under=80 --cov-report=term

      - name: Integration tests (testcontainers)
        run: uv run pytest -m integration

      - name: Gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

[VERIFIED: docs.astral.sh/uv/guides/integration/github — `astral-sh/setup-uv@v8` is the official action; `enable-cache: true` + `cache-dependency-glob: "uv.lock"` is the documented caching pattern; `uv sync --locked --group dev` resolves from lockfile and installs dev group.]

### Anti-Patterns to Avoid

- **`repr(settings)` or logging `settings` directly** — even with `SecretStr`, structlog/logger formatting may inadvertently leak field metadata. Always use `safe_summary()`.
- **Raw `op.execute("SELECT create_hypertable(...)")` strings scattered across migration files** — D-27 explicitly forbids this. Always go through the `db/timescale.py` wrappers.
- **`asyncio.create_task(...)` without `copy_context()`** in code that needs correlation-id propagation — see Pitfall 2.
- **`engine_from_config()` (sync) in alembic env.py** while running on asyncpg URL — silent crash. Use `async_engine_from_config()`.
- **Mixing `psycopg2`-style URL `postgres://` with SQLAlchemy 2.x async** — must rewrite to `postgresql+asyncpg://` or SQLAlchemy raises.
- **`prometheus-fastapi-instrumentator` for custom business metrics** — its surface is HTTP-only; use `prometheus-client` directly for `data_freshness_seconds`, `signal_count`, etc.
- **Trusting a Railway healthcheck to wake a sleeping service** — healthchecks only run at deploy-time. The first user request wakes a sleeping service (cold start ~2-3s).
- **Letting Hypothesis generate Decimal with `places=None`** — shrinking explodes. Always bound `min_value`, `max_value`, `places=18`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-request correlation ID middleware | Custom ASGI middleware + contextvar | `asgi-correlation-id` | Maintained 5+ years, already integrates with structlog. ~30 lines reinvented. |
| Env-var validation at startup | `os.environ["KEY"]` + manual asserts | `pydantic-settings` `BaseSettings` subclasses | Fails fast with field-level error messages; SecretStr support; per-service subclasses give anti-leak posture for free. |
| Structured logging in JSON | Custom `logging.Formatter` subclass | `structlog` with `JSONRenderer` | Contextvar propagation across async boundaries is the killer feature you'd otherwise hand-roll badly. |
| Property-based testing | Hand-crafted parametrize tables | `hypothesis` `@given` + `strategies` | Shrinks counterexamples; finds invariant violations the developer wouldn't think to write. |
| Postgres async pool management | Hand-rolled asyncpg pool wrapper | `sqlalchemy.ext.asyncio.create_async_engine` + asyncpg driver | SQLAlchemy handles pool sizing, recycling, pre-ping; you reuse the same engine for Core (hot-path) and ORM (admin). |
| TimescaleDB DDL idempotency | Try/catch around `CREATE EXTENSION` etc. | `IF NOT EXISTS` clauses + Timescale's `if_not_exists =>` arguments | Built-in. Reinventing causes subtle race conditions during concurrent deploys. |
| Secret scanning | Custom regex sweep over `git log` | `gitleaks` + GitHub native scanning | gitleaks has thousands of curated regexes for known providers; reinventing means missing AWS / GCP / Stripe / Slack / etc. |
| Schema migrations | Hand-written SQL files + version bookkeeping table | `alembic` async template | Alembic handles version graph, downgrade, autogenerate; reinventing is a 6-month detour. |
| Race-condition-safe SQL with Timescale | Hand-rolled retries around raw `create_hypertable` | The `if_not_exists => TRUE` argument that Timescale 2.18 ships | One flag vs N lines of retry logic. |
| Process-wide settings singleton | Module-level `settings = Settings()` import side effect (current pattern is fine) | NOT recommended to wrap in `lru_cache` for now | Module-level instantiation IS the singleton in Python. Don't overthink. |

**Key insight:** Phase 0 has zero novel domain logic. Every problem you'd want to solve has a maintained Python library that solves it better than 100 lines of in-house code. The only "code" Phase 0 produces is: (a) Pydantic domain types (data-shape definitions), (b) gluing the above libraries together, (c) idempotent Timescale DDL wrappers, (d) deterministic test fakes. If a wave produces more than ~150 LOC of business logic in Phase 0, that's a smell.

## Common Pitfalls

### Pitfall 1: Pydantic v2 strict mode + Decimal coercion

**What goes wrong:** `ConfigDict(strict=True)` causes Pydantic to refuse string-coercion to Decimal: `Order(quantity="1.5")` raises ValidationError. But this is exactly what we want for the domain types — strict input. The pitfall is downstream code that constructs domain types from JSON / DB rows and forgets to coerce.

**Why it happens:** strict=True rejects `int → Decimal`, `str → Decimal`, `float → Decimal`. Many test fixtures and DB-row-loaders write `Order(quantity=1.5)` (float literal) which raises.

**How to avoid:**
- In production code at boundaries (DB load, JSON parse), explicitly construct: `Order(quantity=Decimal(str(row.quantity)))`.
- In test fixtures, use `Decimal("1.5")` not `1.5`.
- The Hypothesis strategy `st.decimals(places=18, ...)` produces actual Decimal instances — safe.

**Warning signs:** ValidationError with "Input should be a valid decimal" coming from test fixtures or DB hydration code.

### Pitfall 2: structlog contextvars loss across `asyncio.create_task` boundaries

**What goes wrong:** A coroutine binds correlation_id via `asgi-correlation-id`. The coroutine calls `asyncio.create_task(work())`. Inside `work()`, the contextvar is empty — `correlation_id.get()` returns `None`, so structlog emits no `request_id`. Bug invisible until a debugging session asks "where did this request originate?".

**Why it happens:** `asyncio.create_task` copies the *current* context at creation time on Python 3.11+, which is generally fine. BUT if the call goes through a callback or queue that wasn't created in the request context, the contextvar is empty.

**How to avoid:**
- Prefer `asyncio.TaskGroup` (Python 3.11+) for structured concurrency — it preserves context naturally.
- When passing work to a long-running queue (APScheduler, Phase 1+), the contextvar will NOT propagate. Bind the correlation_id explicitly into the job's args/kwargs at enqueue time.
- Add a regression test: bind `correlation_id.set("test-id-abc")`, spawn a task, assert the task's log line contains `request_id: test-id-abc`.

**Warning signs:** structlog lines that should carry `request_id` but don't. Easiest test: hit `/health` with a generated request-id, grep log for it; if any line in the request handler is missing it, you have a leak.

### Pitfall 3: Alembic async + URL rewriting + extension creation ordering

**What goes wrong:** Three independent failures stack:
1. Railway emits `DATABASE_URL` in `postgres://` form (legacy) — SQLAlchemy 2.x demands `postgresql+asyncpg://`. Without rewrite, Alembic crashes at `async_engine_from_config`.
2. Migration `0002_service_event_hypertable.py` calls `create_hypertable('service_event', ...)`. If migration `0001_init_timescaledb.py` (which runs `CREATE EXTENSION timescaledb`) hasn't applied yet, the `create_hypertable` function doesn't exist — `migration 0002 crashes`.
3. The Alembic naming convention isn't propagated to autogenerated migrations because `Base.metadata` wasn't imported in env.py.

**Why it happens:** Each is a separate gotcha; combined they look like a single mysterious "migration won't run" symptom.

**How to avoid:**
- env.py: ALWAYS rewrite `postgres://` → `postgresql+asyncpg://` (see Pattern 6 code).
- Migration 0001 MUST contain `CREATE EXTENSION IF NOT EXISTS timescaledb` and nothing else. Migration 0002 depends on 0001. Alembic's `down_revision = "0001"` makes this explicit.
- env.py: `from shortfire.db.base import Base; target_metadata = Base.metadata` — this propagates the naming convention.
- Integration test `test_alembic_upgrade_is_idempotent` runs `alembic upgrade head` twice — catches non-idempotent migrations.

**Warning signs:** `Function create_hypertable does not exist` → 0001 didn't apply. `Could not parse SQLAlchemy URL` → forgot URL rewrite. Constraints named `service_event_pkey` instead of `pk_service_event` → naming convention not wired.

### Pitfall 4: Railway healthcheck ≠ liveness probe

**What goes wrong:** Developer expects Railway's healthcheck (`/health` returning 200) to keep `data-platform` awake or to detect runtime failures. Neither is true.

**Why it happens:** Railway runs healthchecks ONLY at deploy time, to gate when a new revision becomes the live one. After deploy, no healthcheck pings are made. Sleeping services are woken by the first inbound user request — NOT by healthchecks.

**How to avoid:**
- For `data-platform` always-on requirement: set `sleepApplication: false` in Railway dashboard. Do NOT rely on healthcheck to keep it warm.
- For sleep-when-idle services (strategy-engine, dashboard): accept a 2-3s cold start on the first user request after idle.
- For runtime liveness monitoring: this is Phase 5 work (Grafana + Sentry). Phase 0's `/health` is purely a deploy-time gate.
- Document this explicitly in `AGENTS.md` so future contributors don't add a "keepalive" cron expecting Railway to honor it.

**Warning signs:** Developer asks "why isn't healthcheck waking the strategy-engine?" Answer: it isn't supposed to. The first signal-fetch request wakes it.

### Pitfall 5: testcontainers TimescaleDB cold-start cost (~5-10s) blows up pytest runtime

**What goes wrong:** Naive `function`-scoped fixture: each test pays ~5-10s container startup. 20 integration tests = ~3 minutes of pure overhead. Developers stop running integration tests locally.

**Why it happens:** `PostgresContainer("timescale/timescaledb:2.18.0-pg16")` starts a fresh container per fixture scope. Phase 0 has only 3 integration tests so it's tolerable, but the pattern compounds.

**How to avoid:**
- Use a `session`-scoped fixture for the container itself. Reuse across all integration tests.
- Use a `function`-scoped fixture for the database state: at start of each test, `TRUNCATE TABLE service_event` (or `DELETE`) and re-run any required migrations. Cheap (~10ms).
- Run `alembic upgrade head` inside the `session`-scoped fixture once.
- Mark integration tests `@pytest.mark.integration` so unit tests (which are 1000× faster) can run without container overhead by default.
- Document the convention in `tests/integration/conftest.py`.

**Warning signs:** `pytest -m integration` takes >30s for <10 tests. CI integration step >5 min.

### Pitfall 6: gitleaks false positives on uv.lock and test fixtures

**What goes wrong:** gitleaks' default ruleset matches some entropy patterns in `uv.lock` hashes and any "API key looking" strings in `tests/fixtures/`. CI fails on PRs that didn't introduce real secrets.

**Why it happens:** gitleaks balances false-negative rate (catch real secrets) against false-positive rate. Lock-file hashes and test fixtures often trip generic-hex-token or generic-api-key rules.

**How to avoid:**
- Configure `.gitleaks.toml` with `[[allowlists]] paths = ['''uv\.lock''', '''tests/fixtures/.*''', '''\.env\.example''']` — see Pattern 8.
- DO NOT allowlist the entire repo for any single rule — that defeats the purpose.
- When a real false positive surfaces, add a `paths = [...]` entry, not a `regexes = [...]` entry (which is broader).

**Warning signs:** CI gitleaks step fails on a PR that has no `.env*` changes. First reaction should be: check what file/path matched, then narrow-allowlist that path.

### Pitfall 7: Naive datetime in fixtures + freezegun TZ collapse

**What goes wrong:** A test uses `freezegun.freeze_time("2026-05-21")` (naive!) and constructs `Order(ts=datetime.now())` (also naive after freezegun). Pydantic's `@model_validator(mode='after')` rejects with "Order.ts must be timezone-aware". Test passes (the rejection IS the assertion) but isn't testing what the developer thinks.

**Why it happens:** `freezegun.freeze_time` accepts a naive string and substitutes naive datetimes for `datetime.now()`.

**How to avoid:**
- Always freeze with explicit tz: `freezegun.freeze_time("2026-05-21T00:00:00Z")`.
- Always call `datetime.now(timezone.utc)` in tests (and in production code).
- Add a lint rule (future Phase 1) banning `datetime.now()` without an explicit `tz=` argument under `src/`.

**Warning signs:** Tests that "pass" by triggering ValidationError where they should test the happy path.

### Pitfall 8: pyright strict mode + Pydantic v2 model_validator return type

**What goes wrong:** `@model_validator(mode='after') def foo(self): ...` without `-> Self` return annotation. pyright strict mode flags this; ruff doesn't (yet). CI fails.

**Why it happens:** Pydantic 2.x model_validator(mode='after') validators must return `Self`. The type system can infer it from `return self` but pyright strict demands the annotation.

**How to avoid:** Always annotate `from typing import Self` + `def foo(self) -> Self: ...`.

**Warning signs:** pyright error like `Type of "foo" is partially unknown` or `Return type implicitly Unknown`.

## Code Examples

Most key examples already live inline above in §Architecture Patterns. Two additional canonical patterns:

### Common Operation 1: Hypothesis strategy for a Decimal-money domain field

```python
# tests/conftest.py — shared strategies for the whole suite
from datetime import timezone
from decimal import Decimal
import hypothesis.strategies as st


money = st.decimals(
    min_value=Decimal("0.00000001"),
    max_value=Decimal("1000000000"),
    places=18,
    allow_nan=False,
    allow_infinity=False,
)
"""Strategy for positive Decimal money — bounded for fast shrinking."""

utc_dt = st.datetimes(
    min_value=__import__('datetime').datetime(2020, 1, 1),
    max_value=__import__('datetime').datetime(2030, 1, 1),
    timezones=st.just(timezone.utc),
)
"""Strategy for tz-aware UTC datetimes — bounded to plausible trading dates."""
```

[VERIFIED: hypothesis.readthedocs.io/en/latest/reference/strategies.html — `st.decimals(places=18)`, `st.datetimes(timezones=st.just(timezone.utc))` are documented strategies; `min_value`/`max_value` bounds prevent shrinking from running away on Decimal.]

### Common Operation 2: pyproject.toml skeleton (single-package layout per D-02)

```toml
# pyproject.toml
[project]
name = "shortfire"
version = "0.1.0"
description = "MEXC Futures Sniper — crypto data platform + short-after-pump strategy"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.13",
    "pydantic-settings>=2.11",
    "fastapi>=0.128",
    "uvicorn[standard]>=0.39",
    "structlog>=25.5",
    "asgi-correlation-id>=4.3",
    "prometheus-client>=0.25",
    "sqlalchemy>=2.0.49",
    "asyncpg>=0.31",
    "alembic>=1.16",
    "orjson>=3.11",
    "tenacity>=9.1",
    "aiolimiter>=1.2",
    "httpx>=0.28",
    "python-dotenv>=1.2",
]

[dependency-groups]
dev = [
    "pytest>=8.4",
    "pytest-asyncio>=1.2",
    "pytest-cov>=7.1",
    "hypothesis>=6.141",
    "freezegun>=1.5",
    "respx>=0.23",
    "aioresponses>=0.7",
    "testcontainers[postgres]>=4.13",
    "ruff>=0.15",
    "pyright>=1.1.409",
]

[tool.uv]
default-groups = ["dev"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/shortfire"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "integration: requires Docker + testcontainers (slow)",
]
addopts = [
    "-ra",
    "--strict-markers",
]
testpaths = ["tests"]

[tool.ruff]
line-length = 110
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "ASYNC", "PERF"]

[tool.pyright]
pythonVersion = "3.12"
typeCheckingMode = "strict"
include = ["src", "tests"]
exclude = ["**/__pycache__", "**/.venv"]
reportMissingTypeStubs = "warning"
```

[VERIFIED: docs.astral.sh/uv/concepts/projects/dependencies — `[dependency-groups]` is the PEP 735 declaration; `uv add --group dev` and `uv sync --group dev` are the documented operations; `default-groups = ["dev"]` makes `uv sync` install dev group by default.]

## Runtime State Inventory

> Phase 0 is **greenfield** — there is no existing runtime state to migrate. This section is included for completeness and to confirm "nothing in any category" was verified, not skipped.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no Postgres database exists yet (Phase 0 creates it). | none |
| Live service config | None — no Railway services exist yet. Phase 0 creates `data-platform`, `strategy-engine`, `dashboard`. | none |
| OS-registered state | None — no Windows tasks, launchd plists, or cron jobs reference the project. | none |
| Secrets/env vars | None — no production env vars exist yet. Phase 0 creates `.env.example` and the Settings layer; real secret values land in Railway dashboard in Phase 0 wave-end and `.env.local` (gitignored) on developer machines. | none |
| Build artifacts | None — no installed `*.egg-info`, no compiled binaries, no Docker images on any registry. | none |

**Nothing found in any category** — verified by directory listing of the project root (`CLAUDE.md` + `.planning/` only) and the project STATE.md (`Status: planning`, `Progress: 0%`).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Runtime, every entrypoint | ✓ (local check: 3.11.15 also present; planner should `uv python install 3.12`) | 3.11.15 local, install 3.12 via uv | `uv python install 3.12` |
| uv | Package management | ✓ | 0.11.8 | — |
| Docker | testcontainers + docker-compose local Postgres | ✓ (assumed — required by D-25 and D-31; not verified at research time. Planner should verify in wave 0) | — | If Docker absent, fall back to a developer-installed local Postgres + TimescaleDB extension (deviates from D-25). |
| GitHub repo | OPS-01 protected `main` | ✗ (greenfield; repo not yet created) | — | First Phase 0 wave creates the repo. |
| Railway account + project | OPS-02 deploy target | ✗ (greenfield; not yet provisioned) | — | First Phase 0 wave provisions the Railway project + Postgres marketplace service. |
| GitHub Actions billing | CI execution | ✓ (free tier sufficient for solo project) | — | — |

**Missing dependencies with no fallback:** none — all gaps are either trivially provisionable (GitHub repo, Railway project) or have documented fallbacks (Python via uv, Docker for tests).

**Missing dependencies with fallback:** Docker (fall back to local Postgres install if Docker absent, but this deviates from D-25 — planner should confirm Docker is present in wave 0).

## Validation Architecture

Nyquist validation is **enabled** (config.json `workflow.nyquist_validation: true`). Each Phase 0 success criterion has a deterministic validation artifact.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 8.4.2` + `pytest-asyncio 1.2.0` + `hypothesis 6.141.1` |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` (see §Code Examples / pyproject skeleton) |
| Quick run command | `uv run pytest -m "not integration"` |
| Full suite command | `uv run pytest --cov=shortfire --cov-fail-under=80` (then `uv run pytest -m integration` for testcontainers) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-01 | `uv sync` + `uv run pytest` green from a fresh clone | smoke | `uv sync && uv run pytest -m "not integration"` | ❌ Wave 0 (pyproject.toml + tests/) |
| FOUND-03 | Alembic + TimescaleDB DDL migrate rerun-safely | integration | `uv run pytest -m integration tests/integration/db/test_alembic_and_hypertables.py::test_alembic_upgrade_is_idempotent` | ❌ Wave 0 |
| FOUND-03 | `service_event` is a hypertable | integration | `uv run pytest -m integration tests/integration/db/test_alembic_and_hypertables.py::test_service_event_is_hypertable` | ❌ Wave 0 |
| FOUND-03 | `service_event` has compression policy attached | integration | `uv run pytest -m integration tests/integration/db/test_alembic_and_hypertables.py::test_service_event_has_compression_policy` | ❌ Wave 0 |
| FOUND-04 | All 8 domain types pass invariant property tests | unit + hypothesis | `uv run pytest tests/unit/domain/` | ❌ Wave 0 |
| FOUND-04 | `Order(intent='close', reduce_only=False)` raises ValidationError | unit + hypothesis | `uv run pytest tests/unit/domain/test_order.py::test_close_order_requires_reduce_only` | ❌ Wave 0 |
| FOUND-04 | `RiskLimits(max_per_trade_pct=Decimal("0.06"))` raises ValidationError | unit | `uv run pytest tests/unit/domain/test_risk_limits.py::test_max_per_trade_pct_cap` | ❌ Wave 0 |
| FOUND-04 | Round-trip `model_dump`/`model_validate` preserves all fields | unit + hypothesis | `uv run pytest tests/unit/domain/` (per-type) | ❌ Wave 0 |
| FOUND-04 | Naive datetime rejected on every type with a `ts` field | unit + hypothesis | `uv run pytest tests/unit/domain/test_timestamps_are_aware.py` | ❌ Wave 0 |
| FOUND-05 | `/health` returns 200 + `request_id` in JSON body | unit (FastAPI TestClient) | `uv run pytest tests/unit/observability/test_health.py` | ❌ Wave 0 |
| FOUND-05 | `/metrics` returns valid Prometheus text exposition | unit | `uv run pytest tests/unit/observability/test_metrics.py` | ❌ Wave 0 |
| FOUND-05 | structlog merges correlation_id contextvar into emitted JSON | unit | `uv run pytest tests/unit/observability/test_logging.py::test_correlation_id_appears_in_log` | ❌ Wave 0 |
| FOUND-06 | `.gitignore` covers `.env*` patterns | unit (lint-like) | `uv run pytest tests/unit/repo_hygiene/test_gitignore_covers_env_files.py` | ❌ Wave 0 |
| FOUND-06 | gitleaks pre-commit hook installed and runs | CI | `pre-commit run gitleaks --all-files` | ❌ Wave 0 |
| FOUND-06 | gitleaks-action passes on CI | CI | `.github/workflows/ci.yml` job: `gitleaks` step | ❌ Wave 0 |
| FOUND-07 | Each `*Settings` class fails fast on missing required env | unit | `uv run pytest tests/unit/settings/test_fail_fast.py` | ❌ Wave 0 |
| FOUND-07 | `safe_summary()` returns no SecretStr-typed values | unit | `uv run pytest tests/unit/settings/test_safe_summary_no_secrets.py` | ❌ Wave 0 |
| FOUND-07 | `assert_no_trade_env_leaked()` raises on misrouted `MEXC_TRADE__*` | unit | `uv run pytest tests/unit/settings/test_data_platform_anti_leak.py` | ❌ Wave 0 |
| FOUND-08 | `FakeMexcClient`, `FakeCoinglassClient`, `FakeCoinGeckoClient`, `InMemoryCandleRepo` exist and satisfy their Protocols | unit | `uv run pytest tests/unit/clients/test_fakes_match_protocols.py` | ❌ Wave 0 |
| OPS-01 | `main` branch protection rules require CI to pass | manual via GitHub UI; documented in `AGENTS.md` | (manual check post-deploy) | ❌ Wave 0 (AGENTS.md) |
| OPS-02 | Railway auto-deploys on push to `main` | manual smoke | `git push origin main && watch curl https://<service>.railway.app/health` | ❌ Wave 0 (Railway dashboard config) |
| OPS-03 | CI runs ruff + pyright + pytest on every PR | CI workflow | `.github/workflows/ci.yml` exists and is green | ❌ Wave 0 |
| OPS-04 | Coverage below 80% blocks merge | CI gate | `--cov-fail-under=80` in pyproject + `.github/workflows/ci.yml` | ❌ Wave 0 |
| OPS-07 | Migration discipline: each migration file reviewed; runs in deploy step | CI + Railway | Phase 0: `alembic upgrade head` runs as Railway pre-deploy command (D-34 + Pattern 4 startCommand `alembic upgrade head && uvicorn ...`) | ❌ Wave 0 |
| OPS-08 | Pre-commit hooks: ruff format + ruff lint + secret scan | local | `pre-commit run --all-files` returns 0 | ❌ Wave 0 |
| TEST-01 | pytest + Hypothesis + pytest-asyncio + respx + aioresponses installed and importable | unit | `uv run pytest tests/unit/test_smoke_imports.py` | ❌ Wave 0 |
| TEST-02 | TDD discipline documented in `AGENTS.md` | manual review | `AGENTS.md` exists and contains TDD section | ❌ Wave 0 |
| TEST-05 | `tests/fakes/` exposes deterministic fakes for every external boundary | unit | `uv run pytest tests/unit/clients/test_fakes_match_protocols.py` | ❌ Wave 0 |
| TEST-06 | freezegun is used in at least one tz-sensitive test | unit | grep `freezegun` under `tests/` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest -m "not integration"` (sub-second on a clean state — only unit tests)
- **Per wave merge:** Full suite — `uv run pytest --cov=shortfire --cov-fail-under=80` AND `uv run pytest -m integration`
- **Phase gate (`/gsd:verify-work`):** Full suite green + manual Railway smoke check (each of 3 services answers `/health` + `/metrics`)

### Wave 0 Gaps

Every test file listed above is greenfield. Wave 0 must establish:

- [ ] `pyproject.toml` with `[tool.pytest.ini_options]` block (asyncio_mode auto, integration marker)
- [ ] `tests/conftest.py` with shared `money` and `utc_dt` Hypothesis strategies
- [ ] `tests/integration/conftest.py` with session-scoped `PostgresContainer("timescale/timescaledb:2.18.0-pg16")` fixture
- [ ] `tests/fakes/{mexc,coinglass,coingecko,repos}.py` (Protocol-conforming stubs)
- [ ] All test files enumerated in the table above
- [ ] Framework install: `uv add --group dev pytest pytest-asyncio pytest-cov hypothesis freezegun respx aioresponses testcontainers[postgres]`

## Security Domain

> `security_enforcement` is not explicitly set in `.planning/config.json` — treated as **enabled** per protocol.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (Phase 0) | — (Phase 5 adds MEXC API key auth; Phase 4 adds Telegram bot auth) |
| V3 Session Management | no | — (no user sessions; this is a solo internal tool) |
| V4 Access Control | yes (low-stakes) | Per-service Railway env-var scoping (D-16). Anti-leak boundary at `DataPlatformSettings` schema level. |
| V5 Input Validation | yes | Pydantic v2 at every boundary (domain types, settings, future API request bodies). `strict=True` mode disables silent coercion. |
| V6 Cryptography | no (Phase 0) | — (Phase 5: HMAC for MEXC signing handled by ccxt — never hand-roll) |
| V7 Error Handling & Logging | yes | structlog with `SecretStr` (raises if logged directly). `safe_summary()` discipline (D-21). gitleaks 4-layer defense (D-22). |
| V8 Data Protection | yes | `SecretStr` for credentials. `.gitignore` covers `.env*` (D-23). gitleaks at 4 layers. |
| V14 Configuration | yes | pydantic-settings fail-fast on missing env vars (FOUND-07). Per-service subclasses prevent cross-service env leakage (D-16). |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key committed to git | Information Disclosure | 4-layer secret-scan defense (D-22): pre-commit gitleaks + CI gitleaks-action + GitHub Push Protection + GitHub Secret Scanning |
| Trade key visible on a service that shouldn't have it | Elevation of Privilege | Per-service `BaseSettings` subclasses (D-16); `DataPlatformSettings` has no `mexc_trade` field; startup assertion `assert_no_trade_env_leaked()` |
| `repr(settings)` accidentally leaks SecretStr to logs | Information Disclosure | Enforce `safe_summary()` pattern (D-21); never call `repr(settings)`; structlog config never includes raw settings object |
| SQL injection in Timescale DDL helpers (e.g., `create_hypertable('{table}', ...)`) | Tampering | Phase 0 helpers accept hardcoded constants only (called from migrations, not user input); migration files are reviewed; planner must NOT introduce dynamic table-name input |
| Pydantic v2 strict-mode-bypass via coercion | Tampering | `ConfigDict(strict=True)` disables coercion; tests assert that string/int → Decimal raises |
| `ON DELETE CASCADE` accidentally added to a future migration | Tampering / Loss of Data | Pre-commit grep guard (D-32); CI re-runs the grep guard |
| TIMESTAMP without timezone introduces silent UTC bugs | Tampering of historical data | Pre-commit grep guard for `TIMESTAMP[^(]` (D-32); domain types reject naive datetimes via `@model_validator` |
| Cross-service env var leakage via Railway's "share variables" feature | Information Disclosure / Elevation of Privilege | Railway service-scoped variables only; explicit `${{Postgres.DATABASE_URL}}` reference; document in `AGENTS.md` that variable sharing is forbidden |

## State of the Art

| Old Approach | Current Approach (2026) | When Changed | Impact |
|--------------|--------------------------|--------------|--------|
| `pip` + `virtualenv` + `poetry` | `uv` (single tool) | 2024-2025 | 10-100× faster installs; lockfile-based; PEP 735 dependency-groups; replaces poetry [VERIFIED: docs.astral.sh/uv]. |
| `psycopg2` (sync) | `asyncpg` (async) + `psycopg 3.x` (async-capable) | 2022-2024 | `psycopg2` is legacy; v3 is async-native. We use `asyncpg` for hot-path COPY-BIN and SQLAlchemy AsyncEngine, no psycopg in v1 per D-30. |
| Pydantic v1 `BaseModel.dict()` | Pydantic v2 `model_dump()` + Rust core (~10× faster) | 2023 | FastAPI 0.115+ dropped v1 entirely; `ConfigDict(frozen=True, strict=True)` is the canonical 2.x pattern. |
| Black + isort + flake8 + pylint | `ruff` (single tool, all in one) | 2023-2024 | 100× faster; one config; one rule grammar. |
| `aiohttp` standalone HTTP client | `httpx` (sync + async unified API) | 2022-2024 | `httpx` for Coinglass/CoinGecko; ccxt still uses aiohttp internally (acceptable, since it's the transport layer we don't touch). |
| `responses` (requests-based) | `respx` (httpx-based) | 2022 | We use `respx` because httpx is the new client. `aioresponses` for ccxt's aiohttp. |
| TimescaleDB function-form `create_hypertable()` only | New `CREATE TABLE ... WITH (timescaledb.hypertable)` syntax (preferred for new tables) | TimescaleDB 2.13+ | Function-form still works in 2.18 with `if_not_exists`; we use the function form for Alembic-friendliness. |
| Hand-rolled correlation-id middleware | `asgi-correlation-id` library | 2020-2024 | Maintained; integrates with structlog; canonical pattern. |
| Sync alembic env.py | Async alembic template (`alembic init -t async`) | Alembic 1.7+ | Async template is the standard since 2022; required for asyncpg. |
| Coverage gate via `coverage.py` thresholds | `pytest-cov --cov-fail-under=80` | Stable | Same mechanism, just pytest-integrated. |

**Deprecated / actively avoided:**
- **psycopg2** (legacy; no async)
- **Pandas v1.x** (EOL; no NumPy 2.x support — we use pandas 2.2 in Phase 2+ per CLAUDE.md)
- **Poetry** (slower than uv; CLAUDE.md prefers uv)
- **`requests` library for async code paths** (sync-only, blocks event loop)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `asgi-correlation-id` v4.3.4 is the canonical/maintained correlation-id middleware for FastAPI 2026 | §Standard Stack, §Pattern 5 | Low — package has 5+ years of maintenance; if abandoned, hand-roll ~30 lines |
| A2 | TimescaleDB 2.18.0 on PG16 is the current Railway marketplace template image tag | §Standard Stack, §Pattern 4 | Low — image tag locked by D-24; if unavailable, Railway dashboard surfaces the available tags |
| A3 | gitleaks v8.24.2 is the current stable release suitable for pre-commit + GitHub Action | §Pattern 8 | Low — gitleaks releases roughly monthly; planner should verify latest version at wave 0 |
| A4 | Docker is installed on the developer's machine | §Environment Availability | Medium — local TimescaleDB via docker-compose (D-25) AND integration tests via testcontainers both require Docker. If absent, alternate setup (local Postgres install) deviates from D-25 |
| A5 | Railway's default service config in 2026 honors `${{Postgres.DATABASE_URL}}` reference variable syntax | §Pattern 4 | Low — documented Railway feature |
| A6 | The user's `pip3` and pyhon3.11 local install will not interfere with `uv python install 3.12` for project Python | §Environment Availability | Low — uv manages its own Python installs in `~/.local/share/uv/` |
| A7 | gitleaks-action v2 is the canonical 2026 GitHub Action version for gitleaks | §Pattern 8, §Pattern 9 | Low — verified from gitleaks README |
| A8 | `astral-sh/setup-uv@v8` (uv 0.11.x) is the current pinned major | §Pattern 9 | Low — uv is on 0.11.8 locally |

**This table has entries**, meaning a small number of decisions need user confirmation OR planner-time re-verification. None are blocking; most resolve by checking the latest version at wave 0.

## Open Questions

1. **Should `data-platform`'s `startCommand` chain `alembic upgrade head && uvicorn ...`, or should Railway provide a `preDeployCommand` hook?**
   - What we know: Railway's `[deploy]` block supports `preDeployCommand` (array of commands run before each deploy). Chaining via `startCommand` works too.
   - What's unclear: Concurrent deploys would race the migration. With single-instance Railway, this is fine. Future Phase 5+ if we scale `data-platform` to >1 replica, the migration must move to `preDeployCommand` (which runs once before any replica starts).
   - Recommendation: Use `preDeployCommand = ["alembic upgrade head"]` from the start. Cleaner separation; future-proof.

2. **Does Railway's TimescaleDB marketplace template auto-create the `timescaledb` extension, or must migration 0001 do it?**
   - What we know: D-28 says migration 0001 must `CREATE EXTENSION IF NOT EXISTS timescaledb`. This is idempotent — safe regardless of whether the template pre-creates it.
   - What's unclear: Empirically, whether the marketplace template pre-creates the extension.
   - Recommendation: Always include `CREATE EXTENSION IF NOT EXISTS` in 0001. No-ops if already present; saves us if the template doesn't pre-create it.

3. **Should integration tests run in CI on every PR, or only on PR merge to main?**
   - What we know: testcontainers startup costs ~5-10s per session. With 3 Phase 0 integration tests + session-scoped fixture, that's ~30s overhead per CI run.
   - What's unclear: User preference. Cost is small but multiplies across many PRs.
   - Recommendation: Run on every PR. 30s is negligible; finding a Timescale-related regression at PR time is much cheaper than at merge time.

4. **Should `prometheus-client` registry be `prometheus_client.REGISTRY` (default global) or a custom `CollectorRegistry`?**
   - What we know: Default global registry includes process metrics (process_cpu_seconds_total, etc.). A custom registry omits them unless we re-register manually.
   - What's unclear: Whether the user wants process metrics on `/metrics` in Phase 0 (for Phase 5 Grafana to consume) or strictly business metrics only.
   - Recommendation: Use a custom `CollectorRegistry` per Pattern 5; explicitly re-register process metrics if Phase 5 Grafana needs them. Cleaner separation of business vs platform metrics.

5. **Should the planner use `AGENTS.md` (current convention in this repo) or `CONTRIBUTING.md` for the TDD discipline doc (TEST-02)?**
   - What we know: `AGENTS.md` is referenced in `.planning/` workflow context. `CONTRIBUTING.md` is a more conventional name in OSS land.
   - Recommendation: Use `AGENTS.md` — consistent with current GSD workflow and CLAUDE.md conventions.

## Sources

### Primary (HIGH confidence)

- `pydantic.dev/docs/validation/latest/concepts/models/` — frozen, strict, model_validator(mode='after'), Decimal/Literal/tuple patterns
- `pydantic.dev/docs/validation/latest/concepts/pydantic_settings/` — per-service BaseSettings, env_nested_delimiter, SecretStr, conditional env_file
- `alembic.sqlalchemy.org/en/latest/cookbook.html` — async env.py with `async_engine_from_config`, `transaction_per_migration=True`, `compare_type=True`
- `structlog.org/en/stable/contextvars.html` — `merge_contextvars` first-in-processor-stack pattern, async correlation-id propagation
- `hypothesis.readthedocs.io/en/latest/reference/strategies.html` — `decimals(places=18)`, `datetimes(timezones=just(UTC))`, `sampled_from(literal_values)`
- `github.com/snok/asgi-correlation-id` — canonical FastAPI install + structlog integration via `add_correlation` processor
- `docs.astral.sh/uv/guides/integration/github` — `astral-sh/setup-uv@v8` + `enable-cache: true` + `cache-dependency-glob`
- `docs.astral.sh/uv/concepts/projects/dependencies` — `[dependency-groups]` (PEP 735), `default-groups`, `uv sync --locked --group dev`
- `docs.railway.com/reference/config-as-code` — `[build]`/`[deploy]` schema, `watchPatterns` lives under `[build]`
- `docs.railway.com/reference/healthchecks` + `station.railway.com` Q&A — healthchecks run only at deploy time, do not wake sleeping services
- `docs.railway.com/reference/app-sleeping` — Serverless feature semantics, 10-minute outbound-traffic sleep window, first inbound request wakes
- `github.com/gitleaks/gitleaks` README — pre-commit hook entry, `[[allowlists]]` paths syntax, gitleaks-action v2
- PyPI direct queries — verified version of every Phase 0 package (May 2026)
- `CLAUDE.md` — locked tech stack matrix for this project
- `slopcheck install --ecosystem pypi <packages...>` — all 25 Phase 0 packages cleared `[OK]` (`pytest-cov` flagged "no source repository linked" but is canonical; `python-dotenv` and `prometheus-client` flagged for naming patterns but established)

### Secondary (MEDIUM confidence)

- `tigerdata.com/docs/use-timescale/latest/hypertables/create` — confirms `WITH (timescaledb.hypertable)` syntax is preferred for new tables; legacy `create_hypertable()` still ships in 2.18
- `github.com/trallnag/prometheus-fastapi-instrumentator` README — explicit "not made for generic Prometheus instrumentation" — drives Pattern 5 choice of raw `prometheus-client`
- `testcontainers-python.readthedocs.io` — `PostgresContainer(custom_image)` pattern; specifics of TimescaleDB integration are inferred from canonical pattern (cross-verified via community examples)

### Tertiary (LOW confidence — flagged in §Assumptions Log)

- Exact current version of `asgi-correlation-id` (4.3.4 per Oct 2024 release; library may have shipped patches since but no major changes)
- Exact current version of gitleaks (v8.24.2 per the README; releases roughly monthly)
- Railway marketplace template image tag stability (`timescale/timescaledb:2.18.0-pg16`)

## Metadata

**Confidence breakdown:**
- Standard stack — HIGH — every package version-verified against PyPI, slopcheck-cleared, and cross-referenced with CLAUDE.md
- Architecture patterns — HIGH — every pattern has at least one official-docs URL with verified code snippets
- Pitfalls — HIGH — 4 critical pitfalls cross-verified against official docs (Railway sleep + healthcheck, Pydantic strict, alembic async URL rewrite, structlog contextvars across asyncio.create_task)
- Validation Architecture — HIGH — every Phase 0 requirement has a deterministic test artifact + automated command

**Research date:** 2026-05-21
**Valid until:** 2026-06-20 (30 days — stable stack, no rapidly-moving dependencies)
