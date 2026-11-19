# Development

The Python service lives under `apps/api`. Use Python 3.12.14 and uv 0.13.9. The root Make targets require a POSIX environment. Install uv with `python -m pip install uv==0.13.9` inside a tooling virtual environment, or use the same release of the standalone CLI.

| Command | Result |
| --- | --- |
| `make setup` | Installs the locked development environment |
| `make check` | Checks formatting, lint, strict Python types and HTTP tests |
| `make serve` | Runs the API at 127.0.0.1:8000 |
| `docker compose up --build --wait` | Builds and starts the local container and waits for liveness |
| `make smoke` | Builds an isolated Compose project, checks the published address and response and tears it down |
| `docker compose down` | Stops the development stack |

Compose reads the optional root `.env`; copy `.env.example` to change the host port. The database and migrations enter in PR-02. Dependency changes belong in `apps/api/pyproject.toml`. Regenerate `uv.lock` with `cd apps/api && uv lock` and review its diff. The image installs the locked production group and runs unprivileged with a read-only filesystem.

## Free-tier CI

The workflow uses a standard Linux runner and a ten-minute timeout. Private repositories consume an account-level allowance. The owner should verify a billing configuration that prevents charges (including a hard stop for Actions overages) before setting the repository Actions variable `PRIVATE_CI_FREE_CONFIRMED=true`. By default, private jobs skip before runner allocation. Public repositories use the standard runner automatically. To trigger the job again, mark a draft ready for review or synchronize the PR. Inspect the job steps and head SHA before merging. An overall green icon can include skipped jobs.

Docker Engine with the Compose v2 plugin is needed for the container smoke test. Host tests use the in-process ASGI transport. They exercise the HTTP contract independently of the container image.
