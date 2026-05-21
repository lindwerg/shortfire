# Phase 1: Data Platform - Pattern Map

**Mapped:** 2026-05-21
**Files analyzed:** 47 (new/modified files extracted from CONTEXT.md D-95/D-96 + RESEARCH.md §2 + observability extensions)
**Analogs found:** 47 / 47 (every file maps to a Phase 0 analog — Phase 0 was specifically designed to seed Phase 1 patterns)

This map exists to lock every Phase 1 file to a Phase 0 analog so the planner does not invent shapes. Every entry below cites an exact line range from an existing file and shows the code that must be copied or mirrored. The planner's job is to write 0-12 plans that each say "follow this analog, with these per-file differences."

---

## File Classification

### Hot-path ingest (`src/shortfire/ingest/`)

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `src/shortfire/ingest/__init__.py` | package-init | — | `src/shortfire/observability/__init__.py` | exact (sibling package style) |
| `src/shortfire/ingest/base.py` | utility | shared helpers | `src/shortfire/observability/logging.py` | role-match (module docstring + config functions) |
| `src/shortfire/ingest/retry.py` | utility | request-response | `src/shortfire/db/timescale.py` | role-match (module of stateless functions/decorators wrapping an external surface) |
| `src/shortfire/ingest/rate_limit.py` | utility | request-response | `src/shortfire/db/timescale.py` | role-match (module of declared constants + helpers) |
| `src/shortfire/ingest/context.py` | utility | singleton accessor | `src/shortfire/db/engine.py` | exact (process-wide singleton factory) |
| `src/shortfire/ingest/storage/__init__.py` | package-init | — | `src/shortfire/observability/__init__.py` | exact |
| `src/shortfire/ingest/storage/copy.py` | service | batch transform/CRUD | `src/shortfire/db/timescale.py` + `src/shortfire/db/engine.py` | exact (single helper with SQL string assembly + AsyncEngine usage) |
| `src/shortfire/ingest/mexc/client.py` | service | request-response (ccxt) | `src/shortfire/clients/mexc.py` (Protocol) | exact — concrete impl of declared Protocol |
| `src/shortfire/ingest/mexc/backfill.py` | service | batch (paginated REST) | `tests/fakes/mexc.py` (`fetch_ohlcv` filter loop) | role-match (paginated iteration shape) |
| `src/shortfire/ingest/mexc/live_candles.py` | service | streaming (ws → COPY) | `src/shortfire/db/engine.py` + new `copy.py` | composite (TaskGroup new, but logging/context pattern matches engine.py) |
| `src/shortfire/ingest/mexc/funding.py` | service | request-response + streaming | `src/shortfire/clients/mexc.py` Protocol shape | exact |
| `src/shortfire/ingest/mexc/oi.py` | service | request-response (REST poll) | `src/shortfire/clients/mexc.py` Protocol shape | exact |
| `src/shortfire/ingest/mexc/orderbook.py` | service | streaming (ws TaskGroup) | `src/shortfire/clients/mexc.py` Protocol (`fetch_order_book`) | role-match |
| `src/shortfire/ingest/mexc/trades.py` | service | streaming + batch COPY | `tests/fakes/mexc.py` + new `copy.py` | composite |
| `src/shortfire/ingest/mexc/liquidations.py` | service | streaming + REST fallback | `src/shortfire/clients/mexc.py` Protocol | role-match |
| `src/shortfire/ingest/mexc/schemas.py` | model | validation | `src/shortfire/domain/market.py` | exact (Pydantic v2 BaseModel + model_validator) |
| `src/shortfire/ingest/coinglass/client.py` | service | request-response (httpx) | `src/shortfire/clients/coinglass.py` (Protocol) | exact |
| `src/shortfire/ingest/coinglass/funding_agg.py` | service | request-response | `src/shortfire/clients/coinglass.py` | role-match |
| `src/shortfire/ingest/coinglass/oi.py` | service | request-response | `src/shortfire/clients/coinglass.py` | role-match |
| `src/shortfire/ingest/coinglass/liq.py` | service | request-response | `src/shortfire/clients/coinglass.py` | role-match |
| `src/shortfire/ingest/coinglass/lsr.py` | service | request-response | `src/shortfire/clients/coinglass.py` | role-match |
| `src/shortfire/ingest/coinglass/schemas.py` | model | validation | `src/shortfire/domain/market.py` | exact |
| `src/shortfire/ingest/coingecko/client.py` | service | request-response (httpx) | `src/shortfire/clients/coingecko.py` (Protocol) | exact |
| `src/shortfire/ingest/coingecko/universe.py` | service | batch | `src/shortfire/clients/coingecko.py` | role-match |
| `src/shortfire/ingest/coingecko/schemas.py` | model | validation | `src/shortfire/domain/market.py` | exact |
| `src/shortfire/ingest/universe/snapshot.py` | service | batch (daily cron) | `tests/fakes/repos.py` (in-memory ops over candles) | role-match |
| `src/shortfire/ingest/universe/tier1.py` | utility | batch | `src/shortfire/db/timescale.py` (helper functions) | role-match |
| `src/shortfire/ingest/backup/pg_dump_r2.py` | service | file-I/O (S3) | `src/shortfire/db/engine.py` (env-driven config + factory) | role-match |
| `src/shortfire/ingest/freshness/gauges.py` | utility | event-driven (gauge updates) | `src/shortfire/observability/metrics.py` | exact (metric builder/setter style) |
| `src/shortfire/ingest/freshness/alerter.py` | service | event-driven | `src/shortfire/observability/middleware.py` (install fn) + new `telegram.py` | composite |
| `src/shortfire/ingest/dead_letter/writer.py` | service | CRUD (write-only) | `src/shortfire/db/timescale.py` + new `copy.py` | role-match |
| `src/shortfire/ingest/dead_letter/alerter.py` | service | event-driven | freshness/alerter.py (sibling) | exact |
| `src/shortfire/ingest/scheduler/bootstrap.py` | service | lifecycle | `src/shortfire/entrypoints/data_platform.py` (lifespan pattern) | exact |
| `src/shortfire/ingest/scheduler/jobs.py` | service | event-driven (cron handlers) | `src/shortfire/observability/events.py` (module of constants + register functions) | role-match |

