---
phase: 0
slug: foundation
status: draft
shadcn_initialized: false
preset: none
created: 2026-05-21
surface_kind: machine_readable_contract
---

# Phase 0 — Machine-Readable Surface Contract

> **Note on scope.** Phase 0 is a backend-only foundation phase. There are NO user-facing UI surfaces — the three Railway services (`data-platform`, `strategy-engine`, `dashboard`) are placeholder FastAPI entrypoints that expose only `/health` (structured JSON) and `/metrics` (Prometheus text). Real dashboards land in Phase 5. This document is therefore the contract for the **machine-readable response, log, config, and CLI output shapes** that Phase 5+ consumers (Grafana, Prometheus, jq pipelines, on-call operators) will depend on. Treating these formats as a frozen contract from Phase 0 prevents schema drift when real frontends/dashboards arrive.
>
> The standard "Spacing / Typography / Color / Copywriting" sections of UI-SPEC.md have been adapted as follows:
> - **Spacing → JSON field ordering & log line shape**
> - **Typography → Field naming convention (snake_case)**
> - **Color → Severity / log-level conventions**
> - **Components → Endpoints + log event taxonomy**
> - **Copywriting → CLI / error message templates**
> - **Accessibility → Tooling compatibility (jq / Prometheus scraper / Grafana / Loki)**

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none (machine-readable surface only — no visual UI) |
| Preset | not applicable |
| Component library | not applicable |
| Icon library | not applicable |
| Font | not applicable (terminal default; JSON consumed by parsers) |

---

## Endpoints (Components)

Every entrypoint (`data_platform`, `strategy_engine`, `dashboard`) MUST expose exactly these two endpoints in Phase 0. No other HTTP surface is permitted.

### `GET /health`

Returns a single structured JSON object describing service readiness. Healthy status is `200 OK`. Any startup-incomplete state returns `503` with the same body shape (`status: "starting"` or `status: "degraded"`).

**Response body (JSON, sorted keys, no trailing newline):**

```json
{
  "correlation_id": "9f3b1c40-7e8e-4b6a-9a3b-1a2c3d4e5f60",
  "env": "production",
  "service_name": "data-platform",
  "status": "ok",
  "ts": "2026-05-21T10:26:24.849Z",
  "version": "0.1.0"
}
```

**Field contract:**

| Field | Type | Required | Source | Notes |
|-------|------|----------|--------|-------|
| `correlation_id` | string (UUID4) | yes | `asgi-correlation-id` middleware, or generated server-side if header absent | Lowercase, hyphenated, RFC 4122 |
| `env` | string enum | yes | `BaseAppSettings.common.env` | One of: `local`, `ci`, `staging`, `production` |
| `service_name` | string | yes | `BaseAppSettings.service_name` | Kebab-case, one of: `data-platform`, `strategy-engine`, `dashboard` |
| `status` | string enum | yes | computed | One of: `ok`, `starting`, `degraded` (Phase 0 only emits `ok` after Settings load; `starting` if pre-startup; reserved `degraded` for Phase 1+) |
| `ts` | string (ISO-8601, UTC, `Z` suffix) | yes | `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")` | Millisecond precision exactly (3 decimals before `Z`). NEVER naive timestamps. Mirrors STOR-03. |
| `version` | string (semver) | yes | `shortfire.__version__` | `MAJOR.MINOR.PATCH` only — no build metadata in Phase 0 |

**Forbidden fields (NEVER add in Phase 0):**
- `uptime_seconds` (Phase 5 dashboards)
- `db_ping_ms` (Phase 1 readiness probe extension)
- `commit_sha` (Phase 1 — needs build-time injection wiring)
- Any field containing credentials, hostnames with embedded credentials, or sensitive operator metadata.

