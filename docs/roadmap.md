# Release roadmap and maturity assessment

Baseline: main at `d73a196`, 26 November 2026. Target users are small API teams that can instrument their own services and need to investigate unusual requests against an OpenAPI contract. The supported deployment is a local, single-host Compose stack.

## Existing evidence

The repository contains an event contract, scoped keys, transactional event jobs, three configurable rules, correlated evidence, incident history, scoped retention, structured request logs and recovery tooling. The [release checklist](release-readiness.md) identifies the exact revisions tested on Ubuntu and Windows. The [recorded investigation](local-demo.md) uses synthetic data. A published release, independent deployment, throughput target and off-host restore were unverified at this baseline.

| Priority | Deliverable | Acceptance evidence |
| --- | --- | --- |
| P0 | Correct readiness when application DB access fails | Valid application grants produce 200. Missing credentials, invalid credentials and an unreadable project table produce 503. Liveness survives a database outage. |
| P0 | Preserve credentials during upgrades | Reinitializing a disposable existing Compose environment preserves effective DB credentials and HMAC key, including supported assignment syntax. A replay remains attributable to the same actor. |
| P0 | Verify a named release candidate | Record exact head, Linux and Windows startup, advisory and image scans, tenant tests and a restore rehearsal. Record scan failures and outstanding findings. |
| P1 | Make contribution and release maintenance repeatable | Publish contributor and disclosure guidance, issue and PR templates, grouped dependency updates, release notes and upgrade instructions. Obtain an owner decision on licensing before encouraging redistribution. |
| P1 | Establish ingestion capacity | Record hardware, image revisions, event shape, concurrency, replay ratio, successful throughput, p50/p95 latency, worker lag and peak CPU/memory. Include raw commands and failure counts. |
| P1 | Support real application emitters | Validate FastAPI and Express examples using matched route templates, status and bounded duration. An unavailable collector must leave application responses intact. Verify retries preserve event identity. |
| P1 | Measure observed application traffic | Add optional request duration with compatibility coverage for older events. Define denominators and sampling for error rates. Keep service metrics separate from observed application metrics. |
| P2 | Extend detection and delivery | Evaluate per-project thresholds, replay behavior and explainable baselines against labeled fixtures. Before outbound webhooks, review destination authorization, DNS changes, redirects, retries, deduplication and secret handling. |
| P2 | Verify operations outside a single host | Restore onto replacement infrastructure, validate ingress policy, rehearse key and session revocation after restore, and document measured recovery objectives. |

## Security and adoption

Use the [threat model](threat-model.md) and [security checks](security-checks.md) when changing object authorization, roles, resource limits or external calls. Preserve evidence that users in another organization cannot read records, and that revoked keys cannot ingest. Track advisories against locked packages and built images separately. A green unit suite alone leaves these questions open.

Record independent integrations and deployments only with permission. Useful feedback includes time to the first accepted event, whether an operator could explain an alert from its evidence, and what prevented installation. Link reports to reproducible fixes.

## Tool comparison and project scope

| Reference | What it provides | Implication for API Sentinel |
| --- | --- | --- |
| [Akto inventory](https://docs.akto.io/api-inventory/concepts) | Traffic inventory concepts include shadow APIs, dependency graphs and sensitive-data classification. | Describe the current inventory as imported contracts. Compare declared and observed routes only after instrumented traffic has a tested normalization contract. |
| [Prometheus instrumentation](https://prometheus.io/docs/practices/instrumentation/) | Request counts, errors, latency and queue health are standard operational signals. | Expose bounded service metrics and measure emitter latency separately. Keep project names, actor labels and raw paths out of metric labels. |

## Security review scope

The [OWASP API Security Top 10](https://owasp.org/API-Security/editions/2023/en/0x11-t10/) gives the review a common vocabulary. Object, property and function authorization apply to project records, investigation details and administrative actions. Authentication applies to sessions, key issuance and revocation. Resource consumption applies to import size, event batches, queue growth and retention. Sensitive business flows need explicit abuse cases for login and key issuance. Misconfiguration and inventory management apply to Compose exposure, service grants and contract drift. SSRF and unsafe consumption of APIs need new review when introducing external destinations or remote data sources. Recheck each applicable boundary on the named release candidate.

## License decision

Two permissive options fit reusable middleware and a self-hosted service. [MIT](https://choosealicense.com/licenses/mit/) has a short notice-preservation requirement. [Apache-2.0](https://choosealicense.com/licenses/apache-2.0/) includes an express contributor patent grant and additional notice and change-marking requirements. The owner selects a license separately.