### Database models (relational lookup tables — `src/shortfire/db/models/`)

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `src/shortfire/db/models/__init__.py` | package-init | — | `src/shortfire/observability/__init__.py` | exact |
| `src/shortfire/db/models/symbols.py` | model | CRUD | `src/shortfire/db/base.py` (`Base` + naming convention) | exact (SQLAlchemy model on Base) |
| `src/shortfire/db/models/ingest_runs.py` | model | CRUD | `src/shortfire/db/base.py` | exact |
| `src/shortfire/db/models/dead_letter.py` | model | CRUD | `src/shortfire/db/base.py` | exact |

### Observability extensions (`src/shortfire/observability/`)

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---------------|------|-----------|----------------|---------------|
| `src/shortfire/observability/events.py` *(modified)* | config | — | itself (current file) — add 13 entries to `EVENTS` frozenset | exact (existing extension pattern documented in file docstring) |
| `src/shortfire/observability/metrics.py` *(modified)* | utility | — | itself (current file) — add new metric families to `build_metrics_for_service` | exact |
| `src/shortfire/observability/telegram.py` *(new)* | service | request-response (raw httpx) | `src/shortfire/clients/coinglass.py` Protocol style + a fresh httpx call | composite (new shape, but Pydantic settings + httpx pattern from CoinglassClient seam) |
| `src/shortfire/observability/metrics_data_platform.py` *(new)* | utility | — | `src/shortfire/observability/metrics.py` | exact — extends per D-84 |

### Settings extensions (`src/shortfire/settings/data_platform.py`)

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---------------|------|-----------|----------------|---------------|
| `src/shortfire/settings/data_platform.py` *(modified)* | config | — | itself (`MexcReadSettings`, `CoinglassSettings` blocks) | exact — add `TelegramSettings` + `R2BackupSettings` siblings |

### Domain updates

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---------------|------|-----------|----------------|---------------|
| `src/shortfire/domain/market.py` *(modified)* | model | — | itself — change `Source` Literal values | exact (single line edit + matching test fixture updates) |

### Alembic migrations (12 new migrations)

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `alembic/versions/0003_raw_mexc_candles_1m_1d.py` | migration | DDL | `alembic/versions/0002_service_event_hypertable.py` | exact |
| `alembic/versions/0004_raw_mexc_funding.py` | migration | DDL | `alembic/versions/0002_*` | exact |
| `alembic/versions/0005_raw_mexc_oi.py` | migration | DDL | `alembic/versions/0002_*` | exact |
| `alembic/versions/0006_raw_mexc_trades.py` | migration | DDL | `alembic/versions/0002_*` | exact |
| `alembic/versions/0007_raw_mexc_l2_top20.py` | migration | DDL | `alembic/versions/0002_*` | exact |
| `alembic/versions/0008_raw_mexc_liquidations.py` | migration | DDL | `alembic/versions/0002_*` | exact |
| `alembic/versions/0009_raw_coinglass.py` | migration | DDL | `alembic/versions/0002_*` | exact |
| `alembic/versions/0010_raw_coingecko_market.py` | migration | DDL | `alembic/versions/0002_*` | exact |
| `alembic/versions/0011_universe_snapshots.py` | migration | DDL | `alembic/versions/0002_*` | exact |
| `alembic/versions/0012_symbols_lookup.py` | migration | DDL (relational, no hypertable) | `alembic/versions/0001_init_timescaledb.py` (raw `op.execute` style) + `0002_*` (`op.create_table` style) | composite |
| `alembic/versions/0013_dead_letter_and_ingest_runs.py` | migration | DDL | `alembic/versions/0002_*` | exact |
| `alembic/versions/0014_continuous_aggregates_5m_15m_1h_4h.py` | migration | DDL (continuous aggregate carve-out) | `alembic/versions/0001_init_timescaledb.py` (raw `op.execute`) — JUSTIFIED INLINE | role-match — see RESEARCH.md §3.5 helper recommendation |

