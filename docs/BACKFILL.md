# Historical Backfill — Phase 1 Data Platform

One-shot operational runbook for backfilling 1–2 years of MEXC OHLCV, funding, and OI history
into the production TimescaleDB warehouse (CONTEXT.md D-38 scope; STOR-08 requirement).

This is **NOT a scheduled cron job** — it runs from a developer machine against the production
`DATABASE_URL`. Once the backfill completes, the live ingest scheduled in plan 01-08 keeps the
warehouse current going forward.

## Why Not a Railway Cron?

- Backfill is a multi-hour batch task (see wall-clock estimate below). Railway service restarts
  during long-running jobs cause partial-completion drift (mitigated by idempotent
  `ON CONFLICT DO NOTHING`, but the unnecessary churn adds noise to `ingest_runs`).
- The MEXC public REST quota (20 req/s) is shared by the `data-platform` live service AND the
  backfill. Running both concurrently risks rate-limit pressure on live ingest.
- Backfill state (`ingest_runs.kv_state` cursor) is most observable from a local terminal where
  the operator can watch `structlog` NDJSON output in real time and interrupt cleanly via Ctrl-C.
  A Railway cron failure is harder to inspect mid-run.

## Scope (D-38)

| Source | Timeframes | Depth | Notes |
|--------|-----------|-------|-------|
| MEXC OHLCV | 1m, 1d | 1 yr minimum, 2 yr aspirational | 5m/15m/1h/4h materialize from continuous aggregates over 1m base (D-67) |
| MEXC funding | settlement cadence | Full available depth | `fetch_funding_rate_history` paginates REST |
| MEXC open interest | hourly | Full available depth | `fetch_open_interest_history` REST |
| Coinglass aggregates | 1m | ~6 days only (Hobbyist tier per D-35) | 5m+/15m+/1h+ months-deep; daily full |
| L2 top-20, trades, liquidations | — | Forward-capture only | No backfill possible (D-39) |

## Prerequisites

- Local dev machine with `uv` + Python 3.12 and `postgresql-client-16` installed
- `.env.local` (or shell export) populated with production `DATABASE_URL` and `MEXC__READ_KEY` /
  `MEXC__READ_SECRET` values (use a Railway SSH tunnel or copy from Railway Variables)
- The production DB is already at Alembic revision `0014` (`alembic upgrade head` ran via
  Railway `preDeployCommand` on the most recent deploy)
- Pre-commit hooks installed: `pre-commit install` (Phase 0 grep guards are active)

## Steps

1. **Build the qualifying universe at backfill-start time**

   Run the universe-snapshot job once to populate the `symbols` table with the current qualifying
   set before the backfill cursor starts:

   ```bash
   DATABASE_URL=<prod_dsn> uv run python - <<'PYEOF'
   import asyncio
   from shortfire.settings.data_platform import DataPlatformSettings
   from shortfire.ingest.mexc.client import build_mexc_swap_client
   from shortfire.ingest.universe.snapshot import universe_snapshot_job
   from shortfire.db.engine import create_engine_from_env

   async def main() -> None:
       engine = create_engine_from_env()
       settings = DataPlatformSettings()
       client = build_mexc_swap_client(settings)
       try:
           await universe_snapshot_job(engine, client, None)
           print("universe snapshot done")
       finally:
           await client.close()
           await engine.dispose()

   asyncio.run(main())
   PYEOF
   ```

   Verify row count: `psql "$DATABASE_URL" -c "SELECT count(*) FROM symbols WHERE delisted_at IS NULL"`

