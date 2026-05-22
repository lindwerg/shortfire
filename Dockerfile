# syntax=docker/dockerfile:1.7
#
# Multi-stage build — single image shared by all 3 Railway services (D-03).
# Each service overrides the startCommand via its own railway.*.toml file
# (data-platform → railway.toml, strategy-engine → railway.strategy-engine.toml,
# dashboard → railway.dashboard.toml). The default CMD here targets data-platform
# so a bare `docker run` is meaningful.
#
# T-00-01 mitigations applied:
#   - .dockerignore excludes .env*, .planning/, tests/, docs
#   - Runtime stage runs as UID 1000 (non-root), never as root
#   - uv sync --no-dev: dev dependencies are never shipped in the image
#   - Runtime stage carries NO uv, NO build tools — only the resolved venv
#     and application source.
#
# python:3.12-slim-bookworm pinned (Debian 12). Debian 13 (trixie) no longer ships
# postgresql-client-16 — only client-17. We need a client matching the PG16 server
# version (T-1-BCK-04), so bookworm is the right base until the server upgrades to PG17.
FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# ── deps stage ─────────────────────────────────────────────────────────────────
# Installs uv and resolves production dependencies into /app/.venv.
# This layer is cache-friendly: only invalidated when pyproject.toml or uv.lock
# change, not when application source changes.
FROM base AS deps

# uv installed via official Astral image (no curl/wget required in slim base).
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
# uv sync installs the project itself (editable .pth → /app/src/shortfire) AND its
# dependencies, so the package source MUST be present before `uv sync` runs.
# Without this, the resolved venv contains every dependency but NOT shortfire,
# producing `ModuleNotFoundError: No module named 'shortfire'` at runtime
# (caught during the first Railway deploy).
COPY src ./src

# --no-dev: production image never ships test/dev tooling.
# --locked: hard-pin exact versions from uv.lock; never resolve floating deps.
RUN uv sync --locked --no-dev

# ── runtime stage ──────────────────────────────────────────────────────────────
# Copies only the built venv + application source — no uv, no build tools.
FROM base AS runtime

# postgresql-client-16: provides pg_dump matching the PG16 server version (RESEARCH.md §8.1 + §17).
# Installed in the runtime stage (not deps) because it is a runtime binary, not a build dependency.
# T-1-BCK-04: version must match the Railway PostgreSQL server (PG16 pinned in Phase 0 plan 00-07).
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 && rm -rf /var/lib/apt/lists/*

# Non-root user (T-00-01)
RUN groupadd --system app && useradd --system --gid app --uid 1000 app

WORKDIR /app

# Venv from deps stage (alembic + uvicorn + fastapi + … all already installed)
COPY --from=deps /app/.venv /app/.venv

# Application source
COPY src/shortfire /app/src/shortfire

# Alembic migrations — needed by data-platform's preDeployCommand (OPS-07).
# alembic.ini's `prepend_sys_path = src` (set in Plan 00-04) makes
# `alembic upgrade head` find the package without uv-in-runtime.
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

# Drop privileges
USER app

EXPOSE 8000

# Default startCommand — overridden per service in each railway.*.toml (D-03).
# Railway injects $PORT at runtime; we fall back to 8000 for local `docker run`.
CMD ["sh", "-c", "uvicorn shortfire.entrypoints.data_platform:app --host 0.0.0.0 --port ${PORT:-8000}"]