### Tests

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `tests/unit/ingest/test_retry_policies.py` | test | — | `tests/unit/db/test_timescale_helpers.py` | exact (patch-based unit shape) |
| `tests/unit/ingest/test_rate_limit.py` | test | — | `tests/unit/db/test_timescale_helpers.py` | role-match |
| `tests/unit/ingest/test_copy_into_hypertable.py` | test | — | `tests/unit/db/test_timescale_helpers.py` | role-match |
| `tests/unit/ingest/test_mexc_schemas.py` | test | — | `tests/unit/domain/test_candle.py` | exact (Pydantic invariant tests via Hypothesis) |
| `tests/unit/ingest/test_coinglass_schemas.py` | test | — | `tests/unit/domain/test_candle.py` | exact |
| `tests/unit/ingest/test_coingecko_schemas.py` | test | — | `tests/unit/domain/test_candle.py` | exact |
| `tests/unit/ingest/test_universe_snapshot.py` | test | — | `tests/unit/clients/test_fakes_match_protocols.py` | role-match (Protocol-conformant + Hypothesis property) |
| `tests/unit/ingest/test_dead_letter_writer.py` | test | — | `tests/unit/db/test_timescale_helpers.py` | role-match |
| `tests/unit/ingest/test_telegram_client.py` | test | — | `tests/unit/observability/test_metrics.py` | role-match |
| `tests/unit/observability/test_events_phase1_extensions.py` | test | — | `tests/unit/observability/test_event_taxonomy.py` | exact |
| `tests/unit/observability/test_data_platform_metrics.py` | test | — | `tests/unit/observability/test_metrics.py` | exact |
| `tests/integration/ingest/test_idempotent_reingest.py` | test | — | `tests/integration/db/test_alembic_and_hypertables.py` | exact (testcontainers session-scoped) |
| `tests/integration/ingest/test_source_check_constraint.py` | test | — | `tests/integration/db/test_alembic_and_hypertables.py` | exact |
| `tests/integration/ingest/test_continuous_aggregates.py` | test | — | `tests/integration/db/test_alembic_and_hypertables.py` | exact |
| `tests/integration/ingest/test_universe_point_in_time.py` | test | — | `tests/integration/db/test_alembic_and_hypertables.py` | exact (extends with Hypothesis property) |

### Documentation

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `docs/RESTORE.md` | docs | — | (no analog; first docs/ file) | none — see "No Analog Found" |

---

## Pattern Assignments

### Group 1 — Alembic migration files (`alembic/versions/0003*..0013*.py`)

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/alembic/versions/0002_service_event_hypertable.py`

**Imports + revision header pattern** (lines 1-22):
```python
"""service_event hypertable + compression policy

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-21

D-28: service_event is a REAL long-term observability table, not a throwaway
smoke object. Every service writes heartbeat/restart/task events here.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op
from shortfire.db.timescale import add_compression_policy, create_hypertable, enable_compression

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None
```

**Core DDL + hypertable + compression pattern** (lines 27-44):
```python
def upgrade() -> None:
    """Create service_event hypertable with compression policy (D-28, D-27)."""
    op.create_table(
        "service_event",
        sa.Column(
            "ts",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
    )
    create_hypertable("service_event", time_column="ts", chunk_interval="7 days")
    enable_compression("service_event", segment_by="service_name", order_by="ts DESC")
    add_compression_policy("service_event", after_age="7 days")
```

**Downgrade pattern** (lines 47-49):
```python
def downgrade() -> None:
    """Drop service_event table (includes hypertable chunks + compression policy)."""
    op.drop_table("service_event")
```

**Per-migration deltas (apply to 0003–0013):**
- Add `source TEXT NOT NULL` column + `sa.CheckConstraint` for `source IN ('mexc_native','coinglass_aggregate','coinglass_mexc_only','coingecko')` (D-59)
- Add `quality_flag TEXT NOT NULL DEFAULT 'ok'` column + matching `sa.CheckConstraint` (D-60)
- Add `ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()` column (D-61)
- For each table the planner consults D-58 table inventory for: `chunk_interval`, `segment_by`, `compress_after`
- All time columns use `sa.TIMESTAMP(timezone=True)` — Phase 0 pre-commit grep guard refuses `TIMESTAMP[^(]`
- **NEVER** use `ON DELETE CASCADE` — banned by pre-commit grep guard (D-63 + Phase 0)
- 0012 (symbols) is the only relational table — skip `create_hypertable`/`enable_compression`/`add_compression_policy` calls; add the PK and soft-delete column instead

**Migration 0014 carve-out (continuous aggregates):**

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/alembic/versions/0001_init_timescaledb.py` (lines 20-27 — raw `op.execute` pattern)

```python
def upgrade() -> None:
    """Create the timescaledb extension (idempotent)."""
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
```

Migration 0014 follows the SAME raw-`op.execute` style but with the `CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)` + `SELECT add_continuous_aggregate_policy(...)` block per RESEARCH.md §3.5. **The planner MUST add `create_continuous_aggregate(...)` to `src/shortfire/db/timescale.py`** to preserve D-27 discipline — see RESEARCH.md §3.5 signature.

---

### Group 2 — SQLAlchemy lookup-table models (`src/shortfire/db/models/*.py`)

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/db/base.py`

**Base + naming convention pattern** (lines 8-23):
```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Project-wide DeclarativeBase with enforced constraint naming convention (D-29)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

**New model files** (e.g. `src/shortfire/db/models/symbols.py`) should:
- `from shortfire.db.base import Base` — never define a new `DeclarativeBase`
- Use `sa.TIMESTAMP(timezone=True)` for every timestamp column (D-65)
- Soft-delete via nullable `delisted_at TIMESTAMPTZ` — NEVER `ON DELETE CASCADE` (D-63 + Phase 0 guard)
- The `symbols` table sets `symbol TEXT PRIMARY KEY` per D-63

---

### Group 3 — Pydantic schema files (`src/shortfire/ingest/{mexc,coinglass,coingecko}/schemas.py`)

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/domain/market.py`

**Imports + Literal aliases pattern** (lines 1-23):
```python
"""Market data domain types — Candle, OrderBookLevel, OrderBook, Funding, Liquidation.

