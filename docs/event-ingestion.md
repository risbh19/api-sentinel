# Security event ingestion

`POST /api/v1/ingest/events` accepts uncompressed `application/json` with a
project ingestion key in `Authorization: Bearer ...`. The credential determines
the project. A web session alone cannot submit events; a machine key cannot
read events or access the workspace. An already authorized in-flight request
finishes before a concurrent revocation completes; subsequent requests fail.

## Wire contract

```json
{
  "source_id": "synthetic-demo-api",
  "events": [{
    "event_id": "synthetic-login-0001",
    "occurred_at": "2026-11-21T00:00:00Z",
    "event_type": "authentication_failure",
    "method": "POST",
    "route_template": "/api/login",
    "status_code": 401,
    "actor_token": "synthetic-user-01",
    "client_token": "synthetic-client-01"
  }]
}
```

The timestamp above is illustrative. Emit a current timestamp when trying it.
Only the listed fields are allowed. Actor/client tokens are optional opaque
labels, using 1–128 ASCII letters, digits, underscores or hyphens. Do not send
usernames, email addresses, IP addresses, credentials, cookies, arbitrary headers,
request bodies, query strings or other sensitive identifiers in any field.
Field syntax cannot establish that an application supplied privacy-safe labels.
The emitter remains responsible for selecting appropriate metadata.

- Up to 128 KiB and 100 events per batch; at least one event is required.
- Source identifiers start with an ASCII letter and contain up to 64 letters,
  digits, underscores or hyphens. The first accepted delivery registers the
  source in that project. All keys for that project may use its sources.
- Event IDs are opaque strings of up to 96 letters, digits, underscores or
  hyphens, starting with a letter or digit. Generate these independently of PII.
- Supported types: `request`, `authentication_failure`, `authorization_denial`.
  Failure/denial types require status 401/403 respectively. Status must be an
  integer from 100 through 599. HTTP methods must be uppercase standard methods.
- Routes use slash-separated names or `{named_parameters}`; numeric literal
  segments, dots, percent escapes, URLs, query strings and control characters are
  rejected. Send `/api/users/{id}` rather than an individual user's URL.
- Timestamps are RFC 3339 strings with a timezone and at most six fractional
  digits. They normalize to UTC and must be within 30 days before the database
  clock and five minutes ahead. Out-of-order events inside that window are valid.

## Atomic delivery and limits

A successful HTTP 200 returns `project_id`, `accepted`, `duplicate`, and
`rejected` counts. Accepted means newly persisted. Rejected is zero on success;
an invalid batch fails as a whole, including otherwise valid entries. Validation
errors return 422 with bounded field paths and a request ID, without rejected
values. Invalid credentials return 401, size overflow 413, unsupported media
415, source capacity 409 and the authenticated project rate limit 429 with
`Retry-After: 60`. Storage failures return 503. These failures commit no events.
The nginx edge may produce its own 413 response before the API sees a large body.

The unique identity is `(project, source_id, event_id)`. Within and across
batches, the first stored version wins; a changed retry never edits an event.
Use the same IDs after an uncertain network result. Every retry still undergoes
validation, including the age check. Different sources/projects have separate
ID namespaces. The local emitter disables proxies and redirects.

Each project permits 32 distinct sources and 60 successful batch transactions
per database-clock minute, shared by all its keys. Duplicate-only successes
count toward this limit. A project row serializes quota checks and event sequence
allocation, including requests using different keys. Invalid bodies and invalid
credentials are size bounded but do not consume the successful-batch quota.
These are fixed local limits, not a public internet abuse-protection claim.

## Reading events

`GET /api/v1/projects/{project_id}/events` requires a session and explicit
timezone-aware `since` and `until` values, inclusive and ordered, at most 30 days
apart. Optional filters are `source`, `event_type`, and `status_code`. `limit`
is 1–100, default 25. Results are newest received sequence first, rather than
event occurrence order. Each entry includes its UUID, source, UTC occurrence
and receipt times, category, method, route and status.

Send the returned `next_cursor` as `after`, preserving the time range and
filters. The authenticated cursor binds project, filters and the first page's
committed sequence ceiling. New deliveries are excluded until refresh. Cursor
tampering, reuse for another project or changed filters returns 400. Changing
the page size is supported. Sequences can have gaps after duplicate deliveries.

All organization roles may read summaries. Owners, analysts and developers may
also call `GET /api/v1/projects/{project_id}/events/{event_id}` for the emitter
event ID, actor/client HMAC pseudonyms and pseudonym key version. Viewers cannot
read these details. Foreign project IDs and event links remain inaccessible.
Responses use `Cache-Control: no-store`; application logs omit payloads and keys.

## Pseudonymization and retention

`SENTINEL_EVENT_HMAC_KEY` is a generated 32-byte key represented by 64 lowercase
hex digits in `.env`. HMAC-SHA-256 incorporates project UUID and separate actor
and client domains. Raw tokens are discarded before persistence. The same label
in two projects or domains yields different pseudonyms. A non-secret 16-character
key fingerprint records the correlation version. Ingestion key rotation leaves
pseudonyms stable. Replacing the HMAC key changes future correlations and
invalidates existing pagination cursors; old records keep their existing hashes.
Back up this configuration with the database and coordinate intentional changes.

The operator can run a bounded expiry job for one project. Preview is the default;
applying a batch explicitly removes only events with successful jobs older than
the receipt-time cutoff. The default retention period is 30 days. See the
[retention and recovery runbook](operations.md) for commands and evidence semantics.

Cleanup removes delivery deduplication records for those rows. Source names and
sequence counters remain; project deletion cascades to sources, counters, keys
and events while retaining the established audit history. Events have no public
update/delete API and the application database role has no event update/delete
grant. Downgrading revision 0006 explicitly discards telemetry; use disposable
databases for rollback tests and back up valuable data first.

## Worker processing

Run `python scripts/init_env.py` on upgrade to add the worker credential. The
Compose bootstrap grants the worker access to job state, the event fields used
by detection rules and finding storage. The API process keeps its own login.

An insert trigger queues each new event in the same transaction. Migration
0007 also queues existing events. Replayed deliveries keep their original job.
Each worker claims up to 16 due jobs using PostgreSQL row locks and skips rows
another worker holds. A claim has a 30-second lease. After a crash, another
worker can claim an expired lease. The attempt number fences stale workers.
Completion and the signed millisecond difference between receipt and occurrence
commit together. A future-dated observation can have a negative delay.

Handler failures roll back partial results and reschedule after 1, 2, 4 or 8
seconds. Five failed or abandoned attempts leave the job in the `dead` state
for operator inspection. Database outages cause the worker to reconnect.
Inspect aggregate job counts and the age of the oldest open job in seconds:

```sh
docker compose exec -T worker python -m api_sentinel.worker --status
```

Operators can inspect `event_jobs.last_error_code` for `processing_failed` or
`lease_expired`. Removing an event also removes its job. Downgrading to 0006
discards job history; re-upgrading queues retained events again. The worker
evaluates the [versioned detection rules](detection-rules.md) in its job transaction.