**Key ordering:** Alphabetical (Python's `json.dumps(..., sort_keys=True)` or `orjson.dumps(..., option=orjson.OPT_SORT_KEYS)`). This is mandatory — log diff tooling and jq pipelines depend on stable ordering.

---

### `GET /metrics`

Returns Prometheus text exposition format v0.0.4. Content-Type MUST be `text/plain; version=0.0.4; charset=utf-8`.

**Metric naming convention (locked from Phase 0):**

```
shortfire_<service>_<subsystem>_<metric_name>_<unit>
```

Where:
- `service` = one of `data_platform`, `strategy_engine`, `dashboard` (snake_case — Prometheus convention forbids hyphens in metric names; map kebab-case service names to snake_case here ONLY)
- `subsystem` = optional, snake_case, free-form (e.g., `http`, `db`, `ingest`, `signals`)
- `metric_name` = snake_case verb-or-noun (e.g., `requests_total`, `request_duration`, `events_emitted`)
- `unit` = Prometheus base unit suffix (`_seconds`, `_bytes`, `_total` for counters, `_ratio` for 0..1 gauges) — REQUIRED on every metric per Prometheus best practice

**Phase 0 metric registry (mandatory minimum):**

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `shortfire_<service>_http_requests_total` | Counter | `method`, `path`, `status` | HTTP request counter (auto-incremented by middleware) |
| `shortfire_<service>_http_request_duration_seconds` | Histogram | `method`, `path` | HTTP latency. Buckets: `[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]` |
| `shortfire_<service>_service_event_emitted_total` | Counter | `event_type` | Counts `service_event` table writes (heartbeat, startup, shutdown, scheduled_task_run) |
| `shortfire_<service>_build_info` | Gauge (always `1`) | `version`, `commit_sha`, `env` | Standard build-info pattern; allows joining version metadata into PromQL |

**Forbidden in Phase 0:**
- High-cardinality labels (`user_id`, `correlation_id`, `client_order_id`, `symbol`)
- Non-base-unit suffixes (`_ms`, `_kb`)
- Metrics without unit suffix
- Custom registries (every metric registers into the default `prometheus_client.REGISTRY`)

**Empty-state contract:** Even before the first request, `/metrics` MUST emit the metric NAMES and `# HELP` / `# TYPE` lines for every declared metric (counters at `0`, histograms with empty buckets). Empty `/metrics` body is a contract violation — Grafana panels break on missing series at dashboard load time.

---

## Log/Response Schema Field Naming (Typography)

All field names across `/health`, structlog events, `service_event.payload`, and Prometheus labels MUST follow:

| Surface | Convention | Example | Forbidden |
|---------|------------|---------|-----------|
| JSON response body fields | `snake_case` | `correlation_id`, `service_name` | `camelCase`, `kebab-case`, `PascalCase` |
| structlog event keys | `snake_case` | `request_path`, `db_pool_size` | mixed case |
| Prometheus metric names | `snake_case`, lowercase | `shortfire_data_platform_http_requests_total` | hyphens, uppercase |
| Prometheus label names | `snake_case`, lowercase | `event_type`, `status` | `eventType`, `STATUS` |
| Prometheus label VALUES | free-form lowercase | `"data_platform"`, `"startup"` | mixed case |
| Env var names | `UPPER_SNAKE` with `__` nested delimiter | `DATABASE_URL`, `MEXC__READ_KEY` | single underscore for nesting |
| CLI command exit names | `kebab-case` (where surfaced) | `init-db`, `upgrade-head` | snake_case in CLI surface |

**Reserved key namespace** (these keys mean the same thing everywhere they appear — never repurpose):

| Key | Meaning | Type |
|-----|---------|------|
| `correlation_id` | Per-request UUID4 from `asgi-correlation-id` | string |
| `service_name` | Logical service identifier | string enum |
| `env` | Environment | string enum |
| `ts` | Event/response timestamp (ISO-8601, UTC, `Z`) | string |
| `event` | structlog event name (snake_case, dot-namespaced) | string |
| `level` | structlog log level | string enum |
| `version` | Application semver | string |
| `request_id` | Alias for `correlation_id` in structlog output (kept for `asgi-correlation-id` compatibility) | string |

---

## Severity / Level Conventions (Color)

Phase 0 uses log levels and HTTP status conventions as its "severity color palette." These are the dominant/secondary/accent equivalents.

### Log levels (60/30/10 distribution)

| Role | Level | Usage Share | Reserved For |
|------|-------|-------------|--------------|
| Dominant (60%) | `INFO` | Normal operation | Startup banner, settings.loaded, request lifecycle, scheduled tasks, healthy state transitions |
| Secondary (30%) | `DEBUG` | Disabled in production | Hot-path internals (only when `LOG_LEVEL=DEBUG`); never relied on by alerts |
| Accent (10%) | `WARN` | Degraded but recoverable | Retry-attempting, rate-limit-near-cap, optional config missing, deprecated path use |
| Destructive | `ERROR` | Unrecoverable in this code path | Unhandled exception, fail-fast startup, settings load failure, DB connection failure |

`WARN` is reserved — do NOT use it for routine state changes. If a developer sees `WARN` in Phase 0 logs in production, it must indicate an actual condition worth attention.

`CRITICAL` / `FATAL` are NOT used in Phase 0 (no Telegram severity channels yet — those land in Phase 4 per OBS-03). All fail-fast startup conditions raise unhandled exceptions, which uvicorn renders as `ERROR`-level tracebacks.

### HTTP status conventions

| Code | When Phase 0 returns it |
|------|------------------------|
| `200 OK` | `/health` with `status: "ok"`; `/metrics` always |
| `503 Service Unavailable` | `/health` with `status: "starting"` (Settings not loaded yet) — reserved; not normally emitted in Phase 0 |
| `404 Not Found` | Any path other than `/health` or `/metrics` (FastAPI default) |
| `500 Internal Server Error` | Unhandled exception (FastAPI default; logged at `ERROR` level with traceback + correlation_id) |

Phase 0 does NOT emit `4xx` other than `404` (no auth, no input validation surface).

---

## Log Event Schema (structlog)

Every log line is a single JSON object, one event per line (newline-delimited JSON, NDJSON). The renderer is `structlog.processors.JSONRenderer()`. Sort keys at render time is NOT required from structlog (would defeat readability of `event` first), but the field set IS fixed.

**Mandatory base fields** (every log line, every service, every event):

```json
{
  "ts": "2026-05-21T10:26:24.849Z",
  "level": "info",
  "event": "service.startup",
  "service_name": "data-platform",
  "env": "production",
  "correlation_id": "9f3b1c40-7e8e-4b6a-9a3b-1a2c3d4e5f60"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `ts` | ISO-8601 UTC with `Z` | yes | `structlog.processors.TimeStamper(fmt="iso", utc=True)` |
| `level` | lowercase string | yes | One of: `debug`, `info`, `warning`, `error` |
| `event` | snake_case, dot-namespaced string | yes | See event taxonomy below |
| `service_name` | string enum | yes | Bound via `structlog.contextvars.bind_contextvars` at startup |
| `env` | string enum | yes | Same source as above |
| `correlation_id` | UUID4 or absent | conditional | Present for any log inside a request scope; absent for boot/scheduled events outside a request |

**Forbidden:**
- Multi-line log entries (every event = one line)
- Tracebacks rendered as separate lines — Python tracebacks are rendered into a single `exception` key by `structlog.processors.format_exc_info`
- Free-form English event names — every `event` MUST be from the registered taxonomy

### Event Taxonomy (Phase 0)

| `event` | Level | When | Required Extra Keys |
|---------|-------|------|---------------------|
| `service.startup` | info | Entrypoint `lifespan` enters | `version`, `pid` |
| `service.settings.loaded` | info | After Settings instantiation succeeds | `**settings.safe_summary()` (sanitized) |
| `service.settings.failed` | error | Settings validation failed | `missing_fields` (list[str]), `error` (string) |
| `service.shutdown` | info | Entrypoint `lifespan` exits cleanly | `uptime_seconds` (float) |
| `service.health_check` | debug | Each `/health` request served | `status` (string) |
| `db.engine.created` | info | AsyncEngine instantiated | `db_host` (string, no creds) |
| `db.migration.applied` | info | `alembic upgrade head` succeeded on startup | `revision_from`, `revision_to` |
| `request.received` | info | Inbound HTTP request | `method`, `path` |
| `request.completed` | info | HTTP response sent | `method`, `path`, `status`, `duration_ms` (int) |
| `request.failed` | error | Unhandled exception in request scope | `method`, `path`, `exception` (string) |
| `service_event.emitted` | debug | A row was written to `service_event` table | `event_type` (string), `payload_size_bytes` (int) |
| `secret.guard.tripped` | error | `assert_no_trade_env_leaked()` found `MEXC_TRADE__*` on the wrong service | `leaked_var_names` (list[str]) |

Adding a new event in Phase 1+ requires registering it in `src/shortfire/observability/events.py` (single registry module — prevents Sprache drift across services). Phase 0 establishes this module with the events above.

---

## JSON Field Ordering (Spacing/Layout)

### `/health` response

Strict alphabetical ordering enforced at serialization time. Why: Grafana JSON panels and `jq` paths are stable; diffs in deploy artifacts read cleanly.

### structlog event lines

Readability-first ordering at render time (NOT alphabetical):

1. `ts` — first; humans + log viewers scan timestamp first
2. `level` — second; severity at a glance
3. `event` — third; event name is the primary "what"
4. `service_name`, `env` — context
5. `correlation_id` — trace anchor (when present)
6. Event-specific keys — last, alphabetical among themselves

structlog's default `JSONRenderer` preserves processor-set order; the processor stack appends keys in the order shown above.

### `service_event.payload` JSON column

The `payload` column on `service_event` is `JSONB`. Internally Postgres normalizes JSONB representation (sorted keys, no whitespace) — Phase 0 does not need to enforce app-side ordering for storage. For human-readable `jq` queries against the column, the canonical pattern is:

```bash
psql -c "SELECT jsonb_pretty(payload) FROM service_event WHERE event_type='startup' ORDER BY ts DESC LIMIT 5"
```

### `.env.example` formatting

```
# ============================================================
# COMMON (all services)
# ============================================================

# Logical environment selector. Controls .env.local loading and log emission shape.
ENV=local

# Default log level. Production deploys override via Railway Variables.
LOG_LEVEL=INFO

# ============================================================
# DATABASE
# ============================================================

# Async Postgres URL. Phase 0 rewrites postgres:// to postgresql+asyncpg:// at engine creation.
DATABASE_URL=postgresql://shortfire:shortfire@localhost:5432/shortfire_dev

# ============================================================
# DATA PLATFORM SERVICE — read-only credentials (Phase 1+)
# ============================================================

# MEXC read-only API key (no trade, no withdraw). Leave empty in Phase 0.
MEXC__READ_KEY=your_mexc_read_key_here
MEXC__READ_SECRET=your_mexc_read_secret_here

# Coinglass API key (Hobbyist tier per actual subscription — see Phase 1 reconciliation).
COINGLASS__API_KEY=your_coinglass_api_key_here

# CoinGecko API key (Demo tier free).
COINGECKO__API_KEY=your_coingecko_api_key_here

# ============================================================
# STRATEGY ENGINE SERVICE — trade credentials (Phase 5 ONLY — NEVER fill before Phase 5)
# ============================================================

# MEXC trade-only API key. MUST have withdraw disabled. NEVER commit a real value.
# In production, set via Railway Variables on the strategy-engine service only.
# MEXC_TRADE__TRADE_KEY=
# MEXC_TRADE__TRADE_SECRET=

# ============================================================
# OPTIONAL — observability backends
# ============================================================

# Telegram bot (Phase 4+; commented in Phase 0).
# TELEGRAM__BOT_TOKEN=your_telegram_bot_token_here
```

**Formatting rules:**
- Section banners use exactly `# ===` followed by 56 `=` characters (60 columns total). One blank line above, none below the title comment.
- Every variable has a single-line comment immediately above it describing purpose AND phase of activation.
- Redaction placeholders use the format `your_<purpose>_here` (snake_case noun phrase). Never use `xxxxxxxx`, `CHANGEME`, or angle-bracketed `<value>` (gitleaks heuristics may treat angle-brackets as real secret markers).
- Phase 5 trade credentials are present but COMMENTED OUT — they document the env var shape without inviting accidental local-dev population.

---

## CLI Output Contract (Copywriting Contract)

Phase 0 CLI surfaces are: `uv` task invocations (`uv run pytest`, `uv run ruff check`), `alembic` commands (`alembic upgrade head`, `alembic revision`), and entrypoint startup banners. These are operator-facing — their format is locked.

### Startup banner (stdout, INFO log line, first event emitted)

```
service.startup service_name=data-platform version=0.1.0 env=production pid=1 ts=2026-05-21T10:26:24.849Z
```

In production (`ENV=production`), structlog emits JSON; in `local` it MAY emit key=value (dev convenience) controlled by a processor switch — but JSON is the authoritative format. CI tests assert the JSON form.

### Error messages (stderr, exit non-zero)

**Format:** Single line, two parts separated by `: `

```
[<service_name>] error: <one-sentence problem>. Next: <one-sentence action>.
```

**Examples:**

| Scenario | stderr line |
|----------|-------------|
| Missing required env var | `[data-platform] error: DATABASE_URL is not set. Next: set DATABASE_URL in Railway Variables or .env.local.` |
| Invalid env var value | `[data-platform] error: COMMON__LOG_LEVEL='LOUD' is not one of DEBUG/INFO/WARN/ERROR. Next: set LOG_LEVEL to a valid value.` |
| Trade-key leaked to data-platform | `[data-platform] error: trade-only env var MEXC_TRADE__TRADE_KEY is visible to data-platform. Next: remove MEXC_TRADE__* from data-platform service variables in Railway.` |
| Alembic head mismatch on startup | `[data-platform] error: database schema is behind code (head=0001, code expects 0002). Next: run 'alembic upgrade head' or check Railway deploy startCommand.` |
| TimescaleDB extension missing | `[data-platform] error: TimescaleDB extension is not installed on this database. Next: ensure the Railway Postgres service uses the timescale/timescaledb:2.18.0-pg16 image.` |

**Forbidden:**
- Multi-paragraph error messages
- Stack traces on stderr (they go to structlog via `format_exc_info` only)
- Error messages without a `Next:` action
- Emoji in CLI output
- ANSI color codes (Railway's log viewer renders them as garbage; jq and grep don't strip them)

### Exit codes (canonical mapping — locked from Phase 0)

| Code | Meaning | When |
|------|---------|------|
| `0` | Success | Normal exit; SIGTERM-driven graceful shutdown |
| `1` | Runtime error | Any unhandled exception escaping `main()` |
| `2` | Configuration validation failure | `pydantic_settings.ValidationError` at startup |
| `3` | Database schema mismatch | Alembic head vs. code expectation diverges (Phase 1+ may use; Phase 0 leaves reserved) |
| `64` | Usage error | Invalid CLI arguments (Phase 1+; Phase 0 has no custom CLI surface) |
| `137` | Killed (SIGKILL) | External — not set by app |
| `143` | Terminated (SIGTERM) | Graceful shutdown without unsaved state — Phase 0 returns `0` instead |

The 0/1/2/64 mapping follows BSD sysexits and is supported by tooling like `restartPolicyMaxRetries` semantics on Railway (which counts non-zero exits).

### Empty-state copy (operator-facing)

| Surface | When operator sees it | Copy |
|---------|----------------------|------|
| `/health` body in `starting` state | Pre-Settings-load (rare; race window <100ms) | `{"correlation_id": "...", "env": "...", "service_name": "...", "status": "starting", "ts": "...", "version": "..."}` — no human-readable "loading" string; structured only |
| `/metrics` body with no requests yet | First scrape after deploy | Metric names + `# HELP` + `# TYPE` lines visible; counters at `0`. NEVER a 404 or empty body. |
| `service_event` table on fresh DB | First operator query | Empty result set — operator runs `SELECT * FROM service_event` and gets zero rows. No seed data, no "welcome event." |
| `pytest` with no tests collected | Mistakenly empty test dir | pytest's default `no tests ran` — accept as-is; do NOT customize. |

### Destructive operations (Phase 0)

Phase 0 has exactly TWO destructive operations:

| Operation | Confirmation Mechanism | Copy |
|-----------|------------------------|------|
| `alembic downgrade base` (drops `service_event` hypertable + chunks + policies) | Manual operator command — no CLI prompt; the operator typed it deliberately | Alembic's default output is acceptable: `INFO  [alembic.runtime.migration] Will assume non-transactional DDL.` followed by `Running downgrade 0002 -> 0001, service_event hypertable + compression policy` |
| `docker compose down -v` (drops local Postgres volume) | Documented in README "destructive commands" section | README copy: "**Destructive — local data loss.** `docker compose down -v` removes the `shortfire-pg` volume. Local-only; production data is on Railway and is unaffected." |

There are NO production-destructive operations in Phase 0 — no API DELETE endpoints, no `DROP TABLE` migrations, no kill switch (the latter lands in Phase 4 per RISK-10).

---

## Tooling Compatibility (Accessibility)

The "accessibility" axis for a machine-readable contract is: can the standard tooling chain consume our output without custom adapters? Phase 0 is verified compatible with:

| Tool | Verification | Phase 0 gate |
|------|--------------|--------------|
| `jq` | `curl -s :8000/health \| jq -r '.correlation_id'` returns the UUID | Integration test: assert `/health` body is valid JSON parseable by `json.loads` |
| `jq` for logs | `cat logs.ndjson \| jq -c 'select(.event=="request.completed") \| {ts, path, duration_ms}'` works | NDJSON output (one event per line, no pretty-printing) |
| Prometheus scraper | `curl :8000/metrics` returns text exposition with valid `# HELP` / `# TYPE` / sample lines for every declared metric | Integration test: scrape `/metrics`, assert all 4 base metrics present even before traffic |
| Grafana JSON panel | `/health` body is a JSON object with stable key names and types | Contract column above |
| Loki / Promtail | NDJSON log format; structlog-rendered keys are flat (no nested objects in mandatory base fields) | structlog processor stack does not nest base fields |
| Sentry (Phase 5) | Unhandled exceptions in request scope include `correlation_id` in the breadcrumb so Sentry events join cleanly with Loki logs | structlog `bind_contextvars` covers this; Sentry SDK wires in Phase 5 |
| `psql` operator query | `SELECT ts, service_name, event_type, jsonb_pretty(payload) FROM service_event ORDER BY ts DESC LIMIT N` returns readable output | `payload JSONB` and stable key names guarantee this |
| Railway log viewer | Each log line is a single JSON object; multi-line tracebacks rendered as `exception` string key, NOT separate physical lines | structlog `format_exc_info` processor enforces this |

### Forbidden incompatibility introductions

- Embedding newlines inside any field value (breaks NDJSON parsing)
- Using `null` for mandatory fields (use absence semantics or a string sentinel like `"unknown"` if the field is required)
- Mixed encoding (everything UTF-8, no BOM)
- Variable-length precision on `ts` (always millisecond `.NNNZ`)

---

## Copywriting Contract

| Element | Copy / Pattern |
|---------|----------------|
| Primary "CTA" (operator-facing — there is no UI CTA in Phase 0) | `uv run pytest` — the green-test invocation is the canonical operator action for Phase 0. Documented in `README.md` Quickstart. |
| Empty `service_event` query | (DB-level) operator gets zero rows. No seeded welcome event. |
| `/health` body when settings-not-loaded (rare) | `{"status": "starting", ...}` — programmatic. No human-friendly "Service is starting up..." string. |
| Error envelope | `[<service_name>] error: <problem>. Next: <action>.` (one line, stderr, exit non-zero) |
| Destructive op (`alembic downgrade base`) | Operator types it deliberately; no CLI confirmation prompt added in Phase 0. README documents the consequence. |
| Destructive op (`docker compose down -v`) | README banner under "Local development cleanup": `**Destructive — local data loss.**` prefix. |
| Settings load success | structlog event `service.settings.loaded` with `**settings.safe_summary()` — never `repr(settings)`. |
| Secret-guard trip | `[data-platform] error: trade-only env var <name> is visible to data-platform. Next: remove MEXC_TRADE__* from data-platform service variables in Railway.` — fails-fast on startup with exit code `2`. |

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none | not applicable (no UI in Phase 0) |
| third-party | none | not applicable |

**Phase 0 has no UI registry surface.** The `dashboard` service is a placeholder FastAPI app with `/health` + `/metrics` only. The real dashboard registry (likely shadcn + Grafana embed) lands in Phase 5 and will be specified in `05-UI-SPEC.md`.

---

## Phase Boundary

| In scope (Phase 0 locks these) | Out of scope (later phases) |
|--------------------------------|------------------------------|
| `/health` JSON schema (sorted, 6 fields) | Readiness vs. liveness split (Phase 1 — adds DB ping) |
| `/metrics` Prometheus text format + 4 base metrics | Custom business metrics (Phase 1: data freshness gauges; Phase 4: signal/position metrics; Phase 5: equity/drawdown) |
| structlog NDJSON shape + base fields | Telegram alert message format (Phase 4 per OBS-01..04) |
| Event taxonomy registry (12 base events) | Grafana dashboards / JSON panel specs (Phase 5 per OBS-06) |
| `.env.example` section/comment/placeholder format | Sentry integration / breadcrumb format (Phase 5 per OBS-07) |
| CLI error format `[svc] error: ... Next: ...` | Real user-facing UI of any kind |
| Exit code mapping | Kill-switch HTTP API / Telegram commands (Phase 4) |
| Field naming convention (snake_case, reserved keys) | Visual theme / colors / typography (when a real dashboard lands) |
| Severity / log-level reservation (60/30/10 INFO/DEBUG/WARN) | Severity-tagged Telegram channels (Phase 4 per OBS-03) |

---

## Checker Sign-Off

The standard 6 design-quality dimensions do not apply to a machine-readable surface. For Phase 0, the checker validates against an adapted set:

- [ ] **D1 — Schema completeness:** Every `/health` response field has type + source + ordering rule documented. PASS criteria above.
- [ ] **D2 — Metric naming:** All 4 base metrics follow `shortfire_<service>_<subsystem>_<name>_<unit>` and declare type + labels.
- [ ] **D3 — Severity discipline:** Log level table assigns each level a reserved meaning; `WARN` is not for routine events.
- [ ] **D4 — Field naming consistency:** snake_case across JSON, structlog, Prometheus labels; UPPER_SNAKE for env vars with `__` for nesting.
- [ ] **D5 — Layout/ordering:** `/health` sorted alphabetical; structlog renders ts/level/event first; `.env.example` follows section banner format.
- [ ] **D6 — Tooling compatibility:** jq / Prometheus / Grafana / Loki / Railway log viewer / psql all consume the output without custom adapters; integration tests cover at minimum jq parse + Prometheus scrape.

**Approval:** pending

---

## Pre-Population Source Map

| Field | Source |
|-------|--------|
| 3-service topology (`data-platform` / `strategy-engine` / `dashboard`) | CONTEXT.md D-01 |
| Same container image, 3 startCommands | CONTEXT.md D-03 |
| Pure Pydantic v2 domain types, frozen+strict | CONTEXT.md D-07, D-08 |
| tz-aware UTC timestamps everywhere | CONTEXT.md D-12, STOR-03 |
| `safe_summary()` canonical pattern | CONTEXT.md D-21 |
| 4-layer secret-scan defense (gitleaks etc.) | CONTEXT.md D-22 |
| structlog + `asgi-correlation-id` + Prometheus stack | RESEARCH.md Pattern 5, FOUND-05 |
| Field naming convention (snake_case, `__` nested env vars) | CONTEXT.md D-17, D-18 |
| `service_event` table as real long-term asset | CONTEXT.md D-28, Specific Ideas |
| Coverage gate 80% project-wide | CONTEXT.md D-33 |
| Phase 0 has NO UI / Phase 5 owns real dashboards | Orchestrator scope note + ROADMAP.md Phase 5 |
| Coinglass Hobbyist tier (~$35/mo) reconciliation | CONTEXT.md Deferred + MEMORY.md |
| `MEXC_TRADE__*` anti-leak guard | CONTEXT.md D-16, D-18 |

No user clarification was requested for this UI-SPEC — the orchestrator's scope note explicitly redirected away from typography/color/component-library questions, and every machine-readable contract field was derivable from CONTEXT.md, RESEARCH.md, and REQUIREMENTS.md (FOUND-05, OBS-05).
