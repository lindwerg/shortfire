# Shortfire

MEXC Futures Sniper — crypto data platform with short-after-pump ML strategy.

Detects optimal short entry points on MEXC futures after pumps and overbought conditions.
Solo-use instrument for personal trading with staged autonomy escalation: signal-only →
semi-auto → full-auto, gated on walk-forward validation and paper trading.

## Quickstart

```bash
git clone <repo-url>
cd shortfire
uv sync
pre-commit install
uv run pytest -m "not integration"
```

## Development

Run the full suite (unit + integration, requires Docker):

```bash
uv run pytest --cov=shortfire --cov-fail-under=80
uv run pytest -m integration
```

Lint and type-check:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Local Postgres (TimescaleDB 2.18 on PG16):

```bash
docker compose up -d
# Copy template and fill in your local values:
cp .env.example .env.local
# (edit .env.local — never commit it)
```

Run migrations:

```bash
uv run alembic upgrade head
```

## Local development cleanup

**Destructive — local data loss.** `docker compose down -v` removes the `shortfire-pg`
volume. Local-only; production data is on Railway and is unaffected.

## Deployment

The project deploys to Railway on every push to `main` (if CI passes). Three services share
the same Docker image with different `startCommand` values:

| Service | Sleep | startCommand |
|---------|-------|-------------|
| `data-platform` | never | `alembic upgrade head && uvicorn shortfire.entrypoints.data_platform:app --host 0.0.0.0 --port $PORT` |
| `strategy-engine` | idle | `uvicorn shortfire.entrypoints.strategy_engine:app --host 0.0.0.0 --port $PORT` |
| `dashboard` | idle | `uvicorn shortfire.entrypoints.dashboard:app --host 0.0.0.0 --port $PORT` |

Each service has `DATABASE_URL=${{Postgres.DATABASE_URL}}` as a reference variable.

## Architecture

See `.planning/phases/00-foundation/00-CONTEXT.md` for locked decisions (D-01 through D-34).
See `AGENTS.md` for contributor and AI-agent guidelines.

## Tech stack

Python 3.12 · FastAPI 0.128+ · uv · Pydantic v2 · TimescaleDB 2.18 on PG16 ·
SQLAlchemy 2.x · asyncpg · Alembic · structlog · pytest + Hypothesis · ruff · pyright
