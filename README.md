# API Sentinel

A local-first API security monitoring application in development. The first
slice displays service readiness from FastAPI and PostgreSQL. Open the web
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

## Develop and test

Install uv 0.13.9 and Node.js 24.22.3 with npm. uv reads .python-version and
installs Python 3.13.18 when needed. Use `python scripts/check.py` on any
supported platform or `.\scripts\check.ps1` in PowerShell. This installs from
both locks, checks Python formatting, lint and types, runs the API and
component tests, and type-checks and builds the frontend.

For frontend development, run the Compose stack with the default API port,
then run `npm ci` and `npm run dev` in apps/web. Open the Vite loopback URL.
For API development, supply libpq's PGHOST, PGPORT, PGDATABASE, PGUSER and
PGPASSWORD for your local PostgreSQL instance. From apps/api run

```sh
uv run --locked uvicorn api_sentinel.main:create_app --factory --app-dir src --host 127.0.0.1 --port 8000 --no-access-log --no-server-header --no-proxy-headers
```

Run dependency checks from apps/api with `uv audit --locked` and from
apps/web with `npm audit`. Both require access to an advisory service.

## Data and scope

The readiness probe executes SELECT 1 using a dedicated PostgreSQL login.
The API receives only the probe password. Local Compose credentials are
visible to users with access to the Docker daemon. Keep .env private. The
documented servers disable request access logs. Health responses carry
service state only. This slice stores no application records and introduces
no schema migrations. Authentication, inventory, event ingestion, detection
and incident management are planned.

[Runtime decision](docs/decisions/0001-local-runtime.md) ·
[Implementation status](docs/implementation-status.md) · [License](LICENSE)
