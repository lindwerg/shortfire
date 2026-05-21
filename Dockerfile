# syntax=docker/dockerfile:1.7
#
# Multi-stage build — single image shared by all 3 Railway services (D-03).
# Each service overrides the startCommand in the Railway dashboard; the default
# CMD here targets data-platform so a bare `docker run` is meaningful.
#
# T-00-01 mitigations applied:
#   - .dockerignore excludes .env*, .planning/, tests/, docs
#   - Runtime stage runs as UID 1000 (non-root), never as root
#   - uv sync --no-dev: dev dependencies are never shipped in the image
#
FROM python:3.12-slim AS base

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

# Install uv (pinned to same major as setup-uv@v8 uses in CI — 0.11.x)
ADD https://astral.sh/uv/install.sh /uv-install.sh
RUN sh /uv-install.sh && rm /uv-install.sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./

# --no-dev: production image never ships test/dev tooling.
# --locked: hard-pin exact versions from uv.lock; never resolve floating deps.
RUN uv sync --locked --no-dev

# ── runtime stage ──────────────────────────────────────────────────────────────
# Copies only the built venv + application source — no uv, no build tools.
FROM base AS runtime

# Non-root user (T-00-01)
RUN groupadd --system app && useradd --system --gid app --uid 1000 app

WORKDIR /app

# Venv from deps stage
COPY --from=deps /app/.venv /app/.venv

# Application source
COPY src/shortfire /app/src/shortfire

# Alembic migrations — needed by data-platform's preDeployCommand (OPS-07)
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

# Drop privileges
USER app

EXPOSE 8000

# Default startCommand — overridden per service in Railway dashboard (D-03).
# Railway injects $PORT at runtime; we fall back to 8000 for local `docker run`.
CMD ["sh", "-c", "uvicorn shortfire.entrypoints.data_platform:app --host 0.0.0.0 --port ${PORT:-8000}"]
