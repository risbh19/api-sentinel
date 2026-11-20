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

Missing actor or client pseudonyms skip that particular rule. Rotating the
pseudonym key starts a new group. Emitters should send one observation per
request. Each timestamp boundary is inclusive. Within one source, external event
ID orders ties. A match retains the most recent threshold-sized set ending at the
matching event, including that event. Overlapping windows can produce several
findings. Alert correlation and severity assignment are a later step.

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
