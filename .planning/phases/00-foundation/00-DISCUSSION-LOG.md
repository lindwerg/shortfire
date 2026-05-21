# Phase 0: Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `00-CONTEXT.md` — this log preserves the alternatives considered and the analysis behind each pick.

**Date:** 2026-05-21
**Phase:** 0-Foundation
**Areas discussed:** Service split from day 0, Domain types modeling, Settings + local-dev secrets, TimescaleDB local dev + migrations
**Mode:** Default interactive discuss + user-requested 8 iterations of `mcp__sequential-thinking` per area + Context7 docs lookup on each area's load-bearing libraries.

---

## Area 1: Service split from day 0

### Primary question — How many Railway services in Phase 0?
| Option | Description | Selected |
|--------|-------------|----------|
| 3 placeholder services right away | data-platform / strategy-engine / dashboard all start in Phase 0; each serves /health + /metrics; Railway env-var-scoping boundaries established before any keys exist; ~$5-10/mo extra | ✓ |
| 1 service in Phase 0, +2 in Phase 1 | Only data-platform in Phase 0 (matches success criterion #2 literally); first Phase 1 plan adds the other two; saves ~$5-10/mo for 2-4 weeks | |
| Different approach (open text) | (user did not pick) | |

### Naming
| Option | Description | Selected |
|--------|-------------|----------|
| Final v1 names from day 0 | `data-platform`, `strategy-engine`, `dashboard` — no rename later | ✓ |
| Temporary name "app" | Phase 0 single service named "app" or "shortfire"; rename in Phase 1 | |

### Repo layout
| Option | Description | Selected |
|--------|-------------|----------|
| Single Python package + entrypoints/ | `src/shortfire/` one package; `src/shortfire/entrypoints/{data_platform,strategy_engine,dashboard}.py`; one Dockerfile / pyproject / Alembic | ✓ |
| uv workspace (`packages/*`) | Per-service packages (`shortfire-core`, `shortfire-data`, ...) | |
| `apps/` subdirectories + shared `src/` | apps/data-platform/main.py with own Dockerfile; shared lib in src/shortfire/ | |

### Secondary follow-ups
- **Dockerfile** → "Один Dockerfile на весь монорепо" (selected) vs "Dockerfile на сервис". One shared image, each service overrides `startCommand`.
- **sleepApplication for placeholders** → "Sleep вкл. для placeholder'ов" (selected) vs "Все always-on". data-platform stays always-on for Phase 1 ingest scheduler; strategy-engine and dashboard sleep when idle.
- **watchPatterns** → "Нет — любой коммит редеплоит все 3" (selected) vs "watchPatterns per service". Matches PROJECT.md "commit → push → deploy after every task"; revisit if cost/instability emerges.

### Analysis behind the picks
- Context7 confirmed Railway supports multi-service monorepo via per-service `startCommand`, `rootDirectory`, `watchPatterns`, `sleepApplication`, and `${{service.RAILWAY_PRIVATE_DOMAIN}}` reference variables.
- uv workspaces are real and well-documented (`[tool.uv.workspace] members = ["packages/*"]`, single shared lockfile, `uv run --package`) but overkill for ShortFIRE's coupling profile.
- The decisive structural argument: Railway scopes env vars per-service, which means env-var-scoping is a security boundary. `TRADE_KEY` (Phase 5) on `strategy-engine` is structurally invisible to `data-platform` — but that boundary must be put in place BEFORE any key exists (Phase 0), not retrofitted.

### Notes
None additional.

---

## Area 2: Domain types modeling

### Primary question — Modeling approach for the 8 domain types
| Option | Description | Selected |
|--------|-------------|----------|
| Pydantic everywhere (8/8 types) | All 8 = Pydantic v2 BaseModel with frozen+strict; matches FOUND-04 literally; hot-path bypass via asyncpg COPY in Phase 1, not via switching to msgspec | ✓ |
| Hybrid: Pydantic for business + msgspec for data | Signal/Order/Position/RiskLimits = Pydantic; Candle/OrderBook/Funding/Liquidation = msgspec.Struct | |
| Different approach (open text) | (user did not pick) | |

### Money
| Option | Description | Selected |
|--------|-------------|----------|
| Decimal everywhere + lint rule against float | Price/quantity/PnL/notional all Decimal; NUMERIC(38,18) in Postgres; pre-commit grep bans `: float` in `src/shortfire/domain/`; cast to float64 only at the polars/numpy ML boundary | ✓ |
| Decimal for money, float for probabilities | `Signal.confidence: float` (probability in [0,1]) but everything else Decimal | |
| Float everywhere | Precision drift on memecoin prices at 1e-8; not recommended for trading | |

### Position mutability
| Option | Description | Selected |
|--------|-------------|----------|
| Mutable Position in Phase 0 | Position(frozen=False); mutates as fills land; event-sourcing in Phase 3 backtester deferred | ✓ |
| Immutable Position + Fill events from day 0 | Position(frozen=True); each fill returns new Position; better BACK-10 reproducibility but premature for Phase 0 | |

### Enums
| Option | Description | Selected |
|--------|-------------|----------|
| Literal[...] everywhere | `Literal["short", "long"]`, `Literal["open", "close"]`, etc.; Pydantic-native, pyright strict friendly, no instance state | ✓ |
| StrEnum for OrderIntent + Literal for the rest | OrderIntent.OPEN/.CLOSE as real classes (because EXEC-01/02 is THE most important invariant); rest as Literal | |
| StrEnum everywhere | All enums as real classes; more boilerplate but method-extensible | |

### Analysis behind the picks
- Context7 verified Pydantic v2 (pydantic-core/Rust) construction is ~3-10μs per simple record; even at L2 cascade peaks of ~5000 events/sec, validation is <50ms/sec — irrelevant. The real bottleneck in Phase 1+ ingest is network and DB write throughput, not Pydantic.
- msgspec.Struct (10-30× faster than Pydantic, supports `frozen=True`, hashable) is a real option but its missing surface (no custom validators / computed_field) makes EXEC-02-style invariants more awkward.
- CLAUDE.md tech stack already commits to "Use SQLAlchemy Core (not ORM) for hot-path hypertable inserts" — meaning ingest hot-path bypasses Pydantic anyway via asyncpg COPY.
- Hypothesis property tests work identically with Pydantic or msgspec; this isn't a tie-breaker.
- The user explicitly accepted the recommendation in all 4 sub-questions.

### Notes
None additional.

---

## Area 3: Settings + local-dev secrets

### Primary question — Settings shape
| Option | Description | Selected |
|--------|-------------|----------|
| Per-service subclasses + nested submodels | `BaseAppSettings` with common fields; `DataPlatformSettings`, `StrategyEngineSettings`, `DashboardSettings`, `RiskGuardSettings` subclasses; nested submodels (`MexcReadSettings`, `MexcTradeSettings`, `CoinglassSettings`, ...); pydantic-native fail-fast on missing required fields; Phase 5 `mexc_trade` lives only on StrategyEngineSettings = data-platform structurally cannot accept TRADE_KEY | ✓ |
| One AppSettings, all optional + runtime check | One class; each entrypoint calls `require_fields(...)` in main(); simpler initially but worse anti-leak posture | |

### Local-dev secrets strategy
| Option | Description | Selected |
|--------|-------------|----------|
| `.env.local` + pydantic-settings | `.env.example` committed; `.env.local` gitignored; pydantic-settings loads it when `ENV != "production"`; Phase 4+ real trade keys via `railway run` only | ✓ |
| Only `railway run`, no .env files | All local invocations via Railway CLI; zero secrets on disk; slow startup + risk of touching prod data accidentally | |
| Hybrid: .env.local for dev data, railway run for live API keys | Combination of above; practical but discipline-dependent | |

### Secret-scan tool in pre-commit
| Option | Description | Selected |
|--------|-------------|----------|
| gitleaks (pre-commit + CI + GH push protection) | 4-layer defense: pre-commit gitleaks + CI gitleaks-action + GitHub Secret Scanning + GitHub Push Protection | ✓ |
| detect-secrets (Yelp) + GH secret scanning | More allowlist-friendly Python tool, slower than gitleaks | |
| trufflehog | Entropy-based, more false positives | |

### Nested env-var delimiter
| Option | Description | Selected |
|--------|-------------|----------|
| Double underscore `__` (MEXC__READ_KEY) | pydantic-settings default; ASCII-safe in shell; documented pattern | ✓ |
| Single `_` (flat, no nesting) | Flat naming; loses grouping; needs validation_alias on every field — more boilerplate | |

### Analysis behind the picks
- Context7 verified `env_nested_delimiter='__'` is the canonical pydantic-settings approach. `SecretStr` is the standard for masking via repr; structlog redactor for defense-in-depth.
- The "per-service subclasses" pattern provides STRUCTURAL anti-leak: a service whose Settings class doesn't have a `mexc_trade` field cannot load `MEXC_TRADE__*` env vars even if they're somehow visible. This complements Railway's env-var scoping for layered defense.
- 4-layer secret-scan defense (gitleaks pre-commit + CI + GH Push Protection + GH Secret Scanning) is established 2025-2026 best practice.

### Notes
None additional.

---

## Area 4: TimescaleDB local dev + migrations

### Primary question — TimescaleDB provisioning on Railway
| Option | Description | Selected |
|--------|-------------|----------|
| Railway marketplace TimescaleDB template | Railway docs explicitly: "for popular extensions like PostGIS, TimescaleDB, and pgvector, there are several specialized options available in the template marketplace"; private network postgres.railway.internal; DATABASE_URL via reference variable | ✓ |
| TigerData (Timescale Cloud) external | Externally managed Timescale; PITR backups, tiered S3, dashboard; ~$20-50/mo minimum; overkill for Phase 0 | |
| DIY: timescale/timescaledb image as Railway service | Raw Docker image as Railway service with persistent volume; small backup/monitoring gaps | |

### First hypertable in Phase 0
| Option | Description | Selected |
|--------|-------------|----------|
| `service_event` (observability) | `service_event(ts TIMESTAMPTZ, service_name TEXT, event_type TEXT, payload JSONB)`; every service writes heartbeats/restarts/scheduled-task-runs; real long-term table | ✓ |
| `_smoke_metric` (throwaway) | Pure smoke object; dropped in Phase 1; doesn't carry observability value | |
| `raw_mexc_candles_1m` (Phase 1 table early) | Scope creep — Phase 1 schema not yet finalized | |

### Integration tests with Timescale
| Option | Description | Selected |
|--------|-------------|----------|
| testcontainers (isolated per session) | `PostgresContainer("timescale/timescaledb:2.18.0-pg16")` from testcontainers-python; ~5-10s session startup; full isolation between CI runs; pytest marker `@integration` | ✓ |
| Reuse local docker-compose container | Faster (no container startup) but developer must run docker-compose first; CI still uses testcontainers | |
| Hybrid: testcontainers in CI, docker-compose locally | Best dev exp but more config; can add later | |

### Async DB driver
| Option | Description | Selected |
|--------|-------------|----------|
| asyncpg (direct, hot-path) | asyncpg 0.30+; fastest async Postgres driver; `COPY BIN` support for Phase 1 bulk ingest; SQLAlchemy 2.x via `postgresql+asyncpg://` | ✓ |
| psycopg v3 async | More feature-rich (server-side cursors), slightly slower on hot-path | |
| Both: asyncpg + psycopg | Two drivers, more deps, sharper concerns separation | |

### Analysis behind the picks
- Context7 query against `/railwayapp/docs` returned a direct quote confirming Railway marketplace TimescaleDB template exists.
- Context7 query against `/timescale/timescaledb` returned the SQL primitives needed (`create_hypertable`, `add_compression_policy`, `add_retention_policy`) all with `if_not_exists` flags for idempotency.
- Context7 query against `/websites/alembic_sqlalchemy` returned the async template (`alembic init -t async`) and the canonical `async_engine_from_config` env.py pattern.
- Phase 0 success criterion #4 ("alembic upgrade head applies TimescaleDB-aware migration (hypertable + compression policy) and is rerun-safe") is structurally satisfied by D-27 (helper module with `if_not_exists=True` flags) + D-28 (the actual 2 migrations) + D-31 (integration tests proving rerun safety).

### Notes
None additional.

---

## Claude's Discretion

The user did NOT say "you decide" on any of the 12 sub-questions across the 4 areas — every decision came from an explicit user pick or follow-up confirmation. Claude has discretion only on second-order details not surfaced in this discussion (precise JSON schema of `service_event.payload`, exact structlog processor stack, Dockerfile multistage layering, pytest fixture naming, etc.) — those will be resolved at planning time per Phase 0 plan-phase.

## Deferred Ideas

- **Event-sourced Position** (immutable Position + Fill events) — revisit in Phase 3 backtester if BACK-10 reproducibility demands it.
- **msgspec for hot-path domain types** — revisit only if Phase 1+ profiling shows Pydantic in the top-3 hot path.
- **watchPatterns per Railway service** — defer until cost or instability becomes a concern.

## Must-Do Before Phase 1 plan-phase

- **Update ROADMAP.md / REQUIREMENTS.md** to reflect user's actual data-tier subscriptions: Coinglass ~$35/mo (likely Hobbyist tier, NOT Startup $79 referenced in DATA-07, STOR-08, V2-DATA-01) and CoinGecko ~$35/mo (NOT Analyst $129). This affects Phase 1 backfill scope and rate-limit planning. Recorded in agent memory at `project_data_tier_subscriptions.md`.
