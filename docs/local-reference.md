# Local development and operator reference

## Start locally

Use Git, Docker with Compose v2.20+ and Python 3.11+ for the full verification walkthrough. On Windows, start Docker Desktop in Linux container mode. From PowerShell, Bash or zsh, clone the repository and start the stack:

```sh
git clone https://github.com/risbh19/api-sentinel.git
cd api-sentinel
python scripts/init_env.py
docker compose up --build --wait
docker compose ps
python scripts/smoke.py
```

On Windows, use `py -3.11` in place of `python` if that is how the interpreter is installed. The first build needs network access for the pinned dependencies and base images. The running demo uses local services.

Open [Service status](http://127.0.0.1:8080). The API is available on port
8000. Only the web and API ports are published, both on loopback. Set
`WEB_PORT` or `API_PORT` in .env to change them and pass the corresponding
ports to the smoke script. To inspect processing lag, run
`docker compose exec -T worker python -m api_sentinel.worker --status`.

| Route | Success | Database unavailable |
| --- | --- | --- |
| GET /health/live | 200, status ok | 200, status ok |
| GET /health/ready | 200, status ready | 503, status unavailable |

Compose uses a named database volume. Keep the generated .env with it.
PostgreSQL applies the initialization SQL only when creating an empty
database directory. Editing passwords in .env alone will break the matching
database login. Use `docker compose down` to stop and retain local data.

See the [operations runbook](operations.md) for scoped event expiry, worker lag, backup and restore rehearsal.

## Check database recovery

Use this sequence on your local development stack after startup. It
temporarily stops its database and then verifies recovery through the web
proxy and direct API.

```sh
docker compose stop db
python scripts/smoke.py --db-down
docker compose up -d --wait
python scripts/smoke.py
```

## Sign in and manage project access

After startup, provision your first local owner from a terminal. The command
prompts for a password (12–256 characters) and prints the new user's UUID.

```sh
docker compose run --rm migrate python -m api_sentinel.identity.operator create-user owner@example.test --new-organization "Local team"
```

Open [Project workspace](http://127.0.0.1:8080/#workspace) and sign in with
that account. For an organization created before this migration, replace
`--new-organization "Local team"` with `--organization-id EXISTING_UUID`.
Only an organization with no members can receive its initial owner this way.
Running the command without either option creates an account with no access.

All four roles can list and read projects in their own organizations. Owners
and developers can create projects. Only owners can delete projects or manage
memberships. Project access follows organization membership. A role change
takes effect on the next request. The workspace supports switching organizations,
listing projects and signing out. Administrative writes use the HTTP API.

| Endpoint under /api/v1 | Purpose |
| --- | --- |
| POST /auth/login, GET /auth/me, POST /auth/logout | Start, inspect or revoke a session |
| GET or POST /organizations/{org_id}/projects | List or create projects |
| GET /projects/{id} | Read an accessible project |
| DELETE /organizations/{org_id}/projects/{id} | Delete a project |
| PUT or DELETE /organizations/{org_id}/members/{user_id} | Set a role using a JSON role field or remove membership |

Mutations require the configured web Origin. Authenticated mutations also
require the `X-CSRF-Token` returned by login or `/auth/me`. Sessions last
eight hours and use HttpOnly, SameSite=Strict cookies scoped to `/api/v1`.
HTTPS enables the Secure flag. HTTP is supported only for local loopback
origins. Passwords use Argon2id and only a digest of each session token is
stored. Within a database-clock minute login permits 100 attempts overall
and eight per email hash bucket. Accounts sharing a bucket share its limit.

## Read security activity

In the project workspace, owners and analysts can select **View audit activity**
for their current organization. Entries show the actor, affected project or
member, timestamp and role changes. Project deletion preserves its history.
Developer and viewer roles cannot read organization audit history.

| GET endpoint under /api/v1 | Scope |
| --- | --- |
| /auth/activity | Signed-in user's provisioning and session history |
| /organizations/{org_id}/audit | Current owner's or analyst's organization history |
| /organizations/{org_id}/audit?project_id={id} | Same permissions, filtered to one project including deleted projects |

Pages return `entries` newest first and `next_cursor`. Pass its value as
`before` to fetch older entries with the same filter. `limit` defaults to 50
and accepts 1–100. A cursor must identify an entry visible in that query.

The audit record and its successful mutation commit together. Entries contain
fixed action names, UUIDs, a database timestamp, and applicable old/new roles.
HTTP operations use the server-generated request ID from the response.
A new sign-in that replaces a live cookie records the replacement in the old
account's history without disclosing the new user's identity. Local operator
actions have no HTTP request ID or signed-in actor. Repeating
an unchanged role assignment creates no additional record.

Failed credential checks produce anonymous entries available to a database
operator. Throttled or malformed requests only appear in minimal request logs.
Audit entries omit emails, project names, passwords, tokens, headers, addresses
and request bodies. Account activity is separate from organization history.

Audit history begins at this migration and is retained in the local volume until
an administrator deliberately removes it. The application role can read and
append entries. PostgreSQL rejects ordinary updates, deletes and truncation.
A database administrator controls the schema and backups. There is no external
tamper-proof archive or scheduled audit cleanup.

## Import a project contract

In the workspace, select **Inventory** beside a project, choose a local file
and select **Import file**. Try [the synthetic pet service](../examples/petstore.yaml).
It declares two GET operations. The pet operation inherits the contract's
`localSession` security requirement and the status operation clears it.

Owners, analysts and developers can import. All four project roles can browse
methods, path templates, operation IDs and declared security. Security
alternatives preserve the contract's AND/OR groups and scopes. An inventory
describes the uploaded contract. The importer never contacts a declared server.

| Endpoint under /api/v1/projects/{project_id} | Behavior |
| --- | --- |
| POST /imports | Send the raw UTF-8 file body as application/json, application/yaml or text/yaml using the normal session, Origin and CSRF headers. A new revision returns 201. Repeating identical bytes returns 200 and the original revision, even after newer imports. |
| GET /imports | Read history newest first. Pass the last revision as `before` to read older entries. |
| GET /endpoints | Browse the latest revision or pass `revision`. Filter by uppercase `method`, and pass the returned revision and `next_offset` to page through a stable snapshot. Both readers accept `limit` from 1 to 100. |

The inventory profile supports OpenAPI 3.0.x and 3.1.x with a paths object.
It validates inventory fields and local JSON Pointer targets. It does not
validate every request/response schema. External references, remote uploads,
compressed bodies, YAML tags, anchors, aliases, multi-document streams,
dynamic references and percent-encoded pointer escapes are unsupported.
Path item references must stand alone. Callbacks and webhooks are omitted
with a warning. Empty paths produce an empty revision with a warning.

Limits include 128 KiB per file, 40 nesting levels, 12,000 parser events or
nodes, 12,000 expanded path-item and response fields, 500 operations,
512 characters per path, and 512 KiB of expanded endpoint
metadata. Scheme names, scopes and operation IDs use up to 128 ASCII letters,
digits or characters from `._:/-`. Quote YAML string versions such as `"1"`.
Import errors use fixed messages. The service stores a SHA-256 digest of the
file, normalized endpoint metadata, format version, warnings and revision time.
Raw file contents, filenames, example bodies, server URLs and descriptions are
discarded. Names and paths are visible to authorized project readers. Deleting
a project removes its inventory revisions and retains its audit entries.

## Connect a local emitter

Open **Integrations** beside a project. Owners and developers can create,
rotate and revoke its ingestion keys. Analysts can read masked metadata.
Viewers have no key-management access. Enter an emitter name and select
**Create key**. Save the one-time value in the emitter's secret store. Closing
the panel or reloading the page clears the displayed value.

To check the credential, use the project UUID shown in the panel's check URL.
Run this command from the repository root and enter the key at the hidden prompt.

```sh
python scripts/check_emitter.py YOUR_PROJECT_UUID
```

The helper targets the loopback web proxy on port 8080. Pass `--port` for a
custom web port. For unattended use, supply `SENTINEL_INGESTION_KEY` from your
emitter's secret store. An accepted check returns HTTP 204 and updates the
key's last-used timestamp.

| Action under /api/v1/projects/{project_id}/ingestion-keys | Authentication and result |
| --- | --- |
| POST with a JSON label | Session, Origin and CSRF token. Returns 201 with metadata and a one-time secret. |
| GET | Session with read permission. Returns masked entries ordered by prefix, with `next_cursor` for the `after` parameter. |
| POST /{key_id}/rotate | Management session, Origin and CSRF token. Revokes the old key and issues its replacement in one transaction. |
| POST /{key_id}/revoke | Same management checks. Returns 204. Repeating a change to a revoked key returns 409. |
| POST /check | Use `Authorization: Bearer <ingestion-key>`. An invalid, revoked or wrong-project credential returns 401. |

The database stores a public prefix and SHA-256 digest of a token containing
32 random secret bytes. Audit records identify the actor, project and key UUID.
The complete token appears only in the issuance response, which carries
`Cache-Control: no-store`. For an uninterrupted handover, create a second
key, update the emitter, verify its connection, then revoke the old key. Atomic
rotation invalidates the old credential immediately. If the issuance response
is lost, use the masked list to identify and revoke the unclaimed key.

## Submit and explore security events

Create a project key, then send a clearly labeled synthetic event through the
loopback web proxy. Enter the key at the hidden prompt; keep it out of command arguments.

```sh
python scripts/emit_event.py --event-id synthetic-login-0001
```

Repeating that command with the same key and event ID returns a duplicate.
Open **Events** beside the project to see the real stored observation. Filter
by a time range, source, category or HTTP status. Owners, analysts and developers
can inspect pseudonymized details; viewers receive summaries only.

Existing installations must rerun `python scripts/init_env.py` before rebuilding.
This adds a missing event pseudonymization key while preserving existing secrets.
See [event contracts and privacy](event-ingestion.md) for the batch schema,
atomic error behavior, quotas, pagination, key rotation and retention boundaries.
The worker evaluates three [detection rules](detection-rules.md) and records
the observations supporting each match. Set the [worker thresholds](detection-rules.md#configure-the-static-thresholds) in the local `.env` and recreate the worker to apply them.

## Apply the database migrations

With the local Compose database running, apply the revision and check the
result against the SQLAlchemy models. Existing setup volumes and .env files
use the same commands as a new installation.

```sh
docker compose run --rm --build migrate
docker compose run --rm migrate alembic current --check-heads
docker compose run --rm migrate alembic check
docker compose run --rm --build record-tests
```

The current revision is `0011_event_retention`. Its downgrade removes the receipt-time index. Downgrading to 0009 refuses to discard incident history. Upgrading from 0008 groups
existing findings immediately. Downgrading to 0008 removes alert IDs and evidence
links and preserves findings and events. Reapplying creates new alert IDs. When upgrading from 0007, stop
the existing worker before migration, then rebuild and start the Compose stack.
Completed jobs are queued again for evaluation. Downgrading to 0007 removes
findings and keeps source events and jobs.
Downgrading to `0006_security_events` discards job history and keeps events.
Reapplying the head revision without a downgrade preserves
existing rows. The test service creates a separate temporary database per
test and exercises upgrade, downgrade and reapply there. Downgrading to
`0005_ingestion_keys` deletes event records, sources and ingestion counters;
identity, keys, inventory and audit history remain. A downgrade to
`0004_api_inventory` removes credential storage and refuses to discard key audit
facts that the older schema cannot represent. A downgrade to
`0003_audit_activity` drops the inventory tables. If an import has been
audited, PostgreSQL refuses this downgrade because the old audit schema cannot
represent that action. The transaction rolls back and preserves the history.
Use a pre-upgrade backup for a full restoration to that earlier state.
Downgrading to
`0002_project_access` deletes audit history and preserves accounts and projects.
Downgrading to `0001_project_records` deletes identity and session data.
Downgrading to base also deletes organization and project data. Use a disposable database
for rollback tests. Back up retained records before an intentional rollback.

These one-shot tools use the local database administrator. API readiness checks
that the application login can read the project ID column without fetching rows.
An invalid application credential or inaccessible project table returns 503.
If liveness succeeds and readiness returns 503, check the application credential,
bootstrap migration result and project table grants before restarting the worker.

The internal records interface accepts an organization scope and supports project creation, lookup, paged
listing, rename and deletion. The database enforces unique slugs within each
organization and prevents deleting an organization that still owns projects.
The application uses the separate sentinel_app database login for authenticated requests.

## Develop and test

Install uv 0.13.9 and Node.js 24.22.3 with npm. uv reads apps/api/.python-version and
installs Python 3.13.18 when needed. Use `python scripts/check.py` on any
supported platform or `.\scripts\check.ps1` in PowerShell. This installs from
both locks, checks Python formatting, lint and types, runs the API and
component tests, and type-checks and builds the frontend.

For frontend development, run the Compose stack with the default API port,
set `SENTINEL_WEB_ORIGIN=http://127.0.0.1:5173` in .env, then recreate the api service.
Run `npm ci` and `npm run dev` in apps/web and open that exact origin.
Restore the Compose web origin when returning to the packaged UI.
For native development use a separate local PostgreSQL 16 cluster. Create a database
named `sentinel` and set `PGHOST`, `PGPORT` and `PGDATABASE=sentinel`.
Generate the local environment with `scripts/init_env.py`. Compose reads that file
automatically. Native processes need the corresponding values set in their own environments.

1. In an administrator shell, supply the administrator's `PGUSER` and `PGPASSWORD` plus the generated `SENTINEL_PROBE_PASSWORD`. From the repository root run `psql -X -v ON_ERROR_STOP=1 -f deploy/postgres/10-probe.sql` once on the fresh database. This creates the probe role and restricts schema access.
2. In that shell set `SENTINEL_APP_PASSWORD` and `SENTINEL_WORKER_PASSWORD` to their distinct generated values. From `apps/api`, with `PYTHONPATH=src`, run `uv run --locked python -m api_sentinel.identity.operator prepare` to apply migrations and runtime grants.
3. In a separate API shell set `PGUSER=sentinel_app`, the matching `SENTINEL_APP_PASSWORD`, and `SENTINEL_EVENT_HMAC_KEY` (64 lowercase hex characters). Set `SENTINEL_WEB_ORIGIN` to the exact frontend origin. From `apps/api` run:

```sh
uv run --locked uvicorn api_sentinel.main:create_app --factory --app-dir src --loop asyncio:SelectorEventLoop --host 127.0.0.1 --port 8000 --no-access-log --no-server-header --no-proxy-headers
```

4. In a worker shell connected to the same database, set `PGUSER=sentinel_worker`, its matching `PGPASSWORD` and `PYTHONPATH=src`. Run `uv run --locked python -m api_sentinel.worker` from `apps/api`. The worker drains queued observations and writes findings.

Run dependency checks from apps/api with `uv audit --locked` and from
apps/web with `npm audit`. Both require access to an advisory service.
The [security regression guide](security-checks.md) covers tenant isolation,
browser permissions, offline secret scanning and how to record findings.

## Data and scope

The readiness probe executes SELECT 1 using a dedicated PostgreSQL login.
The API receives separate probe and application credentials. The administrator
credential is available to the migration and bootstrap tools. Local Compose credentials are
visible to users with access to the Docker daemon. Keep .env private. The
documented servers disable request access logs. Health responses carry
service state only. The records schema stores organization and project names,
project slugs, UUIDs and creation timestamps. The identity schema also stores account email, password hash, active status, roles,
session digests and expiry, and bounded login counters. No public registration or
password recovery is available in this slice. Security event storage and queries
are available. The worker groups versioned findings into project alerts. The [alert API](detection-rules.md#project-alerts) exposes their thresholds and supporting events. The [incident API](incident-workflows.md) supports triage and keeps an investigator timeline. In the project workspace, Overview shows events by occurrence time for the last 24 hours or 7 days in six equal UTC intervals. Open alerts and unresolved incidents are current totals. Use Alerts to inspect evidence or promote an alert, and Incidents to assign, update, and resolve investigations.

[Runtime decision](decisions/0001-local-runtime.md) ·
[Implementation status](implementation-status.md)
