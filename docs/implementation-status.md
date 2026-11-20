# Implementation status

[Application setup](https://github.com/risbh19/api-sentinel/pull/4) merged at
`68b63c5`. Windows Docker testing confirmed startup and database outage recovery.
The worker runs as an idle scaffold.

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

The event-ingestion branch adds atomic, project-key authenticated event batches,
pseudonymization, replay deduplication and a scoped event explorer. It is pending
PR review and merge. Durable detection work and worker recovery are the next slice.
