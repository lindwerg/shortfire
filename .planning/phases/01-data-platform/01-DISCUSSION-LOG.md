# Phase 1: Data Platform - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `01-CONTEXT.md` — this log preserves the alternatives considered.

**Date:** 2026-05-21
**Phase:** 01-Data Platform
**Mode:** `--auto --all` (autonomous, single-pass) — user invoked `/gsd:discuss-phase 1` with the directive «все на автомате с множеством итераций с помощью МСП thinking и МСП Context7! сам все области собери и пройдись по ним максимально детально»
**Areas discussed:** Subscription Reconciliation, ccxt MEXC Integration, Coinglass v4 Integration, CoinGecko Integration, Storage Schema, Universe Snapshots, Idempotency & Dead-Letter, Retry & Rate-Limit, APScheduler Orchestration, Backup & Restore, Observability Extensions, Service Topology, Test Strategy, Code Organization & Migrations

---

## Subscription Reconciliation (precondition lock)

| Option | Description | Selected |
|--------|-------------|----------|
| Stick with $79 Startup tier (per REQUIREMENTS.md DATA-07) | Match the docs as written; assume user budgets $79/mo | |
| Override with user's actual ~$35 Hobbyist tier; patch docs in Phase 1 | Reflect reality: 30 req/min, 6-day 1m derivatives window | ✓ |

**User's choice:** Override (auto-selected — recommended default given memory `project_data_tier_subscriptions.md`).
**Notes:** D-35..D-37 lock the override; D-38 spells out the corresponding backfill scope; the Coinglass Standard ($299/mo) upgrade decision stays deferred to Phase 2 EDA per existing project gate.

---

## ccxt MEXC Integration

