# Incident investigation

Owners and analysts can open investigations manually or promote an alert. All
operations require a project session. Writes also require the trusted origin and
session CSRF token. Developers and viewers can read only the ID, project,
priority, status, timestamps and version. Titles, assignees, alert links, notes
and timeline actors are visible only to investigators.

Use the base path `/api/v1/projects/{project_id}/incidents`.

| Method and suffix | Operation |
| --- | --- |
| POST at the base path | Supply a title (1–120 characters), optional low/medium/high priority (default medium), and optional alert_id. Returns 201 and the current version. |
| GET at the base path | Filter by status. Page in ascending UUID order with limit (1–100) and the last ID as after. |
| GET /{id} | Investigator detail includes the timeline in ascending version order. Pass next_version as after_version for more entries. Other members receive a summary. |
| PATCH /{id} | Send the current version and either a status or an assignee_id. Use null to unassign. |
| PUT /{id}/alerts/{alert_id} | Send the current version to attach another alert from this project. Each alert belongs to at most one incident. The alert_linked entry identifies the alert for evidence lookup. |
| POST /{id}/notes | Send the current version and plain text (1–2000 characters). A note is an immutable timeline entry. |

An incident progresses from open to acknowledged, investigating and resolved.
A resolved incident may be reopened and then investigated again. Returning to
investigation clears the current resolution time. Its timeline retains the earlier
resolution. Reassign before removing an assigned investigator or changing their
role to viewer or developer. Only active owners and analysts in the organization
can be assigned.

An invalid transition, a stale version or a duplicate alert link returns 409.
Refresh detail before retrying. Status, assignment, linked alert, note and actor
are recorded in the same transaction as the change. Timeline entries have no API
for editing or deletion; the application role has only SELECT and INSERT on that
table. Notes are stored as entered: keep credentials, personal data and raw
request contents out of them. Alert evidence follows the existing event retention
policy. A project with incident history cannot be deleted through the API.
Downgrade to revision 0009 is supported only while the incidents table is empty.