All types are pure Pydantic v2 BaseModel with frozen=True and strict=True (D-07, D-08).
Money fields use Decimal exclusively — no float (D-09).
Enum-like fields use Literal[...] (D-10).
Collection fields on frozen models use tuple[X, ...] not list[X] (D-11).
Timestamps reject naive datetime via @model_validator(mode='after') (D-12).
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
```

**Frozen+strict model pattern** (lines 31-56):
```python
class Candle(BaseModel):
    """OHLCV candlestick for a single timeframe bucket.

    Invariants (D-13):
      - ts must be timezone-aware
      - low <= open, close <= high
    """

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str
    source: Source
    timeframe: Timeframe
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Field(ge=Decimal("0"))

    @model_validator(mode="after")
    def _reject_naive_ts(self) -> Self:
        if self.ts.tzinfo is None:
            raise ValueError("Candle.ts must be timezone-aware (UTC)")
        return self
```

**Invariant validator pattern** (lines 57-69):
```python
    @model_validator(mode="after")
    def _low_le_extremes_le_high(self) -> Self:
        if not (
            self.low <= self.open
            and self.low <= self.close
            and self.open <= self.high
            and self.close <= self.high
        ):
            raise ValueError(
                "Candle invariant violated: low <= open,close <= high "
                f"(low={self.low}, open={self.open}, close={self.close}, high={self.high})"
            )
        return self
```

**Per-source schemas should:**
- Match the wire format of MEXC/Coinglass/CoinGecko responses (separate models from domain types — adapter pattern)
- Each schema has a `to_domain() -> Candle | Funding | Liquidation | …` method that constructs the canonical domain type (and triggers domain invariants — Pitfall 16)
- Validation failure raises Pydantic `ValidationError` — the caller routes that exception into `dead_letter` (RESEARCH.md §2 Pattern 2 + D-74)
- `Source` Literal updated per RESEARCH.md §3.2: `Literal["mexc_native", "coinglass_aggregate", "coinglass_mexc_only", "coingecko"]`

---

### Group 4 — Concrete clients (`src/shortfire/ingest/{mexc,coinglass,coingecko}/client.py`)

**Analog (interface seam):** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/clients/mexc.py`

**Protocol method signatures** (lines 14-41):
```python
@runtime_checkable
class MexcClient(Protocol):
    """Typed boundary for all MEXC REST/WS interactions."""

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]: ...

    async def fetch_funding_rate_history(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Funding, ...]: ...

    async def fetch_order_book(
        self,
        symbol: str,
        depth: int = 20,
    ) -> OrderBook: ...

    async def place_order(self, order: Order) -> str: ...
    async def cancel_order(self, client_order_id: str) -> None: ...
```

**Pattern obligations on concrete impls:**
- Every public async method MUST match the Protocol's signature exactly (so `runtime_checkable isinstance` passes — see `tests/unit/clients/test_fakes_match_protocols.py:81-85`)
- Return type is `tuple[X, ...]` (immutable, D-11)
- Use `Decimal` for money (D-09)
- All `datetime` arguments are tz-aware
- Concrete clients hold their underlying transport (`ccxt.async_support.mexc(...)` or `httpx.AsyncClient(...)`) as an injected dependency — easier to fake in tests

**Layered rate-limit + retry call site** (apply per RESEARCH.md §2 Pattern 2):
- Decorate each public async method with the per-source tenacity policy (`mexc_retry`, `coinglass_retry`, `coingecko_retry`)
- `async with <source>_LIMITER:` wraps the actual transport call
- On 4xx-non-429 → write to `dead_letter` via the writer module, DO NOT re-raise

---

### Group 5 — Fakes-in-tests (`tests/fakes/*.py` extensions)

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/tests/fakes/mexc.py`

**Stateful in-memory fake pattern** (lines 13-57):
```python
class FakeMexcClient:
    """Deterministic fake for Phase 0+ unit tests. Phase 1 fills in real implementations."""

    def __init__(self, candles: tuple[Candle, ...] = ()) -> None:
        self._candles = candles
        self._placed_orders: list[Order] = []

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
    ) -> tuple[Candle, ...]:
        """Return canned candles filtered by symbol and time window [since, until]."""
        return tuple(c for c in self._candles if c.symbol == symbol and since <= c.ts <= until)
