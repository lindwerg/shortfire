# AGENTS.md — Shortfire Contributor + AI Agent Guidance

This file documents project-specific conventions that every contributor — human or AI agent —
must follow when working on this codebase.

---

## Project workflow: GSD

This project uses the **Get Shit Done (GSD)** workflow. Before making direct repo edits, use
the GSD entry points documented in `CLAUDE.md` under "GSD Workflow Enforcement":

- `/gsd-quick` — small fixes, doc updates, ad-hoc tasks
- `/gsd-debug` — investigation and bug fixing
- `/gsd-execute-phase` — planned phase work

Do **not** make direct repo edits outside a GSD workflow unless the user explicitly asks to
bypass it.

---

## TDD discipline

**Every module starts with a failing test.** This is non-negotiable (TEST-02).

### Required workflow

1. Write a failing test (RED) — run it and confirm it fails before writing implementation code
2. Write minimal implementation to make the test pass (GREEN)
3. Refactor for clarity without changing behavior (IMPROVE)
4. Verify ≥80% coverage (project-wide gate, ramps to ≥95% for `risk/` and `execution/` in Phase 2+)

### Test shape

Use Arrange-Act-Assert (AAA) structure:

```python
def test_candle_rejects_low_above_high() -> None:
    # Arrange
    from decimal import Decimal
    from datetime import datetime, timezone
    from shortfire.domain.market import Candle

    # Act / Assert — construction must raise
    with pytest.raises(ValidationError):
        Candle(
            symbol="BTCUSDT",
            timeframe="1m",
            open=Decimal("100"),
            high=Decimal("90"),   # high < open — violates invariant
            low=Decimal("80"),
            close=Decimal("95"),
            volume=Decimal("1000"),
            ts=datetime.now(timezone.utc),
            source="mexc",
        )
```

### Hypothesis property tests (D-15)

**Mandatory** for every domain invariant in `src/shortfire/domain/`. At minimum:

- "Violation builds raise ValidationError"
- "Round-trip `model_dump` / `model_validate` preserves all fields"
- "Naive datetime rejected"
- "Order(intent='close', reduce_only=False) raises ValidationError" (EXEC-02)
- "RiskLimits(max_per_trade_pct=0.06) raises ValidationError" (RISK-02 hard cap)

Use the shared strategies from `tests/conftest.py`:

```python
from tests.conftest import money, utc_dt
from hypothesis import given

@given(price=money, ts=utc_dt)
def test_round_trip(price, ts): ...
```

---

## Railway healthchecks are NOT liveness probes

Railway runs healthchecks (`/health`) **only at deploy time** — to gate when a new revision
becomes live. They do NOT:

- Keep services alive after deploy
- Run continuously to detect runtime failures
- Wake sleeping services

**Sleeping services** (`strategy-engine`, `dashboard`) are woken by the **first inbound HTTP
request** after an idle period — NOT by healthchecks. This causes a 2-3s cold start on the
first request. This is expected and acceptable.

**`data-platform`** is set `sleepApplication: false` (always-on) because Phase 1 needs the
ingest scheduler running continuously.

If you see a question like "why isn't healthcheck waking the strategy-engine?" — it isn't
supposed to. The first signal-fetch request wakes it.

---

## Cross-service env var sharing is forbidden

Each Railway service has its own **service-scoped Variables**. Never use Railway's "Share
Variable to Other Services" feature across `data-platform`, `strategy-engine`, `dashboard`.

**Why:** `DataPlatformSettings` has no `mexc_trade` field — if `MEXC_TRADE__TRADE_KEY` is
somehow injected into `data-platform`'s environment, `assert_no_trade_env_leaked()` raises
`RuntimeError` at startup (fail-fast). The anti-leak boundary is structural AND asserted at
runtime.

The only cross-service reference that IS allowed is `DATABASE_URL=${{Postgres.DATABASE_URL}}`
— this is a Railway reference variable, not a secret.

---

## Do not call `repr(settings)` — use `safe_summary()` instead

Every `*Settings` class exposes a `safe_summary()` method that returns a sanitized dict safe
for startup logging. The canonical pattern is:

```python
log.info("service.settings.loaded", **settings.safe_summary())
```

**Never** call `repr(settings)`, `str(settings)`, or log the settings object directly.
Even with `SecretStr`, structlog/logger formatting may inadvertently expose field metadata.

`safe_summary()` deliberately omits all credential fields and only includes non-sensitive
operational context (service_name, port, env, log_level, db_host without credentials).

---

## Decimal everywhere for money (D-09)

**Never** use `float` for prices, quantities, PnL, or notional values. Use `Decimal`.

A pre-commit grep hook (`ban-float-in-domain`) blocks `: float` annotations under
`src/shortfire/domain/`. If you need to pass a value to a polars/numpy ML feature
boundary, cast ONLY at that boundary: `float(value)` — never store floats in domain types.

---

## Timestamps are always tz-aware UTC (D-12)

**Never** use `datetime.now()` without `tz=timezone.utc`. The domain `@model_validator`
rejects naive datetimes with `ValidationError`. Pitfall 7: `freeze_time("2026-05-21")` freezes
naive datetimes — always use `freeze_time("2026-05-21T00:00:00Z")` with an explicit `Z`.

---

## Commit discipline

Each task gets its own atomic commit. Format: `{type}({phase}-{plan}): {description}`.

Types: `feat`, `fix`, `test`, `refactor`, `perf`, `docs`, `style`, `chore`.

TDD RED commit: `test(00-01): add failing test for X`
TDD GREEN commit: `feat(00-01): implement X`
