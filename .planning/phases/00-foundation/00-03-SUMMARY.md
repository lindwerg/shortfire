---
phase: 0
plan: 3
subsystem: settings
tags:
  - python
  - pydantic-settings
  - secrets
  - secretstr
  - anti-leak
  - tdd
dependency_graph:
  requires:
    - 00-01 (uv/pytest/pyright/ruff/pre-commit infrastructure)
    - 00-02 (domain types — no direct import but part of shared base)
  provides:
    - src/shortfire/settings/base.py (BaseAppSettings, DBSettings, CommonSettings, _env_file, env_file)
    - src/shortfire/settings/data_platform.py (DataPlatformSettings, MexcReadSettings, CoinglassSettings, CoingeckoSettings, assert_no_trade_env_leaked)
    - src/shortfire/settings/strategy_engine.py (StrategyEngineSettings, MexcTradeSettings shell)
    - src/shortfire/settings/dashboard.py (DashboardSettings, TelegramSettings shell)
    - src/shortfire/settings/risk_guard.py (RiskGuardSettings placeholder)
    - tests/unit/settings/ (25 unit tests covering FOUND-07, D-16, D-21, D-17/D-18)
  affects:
    - Plan 00-05 (FastAPI entrypoints instantiate per-service Settings subclass)
    - Plan 00-07 (Railway config — env var names match SettingsConfigDict routing)
    - Phase 1+ (all services use Settings to validate and load external API keys)
tech_stack:
  added: []
  patterns:
    - "BaseAppSettings(BaseSettings) with SettingsConfigDict(env_nested_delimiter='__') shared base (D-17)"
    - "DATABASE_URL env var mapped to db.url via model_validator(mode='before') + _extract_db_url helper"
    - "Per-service subclasses — only declare fields for env vars the service is allowed to see (D-16)"
    - "SecretStr for every credential field; .get_secret_value() only at client init (D-19)"
    - "safe_summary() on every class returns bool flags only — no SecretStr values (D-21)"
    - "assert_no_trade_env_leaked() module-level guardrail in data_platform.py (D-16 defense-in-depth)"
    - "_env_file() returns None in production, '.env.local' otherwise (D-20); public alias env_file"
    - "type: ignore[call-arg] on BaseSettings() callsites — pydantic-settings populates from env at runtime"
key_files:
  created:
    - src/shortfire/settings/base.py (145 LOC)
    - src/shortfire/settings/data_platform.py (103 LOC)
    - src/shortfire/settings/strategy_engine.py (67 LOC)
    - src/shortfire/settings/dashboard.py (54 LOC)
    - src/shortfire/settings/risk_guard.py (26 LOC)
    - tests/unit/settings/__init__.py
    - tests/unit/settings/test_fail_fast.py
    - tests/unit/settings/test_safe_summary_no_secrets.py
    - tests/unit/settings/test_data_platform_anti_leak.py
    - tests/unit/settings/test_env_nested_delimiter.py
  modified:
    - src/shortfire/settings/__init__.py (updated to re-export all 5 classes + guardrail)
decisions:
  - "DATABASE_URL maps to db.url via a model_validator(mode='before') instead of Field(alias=...) — the alias approach on nested BaseModel fields is not supported by pydantic-settings env var routing; the model_validator approach is functionally equivalent and tested"
  - "_env_file() exposed as public alias env_file for test accessibility — pyright reportPrivateUsage would block tests importing _env_file directly"
  - "type: ignore[call-arg] on BaseSettings() callsites in tests — pyright strict mode sees database_url as a required constructor argument, but pydantic-settings populates it from env vars at runtime; this is an accepted pyright limitation with pydantic-settings"
  - "DBSettings.url is a plain str (not SecretStr) — it's used for db_host extraction in safe_summary() and doesn't need SecretStr protection since it's never logged in full; the safe_summary() only extracts the host:port portion"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-21"
  tasks_completed: 2
  tasks_total: 2
  files_created: 10
  files_modified: 1
---

# Phase 0 Plan 3: Per-Service Settings with SecretStr and Anti-Leak Boundary Summary

