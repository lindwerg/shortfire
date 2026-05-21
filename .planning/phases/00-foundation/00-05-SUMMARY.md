---
phase: 00-foundation
plan: 05
subsystem: observability
tags: [python, fastapi, structlog, prometheus, asgi-correlation-id, ndjson, metrics, middleware]

# Dependency graph
requires:
  - phase: 00-01
    provides: pyproject.toml with structlog, prometheus-client, asgi-correlation-id, orjson deps
  - phase: 00-03
    provides: DataPlatformSettings, StrategyEngineSettings, DashboardSettings with safe_summary(); assert_no_trade_env_leaked()
provides:
  - "structlog NDJSON pipeline: configure_logging() with merge_contextvars FIRST (Pitfall 2 mitigated)"
  - "asgi-correlation-id middleware: install_correlation_middleware(app)"
  - "Prometheus custom CollectorRegistry (NOT default global): REGISTRY, 4 base metrics, install_metrics_endpoint(app)"
  - "Event taxonomy: EVENTS frozenset of 12 strings + assert_event_registered() guard"
  - "3 FastAPI entrypoints: data_platform, strategy_engine, dashboard with /health + /metrics"
  - "D-16 anti-leak guard enforced in data_platform entrypoint"
affects:
  - 00-06
  - 00-07
  - 00-08

# Tech tracking
tech-stack:
  added:
    - structlog (NDJSON logging pipeline with contextvars, merge_contextvars first)
    - asgi-correlation-id (UUID4 per-request correlation ID middleware)
    - prometheus-client (custom CollectorRegistry, 4 base metrics per service)
    - orjson (fast JSON serialization with OPT_SORT_KEYS for /health)
  patterns:
    - "Processor chain order: merge_contextvars → add_correlation_id → add_log_level → TimeStamper(key='ts') → StackInfoRenderer → format_exc_info → JSONRenderer"
    - "Per-service metric factory: build_metrics_for_service(name) → ServiceMetrics NamedTuple (idempotent via _metrics_cache)"
    - "Entrypoint pattern: Settings at module load → anti-leak guard → configure_logging → bind_contextvars → build_metrics → lifespan → app"
    - "/health: single datetime.now(UTC) call, ts derived from that one value, orjson.OPT_SORT_KEYS for alphabetical ordering"
    - "Event taxonomy: frozenset of 12 strings; assert_event_registered() throws ValueError on unknown events"

key-files:
  created:
    - src/shortfire/observability/logging.py
    - src/shortfire/observability/middleware.py
    - src/shortfire/observability/metrics.py
    - src/shortfire/observability/events.py
    - src/shortfire/entrypoints/data_platform.py
    - src/shortfire/entrypoints/strategy_engine.py
    - src/shortfire/entrypoints/dashboard.py
    - tests/unit/observability/__init__.py
    - tests/unit/observability/test_logging.py
    - tests/unit/observability/test_metrics.py
    - tests/unit/observability/test_event_taxonomy.py
    - tests/unit/observability/test_health.py
  modified:
    - src/shortfire/observability/__init__.py

key-decisions:
  - "PrintLoggerFactory not LoggerFactory: structlog.stdlib.LoggerFactory routes through Python stdlib adding 'INFO:name:' prefix, making JSON unparseable. PrintLoggerFactory writes directly to stdout with no prefix."
  - "Metrics idempotency cache: build_metrics_for_service uses _metrics_cache to avoid ValueError on re-import during tests (REGISTRY is a module-level singleton that persists across re-imports)"
  - "Content-Type hardcoded to text/plain; version=0.0.4; charset=utf-8: prometheus-client 0.25.0 changed CONTENT_TYPE_LATEST to 1.0.0 (OpenMetrics), but UI-SPEC locks the header to 0.0.4 for Prometheus scraper compatibility"
  - "correlation_id test accepts 32-char hex: asgi-correlation-id generates UUID4 as compact 32-char hex (no dashes) by default, not the dashed format"

patterns-established:
  - "Entrypoint wiring order: Settings() → assert_no_trade_env_leaked() → configure_logging() → bind_contextvars() → build_metrics() → lifespan() → app = FastAPI() → install_correlation_middleware() → install_metrics_endpoint() → @app.get('/health')"
  - "Single datetime.now(UTC) per /health handler: ts is derived entirely from one captured `now` variable to prevent millisecond-boundary mismatch"
  - "safe_summary() only: Settings are always logged via settings.safe_summary() never repr(settings) (D-21)"

