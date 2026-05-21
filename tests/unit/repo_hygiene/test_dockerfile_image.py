"""Repo hygiene tests — verifies Dockerfile and .dockerignore static shape.

Structural regression guards:
  - Dockerfile uses Python 3.12-slim base (CLAUDE.md locks Python 3.12.x)
  - Non-root user 'app' at runtime (T-00-01 threat mitigation)
  - Production deps only (--no-dev flag present)
  - Default CMD targets the data_platform entrypoint (D-03)
  - .dockerignore excludes secrets and dev artifacts (T-00-01)

References:
  - CONTEXT.md D-02 (single package, single Dockerfile), D-03 (same image, 3 startCommands)
  - 00-07-PLAN.md threat model T-00-01 (image information disclosure)
"""

import pathlib

ROOT = pathlib.Path(__file__).parent.parent.parent.parent
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


def _dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _dockerignore_text() -> str:
    return DOCKERIGNORE.read_text(encoding="utf-8")


# ── Dockerfile checks ──────────────────────────────────────────────────────────


def test_dockerfile_exists() -> None:
    assert DOCKERFILE.exists(), "Dockerfile missing — required for Railway build (D-03)"


def test_dockerfile_uses_python_312_slim() -> None:
    """Python 3.12-slim base image (CLAUDE.md tech stack lock)."""
    text = _dockerfile_text()
    assert "FROM python:3.12-slim" in text, (
        "Dockerfile must use 'FROM python:3.12-slim' as the base image. "
        "CLAUDE.md locks Python 3.12.x for wheels compatibility."
    )


def test_dockerfile_non_root_user() -> None:
    """T-00-01: runtime stage must run as non-root user 'app'."""
    text = _dockerfile_text()
    assert "USER app" in text, (
        "Dockerfile must drop privileges to 'USER app' in the runtime stage (T-00-01). "
        "Running as root exposes unnecessary privilege inside the container."
    )


def test_dockerfile_expose_8000() -> None:
    """Container must declare EXPOSE 8000 (default Railway port)."""
    text = _dockerfile_text()
    assert "EXPOSE 8000" in text, (
        "Dockerfile must include 'EXPOSE 8000'. "
        "Railway injects $PORT at runtime; 8000 is the fall-back default."
    )


def test_dockerfile_uv_sync_no_dev() -> None:
    """Production image must skip dev dependencies (--no-dev flag).

    Dev deps include pytest, ruff, pyright, testcontainers, hypothesis — none of
    which should ship in the production container.
    """
    text = _dockerfile_text()
    assert "uv sync --locked --no-dev" in text, (
        "Dockerfile must run 'uv sync --locked --no-dev' to exclude dev dependencies "
        "from the production image."
    )


def test_dockerfile_cmd_references_data_platform() -> None:
    """Default CMD must invoke the data_platform entrypoint (D-03).

    strategy-engine and dashboard override startCommand in the Railway dashboard.
    """
    text = _dockerfile_text()
    assert "shortfire.entrypoints.data_platform:app" in text, (
        "Dockerfile CMD must reference 'shortfire.entrypoints.data_platform:app' "
        "as the default entrypoint (D-03)."
    )


def test_dockerfile_does_not_copy_env_files() -> None:
    """T-00-01: Dockerfile must not COPY .env* files into the image."""
    text = _dockerfile_text()
    # Any line that COPYs a .env file (not in a comment) is a violation
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "COPY" in stripped and ".env" in stripped:
            raise AssertionError(
                f"Dockerfile line copies .env* into image (T-00-01): {line!r}. "
                "Secrets must come from Railway environment variables, not baked into the image."
            )


# ── .dockerignore checks ───────────────────────────────────────────────────────


def test_dockerignore_exists() -> None:
    assert DOCKERIGNORE.exists(), ".dockerignore missing — secrets and dev artifacts may leak into image"


def test_dockerignore_excludes_env_file() -> None:
    """.dockerignore must exclude .env (T-00-01)."""
    text = _dockerignore_text()
    assert ".env" in text, ".dockerignore must exclude .env to prevent secret leakage (T-00-01)"


def test_dockerignore_excludes_env_local() -> None:
    """.dockerignore must exclude .env.local (T-00-01)."""
    text = _dockerignore_text()
    assert ".env.local" in text, ".dockerignore must exclude .env.local (T-00-01)"


def test_dockerignore_excludes_tests() -> None:
    """.dockerignore must exclude tests/ to keep the image slim."""
    text = _dockerignore_text()
    assert "tests" in text, ".dockerignore must exclude tests/ directory"


def test_dockerignore_excludes_planning() -> None:
    """.dockerignore must exclude .planning/ (dev-only metadata)."""
    text = _dockerignore_text()
    assert ".planning" in text, ".dockerignore must exclude .planning/ directory"


def test_dockerignore_excludes_venv() -> None:
    """.dockerignore must exclude .venv (local dev venv, not needed in image)."""
    text = _dockerignore_text()
    assert ".venv" in text, ".dockerignore must exclude .venv/"


def test_dockerignore_excludes_pycache() -> None:
    """.dockerignore must exclude __pycache__."""
    text = _dockerignore_text()
    assert "__pycache__" in text, ".dockerignore must exclude __pycache__"


def test_dockerignore_excludes_git() -> None:
    """.dockerignore must exclude .git to prevent version history leakage."""
    text = _dockerignore_text()
    assert ".git" in text, ".dockerignore must exclude .git"
