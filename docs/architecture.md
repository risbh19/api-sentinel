# Architecture and implementation sequence

At baseline commit `d7bd16b7921466fc980c4debab4a846ba5c3ef09`, the tree contained an Apache-2.0 LICENSE. The repository was private, main reported protection disabled, and the ruleset list was empty. Issue #1 already specified a first API slice. Repository visibility and publication are owner decisions.

## Current decisions

The first deployable is a FastAPI modular monolith under `apps/api`. Its sole route, `GET /health/live`, returns HTTP 200 and a fixed JSON status when the serving process handles a request. It does no network or database I/O. Readiness will enter with the first dependency. Python 3.12.14, uv 0.13.9, FastAPI 0.141.1 and Uvicorn 0.52.1 are pinned. The frontend begins with its first user workflow, and a separate worker process begins with a durable queue.

| ADR | Subject | State / validation |
| --- | --- | --- |
| 001 | Modular monolith | Accepted. One backend dependency graph and process today; separate processes can share domain code later. |
| 002 | PostgreSQL-backed work delivery | Proposed. Require transaction, replay, restart and concurrent-claim tests. |
| 003 | Minimal event metadata | Proposed. Allowlist fields and pseudonymize actor identifiers. |
| 004 | Tenant isolation | Proposed. Bind access to authenticated memberships, scope queries, and test database constraints. |
| 005 | Local OpenAPI files | Proposed. Bound input size and parser work, reject remote references. |
| 006 | Deterministic rules | Proposed. Pin rule versions, exercise positive and negative fixtures. |
| 007 | Passive observation | Accepted for MVP. Keep signal evidence and confidence explicit. |

## Revised MVP backlog

| PR | Reviewable outcome | Acceptance evidence |
| --- | --- | --- |
| 01 | Local process-liveness API, Compose and contributor checks | Locked clean checkout, HTTP contract, lint/types, Compose smoke, executed CI and reviewed diff |
| 02 | PostgreSQL, Alembic and tenant-aware organization/project relationships | Migrate an empty database; reject orphan and inconsistent tenant references |
| 03 | Sessions, CSRF and project RBAC | Allow/deny matrix including cross-tenant object access |
| 04 | Bounded file-only OpenAPI inventory | Valid imports, malformed/oversize files, blocked remote refs and tenant denial |
| 05 | Project ingestion credentials | Hashed storage, rotation, revocation and authorization tests |
| 06 | Idempotent metadata ingestion | Atomic deduplication, validation, backpressure and replay tests |
| 07 | Durable worker | Concurrent claim, crash recovery and dead-letter tests |
| 08 | Explainable detection | Versioned positive/negative fixtures and repeat-safe evidence |
| 09 | Incident workflow | State transitions and audit history within project scope |
| 10–13 | Authenticated web shell, inventory, event evidence and incident triage, in separate PRs | Real API integration and accessible end-to-end flows |
| 14 | Synthetic demo | Repeatable event-to-incident walkthrough with labeled fixtures |
| 15 | Hardening and release | Retention, dependency and secret scans, measured load, release and recovery evidence |

The [master plan](planning/MASTER_BUILD_PLAN.md) supplies the longer-term design. Only implemented slices should appear in product status reports.