requirements-completed:
  - FOUND-05
  - FOUND-07
  - OPS-04
  - OPS-07

# Metrics
duration: ~45min
completed: 2026-05-21
---

# Phase 0 Plan 05: Observability Skeleton + 3 FastAPI Entrypoints Summary

**structlog NDJSON pipeline (merge_contextvars first, Pitfall 2 mitigated) + asgi-correlation-id + Prometheus custom CollectorRegistry (4 base metrics per service) + 3 FastAPI entrypoints with /health (single-now, sorted keys) and /metrics**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-05-21T12:00:00Z
- **Completed:** 2026-05-21T12:50:12Z
- **Tasks:** 2 (TDD: 4 commits total — 2 RED + 2 GREEN)
- **Files modified:** 13

## Accomplishments

- structlog NDJSON pipeline with `merge_contextvars` as FIRST processor (Pitfall 2: async correlation-id propagation across asyncio.create_task boundaries)
- 12-event taxonomy frozenset in `events.py` with `assert_event_registered()` guard preventing free-form event names
- Prometheus custom `CollectorRegistry` (isolated from default global; avoids process metrics leakage) with per-service factory returning 4 base metrics: `shortfire_<svc>_http_requests_total`, `shortfire_<svc>_http_request_duration_seconds` (locked bucket list), `shortfire_<svc>_service_event_emitted_total`, `shortfire_<svc>_build_info`
- 3 FastAPI entrypoints (`data_platform`, `strategy_engine`, `dashboard`) — each instantiates its specific Settings class at module load, binds service-wide contextvars, mounts middleware + /health + /metrics, and emits `service.startup` + `service.settings.loaded` events during lifespan
- `data_platform` entrypoint calls `assert_no_trade_env_leaked()` immediately after Settings load (D-16); crashes loudly if MEXC_TRADE__* env vars are present
- `/health` returns 6-field JSON with `orjson.OPT_SORT_KEYS` alphabetical ordering; `ts` derived from a single `datetime.now(UTC)` call (no millisecond-boundary mismatch risk)

## Structlog Processor Chain Order

Final chain in `configure_logging()`:
```
1. structlog.contextvars.merge_contextvars  ← MUST BE FIRST (Pitfall 2)
2. add_correlation_id                        ← pulls asgi-correlation-id contextvar
3. structlog.stdlib.add_log_level            ← adds `level` key (lowercase)
4. TimeStamper(fmt="iso", utc=True, key="ts") ← UI-SPEC §Log Event Schema: key="ts"
5. structlog.processors.StackInfoRenderer()
6. structlog.processors.format_exc_info
7. structlog.processors.JSONRenderer()       ← MUST BE LAST
```
`logger_factory=structlog.PrintLoggerFactory()` — writes directly to stdout (no stdlib prefix).

## Example /health Response

```json
{
  "correlation_id": "e4e7e900456f44d2a0987ab5796f21d9",
  "env": "ci",
  "service_name": "data-platform",
  "status": "ok",
  "ts": "2026-05-21T12:45:33.042Z",
  "version": "0.1.0"
}
```
Keys are alphabetically sorted (enforced by `orjson.OPT_SORT_KEYS`).

## 4 Base Prometheus Metrics for data-platform

From `GET /metrics` (classic text exposition format v0.0.4):
```
# HELP shortfire_data_platform_http_requests_total HTTP request count by method, path, and status code
# TYPE shortfire_data_platform_http_requests_total counter
# HELP shortfire_data_platform_http_request_duration_seconds HTTP request latency in seconds
# TYPE shortfire_data_platform_http_request_duration_seconds histogram
# HELP shortfire_data_platform_service_event_emitted_total Count of service_event table rows written, by event_type
# TYPE shortfire_data_platform_service_event_emitted_total counter
# HELP shortfire_data_platform_build_info Build metadata gauge (always 1) — join version/commit/env into PromQL
# TYPE shortfire_data_platform_build_info gauge
```

## Single datetime.now() Verification

