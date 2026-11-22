# Implementation status

[Application setup](https://github.com/risbh19/api-sentinel/pull/4) merged at
`68b63c5`. Windows Docker testing confirmed startup and database outage recovery.
That revision introduced the worker scaffold.

[Project records](https://github.com/risbh19/api-sentinel/pull/5) merged at
`efae961` with the initial Alembic migration and organization-scoped project
storage.

[Project access](https://github.com/risbh19/api-sentinel/pull/6) merged at
`ef49819` with local sign-in, server-side sessions and organization roles.

[Audit activity](https://github.com/risbh19/api-sentinel/pull/7) merged at
`c09615e` with append-only history and a scoped workspace reader.

[API inventory](https://github.com/risbh19/api-sentinel/pull/8) merged at
`846ad4e` with bounded contract imports and versioned project inventories.

[Integration keys](https://github.com/risbh19/api-sentinel/pull/9) merged at
`8c7a207` with one-time credentials, rotation, revocation and a local emitter check.

[Event ingestion](https://github.com/risbh19/api-sentinel/pull/10) merged at
`912296a` with atomic project-scoped batches, pseudonymization, replay
deduplication and the event explorer.

[Event processing](https://github.com/risbh19/api-sentinel/pull/11) merged at
`db84972` with a durable job per event, worker recovery and aggregate queue status.

[Detection rules](https://github.com/risbh19/api-sentinel/pull/12) merged at
`a269dca` with three rolling thresholds and versioned findings.

[Alert correlation](https://github.com/risbh19/api-sentinel/pull/13) merged at
`584beb1` with correlated findings and paginated evidence.

[Incident workflows](https://github.com/risbh19/api-sentinel/pull/14) merged at
`221071b` with alert promotion, assignment, notes and resolution history.

[Security dashboard](https://github.com/risbh19/api-sentinel/pull/15) merged at
`6a3933e` with scoped metrics, evidence and incident investigation screens.

[Local demo](https://github.com/risbh19/api-sentinel/pull/16) merged at
`2efb4f5` with explicit synthetic onboarding and repeatable telemetry.

[Security checks](https://github.com/risbh19/api-sentinel/pull/17) merged at
`fe08ba7` with cross-tenant replay, viewer redaction and membership-removal checks.

[Operations](https://github.com/risbh19/api-sentinel/pull/18) merged at
`88eae15` with bounded event expiry, worker diagnostics and a backup restore rehearsal.

See the [release checklist](release-readiness.md) for validation evidence and open gates.