```

**Phase 1 fakes must:**
- Replace each `raise NotImplementedError("Phase 1 fills this in")` with a deterministic in-memory body
- Keep the constructor signature minimal (canned data tuple in, no real I/O)
- Add deterministic OHLCV/funding/OI/orderbook generators for integration tests (CONTEXT.md §canonical_refs)

---

### Group 6 — Unit tests (Pydantic-domain shape)

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/tests/unit/domain/test_candle.py`

**Imports + Hypothesis strategies** (lines 8-21):
```python
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from pydantic import ValidationError

from shortfire.domain.market import Candle
from tests.conftest import money, utc_dt
```

**Hypothesis property test** (lines 23-54):
```python
@given(
    low=money,
    delta1=money,
    delta2=money,
    volume=money,
    ts=utc_dt,
)
@settings(max_examples=100)
def test_candle_round_trip(low, delta1, delta2, volume, ts) -> None:
    """Round-trip model_dump / model_validate preserves all fields for valid candles."""
    open_ = low + delta1
    high = max(open_, low + delta2)
    close = low + (delta1 + delta2) / Decimal("2")
    assume(low <= open_ <= high)
    assume(low <= close <= high)

    c = Candle(symbol="BTCUSDT", source="mexc", timeframe="1m", ts=ts,
               open=open_, high=high, low=low, close=close, volume=volume)
    assert Candle.model_validate(c.model_dump()) == c
```

**Negative invariant test** (lines 57-70):
```python
def test_candle_invariant_low_gt_high_raises() -> None:
    """Candle with low > high raises ValidationError."""
    with pytest.raises(ValidationError, match=r"low.*<=.*high|Candle invariant"):
        Candle(symbol="BTCUSDT", source="mexc", timeframe="1m",
               ts=datetime(2026, 5, 21, tzinfo=UTC),
               open=Decimal("100"), high=Decimal("99"),
               low=Decimal("100"), close=Decimal("100"), volume=Decimal("10"))
```

**Tests for `mexc/schemas.py`, `coinglass/schemas.py`, `coingecko/schemas.py` should mirror this shape.** Strategies in `tests/conftest.py` (lines 31-49) — `money` and `utc_dt` — are the canonical Hypothesis seeds; do not redefine.

---

### Group 7 — Unit tests (helper-shape with `unittest.mock.patch`)

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/tests/unit/db/test_timescale_helpers.py`

**Patch-based unit test pattern** (lines 16-26):
```python
def test_create_hypertable_sql_shape() -> None:
    """create_hypertable must issue SQL containing all required TimescaleDB arguments."""
    with patch("shortfire.db.timescale.op") as mock_op:
        create_hypertable("service_event")
        mock_op.execute.assert_called_once()
        sql_arg = str(mock_op.execute.call_args[0][0])
        assert "create_hypertable" in sql_arg
        assert "'service_event'" in sql_arg
        assert "chunk_time_interval" in sql_arg
        assert "INTERVAL '7 days'" in sql_arg
        assert "if_not_exists => TRUE" in sql_arg
```

**Use for:** `test_retry_policies.py`, `test_rate_limit.py`, `test_copy_into_hypertable.py`, `test_dead_letter_writer.py`, `test_telegram_client.py`. Patch the external transport (asyncpg, httpx, prometheus_client) and assert the contract of the wrapper.

---

### Group 8 — Integration tests (testcontainers-based)

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/tests/integration/db/test_alembic_and_hypertables.py`

**Asyncpg URL helper pattern** (lines 30-39):
```python
def _to_asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy dialect suffix for asyncpg.connect().

    asyncpg.connect() rejects `+asyncpg` / `+psycopg2` suffixes.
    """
    if "postgresql+" in url:
        rest_start = url.index("://")
        return "postgresql" + url[rest_start:]
    return url
```

**Hypertable existence assertion pattern** (lines 96-119):
```python
@pytest.mark.integration
async def test_service_event_is_hypertable(migrated_db: str) -> None:
    asyncpg_url = _to_asyncpg_url(migrated_db)
    conn = await asyncpg.connect(asyncpg_url)
    try:
        rows = await conn.fetch(
            "SELECT hypertable_name "
            "FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'service_event'"
        )
    finally:
        await conn.close()

    assert len(rows) == 1
    assert rows[0]["hypertable_name"] == "service_event"
```

**Compression settings assertion pattern** (lines 127-217):

See lines 168-213 — the canonical pattern for asserting `segmentby_column_index`, `orderby_column_index`, and `orderby_asc` against `timescaledb_information.compression_settings`. **Phase 1 integration tests for every new hypertable must copy this query shape** (TimescaleDB 2.18.0-pg16 column layout — verified in Phase 0).

**Session-scoped container fixture** (from `tests/integration/conftest.py:87-98`):
```python
_TIMESCALE_IMAGE = "timescale/timescaledb:2.18.0-pg16"

@pytest.fixture(scope="session")
def timescale_container() -> Generator[PostgresContainer, None, None]:
    if not _DOCKER_OK:
        pytest.skip("Docker not available — integration tests require Docker (Assumption A4)")
    with PostgresContainer(_TIMESCALE_IMAGE) as container:
        yield container
```

