"""Repo hygiene tests — verifies railway.toml static shape.

These tests act as a regression guard: if someone accidentally adds watchPatterns
(D-05 violation), removes the preDeployCommand (OPS-07 regression), or changes
the healthcheck path, the CI run catches it immediately.

References:
  - RESEARCH.md §Pattern 4 (Railway 3-service shape)
  - RESEARCH.md Open Question 1 (preDeployCommand recommendation)
  - CONTEXT.md D-05 (no watchPatterns in Phase 0)
  - CONTEXT.md D-34 (CI gate + auto-deploy)
"""

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).parent.parent.parent.parent
RAILWAY_TOML = ROOT / "railway.toml"
RAILWAY_STRATEGY_ENGINE_TOML = ROOT / "railway.strategy-engine.toml"
RAILWAY_DASHBOARD_TOML = ROOT / "railway.dashboard.toml"


def _load() -> dict:
    with RAILWAY_TOML.open("rb") as fh:
        return tomllib.load(fh)


def _load_path(path: pathlib.Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def test_strategy_engine_toml_exists() -> None:
    assert RAILWAY_STRATEGY_ENGINE_TOML.exists(), (
        "railway.strategy-engine.toml missing — required for strategy-engine config-as-code"
    )


def test_dashboard_toml_exists() -> None:
    assert RAILWAY_DASHBOARD_TOML.exists(), (
        "railway.dashboard.toml missing — required for dashboard config-as-code"
    )


def test_strategy_engine_start_command_references_correct_entrypoint() -> None:
    doc = _load_path(RAILWAY_STRATEGY_ENGINE_TOML)
    start_cmd = doc["deploy"]["startCommand"]
    expected = "shortfire.entrypoints.strategy_engine"
    assert expected in start_cmd, f"strategy-engine startCommand must reference {expected}, got {start_cmd!r}"


def test_dashboard_start_command_references_correct_entrypoint() -> None:
    doc = _load_path(RAILWAY_DASHBOARD_TOML)
    start_cmd = doc["deploy"]["startCommand"]
    assert "shortfire.entrypoints.dashboard" in start_cmd, (
        f"dashboard startCommand must reference shortfire.entrypoints.dashboard, got {start_cmd!r}"
    )


def test_strategy_engine_sleeps_when_idle() -> None:
    """D-04: strategy-engine is sleep-when-idle in Phase 0."""
    doc = _load_path(RAILWAY_STRATEGY_ENGINE_TOML)
    assert doc["deploy"].get("sleepApplication") is True, (
        "strategy-engine sleepApplication must be true (D-04)"
    )


def test_dashboard_sleeps_when_idle() -> None:
    """D-04: dashboard is sleep-when-idle in Phase 0."""
    doc = _load_path(RAILWAY_DASHBOARD_TOML)
    assert doc["deploy"].get("sleepApplication") is True, "dashboard sleepApplication must be true (D-04)"


def test_strategy_engine_has_no_predeploy_command() -> None:
    """Only data-platform runs alembic migrations; strategy-engine must NOT.

    Two services racing on `alembic upgrade head` is a known TimescaleDB foot-gun
    (advisory lock contention).
    """
    doc = _load_path(RAILWAY_STRATEGY_ENGINE_TOML)
    assert "preDeployCommand" not in doc["deploy"], (
        "strategy-engine must not set preDeployCommand — only data-platform runs migrations"
    )


def test_dashboard_has_no_predeploy_command() -> None:
    """Only data-platform runs alembic migrations; dashboard must NOT."""
    doc = _load_path(RAILWAY_DASHBOARD_TOML)
    assert "preDeployCommand" not in doc["deploy"], (
        "dashboard must not set preDeployCommand — only data-platform runs migrations"
    )


def test_railway_toml_exists() -> None:
    assert RAILWAY_TOML.exists(), "railway.toml missing — required for Railway deploy config"


def test_build_builder_is_dockerfile() -> None:
    """[build].builder must be DOCKERFILE (D-03 — single image for all 3 services)."""
    doc = _load()
    assert doc["build"]["builder"] == "DOCKERFILE", (
        f"[build].builder must be 'DOCKERFILE', got {doc['build'].get('builder')!r}"
    )


def test_build_dockerfile_path() -> None:
    """[build].dockerfilePath must point to the root Dockerfile (D-03)."""
    doc = _load()
    assert doc["build"]["dockerfilePath"] == "Dockerfile", (
        f"[build].dockerfilePath must be 'Dockerfile', got {doc['build'].get('dockerfilePath')!r}"
    )


def test_no_watch_patterns_in_build() -> None:
    """D-05: watchPatterns MUST NOT be present in Phase 0.

    Every commit must redeploy all 3 services to match the PROJECT.md
    'commit → push → deploy after every task' discipline.
    """
    doc = _load()
    assert "watchPatterns" not in doc.get("build", {}), (
        "D-05 violation: watchPatterns found in [build]. "
        "Remove watchPatterns — every commit must redeploy all services in Phase 0."
    )


def test_predeploy_command() -> None:
    """[deploy].preDeployCommand must run alembic upgrade head (OPS-07, RESEARCH.md Open Question 1).

    Using preDeployCommand (not baking into startCommand) ensures Railway waits
    for the migration to succeed before routing traffic to the new replica.
    """
    doc = _load()
    cmd = doc["deploy"]["preDeployCommand"]
    # Accept either the array form ["uv", "run", "alembic", "upgrade", "head"]
    # or the string form "uv run alembic upgrade head"
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    assert "alembic" in cmd_str, f"[deploy].preDeployCommand must invoke alembic, got {cmd!r}"
    assert "upgrade" in cmd_str, f"[deploy].preDeployCommand must include 'upgrade', got {cmd!r}"
    assert "head" in cmd_str, f"[deploy].preDeployCommand must include 'head', got {cmd!r}"


def test_start_command_references_data_platform_entrypoint() -> None:
    """[deploy].startCommand must invoke the data_platform entrypoint (D-03).

    This is the data-platform service default. strategy-engine and dashboard
    override this in the Railway dashboard.
    """
    doc = _load()
    start_cmd = doc["deploy"]["startCommand"]
    assert "shortfire.entrypoints.data_platform" in start_cmd, (
        f"[deploy].startCommand must reference shortfire.entrypoints.data_platform, got {start_cmd!r}"
    )
    assert "uvicorn" in start_cmd, f"[deploy].startCommand must invoke uvicorn, got {start_cmd!r}"


def test_healthcheck_path() -> None:
    """[deploy].healthcheckPath must be '/health' (UI-SPEC §GET /health)."""
    doc = _load()
    assert doc["deploy"]["healthcheckPath"] == "/health", (
        f"[deploy].healthcheckPath must be '/health', got {doc['deploy'].get('healthcheckPath')!r}"
    )


def test_restart_policy_type() -> None:
    """[deploy].restartPolicyType must be ON_FAILURE (crash-loop protection)."""
    doc = _load()
    assert doc["deploy"]["restartPolicyType"] == "ON_FAILURE", (
        f"[deploy].restartPolicyType must be 'ON_FAILURE', got {doc['deploy'].get('restartPolicyType')!r}"
    )


def test_restart_policy_max_retries() -> None:
    """[deploy].restartPolicyMaxRetries must be 5 (bounded retry budget)."""
    doc = _load()
    assert doc["deploy"]["restartPolicyMaxRetries"] == 5, (
        f"[deploy].restartPolicyMaxRetries must be 5, got {doc['deploy'].get('restartPolicyMaxRetries')!r}"
    )