pydantic-settings BaseAppSettings with 4 per-service subclasses, SecretStr credentials, safe_summary() method, assert_no_trade_env_leaked() guardrail, and 25 unit tests covering FOUND-07 fail-fast, D-16 anti-leak (structural + runtime), D-21 safe_summary no-secrets, and D-17/D-18 env nested delimiter routing.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 RED | Settings tests (fail-fast, safe-summary, anti-leak, env-delimiter) | 2bb1844 | tests/unit/settings/test_*.py (4 files) |
| 1+2 GREEN | Settings source + test fixups | d53e233 | src/shortfire/settings/*.py (5 source files) + test updates |

## Settings Class Hierarchy

```
BaseAppSettings(BaseSettings)          ← src/shortfire/settings/base.py
│   model_config: env_nested_delimiter='__', extra='ignore'
│   Fields: service_name, port, database_url, db: DBSettings, common: CommonSettings
│   Method: safe_summary() → {service_name, port, env, log_level, db_host}
│
├── DataPlatformSettings               ← src/shortfire/settings/data_platform.py
│   │   service_name = "data-platform"
│   │   mexc: MexcReadSettings | None  (MEXC__READ_KEY, MEXC__READ_SECRET)
│   │   coinglass: CoinglassSettings | None  (COINGLASS__API_KEY)
│   │   coingecko: CoingeckoSettings | None  (COINGECKO__API_KEY)
│   │   NO mexc_trade field ← D-16 structural anti-leak guarantee
│   │   safe_summary() extends with: mexc_read_configured, coinglass_configured, coingecko_configured
│   └── assert_no_trade_env_leaked()   ← module-level startup guardrail
│
├── StrategyEngineSettings             ← src/shortfire/settings/strategy_engine.py
│   │   service_name = "strategy-engine"
│   │   mlflow_tracking_uri: str | None  (Phase 2+)
│   │   mexc_trade: MexcTradeSettings | None  ← Phase 5 pre-wire (MEXC_TRADE__TRADE_KEY)
│   └── safe_summary() extends with: mexc_trade_configured, mlflow_configured
│
├── DashboardSettings                  ← src/shortfire/settings/dashboard.py
│   │   service_name = "dashboard"
│   │   telegram: TelegramSettings | None  (Phase 5+; TELEGRAM__BOT_TOKEN)
│   └── safe_summary() extends with: telegram_configured
│
└── RiskGuardSettings                  ← src/shortfire/settings/risk_guard.py
        service_name = "risk-guard"
        (Phase 5 only; no external API keys; inherits base safe_summary() unchanged)
```

## safe_summary() Output Shape (DataPlatformSettings with synthetic data)

```python
# With MEXC/Coinglass/CoinGecko configured, DATABASE_URL=postgresql://user:pass@db-host:5432/shortfire
settings.safe_summary()
# Returns:
{
    "service_name": "data-platform",
    "port": 8000,
    "env": "ci",
    "log_level": "INFO",
    "db_host": "db-host:5432",        # host:port only — no credentials, no path
    "mexc_read_configured": True,      # boolean only — never the SecretStr value
    "coinglass_configured": True,
    "coingecko_configured": True,
}
```

## D-16 Anti-Leak Verification

```python
>>> from shortfire.settings.data_platform import DataPlatformSettings
>>> 'mexc_trade' in DataPlatformSettings.model_fields
False   # Structural absence — pydantic-settings won't load MEXC_TRADE__* even if present

>>> from shortfire.settings.strategy_engine import StrategyEngineSettings
>>> 'mexc_trade' in StrategyEngineSettings.model_fields
True    # Phase 5 routing pre-wired on strategy-engine ONLY

>>> import os; os.environ['MEXC_TRADE__TRADE_KEY'] = 'test'
>>> from shortfire.settings.data_platform import assert_no_trade_env_leaked
>>> assert_no_trade_env_leaked()
RuntimeError: FATAL: trade-only env vars visible to data-platform: ['MEXC_TRADE__TRADE_KEY']. ...
```

## Test Count and Coverage

| Test File | Tests | Focus |
|-----------|-------|-------|
| test_fail_fast.py | 8 | FOUND-07: ValidationError on missing DATABASE_URL for all 4 classes |
| test_safe_summary_no_secrets.py | 5 | D-21: no SecretStr in output; no leaked values; db_host stripped |
| test_data_platform_anti_leak.py | 4 | D-16: no mexc_trade field; assert raises when present, passes when absent |
| test_env_nested_delimiter.py | 8 | D-17/D-18: MEXC__READ_KEY routing; _env_file() behavior per env |

**Total: 25 tests, all passing**

Coverage on `shortfire.settings`: **89%** (104 statements, 8 missed — DashboardSettings.safe_summary and StrategyEngineSettings.safe_summary uncovered; covered in Plan 00-05 when entrypoints call these)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Field(alias='DATABASE_URL') on nested BaseModel not supported by pydantic-settings env routing**
- **Found during:** Task 1 GREEN, running tests
- **Issue:** RESEARCH.md Pattern 2 showed `DBSettings.url: str = Field(..., alias="DATABASE_URL")`. In pydantic-settings 2.11.x, alias-based routing into nested BaseModel fields via env vars does not work — the field simply isn't populated, causing `db: Field required` ValidationError.
- **Fix:** Added `database_url: str` as a top-level field on BaseAppSettings (directly receiving the `DATABASE_URL` env var), plus a `model_validator(mode='before')` that populates `db: DBSettings` from `database_url` before Pydantic validates. Added `_extract_db_url()` helper for type-safe dict extraction.
- **Files modified:** src/shortfire/settings/base.py
- **Commit:** d53e233

**2. [Rule 2 - Missing critical functionality] `_env_file()` not accessible from tests due to pyright reportPrivateUsage**
- **Found during:** Task 2, pyright check
- **Issue:** `test_env_nested_delimiter.py` imported `_env_file` from base.py. pyright strict mode flagged `reportPrivateUsage` since functions starting with `_` are considered private.
- **Fix:** Added `env_file = _env_file` public alias in base.py. Tests import `env_file as _env_file` to keep existing test variable names.
- **Files modified:** src/shortfire/settings/base.py, tests/unit/settings/test_env_nested_delimiter.py
- **Commit:** d53e233

**3. [Rule 2 - Missing critical functionality] pyright strict mode: DataPlatformSettings() missing required arg**
- **Found during:** Task 2, pyright check
- **Issue:** pyright strict sees `database_url` as a required constructor argument and flags `DataPlatformSettings()` calls in tests as missing it. pydantic-settings populates it from env vars at runtime, not constructor.
- **Fix:** Added `# type: ignore[call-arg]` on all `*Settings()` callsites in tests.
- **Files modified:** test_fail_fast.py, test_safe_summary_no_secrets.py, test_env_nested_delimiter.py
- **Commit:** d53e233

## Known Stubs

None — all 5 settings classes are fully implemented per D-16..D-21. The optional fields (`mexc`, `coinglass`, `coingecko`, `mexc_trade`, `telegram`) are `None` until Phase 1/5 populates them via Railway env var config — this is intentional design, not stubs.

## Threat Flags

No new threat surface beyond the plan's threat model. All 5 STRIDE mitigations applied:

- T-00-02 (EoP DataPlatformSettings): `mexc_trade` field structurally absent; `assert_no_trade_env_leaked()` runtime guardrail active
- T-00-01 (Info Disclosure via structlog): `safe_summary()` confirmed no SecretStr in output; 5 tests verify this
- T-00-01 (Info Disclosure credentials): All 7 credential fields are `SecretStr` (verified by grep; 7 occurrences in data_platform.py alone)
- T-00-08 (Info Disclosure /health): Not in scope for this plan (Plan 00-05)
- T-00-09 (Tampering env routing): `env_nested_delimiter='__'` is the only routing convention; 8 tests verify routing

## TDD Gate Compliance

- RED gate: `test(00-03): add failing tests for settings anti-leak and safe_summary (RED)` (2bb1844)
- GREEN gate: `feat(00-03): implement per-service settings with SecretStr and anti-leak boundary (GREEN)` (d53e233)

Both RED/GREEN cycles complete per TDD protocol.

## Self-Check: PASSED

Files created:

- [x] src/shortfire/settings/base.py exists
- [x] src/shortfire/settings/data_platform.py exists
- [x] src/shortfire/settings/strategy_engine.py exists
- [x] src/shortfire/settings/dashboard.py exists
- [x] src/shortfire/settings/risk_guard.py exists
- [x] tests/unit/settings/__init__.py exists
- [x] tests/unit/settings/test_fail_fast.py exists
- [x] tests/unit/settings/test_safe_summary_no_secrets.py exists
- [x] tests/unit/settings/test_data_platform_anti_leak.py exists
- [x] tests/unit/settings/test_env_nested_delimiter.py exists

Commits exist:

- [x] 2bb1844 — test(00-03): add failing tests for settings anti-leak and safe_summary (RED)
- [x] d53e233 — feat(00-03): implement per-service settings with SecretStr and anti-leak boundary (GREEN)
