# API Sentinel

A local-first API security monitoring application in development. The web workspace supports local sign-in and shows projects from PostgreSQL.
The service status page reports FastAPI and database readiness. Open the web
page to check the connection again after stopping or restarting the database.

## Start locally

Install Docker with Compose v2.20+ and Python 3.10+ for the helper scripts.
From the repository root, run these commands in PowerShell, Bash or zsh.

```sh
python scripts/init_env.py
docker compose up --build --wait
docker compose ps
python scripts/smoke.py
```

Open [Service status](http://127.0.0.1:8080). The API is available on port
8000. Only the web and API ports are published, both on loopback. Set
`WEB_PORT` or `API_PORT` in .env to change them and pass the corresponding
ports to the smoke script. The worker reports its idle state at startup.

| Route | Success | Database unavailable |
| --- | --- | --- |
| GET /health/live | 200, status ok | 200, status ok |
| GET /health/ready | 200, status ready | 503, status unavailable |

Compose uses a named database volume. Keep the generated .env with it.
PostgreSQL applies the initialization SQL only when creating an empty
database directory. Editing passwords in .env alone will break the matching
database login. Use `docker compose down` to stop and retain local data.

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

## Apply the database migrations

With the local Compose database running, apply the revision and check the
result against the SQLAlchemy models. Existing setup volumes and .env files
use the same commands as a new installation.

```sh
docker compose run --rm --build migrate
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic check
docker compose run --rm --build record-tests
```

The current revision is `0002_project_access`. Reapplying it preserves
existing rows. The test service creates a separate temporary database per
test and exercises upgrade, downgrade and reapply there. Downgrading to `0001_project_records` deletes identity and session data.
Downgrading to base also deletes organization and project data. Use a disposable database
for rollback tests. Back up retained records before an intentional rollback.

These one-shot tools use the local database administrator. API readiness
continues to use the restricted probe login. The internal records interface
accepts an organization scope and supports project creation, lookup, paged
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
For native API development, set PGHOST, PGPORT and PGDATABASE for a local
PostgreSQL database. With the administrator PGUSER and PGPASSWORD, set
SENTINEL_APP_PASSWORD to a generated secret of at least 32 characters and run
`uv run --locked python -m api_sentinel.identity.operator prepare`
from apps/api with PYTHONPATH set to src. If you already ran Compose setup,
use its provisioned roles and app credential instead. Start the server with
PGUSER=sentinel_probe, PGPASSWORD set to its probe password, the matching
SENTINEL_APP_PASSWORD and the web origin for your frontend.

```sh
uv run --locked uvicorn api_sentinel.main:create_app --factory --app-dir src --loop asyncio:SelectorEventLoop --host 127.0.0.1 --port 8000 --no-access-log --no-server-header --no-proxy-headers
```

Run dependency checks from apps/api with `uv audit --locked` and from
apps/web with `npm audit`. Both require access to an advisory service.

## Data and scope

The readiness probe executes SELECT 1 using a dedicated PostgreSQL login.
The API receives separate probe and application credentials. The administrator
credential is available to the migration and bootstrap tools. Local Compose credentials are
visible to users with access to the Docker daemon. Keep .env private. The
documented servers disable request access logs. Health responses carry
service state only. The records schema stores organization and project names,
project slugs, UUIDs and creation timestamps. The identity schema also stores account email, password hash, active status, roles,
session digests and expiry, and bounded login counters. No public registration or
password recovery is available in this slice. Inventory, event ingestion, detection
and incident management remain planned.

[Runtime decision](docs/decisions/0001-local-runtime.md) ·
[Implementation status](docs/implementation-status.md) · [License](LICENSE)
