# Detection rules

Each finding names a rule, its version, the event that met its threshold, the
window in seconds and the ordered event IDs that explain the match. All rules
use occurrence time and group observations within one project and source.
The version 1 thresholds are synthetic defaults.

| Rule | Match in a rolling window | Possible benign explanation |
| --- | --- | --- |
| `authentication_failures` | At least 8 authentication failure events (401) for one actor in 5 minutes | A client is retrying expired credentials. |
| `authorization_denials` | At least 10 authorization denial events (403) for one actor, method and route template in 10 minutes | A client is using an outdated role or route configuration. |
| `high_request_volume` | More than 60 reported requests of any category for one client in 60 seconds | A batch job or legitimate traffic spike. |

## Configure the static thresholds

Set these worker settings in the checkout's `.env`. Each value is the minimum number of observations for a match, from 1 to 100 inclusive. The upper bound limits how many evidence records each rolling window retains.

| Setting | Default | Rolling window |
| --- | --- | --- |
| `SENTINEL_AUTHENTICATION_FAILURES_THRESHOLD` | 8 | 300 seconds |
| `SENTINEL_AUTHORIZATION_DENIALS_THRESHOLD` | 10 | 600 seconds |
| `SENTINEL_HIGH_REQUEST_VOLUME_THRESHOLD` | 61 | 60 seconds |

For example, set `SENTINEL_HIGH_REQUEST_VOLUME_THRESHOLD=40`, then run `docker compose up -d --force-recreate worker`. The worker reads the settings at startup and exits before claiming jobs if a value is invalid. Use the same settings on every worker in a deployment. They apply across projects. The packaged demo and smoke walkthrough use the defaults.

A default threshold retains rule version 1. For these three rules, a custom threshold N selects version 1000 + N, so 40 observations select version 1040. Restoring a previous threshold restores its version. Alerts keep the version, threshold, window and evidence stored with the finding. Versions have separate alert fingerprints.

New and pending jobs use the settings active when the worker processes them. Their rolling windows can include earlier observations. Changing settings does not enqueue completed jobs for a historical replay.

## Window and evidence behavior

Missing actor or client pseudonyms skip that particular rule. Rotating the
pseudonym key starts a new group. Emitters should send one observation per
request. Each timestamp boundary is inclusive. Within one source, external event
ID orders ties. A match retains the most recent threshold-sized set ending at the
matching event, including that event. Overlapping windows can produce several
findings. Each finding belongs to one project alert.

Late arrivals update affected evidence even when the original jobs have already
completed. With a threshold of N, the worker reads at most N−1 earlier and N
current/later observations for the group. Concurrent evaluations for a source
serialize their writes. Replaying a job preserves one finding per event, rule and
version. Findings and job completion commit together.

An operator can inspect findings in the local database:

```sql
SELECT e.project_id, e.source_id, e.occurred_at, f.rule_key, f.version,
       f.threshold, f.window_seconds, f.evidence
FROM rule_findings AS f JOIN security_events AS e ON e.id = f.event_id
ORDER BY e.occurred_at DESC, e.external_event_id DESC LIMIT 20;
```

The evidence array stores internal UUIDs. Deleting the ending event deletes its
finding. If an earlier supporting event is removed, its UUID can remain in a
surviving finding until the ending event is removed. Deleting the project
cascades through its events and findings.

Stop old workers before applying revision 0008. It requeues previously
succeeded jobs so retained observations are evaluated under version 1. Pending,
leased and dead jobs keep their existing state. Start the rebuilt stack to apply
the worker grants. A downgrade drops findings and the rule indexes. Source
events remain available for a subsequent rebuild.


## Project alerts

The worker groups findings with the same project, source, rule version and
rule-specific dimensions from the table above. Each alert covers a fixed UTC
bucket as long as the rule window, aligned to the Unix epoch. The ending
event selects the bucket. Two matches on opposite sides of a bucket boundary
produce two alerts, even when they share supporting events.

`occurrence_count` counts distinct matching findings. `first_seen` and
`last_seen` are occurrence times of their earliest and latest ending events.
The evidence list is the union of surviving events in those findings. Late
arrivals can replace supporting events. Re-evaluation preserves the alert ID,
count and distinct evidence for the same inputs. Deleting a supporting event
removes its evidence link. An alert with no surviving findings drops out of
the API. The project owns its alert records until project deletion.

The initial status is `open`. Authentication and authorization patterns receive
medium severity, request volume receives low severity. These synthetic priorities
help with triage. Confirm the context with the emitter before drawing conclusions
about compromise.

- `GET /api/v1/projects/{project_id}/alerts` lists summaries, newest bucket
  first. Filter by `status` and pass `next_cursor` as `after` for the next page.
- `GET /api/v1/projects/{project_id}/alerts/{alert_id}` returns the explanation,
  benign interpretation and internal event UUIDs. For additional evidence pass
  `next_evidence_cursor` as `after`. Each UUID resolves through the project event
  detail endpoint. Both endpoints accept a page size of 1 to 100 with `limit`.
  Pagination reads current data and may change as findings arrive or expire.
- Viewers can read summaries. Owners, analysts and developers can also read
  evidence under their existing event-detail permission. Only a signed-in
  project member can query alerts.

Revision 0009 groups existing findings during migration. Allow time for this
transaction on larger databases. Rebuild the services and run the migration
service to apply app and worker grants. Downgrading removes correlations and
preserves original findings. Reapplying rebuilds the groups with new alert IDs.