**Phase 1 integration tests reuse the existing `migrated_db` session fixture.** Per-test cleanup follows the `clean_service_event` pattern (`tests/integration/conftest.py:148-171`): TRUNCATE the target hypertable before/after each test.

---

### Group 9 — Settings extensions (`src/shortfire/settings/data_platform.py`)

**Analog:** itself (`/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/settings/data_platform.py`)

**Optional nested BaseModel pattern** (lines 34-43):
```python
class CoinglassSettings(BaseModel):
    """Coinglass API credentials for derivatives data (OI, funding, liquidations)."""

    api_key: SecretStr


class CoingeckoSettings(BaseModel):
    """CoinGecko API credentials for market metadata and universe filtering."""

    api_key: SecretStr
```

**Optional wiring on top-level Settings** (lines 60-64):
```python
    # Optional — None until Phase 1 wires the real keys.
    mexc: MexcReadSettings | None = None
    coinglass: CoinglassSettings | None = None
    coingecko: CoingeckoSettings | None = None
```

**Add for Phase 1:**
```python
class TelegramSettings(BaseModel):
    bot_token: SecretStr
    operator_chat_id: str


class R2BackupSettings(BaseModel):
    account_id: str
    access_key_id: SecretStr
    secret_access_key: SecretStr
    bucket_name: str


# In DataPlatformSettings:
    telegram: TelegramSettings | None = None  # None = alerts logged only
    r2_backup: R2BackupSettings | None = None
```

**Extend `safe_summary()`** (lines 69-79):
```python
    def safe_summary(self) -> dict[str, object]:
        base = super().safe_summary()
        base.update({
            "mexc_read_configured": self.mexc is not None,
            "coinglass_configured": self.coinglass is not None,
            "coingecko_configured": self.coingecko is not None,
            "telegram_configured": self.telegram is not None,
            "r2_backup_configured": self.r2_backup is not None,
        })
        return base
```

**D-21 invariant:** `safe_summary()` returns booleans only — NEVER SecretStr values.

---

### Group 10 — Events registry extension (`src/shortfire/observability/events.py`)

**Analog:** itself (`/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/observability/events.py`)

**Frozenset extension pattern** (lines 16-31):
```python
EVENTS: frozenset[str] = frozenset(
    {
        "service.startup",
        "service.settings.loaded",
        ...
        "secret.guard.tripped",
    }
)
```

**`assert_event_registered` guard** (lines 41-54):
```python
def assert_event_registered(name: str) -> None:
    if name not in EVENTS:
        raise ValueError(
            f"Event {name!r} not in registered taxonomy. "
            f"Add to EVENTS in src/shortfire/observability/events.py before using it."
        )
```

**Phase 1 adds 18 new event names per D-85** (matches CONTEXT.md exactly):
`ingest.started`, `ingest.completed`, `ingest.failed`, `ingest.rate_limited`, `ingest.dead_letter`, `universe.snapshot.created`, `universe.symbol.new`, `universe.symbol.delisted`, `freshness.degraded`, `freshness.recovered`, `backup.started`, `backup.completed`, `backup.failed`, `ws.connected`, `ws.disconnected`, `ws.reconnect`, `ws.stale`.

**Critical:** Commit the `EVENTS` extension BEFORE any first use — Phase 0's `assert_event_registered` guard will crash the service if any new code path emits an unregistered event name (referenced from `src/shortfire/entrypoints/data_platform.py:69-78`).

---

### Group 11 — Metrics extension (`src/shortfire/observability/metrics.py` + new `metrics_data_platform.py`)

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/observability/metrics.py`

**Custom REGISTRY pattern** (lines 33-37):
```python
# Custom registry — explicitly NOT prometheus_client.REGISTRY (the default global).
# Rationale: avoids leaking process metrics (cpu_seconds, file_descriptors, etc.) into /metrics.
REGISTRY = CollectorRegistry()
```

**Metric construction pattern** (lines 84-110):
```python
result = ServiceMetrics(
    http_requests_total=Counter(
        f"shortfire_{svc}_http_requests_total",
        "HTTP request count by method, path, and status code",
        ["method", "path", "status"],
        registry=REGISTRY,
    ),
    http_request_duration_seconds=Histogram(
        f"shortfire_{svc}_http_request_duration_seconds",
        ...
        buckets=LATENCY_BUCKETS,
        registry=REGISTRY,
    ),
    ...
)
```

**Phase 1 adds 8 new metric families (D-84) registered in the SAME `REGISTRY`** (no new registry):
- `shortfire_data_platform_ingest_rows_total{source, dataset}` — Counter
- `shortfire_data_platform_ingest_duration_seconds{source, dataset}` — Histogram (use `LATENCY_BUCKETS`)
- `shortfire_data_platform_source_freshness_seconds{source, dataset, symbol}` — Gauge
- `shortfire_data_platform_dead_letter_total{source, error_type}` — Counter
- `shortfire_data_platform_universe_symbols_count{status}` — Gauge
- `shortfire_data_platform_backup_age_seconds` — Gauge
- `shortfire_data_platform_ws_reconnects_total{source, stream}` — Counter
- `shortfire_data_platform_rate_limit_remaining{source}` — Gauge

**Module-level cache pattern** (lines 42-47) — reuse for the new file `metrics_data_platform.py`:
```python
_metrics_cache: dict[str, "ServiceMetrics"] = {}
```

Idempotency is mandatory (lines 78-82) — re-import during tests must return the same instances or `prometheus_client.REGISTRY` will raise `Duplicated timeseries`.

---

### Group 12 — `src/shortfire/observability/telegram.py` (new minimal Bot API client)

**Analog (shape):** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/db/engine.py` (config + factory pattern)

