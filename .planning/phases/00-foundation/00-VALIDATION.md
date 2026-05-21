---
phase: 0
slug: foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-21
---

# Phase 0 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + Hypothesis 6.x + pytest-asyncio 0.24 |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) — installed in Wave 1 |
| **Quick run command** | `uv run pytest -m "not integration" -q` |
| **Full suite command** | `uv run pytest --cov=src/shortfire --cov-report=term --cov-fail-under=80` |
| **Estimated runtime** | ~15s quick, ~60s full (testcontainers warm), ~90s cold |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -m "not integration" -q`
- **After every plan wave:** Run `uv run pytest --cov=src/shortfire --cov-report=term --cov-fail-under=80`
- **Before `/gsd:verify-work`:** Full suite (including `-m integration` testcontainers) must be green
- **Max feedback latency:** 90 seconds (cold testcontainers run)

---

## Per-Task Verification Map

> Filled in by planner during plan generation. One row per task. Wave 0 column references infrastructure that must exist before the row's test can run.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> Files / infrastructure that must be in place before any verification can run.

- [ ] `pyproject.toml` with `[project]`, `[dependency-groups]`, `[tool.pytest.ini_options]`, `[tool.ruff]`, `[tool.pyright]`, `[tool.coverage.run]` — installed in Wave 1
- [ ] `uv.lock` committed — produced by `uv sync` in Wave 1
- [ ] `tests/conftest.py` — shared fixtures (event loop policy, Hypothesis profile registration, testcontainers session-scoped DB fixture)
- [ ] `tests/fakes/__init__.py` + per-client fake module stubs
- [ ] `pytest-asyncio` configured with `asyncio_mode = "auto"` in `pyproject.toml`
- [ ] `Hypothesis` registered profile `ci` with `deadline=None, max_examples=200`
- [ ] `docker-compose.yml` Timescale service for local DB tests (no testcontainers needed for some unit DB tests)
- [ ] `.github/workflows/ci.yml` executes the suite in CI

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Railway auto-deploy fires on green `main` push | OPS-02, FOUND-02 | Railway is external infra; CI cannot assert deploy state without an authenticated probe | Push a no-op commit to `main`, observe Railway dashboard shows new deploy for all 3 services within 5 min, all return 200 on `/health` |
| GitHub Push Protection blocks a secret push | OPS-08, FOUND-08 | Push Protection is a GitHub-side mechanism; cannot test via local pytest | Attempt `git push` a branch containing a fake AWS key in a fixture — push must be rejected with Push Protection error |
| `sleepApplication: true` services wake on inbound request | OPS-01, OPS-03 | Railway sleep cycle is async + only triggered by inbound HTTP, not synthetic events | After 1h idle, curl `/health` on `strategy-engine` or `dashboard` — first request takes ~2-3s cold-start, returns 200 |
| GitHub Secret Scanning surfaces historical leaks | OPS-08 | GitHub-side server scan, no local equivalent | Confirm repo settings show "Secret scanning: enabled" in Security tab |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