2. **Run OHLCV backfill — 1m and 1d timeframes (one year)**

   5m/15m/1h/4h candles are continuous aggregates over `raw_mexc_candles_1m` (D-67) and are
   **NOT** backfilled directly — they materialize automatically in step 5.

   ```bash
   DATABASE_URL=<prod_dsn> \
   MEXC__READ_KEY=<key> \
   MEXC__READ_SECRET=<secret> \
   uv run python - <<'PYEOF'
   import asyncio
   from datetime import datetime, timezone, timedelta
   from sqlalchemy import text
   from shortfire.settings.data_platform import DataPlatformSettings
   from shortfire.ingest.mexc.client import build_mexc_swap_client
   from shortfire.ingest.mexc.backfill import backfill_universe
   from shortfire.db.engine import create_engine_from_env

   async def main() -> None:
       engine = create_engine_from_env()
       settings = DataPlatformSettings()
       client = build_mexc_swap_client(settings)
       try:
           async with engine.connect() as conn:
               rows = await conn.execute(
                   text("SELECT symbol FROM symbols WHERE delisted_at IS NULL ORDER BY tier ASC, symbol ASC")
               )
               symbols = [r[0] for r in rows]
           print(f"Backfilling {len(symbols)} symbols...")
           since = datetime.now(timezone.utc) - timedelta(days=365)
           until = datetime.now(timezone.utc)
           results = await backfill_universe(
               engine, client, symbols,
               timeframes=["1m", "1d"],
               since=since, until=until,
               max_concurrency=8,
           )
           total = sum(results.values())
           print(f"Done: rows_written={total}")
       finally:
           await client.close()
           await engine.dispose()

   asyncio.run(main())
   PYEOF
   ```

   **Wall-clock estimate:** ~200 symbols × 525 600 1m candles (365 days) × paginated REST
   (1 000 candles/page, ~1 s/page under 18 req/s limiter) = **~8–12 hours** for 1 year.
   For 2 years roughly double. Plan an **overnight run**.

   The backfill is **idempotent** via `ON CONFLICT (symbol, ts) DO NOTHING` (D-62 / STOR-08).
   Partial completion can be resumed by re-running the same command — already-ingested rows
   are silent no-ops.

3. **Run funding history backfill**

   ```bash
   DATABASE_URL=<prod_dsn> \
   MEXC__READ_KEY=<key> \
   MEXC__READ_SECRET=<secret> \
   uv run python - <<'PYEOF'
   import asyncio
   from datetime import datetime, timezone, timedelta
   from sqlalchemy import text
   from shortfire.settings.data_platform import DataPlatformSettings
   from shortfire.ingest.mexc.client import build_mexc_swap_client
   from shortfire.ingest.mexc.backfill import backfill_funding
   from shortfire.db.engine import create_engine_from_env

   async def main() -> None:
       engine = create_engine_from_env()
       settings = DataPlatformSettings()
       client = build_mexc_swap_client(settings)
       sem = asyncio.Semaphore(8)
       try:
           async with engine.connect() as conn:
               rows = await conn.execute(
                   text("SELECT symbol FROM symbols WHERE delisted_at IS NULL ORDER BY symbol")
               )
               symbols = [r[0] for r in rows]
           since = datetime.now(timezone.utc) - timedelta(days=365)
           until = datetime.now(timezone.utc)
           async with asyncio.TaskGroup() as tg:
               for sym in symbols:
                   tg.create_task(
                       backfill_funding(engine, client, sym, since, until, sem),
                       name=f"funding.{sym}",
                   )
           print("Funding backfill done")
       finally:
           await client.close()
           await engine.dispose()

   asyncio.run(main())
   PYEOF
   ```

4. **Run open-interest backfill** (hourly granularity, REST endpoint)

   MEXC OI history is available hourly via `fetch_open_interest_history`. The live scheduler
   in plan 01-08 runs an OI round-robin every hour going forward. For the historical backfill,
   run the scheduler's `ingest_oi_round_robin` job once per symbol manually, or implement a
   loop following the same `backfill_funding` pattern using `backfill_oi` (to be extracted
   from the scheduler in a Phase 1.x patch if the inline round-robin is not directly callable):

   ```bash
   # Placeholder: follow the backfill_funding pattern above, substituting
   # client.fetch_open_interest_history and raw_mexc_oi target table.
   # Check src/shortfire/ingest/mexc/backfill.py for the canonical helper
   # once a dedicated backfill_oi function is available.
   echo "OI backfill: use backfill_oi helper (Phase 1.x) or adapt the funding pattern above"
   ```