`grep -nE "datetime\.now\(" src/shortfire/entrypoints/*.py` reports exactly one call per `health()` function body across all 3 entrypoints. Test 8 (`test_data_platform_health_ts_uses_single_now_call`) asserts ms-precision format is correct, confirming the pattern.

Note: actual Railway `startCommand` wiring (pointing uvicorn at each entrypoint) lives in Plan 00-07.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing observability tests** - `19cc89f` (test)
2. **Task 1 GREEN: Observability primitives** - `b014b09` (feat)
3. **Task 2 RED: Failing entrypoint tests** - `9514b50` (test)
4. **Task 2 GREEN: 3 FastAPI entrypoints** - `981bc83` (feat)

## Files Created/Modified

- `src/shortfire/observability/logging.py` — configure_logging() + add_correlation_id processor
- `src/shortfire/observability/middleware.py` — install_correlation_middleware(app)
- `src/shortfire/observability/metrics.py` — REGISTRY, ServiceMetrics, build_metrics_for_service(), install_metrics_endpoint()
- `src/shortfire/observability/events.py` — EVENTS frozenset (12 strings) + assert_event_registered()
- `src/shortfire/observability/__init__.py` — re-exports all observability symbols
- `src/shortfire/entrypoints/data_platform.py` — FastAPI app for data-platform (with D-16 guard)
- `src/shortfire/entrypoints/strategy_engine.py` — FastAPI app for strategy-engine
- `src/shortfire/entrypoints/dashboard.py` — FastAPI app for dashboard
- `tests/unit/observability/__init__.py` — package marker
- `tests/unit/observability/test_logging.py` — 4 structlog tests
- `tests/unit/observability/test_metrics.py` — 7 Prometheus tests
- `tests/unit/observability/test_event_taxonomy.py` — 8 event taxonomy tests
- `tests/unit/observability/test_health.py` — 19 entrypoint tests (3 apps × /health + /metrics + anti-leak + lifespan)

## Decisions Made

- `PrintLoggerFactory` not `LoggerFactory`: stdlib `LoggerFactory` routes through Python stdlib and adds `INFO:name:message` prefix, making JSON unparseable. `PrintLoggerFactory` writes directly to stdout with no prefix — required for NDJSON output.
- Metrics idempotency cache (`_metrics_cache`): `build_metrics_for_service()` is called at module load in each entrypoint. In tests, `_fresh_app()` re-imports the module while `REGISTRY` (module-level singleton) persists. Without the cache, the second import raises `ValueError: Duplicated timeseries`. The cache returns the existing `ServiceMetrics` on subsequent calls with the same service name.
- Content-Type hardcoded to `text/plain; version=0.0.4; charset=utf-8`: `prometheus-client 0.25.0` changed `CONTENT_TYPE_LATEST` to `version=1.0.0` (OpenMetrics format). UI-SPEC locks the content type to `0.0.4` for Prometheus scraper compatibility. We override `CONTENT_TYPE_LATEST` with the spec-mandated value.
- `correlation_id` test accepts 32-char hex: `asgi-correlation-id` generates compact hex UUIDs (32 chars, no dashes) by default, not the canonical hyphenated form. Test relaxed to accept both.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] structlog PrintLoggerFactory instead of LoggerFactory**
- **Found during:** Task 1 GREEN (logging implementation)
- **Issue:** `structlog.stdlib.LoggerFactory()` routes through Python stdlib which adds `INFO:name:` prefix, making JSON output unparseable. Additionally, stdlib LoggerFactory requires `add_logger_name` processor which throws `AttributeError` on `PrintLogger` (no `.name` attribute).
- **Fix:** Switched to `structlog.PrintLoggerFactory()`. Removed `add_logger_name` processor entirely (not required by UI-SPEC §Log Event Schema). Changed `logging.StreamHandler()` default (stderr) to `logging.StreamHandler(sys.stdout)`.
- **Files modified:** `src/shortfire/observability/logging.py`
- **Verification:** `test_logging_mandatory_base_fields_in_output` passes — log line is parseable JSON with correct field names
- **Committed in:** `b014b09`

