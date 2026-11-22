# Local operations

Run these commands from the repository root with the same Compose project and environment as the data you intend to maintain. The migration container has database administrator privileges. The API and detection worker retain their existing database roles.

## Expire processed telemetry

Choose the project UUID from its workspace or project API response. Preview the next batch, then run the same command with `--apply` to commit that batch:

```sh
docker compose run --rm migrate python -m api_sentinel.retention --project PROJECT_UUID --days 30 --limit 500
docker compose run --rm migrate python -m api_sentinel.retention --project PROJECT_UUID --days 30 --limit 500 --apply
```

The project is required. Days default to 30 (range 1–3650) and batch size defaults to 500 (range 1–1000). Age is measured from the database receipt timestamp. The oldest eligible events are selected first. Preview counts at most one batch. Apply skips locked rows and commits one transaction. A zero result can also mean eligible rows were locked. Retry later if workers or another cleanup were active. An operator can schedule this command per project. Normal stack startup never schedules expiry.

Only events whose job succeeded are eligible. Pending, running and dead jobs remain available for processing or diagnosis. Deleting an event also removes its job, delivery ID, and associated finding or evidence rows through the existing foreign keys and triggers. A replay can be accepted again if its timestamp is still within the ingestion window. An alert disappears from the summary when its last finding expires. The incident, alert link, investigator timeline, project audit, source names and sequence counters remain. Archive before expiry if the underlying observations must be recoverable.

## Diagnose a worker or database outage

```sh
python scripts/smoke.py
docker compose exec -T worker python -m api_sentinel.worker --status
docker compose logs --tail 30 worker
```

The public liveness endpoint reports API availability. Readiness runs a database query. Detailed queue counts require operator access to the worker container. `due_pending` counts pending jobs available for immediate work. `expired_leases` counts abandoned running jobs eligible for reclaim. `oldest_open_seconds` includes delayed and leased jobs. Compare successive readings alongside the dead-job count. These aggregate values contain no event identifiers or account data.

Stopping the worker finishes the current transaction or leaves an uncompleted claim for lease recovery. Look for the structured worker states `started`, `database_unavailable` and `stopped` on graceful shutdown. A forced termination may have no final log. A new worker can reclaim expired jobs after the 30-second lease. The [worker processing guide](event-ingestion.md#worker-processing) describes retries.

To exercise failure recovery on a disposable stack:

```sh
docker compose stop db
python scripts/smoke.py --db-down
docker compose up -d --wait
docker compose restart worker
python scripts/smoke.py
docker compose exec -T worker python -m api_sentinel.worker --status
```

## Back up, verify and recover

Choose a new filename in a private directory outside the checkout. The helper writes PostgreSQL's binary custom archive directly and refuses to overwrite an existing file. Dumps contain private telemetry, incident notes, identity records and credential hashes. Protect the archive and store the matching service credentials and event HMAC key separately. A database dump alone does not recreate PostgreSQL cluster roles.

```sh
python scripts/database_backup.py create ../sentinel-before-upgrade.dump
python scripts/database_backup.py verify ../sentinel-before-upgrade.dump
```

Verify only archives produced by a trusted operator. Verification restores into a newly named database in the same Compose cluster in one transaction. It checks that the restored Alembic revision matches the checkout, that every event has a job and that every incident has its current timeline entry. It prints aggregate counts and drops the rehearsal database on normal exit or failure. A hard interruption can leave an incomplete archive or a database prefixed `sentinel_restore_`. Inspect the database name and active maintenance processes before removing it. The rehearsal checks logical database recovery on the current cluster. It does not exercise recovery of the Docker host or separately stored secrets.

Before schema changes, verify the archive with the matching checkout. Apply migrations with `docker compose run --rm --build migrate`, then run `docker compose run --rm migrate alembic current --check-heads` and `docker compose run --rm migrate alembic check`. Revision `0011_event_retention` builds the project receipt-time index. Allow a maintenance window for the index build on a populated database. Downgrading this revision removes only that index. Earlier revisions may discard telemetry or refuse to downgrade when audit and incident history exists.

For recovery, keep the original volume offline. Use a separate, compatible PostgreSQL 16 cluster with the expected roles and matching secrets. Restore the trusted archive with `pg_restore --single-transaction` into an empty database, run the matching Alembic and integrity checks there, and verify application sign-in, worker access and incident history before redirecting clients. A restored snapshot can reinstate accounts, sessions or keys that were revoked after the backup. Reconcile those changes before exposing the recovered stack.
