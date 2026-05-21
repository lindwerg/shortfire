---
phase: 00-foundation
plan: 07
subsystem: infrastructure
tags: [railway, docker, deploy, timescaledb, infrastructure]

# Dependency graph
requires:
  - phase: 00-03
    provides: DataPlatformSettings, StrategyEngineSettings, DashboardSettings entrypoints
  - phase: 00-04
    provides: alembic migrations (0001, 0002) ready for preDeployCommand
  - phase: 00-05
    provides: 3 FastAPI entrypoints with /health + /metrics — startCommand targets these

provides:
  - "Dockerfile: multistage Python 3.12-slim image (deps -> runtime), non-root UID 1000"
  - ".dockerignore: excludes .env*, tests/, .planning/, .venv, __pycache__, .git"
  - "railway.toml: [build] builder=DOCKERFILE, no watchPatterns; [deploy] preDeployCommand for alembic, healthcheckPath=/health, restartPolicyType=ON_FAILURE"
  - "Static unit tests: test_railway_toml.py (8 assertions) + test_dockerfile_image.py (12 assertions)"

affects:
  - 00-08  # CI workflow pushes to main -> Railway auto-deploys

# Tech tracking
tech-stack:
  added:
    - "Dockerfile multistage build (deps stage + runtime stage, Python 3.12-slim)"
    - "uv sync --locked --no-dev (production-only deps)"
    - "railway.toml config-as-code (docs.railway.com/reference/config-as-code)"
  patterns:
    - "preDeployCommand = [\"uv\", \"run\", \"alembic\", \"upgrade\", \"head\"] — migration runs before Railway routes traffic (RESEARCH Open Q1)"
    - "Single Dockerfile, per-service startCommand override in Railway dashboard (D-03)"
    - "sleepApplication=true on strategy-engine + dashboard in dashboard; data-platform always-on (D-04)"
    - "DATABASE_URL = ${{Postgres.DATABASE_URL}} reference variable wired in dashboard (D-24)"

key-files:
  created:
    - Dockerfile
    - .dockerignore
    - railway.toml
    - tests/unit/repo_hygiene/test_railway_toml.py
    - tests/unit/repo_hygiene/test_dockerfile_image.py
  modified: []

key-decisions:
  - "preDeployCommand uses array form [\"uv\", \"run\", \"alembic\", \"upgrade\", \"head\"] — TOML array form avoids shell-quoting ambiguity"
  - "railway.toml $schema key quoted as '\"$schema\"' — TOML requires quoting keys that contain dollar sign"
  - "No watchPatterns in Phase 0 (D-05) — every push redeploys all 3 services; regression guard test asserts absence"

requirements:
  - FOUND-01
  - FOUND-02
  - OPS-01
  - OPS-02
  - OPS-03
  - OPS-07

# Metrics
duration: ~5min (Task 1 only; Task 2 human-action checkpoint pending)
completed: 2026-05-21
---

# Phase 0 Plan 07: Railway Deployment Config Summary

**Multi-stage Dockerfile (Python 3.12-slim, non-root) + .dockerignore + railway.toml (preDeployCommand for alembic, no watchPatterns) + 24 static-shape unit tests — paused at human-action checkpoint for Railway dashboard provisioning.**

## Status

Task 1 (static config + unit tests): **COMPLETE** — commit `7312bea`
Task 2 (Railway dashboard provisioning): **AWAITING HUMAN ACTION** — checkpoint below

## Performance

- **Duration:** ~5 min (Task 1)
- **Started:** 2026-05-21T13:17:00Z
- **Completed (Task 1):** 2026-05-21T13:22:50Z
- **Tasks:** 1 complete, 1 pending (human-action)
- **Files created:** 5

## Accomplishments (Task 1)

### Dockerfile

Multi-stage build with clear cache-friendly layering:

1. **`base`** — Python 3.12-slim with uv environment variables set
2. **`deps`** — installs uv, copies `pyproject.toml` + `uv.lock`, runs `uv sync --locked --no-dev` (production only, T-00-01)
3. **`runtime`** — copies venv from deps stage + application source; creates non-root user `app` (UID 1000, T-00-01); exposes port 8000; default CMD targets `shortfire.entrypoints.data_platform:app` (D-03)

Key security properties:
- No `.env*` files copied into image
- Dev dependencies excluded (`--no-dev`)
- Runs as UID 1000, not root

### .dockerignore

Excludes from build context (keeps image slim and secrets-safe):
- `.env`, `.env.local`, `.env.*.local` — secret files (T-00-01)
- `tests/`, `.pytest_cache/`, `.coverage` — test infrastructure
- `.planning/`, `.claude/` — dev metadata
- `.venv/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/` — dev caches
- `.git/`, `.github/` — version metadata
- `docker-compose.yml`, `.pre-commit-config.yaml` — dev tooling

### railway.toml

```toml
"$schema" = "https://railway.com/railway.schema.json"

[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
preDeployCommand = ["uv", "run", "alembic", "upgrade", "head"]
startCommand = "uvicorn shortfire.entrypoints.data_platform:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
healthcheckTimeout = 60
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5
```

Key facts:
- `watchPatterns` intentionally ABSENT (D-05 — every push redeploys all 3 services)
- `preDeployCommand` uses array form to avoid shell quoting ambiguity
- `sleepApplication` NOT set here — data-platform is always-on; strategy-engine and dashboard set it to `true` in the Railway dashboard (D-04)