**2. [Rule 1 - Bug] CONTENT_TYPE_LATEST changed in prometheus-client 0.25.0**
- **Found during:** Task 2 GREEN (metrics content-type test)
- **Issue:** `CONTENT_TYPE_LATEST` now returns `text/plain; version=1.0.0; charset=utf-8` (OpenMetrics) but UI-SPEC mandates `version=0.0.4`. Test `test_data_platform_metrics_content_type` was asserting the spec value.
- **Fix:** Hardcoded `media_type="text/plain; version=0.0.4; charset=utf-8"` in `install_metrics_endpoint()`. Removed `CONTENT_TYPE_LATEST` import (now unused).
- **Files modified:** `src/shortfire/observability/metrics.py`
- **Verification:** `test_data_platform_metrics_content_type` passes
- **Committed in:** `981bc83`

**3. [Rule 1 - Bug] asgi-correlation-id generates 32-char hex without dashes**
- **Found during:** Task 2 GREEN (health field values test)
- **Issue:** Test expected standard UUID4 dashed format (`8-4-4-4-12`). Library generates compact hex without dashes (`e4e7e900456f44d2a0987ab5796f21d9`).
- **Fix:** Updated test to accept either 32-char hex OR dashed UUID4 format.
- **Files modified:** `tests/unit/observability/test_health.py`
- **Verification:** `test_data_platform_health_field_values` passes
- **Committed in:** `981bc83`

**4. [Rule 2 - Missing Critical] Metrics idempotency cache**
- **Found during:** Task 2 GREEN (entrypoint re-import in tests)
- **Issue:** `build_metrics_for_service()` called at module load in each entrypoint; `_fresh_app()` helper re-imports the module while `REGISTRY` singleton persists. Without idempotency, second import raises `ValueError: Duplicated timeseries` preventing all entrypoint tests from running.
- **Fix:** Added `_metrics_cache: dict[str, ServiceMetrics] = {}` in `metrics.py`; `build_metrics_for_service` returns cached instance on subsequent calls with same service name.
- **Files modified:** `src/shortfire/observability/metrics.py`
- **Verification:** All 19 entrypoint tests pass without ValueError
- **Committed in:** `981bc83`

---

**Total deviations:** 4 auto-fixed (2 Rule 1 bugs, 1 Rule 1 test correction, 1 Rule 2 missing critical)
**Impact on plan:** All fixes essential for correctness and spec compliance. No scope creep.

## Issues Encountered

- `add_logger_name` processor removed: incompatible with `PrintLoggerFactory` (requires `logger.name` attribute absent on `PrintLogger`). The `service_name` contextvar fulfills the same semantic role (bound via `bind_contextvars`).
- `asynccontextmanager` deprecation in pyright: `-> AsyncIterator[None]` deprecated in favor of `-> AsyncGenerator[None, None]`. Fixed in all 3 entrypoints.
- ruff `UP017`: `timezone.utc` upgraded to `datetime.UTC` alias (Python 3.11+). Fixed automatically by `ruff --fix`.

## User Setup Required

None — all functionality tested via pytest TestClient. No external services require configuration for this plan. Plan 00-07 handles Railway service wiring.

## Known Stubs

None — no placeholder data or TODO stubs. All functionality is implemented and tested.

## Threat Flags

None — all threat model mitigations from `<threat_model>` are implemented:
- T-00-08: /health locked to 6 fields only via orjson; /metrics namespaced under `shortfire_*`
- T-00-02: `assert_no_trade_env_leaked()` enforced in data_platform entrypoint
- T-00-01: `safe_summary()` used in all lifespan log calls; test verifies no SecretStr leakage
- T-00-09: `merge_contextvars` is FIRST processor; verified by `test_processor_order_merge_contextvars_first`

## Next Phase Readiness

- Plan 00-06 (DB client layer) can import `configure_logging` and `install_correlation_middleware` directly
- Plan 00-07 (Railway config) wires `uvicorn shortfire.entrypoints.data_platform:app` as startCommand — entrypoints are ready
- Plan 00-08 (InMemoryCandleRepo fakes) can use `EVENTS` from `shortfire.observability.events` for event type validation
- All 38 observability tests green; pyright + ruff clean on `src/shortfire/observability/` and `src/shortfire/entrypoints/`

---
*Phase: 00-foundation*
*Completed: 2026-05-21*
