# Restore Drill — Phase 1 Data Platform

Documented restore procedure for the daily `pg_dump --format=custom --compress=zstd:9`
backups in Cloudflare R2 (STOR-10, D-80, D-82).

## Prerequisites

- Docker installed locally (for TimescaleDB restore target container)
- Cloudflare R2 credentials with read access to the backup bucket (READ-ONLY API token is sufficient)
- `pg_restore` binary from `postgresql-client-16` (same major version as the Railway PG server)
- AWS CLI configured with R2 endpoint, OR a Python script using boto3 with R2 credentials

## Steps

1. **Spin up a fresh Postgres+TimescaleDB container** (mirrors the Railway environment exactly):

   ```bash
   docker run --rm -d --name shortfire-restore \
     -e POSTGRES_PASSWORD=restore_test \
     -e POSTGRES_DB=shortfire \
     -p 5432:5432 \
     timescale/timescaledb:2.18.0-pg16
   sleep 5
   ```

2. **Download the latest daily dump from R2:**

   ```bash
   aws s3 cp s3://<BUCKET_NAME>/daily/<TIMESTAMP>.dump.zst restore.dump \
     --endpoint-url=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
   ```

   To list available dumps and find the latest timestamp:
   ```bash
   aws s3 ls s3://<BUCKET_NAME>/daily/ \
     --endpoint-url=https://<ACCOUNT_ID>.r2.cloudflarestorage.com \
     | sort | tail -5
   ```

3. **Restore the dump** (CRITICAL: `--no-owner --no-acl` because the restore target has different
   roles than prod):

   ```bash
   PGPASSWORD=restore_test pg_restore \
     --host localhost --port 5432 \
     --username postgres --dbname shortfire \
     --no-owner --no-acl \
     --verbose \
     restore.dump
   ```

4. **Smoke-check hypertables exist:**

   ```bash
   PGPASSWORD=restore_test psql -h localhost -U postgres -d shortfire \
     -c "SELECT hypertable_name FROM timescaledb_information.hypertables ORDER BY hypertable_name"
   ```

   Expected: at least 16 entries (8 MEXC tables + 4 Coinglass + 1 CoinGecko +
   `universe_snapshots` + `dead_letter` + `ingest_runs` + Phase 0 `service_event`).

5. **Smoke-check row counts within expected range** (per-table comparison):

   ```bash
   for tbl in raw_mexc_candles_1m raw_mexc_funding raw_mexc_oi universe_snapshots symbols; do
     echo -n "$tbl: "
     PGPASSWORD=restore_test psql -h localhost -U postgres -d shortfire \
       -tAc "SELECT count(*) FROM $tbl"
   done
   ```

   Compare against production row counts noted at backup creation time. Counts should be
   within ±10% for actively-ingested tables.

6. **Run the integration test suite against the restored DB** to confirm structural integrity:

   ```bash
   DATABASE_URL=postgresql+asyncpg://postgres:restore_test@localhost:5432/shortfire \
     uv run pytest -m integration \
       tests/integration/db/test_alembic_and_hypertables.py \
       tests/integration/db/test_phase1_mexc_schema.py \
       tests/integration/db/test_phase1_aux_schema.py \
       -v
   ```

   Expected: all tests pass against the restored DB. If Alembic tests fail, check that
   TimescaleDB extension was pre-created (the dump includes it, but the target container
   must have TimescaleDB installed — which `timescale/timescaledb:2.18.0-pg16` provides).

7. **Cleanup:**

   ```bash
   docker rm -f shortfire-restore
   rm restore.dump
   ```

## Drill Cadence

Run this checklist **manually at least quarterly** while the platform is in Phase 1–4.
Automate via a `restore.drill` APScheduler cron in Phase 5 once live trading begins
(the drill becomes DR-critical at that point).

## Known Caveats

- `pg_dump` and `pg_restore` MUST be the same major version as the server (PG16).
  The data-platform Dockerfile installs `postgresql-client-16` for this reason
  (RESEARCH.md §17, T-1-BCK-04). If local `pg_restore --version` shows PG15 or earlier,
  install `postgresql-client-16` via your package manager.

- **TimescaleDB continuous aggregates** restore correctly via
  `pg_restore --no-owner --no-acl` on TimescaleDB 2.18 — verified during Phase 1
  plan 01-04 integration testing. The `_timescaledb_*` internal schemas are included
  in the dump and restore automatically.

- **Retention tiers**: the dump named `daily/<ts>.dump.zst` is the most recent backup.
  Weekly/monthly/annual dumps in the R2 bucket are server-side copies of daily dumps
  (D-81 `_sundown_sweep` uses `copy_object`, not re-uploads). Any tier can be used as
  the restore source — they are functionally identical.

- **Backup age**: check `shortfire_data_platform_backup_age_seconds` in Grafana to
  confirm the last backup age before starting a DR drill. If this metric is stale
  (> 26h), investigate `backup.pg_dump` scheduler job before drilling.
