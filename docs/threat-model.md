# Local deployment threat model

The supported setup is a trusted developer host with loopback-only published ports. Operators with Docker or PostgreSQL administration rights can read application data, credentials or archives. Organization membership is the tenant boundary for interactive users. Each emitter holds a key limited to one project.

| Asset or boundary | Implemented control | Residual exposure and evidence |
| --- | --- | --- |
| Browser session and state-changing requests | Argon2id passwords, HttpOnly SameSite=Strict session cookies, server-side session digests, origin and session-bound CSRF checks. An HTTPS web origin sets the Secure cookie flag. | Loopback HTTP is the demo default. A compromised host or trusted browser session can act as its user. See `test_access.py` and `test_keys.py` in the integration suite. |
| Project records and investigator notes | API-side role checks scope individual reads and writes. A viewer receives a reduced incident response. Membership removal applies on the next read. | A user can retain information previously displayed. Role policy and redaction are exercised by the two-context Chrome workflow. |
| Emitter key and observed traffic | One-time key display, stored key digest, rotation and revocation. The API accepts bounded fields and pseudonymizes supplied actor/client tokens with a project-specific HMAC input. | An authorized emitter can report fabricated observations. Source names, route templates, timestamps and status codes are retained. Pseudonyms permit correlation. |
| Import boundary | Locally supplied documents have size and complexity limits. References resolve within the supplied document. | Inventory reflects the submitted contract. Parser tests exercise malformed input and disable network operations. |
| Worker, audit and backups | Separate database grants, leased jobs, append-only application history and project-scoped expiry. Restore checks cover event jobs and incident timeline integrity. | Privileged operators control the database. Backup archives can contain notes, hashes and previously revoked state. Keep the matching HMAC key and service credentials separately protected. |

## Before changing the deployment boundary

- Keep the default API and web bindings on loopback for this configuration. Confirm the database has no published host port.
- Generate a separate environment for each installation. Keep its secret file out of Git and match it to its database volume. Rehearse restoration before upgrades.
- Review who can provision accounts, issue keys, access the Docker daemon and read backups. Keep secrets and personal data out of free-text incident notes.
- An internet-facing deployment needs its own TLS termination, exact HTTPS web origin, ingress limits, host controls and recovery verification. Compose here exercises a single-host local installation. Public ingress, HA failover and off-host disaster recovery remain unverified.

[Security regression commands](security-checks.md) · [Backup and retention](operations.md)
