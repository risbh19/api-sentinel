# API Sentinel

API Sentinel is a local-first API monitoring project. The first executable slice serves a process-liveness check. Inventory, event ingestion, detection and incident triage are planned milestones.

## Run locally

Install Python 3.12.14, uv 0.13.9 and GNU Make. From the repository root:

```sh
make setup check
make serve
```

In a second terminal:

```sh
curl --fail http://127.0.0.1:8000/health/live
# {"status":"ok"}
```

With Docker Engine and Compose v2, run `docker compose up --build --wait`. Stop it with `docker compose down`. Both entry points publish the service on loopback.

See [development](docs/development.md), [architecture and milestones](docs/architecture.md), [contributing](CONTRIBUTING.md) and the [Apache-2.0 license](LICENSE).
