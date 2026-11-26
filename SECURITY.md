# Reporting a security issue

Use the repository's **Security → Report a vulnerability** option when available. If GitHub does not offer private reporting, open an issue titled **Request for private security contact** with a way for the maintainer to reach you. Keep the issue limited to arranging a private channel.

In private, include the affected revision, deployment configuration, affected boundary and observed impact. Use synthetic identifiers. Remove credentials, session cookies, database dumps, real event data and customer details from attachments.

The maintainer should acknowledge the report privately, confirm the affected versions and coordinate a fix, regression coverage and disclosure with the reporter. Published advisories should identify the fixed revision and any operator action. The [threat model](docs/threat-model.md) describes the supported local deployment boundary.
