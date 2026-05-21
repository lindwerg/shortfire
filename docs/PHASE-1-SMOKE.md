# Phase 1 Smoke Checklist — Data Platform Live on Railway

Manual verification checklist after Phase 1 code is deployed to Railway (OPS-05 + OPS-06 +
ORCH-01..04 + STOR-10 end-to-end smoke). Mirrors the plan 01-11 Task-2 checkpoint so future
operators can replay the smoke without reading PLAN.md.

## Prerequisites

- Phase 1 plans 01-01 through 01-10 all merged and deployed to Railway `main` branch
- Railway Variables populated on the `data-platform` service per `.env.example` section
  `DATA PLATFORM - Phase 1 secrets` (MEXC READ keys + Coinglass + CoinGecko + Telegram + R2)
- These vars must appear on `data-platform` ONLY — NOT on `strategy-engine` or `dashboard`
  (D-16 anti-leak invariant; `assert_no_trade_env_leaked()` guards trade keys but data keys
  require operator discipline)
- Cloudflare R2 bucket and Telegram bot created per plan 01-10 `user_setup` instructions

## Steps

1. **Trigger a no-op deploy** (commit + push to main to verify auto-deploy, OPS-05):

   ```bash
   git commit --allow-empty -m "smoke: phase 1 deploy verification"
   git push origin main
   ```

   Observe the Railway dashboard — confirm all 3 services (`data-platform`, `strategy-engine`,
   `dashboard`) start a new deploy within 5 minutes. Confirm `data-platform` `preDeployCommand`
   runs `alembic upgrade head` to migration `0014` successfully (check deploy logs).

2. **Verify `/health` endpoints** (OPS-06 — three services live):

   ```bash
   for svc in data-platform strategy-engine dashboard; do
     echo "=== $svc ==="
     curl -s "https://${svc}.up.railway.app/health" | python3 -m json.tool
   done
   ```

   Expect each service returns HTTP 200 with structured JSON containing:
   `status: "ok"`, `service_name`, `version`, `ts` (ISO-8601 UTC), `correlation_id`, `env`.

3. **Verify Phase 1 metric families** on `data-platform/metrics` (D-84):

   ```bash
   curl -s https://data-platform.up.railway.app/metrics \
     | grep -E '^(# HELP|# TYPE) shortfire_data_platform_' \
     | sort -u
   ```

   Expect at least these 8 Phase 1 metric families to be present (even with zero observations,
   `# HELP` / `# TYPE` lines emit at service startup):

   - `shortfire_data_platform_ingest_rows_total`
   - `shortfire_data_platform_ingest_duration_seconds`
   - `shortfire_data_platform_source_freshness_seconds`
   - `shortfire_data_platform_dead_letter_total`
   - `shortfire_data_platform_universe_symbols_count`
   - `shortfire_data_platform_backup_age_seconds`
   - `shortfire_data_platform_ws_reconnects_total`
   - `shortfire_data_platform_rate_limit_remaining`

   Plus the 4 Phase 0 base metrics:
   - `shortfire_data_platform_http_requests_total`
   - `shortfire_data_platform_http_request_duration_seconds`
   - `shortfire_data_platform_service_event_emitted_total`
   - `shortfire_data_platform_build_info`

4. **Verify scheduler started** (ORCH-01 / D-77 — 11-job graph):

   Check Railway `data-platform` logs (filter on `scheduler.started` or
   `scheduler.jobs.registered`). Expect a structlog line with `n_jobs=11`.

   The 11 jobs are (D-77):
   - Universe snapshot (00:05 UTC daily)
   - MEXC 1m OHLCV live (every 1 min)
   - MEXC funding (every 1 min)
   - MEXC OI round-robin (every 1 min)
   - Coinglass funding-agg (every 5 min)
   - Coinglass OI-agg (every 5 min)
   - Coinglass LSR (every 5 min)
   - Coinglass liquidations (every 5 min)
   - CoinGecko market metadata (daily, 01:00 UTC)
   - Freshness alerter (every 5 min)
   - R2 daily backup (01:00 UTC)

5. **Verify universe snapshot ran** (UNIV-01/02 — after 00:05 UTC):

   ```bash
   PGPASSWORD=<prod_pw> psql -h <prod_host> -d shortfire -c "
     SELECT snapshot_date, count(*) FILTER (WHERE is_qualifying) AS qualifying_count
     FROM universe_snapshots
     GROUP BY snapshot_date
     ORDER BY snapshot_date DESC
     LIMIT 5
   "
   ```

   Expect today's row present with `qualifying_count > 0` (typically 150–300 qualifying symbols
   with 24h volume > $500K filter, UNIV-01).

6. **Verify R2 backup ran** (STOR-10 — after 01:00 UTC):

   Check the Cloudflare R2 bucket — expect a fresh object under `daily/<TODAY>.dump.zst`:

   ```bash
   aws s3 ls s3://<BUCKET_NAME>/daily/ \
     --endpoint-url=https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com \
     | sort | tail -3
   ```

   Also check Railway `data-platform` logs for `event=backup.completed`. Check `/metrics` —
   `shortfire_data_platform_backup_age_seconds` should be near `0` immediately after a
   successful backup.

7. **Verify Telegram alerts are silent** (ORCH-04 / D-86):

   Open the operator Telegram chat. During the smoke window (first 30 minutes after deploy)
   expect either:
   - Silence — all sources healthy
   - Only legitimate `stale-data` WARN alerts if a source is temporarily behind (e.g. Coinglass
     API is slow); these should auto-resolve once the scheduler catches up

   No CRIT alerts during the initial smoke window indicates the backup, dead-letter threshold,
   and freshness watchdogs are all below their trip thresholds.

8. **Run the STOR-10 restore drill** (docs/RESTORE.md):

   Follow `docs/RESTORE.md` against the `daily/<TODAY>.dump.zst` from R2. All 6 steps must
   pass and the integration test suite must be green against the restored DB. First-time
   execution establishes the baseline restore time for DR planning.

## Pass Criteria

All 8 steps green = Phase 1 ready for the Phase 1 → Phase 2 transition gate (ROADMAP hard gates).

The mandatory **W5 backfill gate** (ROADMAP success criterion #1) requires additionally:
- Executing the ≥1-year historical backfill per `docs/BACKFILL.md`
- Pasting the row-count table into `01-11-SUMMARY.md` showing each table meets the minimum count
- Spot-checking 5 random symbols × 5 random days for OHLCV invariants

This gate is non-negotiable — "looks good" without concrete numbers is insufficient.

## Cadence

- Run on every Phase 1 → 1.x patch deploy
- Run on every major dependency upgrade (ccxt, apscheduler, boto3, asyncpg)
- Run quarterly while the platform is in Phase 1–4 (ad-hoc but documented here)
- Automate via CI smoke job in Phase 2 once the test harness is mature enough to drive it