| Option | Description | Selected |
|--------|-------------|----------|
| `watch_trades` → client-side OHLCV aggregator | Recommended per STACK.md + Pitfall 11 (`watch_ohlcv` hang on MEXC, ccxt#27253) | ✓ |
| `watch_ohlcv` directly | Simpler but documented-broken on MEXC swap in current ccxt minors | |
| REST polling only | Safe fallback but high quota burn at 200-symbol scale | |

**User's choice:** `watch_trades` + client-side aggregator (D-43); REST `fetch_ohlcv` for backfill only (D-42).
**Notes:** Pinned ccxt to `>=4.5.54,<4.6` (D-41) to avoid minor-version MEXC swap endpoint drift (#28532). Tier-1 (top 50 by 7d volume) gets 5s L2 sampling; rest gets 10s (D-46). All long-lived ws tasks via `asyncio.TaskGroup` (Pitfall 27).

---

## Coinglass v4 Integration

| Option | Description | Selected |
|--------|-------------|----------|
| Per-endpoint aiolimiter pool | Maximum fairness across endpoints | |
| Single global aiolimiter at 28 req/min (5% headroom under 30/min Hobbyist) | Coinglass does not document per-endpoint sub-limits — global is simpler and safer | ✓ |
| No rate limiter, rely on Coinglass 429 responses | Risks losing quota mid-pump, no graceful fallback | |

**User's choice:** Single global limiter at 28/min (D-51).
**Notes:** 4 endpoints (funding-rate-list, OI history, liquidation history, long/short ratio) with cadences 5/5/10/15 min respectively (D-53); Pydantic schemas per endpoint with dead-letter fallback (D-52); 1m derivatives backfill explicitly capped at 6 days (D-54).

---

## CoinGecko Integration

| Option | Description | Selected |
|--------|-------------|----------|
| Daily-only universe metadata refresh @ 28 req/min limiter | Within Demo tier; meets DATA-08 + UNIV requirements | ✓ |
| Per-minute polling of `/coins/markets` for live caps | Burns quota with no edge gain | |

**User's choice:** Daily refresh at 00:30 UTC (D-55, D-77).
**Notes:** Schema = `raw_coingecko_market(symbol, ts, source='coingecko', price_usd, volume_24h_usd, market_cap_usd, category, listing_date, raw_payload JSONB)` (D-57). Limiter mirrors Coinglass at 28/min (D-56) — planner verifies actual key tier at plan-phase entry.

---

## Storage Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Universal narrow `(symbol, ts, metric, value)` EAV | "Future-proof" but 5–10× storage tax, JOIN tax forever | |
| Typed-per-source hypertables, one per (source, dataset) | ARCHITECTURE.md Pattern 2; STOR-02 explicit rejection of EAV | ✓ |
| Typed-per-source narrow rows for L2 (40 rows per snapshot) | Cleaner schema but 1.26B rows for 1yr | |
| Typed-per-source wide JSONB for L2 (`bids`, `asks` arrays per snapshot) | 600M rows for 1yr, slippage book-walk in Phase 3 trivial | ✓ |

**User's choice:** Typed-per-source hypertables; wide JSONB for L2 (D-58).
**Notes:** Complete table list with chunk_interval / segment_by / compress-after settings spelled out in D-58. `source` column with CHECK enum on every derivatives row (D-59); `quality_flag` enum on every raw table (D-60); `ingested_at` audit column (D-61). One 1d hypertable independently captured for cross-validation against 1m sum.

---

## Universe Snapshots (Pitfall 1)

| Option | Description | Selected |
|--------|-------------|----------|
| Refresh "currently listed" universe on demand | Pitfall 1 incarnate — survivorship-biased training data | |
| Daily `universe_snapshots` hypertable from commit-zero | UNIV-01..04 + Pitfall 1 mitigation; point-in-time correctness | ✓ |

**User's choice:** Daily snapshot hypertable (D-64), refreshed at 00:05 UTC by APScheduler job (D-77).
**Notes:** New-listing detection within 24h via day-over-day diff (D-64, UNIV-04). Soft-delete on `symbols` table via `delisted_at` (D-63, STOR-07). Hypothesis property test asserts point-in-time correctness (D-92).

---

## Idempotency & Dead-Letter

| Option | Description | Selected |
|--------|-------------|----------|
| `ON CONFLICT DO UPDATE SET ingested_at = EXCLUDED.ingested_at` | Tracks re-ingest stamps but rewrites first-write payloads | |
| `ON CONFLICT DO NOTHING` (first-write wins) | Truly idempotent; re-ingest never overwrites; matches DATA-09 semantics | ✓ |
| Catch `UniqueViolation` per-row | Slow and noisy at COPY scale | |

**User's choice:** Staging-table COPY → `INSERT … ON CONFLICT (symbol, ts, source) DO NOTHING` (D-62).
**Notes:** Validation failures + exhausted retries → `dead_letter` hypertable (D-74); threshold-based Telegram alert (D-87).

---

## Retry & Rate-Limit

| Option | Description | Selected |
|--------|-------------|----------|
| tenacity per-source policies (exponential + jitter, retry on 5xx/429/transport, max 5/120s) + aiolimiter above retry | Standard pattern; matches DATA-10 | ✓ |
| Hand-rolled retry loops | Reinventing tenacity for no gain | |
| Disable aiolimiter, trust ccxt's internal throttler | Single point of failure; STACK.md flags per-endpoint budgets matter | |

**User's choice:** tenacity + aiolimiter (D-72, D-73). ccxt's internal throttler stays ON for defense-in-depth.

---

## APScheduler Orchestration

| Option | Description | Selected |
|--------|-------------|----------|
| APScheduler 3.x `PostgresJobStore` | Older API name in REQUIREMENTS.md ORCH-01 wording | |
| APScheduler 4.x `AsyncScheduler` + `SQLAlchemyDataStore(engine)` + `AsyncpgEventBroker.from_async_sqla_engine(engine)` | Verified via Context7; matches STACK.md "APScheduler 4.x"; shares Phase 0 engine | ✓ |
| Prefect 3 self-hosted | V2-INFRA-01; overkill for Phase 1 cadences | |

**User's choice:** APScheduler 4 `AsyncScheduler` (D-75, D-76). Job graph spelled out in D-77 (15 scheduled jobs + 5 continuous ws tasks managed via `asyncio.TaskGroup`).
**Notes:** Critical — REQUIREMENTS.md ORCH-01 says "PostgresJobStore" but that's APScheduler 3.x nomenclature; Phase 1 code MUST use the v4 class names (`AsyncScheduler` + `SQLAlchemyDataStore`). Continuous ws tasks live in FastAPI `lifespan`, NOT in APScheduler (D-78).

---

## Backup & Restore

| Option | Description | Selected |
|--------|-------------|----------|
| Rely on Railway managed PG backups only | Single-vendor concentration; matches some but not all of STOR-10 | |
| Daily `pg_dump --format=custom --compress=zstd:9` → Cloudflare R2 | $0 egress on restores (vs B2's egress charge); STOR-10 satisfied | ✓ |
| Daily pg_dump → Backblaze B2 | Cheaper storage but egress on restore | |

**User's choice:** R2 (D-80). Retention 7 daily + 4 weekly + 6 monthly + indefinite annual (D-81); ~$2.55/mo at expected size. Restore drill documented in `docs/RESTORE.md` (D-82); first manual drill during Phase 1 verification.

---

## Observability Extensions

| Option | Description | Selected |
|--------|-------------|----------|
| Add 8 Prometheus metric families + 17 event taxonomy entries on the existing custom registry | Continues Phase 0 UI-SPEC contract; no new registry | ✓ |
| Spin up a separate registry for ingest metrics | Fragments Grafana scrape | |
| Skip new metrics until Phase 5 Grafana lands | Violates ORCH-03 freshness gauge requirement | |

**User's choice:** Extend existing registry (D-84) + extend `EVENTS` frozenset (D-85). Telegram alerts for Phase 1 use raw httpx Bot API calls (D-86) — no `python-telegram-bot` framework until Phase 4.
**Notes:** Severity routing per UI-SPEC carries forward (D-87).

---

## Service Topology

| Option | Description | Selected |
|--------|-------------|----------|
| 3 services unchanged (Phase 0 carry-forward) | `data-platform` (always-on, does the work) + `strategy-engine` + `dashboard` (idle placeholders) | ✓ |
| Add `risk-guard` 4th service now | Phase 5 work — premature | |
| Split per-source data-platform sub-services | Pure overhead at solo scale | |

**User's choice:** No change (D-88). `risk-guard` enters in Phase 5. Resource ceiling bumped only on observed OOM/throttle (D-90).

---

## Test Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Drop coverage gate on `ingest/` until Phase 2 | Defers visibility; weakens TEST-04 | |
| Keep 80% gate by removing `src/shortfire/ingest/*` from pyproject `omit` | Forces real test coverage in Phase 1 | ✓ |

**User's choice:** Tighten coverage gate (D-91). Phase 1 testing layers: unit + integration (testcontainers PG+Timescale) + nightly contract job + Hypothesis property tests (D-92, D-93, D-94).

---

## Code Organization & Migrations

| Option | Description | Selected |
|--------|-------------|----------|
| One giant migration adding all Phase 1 tables | Hard to review, hard to debug, hard to roll back | |
| 12 small migrations (one logical schema unit each) | Small blast radius per migration; clear blame trail | ✓ |

**User's choice:** Migrations 0003 → 0014, one schema unit each (D-96). Code organization spelled out in D-95 — populates the empty `src/shortfire/ingest/` from Phase 0 and adds `db/models/`, `observability/telegram.py`, `ingest/scheduler/`.
**Notes:** Lone D-27 carve-out: migration 0014 (continuous aggregates) — planner decides between (a) adding `create_continuous_aggregate` helper to `shortfire.db.timescale` (disciplined) or (b) raw `op.execute` with inline justification (faster).

---

## Claude's Discretion

The user delegated ALL gray-area choices to Claude under `--auto --all`. Decisions D-35..D-96 were resolved by Claude using:

- Context7-verified ccxt 4.5 / TimescaleDB 2.18 / APScheduler 4 APIs
- Phase 0 carry-forward patterns (D-01..D-34) — no rebuilding
- Memory-tracked subscription override (`project_data_tier_subscriptions.md`)
- PITFALLS.md Pitfalls 1, 4, 11, 16, 17, 21, 26, 27 — explicit mitigations on every choice
- ARCHITECTURE.md Patterns 1, 2, 5, 6 + Anti-Patterns 1, 4, 5, 6

Items intentionally left to planning-time resolution by `gsd-phase-researcher` / `gsd-planner`:

- Exact SQLAlchemy table-model class names for the relational lookup tables
- Precise JSONB structure for L2 `bids`/`asks` arrays beyond "array of `[price, qty]` tuples"
- Exact `wait_exponential_jitter(initial=..., max=...)` values per source
- Whether to add a `create_continuous_aggregate` helper or accept one raw `op.execute` in migration 0014
- Specific Prometheus Gauge label vocabulary beyond what D-84 names
- Whether `python-telegram-bot` 21.x is brought in earlier than Phase 4 if Phase 1 ends up needing inline-button confirmations for new-listing alerts (currently locked NO per D-86)

## Deferred Ideas

Captured in `01-CONTEXT.md` `<deferred>` block. Key categories:

- **Phase 2 EDA gates:** Coinglass Standard tier upgrade, per-Coinglass-source attribution split
- **V2 milestones:** Multi-exchange ingest, ClickHouse migration, Prefect 3 migration, backtest-grade L2 reconstruction, retention policies
- **Phase 4/5 milestones:** `python-telegram-bot` framework adoption, MEXC IP allowlist on `TRADE_KEY`
- **Must-do at plan-phase entry:** Patch ROADMAP.md / REQUIREMENTS.md to reflect Hobbyist tier; verify actual CoinGecko key tier