Per-service Railway dashboard overrides needed (documented in railway.toml comments):
- **strategy-engine**: `startCommand = "uvicorn shortfire.entrypoints.strategy_engine:app --host 0.0.0.0 --port $PORT"`, `sleepApplication = true`
- **dashboard**: `startCommand = "uvicorn shortfire.entrypoints.dashboard:app --host 0.0.0.0 --port $PORT"`, `sleepApplication = true`
- **All 3 services**: `DATABASE_URL = ${{Postgres.DATABASE_URL}}`, `ENV = production`, `LOG_LEVEL = INFO`
- **strategy-engine + dashboard**: preDeployCommand = "" (empty — no migrations from these services)

### Unit Tests (24 passing)

`tests/unit/repo_hygiene/test_railway_toml.py` (8 tests):
- `railway.toml` exists
- `[build].builder == "DOCKERFILE"`
- `[build].dockerfilePath == "Dockerfile"`
- `"watchPatterns" not in [build]` (D-05 regression guard)
- `[deploy].preDeployCommand` contains `alembic upgrade head`
- `[deploy].startCommand` references `shortfire.entrypoints.data_platform`
- `[deploy].healthcheckPath == "/health"`
- `[deploy].restartPolicyType == "ON_FAILURE"`, `restartPolicyMaxRetries == 5`

`tests/unit/repo_hygiene/test_dockerfile_image.py` (12 tests):
- Dockerfile exists; contains `FROM python:3.12-slim`, `USER app`, `EXPOSE 8000`, `uv sync --locked --no-dev`, `shortfire.entrypoints.data_platform:app`; no COPY of `.env*` files
- `.dockerignore` exists; excludes `.env`, `.env.local`, `tests`, `.planning`, `.venv`, `__pycache__`, `.git`

## Task Commits

1. **Task 1** - `7312bea` — `feat(00-07): Dockerfile + .dockerignore + railway.toml + static-shape tests`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] railway.toml $schema key requires quoting**
- **Found during:** Task 1 verification (tomllib.TOMLDecodeError on line 1)
- **Issue:** The plan specified `$schema = "..."` but TOML treats `$` as invalid in bare keys; tomllib raised `Invalid statement` on parse.
- **Fix:** Quoted the key: `"$schema" = "https://railway.com/railway.schema.json"`
- **Files modified:** `railway.toml`
- **Commit:** `7312bea`

**2. [Rule 1 - Bug] ruff SIM108: if/else block in test replaced with ternary**
- **Found during:** Task 1 pre-commit hook (ruff lint)
- **Issue:** `if isinstance(cmd, list): cmd_str = ...; else: cmd_str = ...` triggered SIM108.
- **Fix:** Replaced with ternary: `cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd`
- **Files modified:** `tests/unit/repo_hygiene/test_railway_toml.py`
- **Commit:** `7312bea`

## Pending: Task 2 — Railway Dashboard Provisioning

**Status: AWAITING HUMAN ACTION (checkpoint:human-action)**

The Railway dashboard provisioning steps are manually performed by the user. The user has confirmed readiness. See checkpoint details in the completion format below.

**Railway service URLs:** Not yet provisioned — will be added here once Task 2 completes.

**Captured /health responses:** Not yet available — will be added after first deploy.

**preDeployCommand in Railway dashboard:** To confirm — should read `uv run alembic upgrade head` on the data-platform service Settings → Deploy panel.

**Cold-start time on strategy-engine + dashboard:** Expected ~2-3s per Pitfall 4 (first inbound request wakes sleeping service); to be measured after provisioning.

## Open Follow-up: Post-00-08 Status Check Requirement (OPS-01 partial)

**This is a queued open item — do NOT complete during Plan 00-07 execution.**

After Plan 00-08 ships its `.github/workflows/ci.yml` AND a PR has run the `test` workflow green at least once:

1. Go to: GitHub repo → Settings → Branches → Edit rule for `main`
2. Enable: "Require status checks to pass before merging"
3. Add: `test` (the job name from Plan 00-08's `ci.yml`)
4. Enable: "Require branches to be up to date before merging"
5. Save the rule

Until this step is done, OPS-01 is partially satisfied (basic protection: PR review + linear history + block force-push + Push Protection + Secret Scanning). Full OPS-01 is achieved only after the status-check requirement is added.

Cross-reference: 00-08-SUMMARY.md should also note this as an open follow-up.

## Known Stubs

None — all static config is complete. Railway service URLs and /health response captures are deferred to Task 2 completion (human-action checkpoint).

## Threat Flags

None. All T-00-01, T-00-02, T-00-04, T-00-05, T-00-09 mitigations from the threat register are applied:
- T-00-01: `.dockerignore` excludes `.env*`; `USER app` (UID 1000); `--no-dev` in image build
- T-00-09: `preDeployCommand` separates migration concern from `startCommand`; future replica-scaling safe

## Self-Check: PASSED

- `Dockerfile` exists: FOUND
- `.dockerignore` exists: FOUND
- `railway.toml` exists: FOUND
- `tests/unit/repo_hygiene/test_railway_toml.py` exists: FOUND
- `tests/unit/repo_hygiene/test_dockerfile_image.py` exists: FOUND
- Commit `7312bea` exists: FOUND (`git log --oneline | grep 7312bea`)
- 24 new tests pass: CONFIRMED (24 passed in 0.03s)
- Full suite 233 passed: CONFIRMED