5. **Refresh continuous aggregates for the historical window**

   After the OHLCV backfill completes, refresh the 5m/15m/1h/4h continuous aggregates to
   materialize the full historical window:

   ```bash
   PGPASSWORD=<password> psql -h <prod_host> -U <user> -d shortfire <<'SQL'
   CALL refresh_continuous_aggregate('raw_mexc_candles_5m',  NULL, NULL);
   CALL refresh_continuous_aggregate('raw_mexc_candles_15m', NULL, NULL);
   CALL refresh_continuous_aggregate('raw_mexc_candles_1h',  NULL, NULL);
   CALL refresh_continuous_aggregate('raw_mexc_candles_4h',  NULL, NULL);
   SQL
   ```

   This may take 10–30 minutes on a full 1-year window. TimescaleDB processes it
   incrementally — if interrupted, re-run the same `CALL` to resume.

6. **Final sanity row counts** (paste into `01-11-SUMMARY.md` for the W5 gate)

   ```bash
   PGPASSWORD=<password> psql -h <prod_host> -U <user> -d shortfire -tA <<'SQL'
   SELECT 'raw_mexc_candles_1m'    AS t, count(*) FROM raw_mexc_candles_1m;
   SELECT 'raw_mexc_candles_1d'    AS t, count(*) FROM raw_mexc_candles_1d;
   SELECT 'raw_mexc_candles_5m'    AS t, count(*) FROM raw_mexc_candles_5m;
   SELECT 'raw_mexc_funding'       AS t, count(*) FROM raw_mexc_funding;
   SELECT 'raw_mexc_oi'            AS t, count(*) FROM raw_mexc_oi;
   SELECT 'universe_snapshots'     AS t, count(*) FROM universe_snapshots;
   SQL
   ```

   Expected minimum counts for 1 year × ~200 qualifying symbols:

   | Table | Expected minimum | Rationale |
   |-------|-----------------|-----------|
   | `raw_mexc_candles_1m` | ≥ 89.4M | 365 × 1440 × 200 × 0.85 effective coverage |
   | `raw_mexc_candles_1d` | ≥ 62K | 365 × 200 × 0.85 |
   | `raw_mexc_funding` | ≥ 186K | 365 × 3 settlements/day × 200 × 0.85 |
   | `raw_mexc_oi` | ≥ 1.49M | 365 × 24 × 200 × 0.85 |
   | `universe_snapshots` | ≥ 200 | at least one daily snapshot row per symbol |

## Caveats

- **MEXC rate limit**: the `MEXC_LIMITER(18, 1)` from plan 01-01 caps at 18 req/s. The actual
  MEXC quota is 20 req/s. The 10% headroom is intentional so backfill and live ingest can
  coexist without tripping the exchange-level throttle.

- **Gap detection**: after backfill completes, run `flag_gap(...)` (plan 01-08 helper) for any
  `(symbol, minute)` bucket missing in real history — surfaces in `quality_flag='gap_detected'`
  rows for Phase 2 features to branch on. MEXC de-listings and maintenance windows are the
  most common gap sources.

- **Concurrent live ingest**: it is SAFE to run the backfill against the prod DB while the
  Railway `data-platform` service is running live ingest (idempotent COPY + first-write-wins,
  D-62). L2 snapshots, trades, and live-funding rows being written in parallel do not conflict.

- **Coinglass Hobbyist tier (D-35)**: `raw_coinglass_*` 1m-granularity tables receive at most
  ~6 days of history under the Hobbyist subscription (~$35/mo). 5m+/15m+/1h+ history is
  months-deep. The Standard tier ($299/mo) upgrade is V2-DATA-01, deferred to Phase 2 EDA.

- **Resumability**: re-running any step is always safe. `ON CONFLICT DO NOTHING` makes every
  write idempotent. The cursor in `ingest_runs.kv_state` is updated only after each page
  commits, so a crash mid-page at most re-inserts one page worth of no-ops.