**Factory-from-env pattern** (lines 44-66):
```python
def create_engine_from_env() -> AsyncEngine:
    raw_url = os.environ["DATABASE_URL"]
    url = _rewrite_url(raw_url)
    return create_async_engine(
        url,
        pool_size=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )
```

**Phase 1 `telegram.py` should:**
- Single function `async def send_telegram_alert(message: str, severity: Literal["warn","crit"]) -> None`
- httpx call to `https://api.telegram.org/bot<TOKEN>/sendMessage` with `chat_id` from `DataPlatformSettings.telegram`
- Per D-86: NO `python-telegram-bot` framework dep
- If `settings.telegram is None`, log the alert via structlog instead of POSTing (graceful degradation — RESEARCH.md §2)
- Wrap in tenacity policy with `wait_exponential_jitter(initial=1, max=30)` — Telegram rate limit is 30 msg/sec, plenty of headroom

---

### Group 13 — APScheduler scheduler bootstrap (`src/shortfire/ingest/scheduler/bootstrap.py`)

**Analog:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/entrypoints/data_platform.py`

**Lifespan async context pattern** (lines 66-78):
```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: emit service.startup and service.settings.loaded events."""
    assert_event_registered("service.startup")
    log.info("service.startup", version=__version__, pid=os.getpid())

    assert_event_registered("service.settings.loaded")
    log.info("service.settings.loaded", **settings.safe_summary())

    yield

    assert_event_registered("service.shutdown")
    log.info("service.shutdown")
```

**Phase 1 modifies `data_platform.py` lifespan to compose with the new bootstrap**:
- Replace `yield` body with: construct engine, build `AsyncScheduler(SQLAlchemyDataStore(engine), AsyncpgEventBroker.from_async_sqla_engine(engine))`, call `register_all_jobs(scheduler)`, `start_in_background()`, enter `mexc_ws_streams(...)` TaskGroup context, then `yield`
- On exit: `async with scheduler` handles graceful shutdown; TaskGroup cancels ws children
- All new structlog events MUST be in the extended `EVENTS` frozenset before first use

**APScheduler 4 v4 nomenclature** (RESEARCH.md §2 Pattern 4):
- `AsyncScheduler` (NOT `AsyncIOScheduler` — that was v3)
- `SQLAlchemyDataStore(engine)` (NOT `SQLAlchemyJobStore` from v3)
- `AsyncpgEventBroker.from_async_sqla_engine(engine)`

---

## Shared Patterns

### Authentication / Anti-Leak Boundary

**Source:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/settings/data_platform.py` lines 82-103

**Apply to:** Every new client constructor that touches MEXC/Coinglass/CoinGecko/Telegram/R2.

```python
def assert_no_trade_env_leaked() -> None:
    """Startup guardrail: raise if any MEXC_TRADE__* env var is present (D-16)."""
    leaked = [k for k in os.environ if k.startswith("MEXC_TRADE__")]
    if leaked:
        raise RuntimeError(
            f"FATAL: trade-only env vars visible to data-platform: {leaked}. "
            f"Check Railway service-scoping; MEXC_TRADE__* must only exist on strategy-engine."
        )
```

**Phase 1 obligation:** `data-platform` entrypoint already calls `assert_no_trade_env_leaked()` at line 43. Phase 1 must NOT remove this; new R2 / Telegram secrets are read-only and do not change the trade-env boundary.

---

### Error Handling

**Source:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/domain/market.py` lines 51-69

**Apply to:** Every new Pydantic schema in `ingest/{mexc,coinglass,coingecko}/schemas.py`.

```python
@model_validator(mode="after")
def _reject_naive_ts(self) -> Self:
    if self.ts.tzinfo is None:
        raise ValueError("Candle.ts must be timezone-aware (UTC)")
    return self
```

**At ingest boundaries (RESEARCH.md §2 Pattern 2):** Wrap every API call so that:
- Pydantic `ValidationError` → write to `dead_letter` via `dead_letter.writer.write_to_dead_letter(...)`
- 4xx-non-429 → write to `dead_letter`, do NOT raise (tenacity would retry on raise)
- 5xx / 429 / transport errors → raise, tenacity retries with `wait_exponential_jitter`
- Exhausted retries → write to `dead_letter` then re-raise

---

### Validation

**Source:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/domain/market.py` lines 39 + 31-39 (`ConfigDict(frozen=True, strict=True)`)

**Apply to:** All new ingest schemas.

```python
model_config = ConfigDict(frozen=True, strict=True)
```

**Conventions (locked in domain/market.py docstring):**
- D-09 money fields use `Decimal` exclusively — no float
- D-10 enum-like fields use `Literal[...]`
- D-11 collection fields on frozen models use `tuple[X, ...]` not `list[X]`
- D-12 timestamps reject naive datetime via `@model_validator(mode='after')`

---

### Logging (structlog + correlation-id)

**Source:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/observability/logging.py` lines 50-102

**Apply to:** Every new ingest module — never use `print()` or `logging.getLogger(...)` directly with bare strings.

```python
import structlog
log = structlog.get_logger("ingest.mexc.live_candles")

log.info("ingest.started", source="mexc_native", dataset="candles_1m", symbol=symbol)
```

**`assert_event_registered("ingest.started")` MUST be called before first emit (Phase 0 guard).** All Phase 1 events register in `events.py` first (Group 10 above).

---

### Idempotent SQL writes (hot-path)

**Source:** RESEARCH.md §2 Pattern 1 (skeleton in `src/shortfire/ingest/storage/copy.py` — to be authored)

**Apply to:** Every hypertable insert in Phase 1.

```python
async def copy_into_hypertable(
    engine: AsyncEngine,
    target_table: str,
    records: Iterable[tuple[Any, ...]],
    columns: tuple[str, ...],
    conflict_columns: tuple[str, ...],
) -> int:
    """COPY → UNLOGGED staging → INSERT … ON CONFLICT DO NOTHING. Returns row count.

    D-62/D-70: staging is per-session (UNLOGGED) for speed; conflict policy is
    DO NOTHING (first-write-wins) per D-62. Never DO UPDATE.
    """
```

**Repo implementations** (`mexc/backfill.py`, `mexc/live_candles.py`, `coinglass/*.py`, etc.) all delegate to this single function — they only assemble the records tuple. Conflict columns per D-58 PK column list.

---

### Migration testing (testcontainers)

**Source:** `/Users/mishanikhinkirtill/Desktop/ShortFIRE/tests/integration/conftest.py` lines 87-171

**Apply to:** Every new integration test in `tests/integration/ingest/`.

Reuse the session-scoped fixtures verbatim:
```python
@pytest.fixture(scope="session")
def timescale_container() -> Generator[PostgresContainer, None, None]:
    if not _DOCKER_OK:
        pytest.skip("Docker not available — integration tests require Docker (Assumption A4)")
    with PostgresContainer(_TIMESCALE_IMAGE) as container:
        yield container
```

Per-test cleanup follows `clean_service_event` shape (lines 148-171) — TRUNCATE the target hypertable(s) before and after each test.

---

## No Analog Found

| File | Role | Data Flow | Reason | Fallback |
|------|------|-----------|--------|----------|
| `docs/RESTORE.md` | docs | — | No `docs/` directory exists yet; first prose deliverable | Planner writes from D-82 spec; checklist-style; runnable steps using testcontainers from `tests/integration/conftest.py` |

**Every other Phase 1 file has at least one strong Phase 0 analog.** This is by design — Phase 0 was scoped specifically to seed Phase 1 patterns (FOUND-08 Protocols, D-27 TimescaleDB helpers, D-29 Base+naming convention, D-31 testcontainers harness, Phase 0 pre-commit grep guards, the 4 base metrics + custom REGISTRY).

---

## Metadata

**Analog search scope:**
- `/Users/mishanikhinkirtill/Desktop/ShortFIRE/src/shortfire/` (all subpackages)
- `/Users/mishanikhinkirtill/Desktop/ShortFIRE/alembic/versions/`
- `/Users/mishanikhinkirtill/Desktop/ShortFIRE/tests/` (unit + integration + fakes + conftest)
- `/Users/mishanikhinkirtill/Desktop/ShortFIRE/.planning/phases/00-foundation/` (cross-reference D-01..D-34)

**Files scanned:** 34 Python modules (src) + 2 Alembic migrations + 18 test files + 2 fixture/conftest files + 4 settings files = 60 total

**Pattern extraction date:** 2026-05-21

**Phase 0 anchors that drove every decision:**
- D-06/FOUND-08: Protocol seams `src/shortfire/clients/{mexc,coinglass,coingecko,repos}.py`
- D-27: TimescaleDB helpers in `src/shortfire/db/timescale.py` (NEVER raw `op.execute` for hypertable/compression DDL; carve-out only for 0014 continuous aggregates)
- D-28: Alembic migration shape `alembic/versions/0002_service_event_hypertable.py`
- D-29: SQLAlchemy `Base` + NAMING_CONVENTION in `src/shortfire/db/base.py`
- D-30: asyncpg is the sole driver
- D-31: testcontainers session-scoped fixtures in `tests/integration/conftest.py`
- D-16/D-18/D-21: Settings anti-leak + safe_summary in `src/shortfire/settings/data_platform.py`
- UI-SPEC §Metric registry: custom `CollectorRegistry` + 4 base metrics in `src/shortfire/observability/metrics.py`
- UI-SPEC §Event Taxonomy: `EVENTS` frozenset + `assert_event_registered` in `src/shortfire/observability/events.py`
