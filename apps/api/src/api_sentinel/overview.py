from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from api_sentinel.identity.routes import DB, Principal, project_scope
from api_sentinel.identity.security import Permission

router = APIRouter(prefix="/api/v1/projects/{project_id}")


class Bucket(BaseModel):
    start: datetime
    events: int


class Overview(BaseModel):
    since: datetime
    until: datetime
    events: int
    open_alerts: int
    active_incidents: int
    buckets: list[Bucket]


@router.get("/metrics/overview")
def overview(
    project_id: UUID, user: Principal, db: DB, window: Literal["24h", "7d"] = "24h"
) -> Overview:
    project_scope(db, user, project_id, Permission.READ_EVENTS)
    until = datetime.now(UTC)
    span = timedelta(days=1 if window == "24h" else 7)
    since, width = until - span, span / 6
    # Read the six time buckets and both current-state totals in one PostgreSQL snapshot.
    rows = db.execute(
        text("""
        WITH counts AS (
            SELECT floor(extract(epoch FROM (occurred_at - CAST(:since AS timestamptz)))
                         / :seconds)::integer AS bucket, count(*) AS n
            FROM security_events WHERE project_id=:project AND occurred_at>=:since AND occurred_at<:until
            GROUP BY bucket
        )
        SELECT i, coalesce(n, 0) AS events,
               (SELECT count(*) FROM alert_summaries WHERE project_id=:project AND status='open') AS open_alerts,
               (SELECT count(*) FROM incidents WHERE project_id=:project AND status<>'resolved') AS active_incidents
        FROM generate_series(0, 5) AS slots(i) LEFT JOIN counts ON counts.bucket=i ORDER BY i
    """),
        {
            "project": project_id,
            "since": since,
            "until": until,
            "seconds": int(width.total_seconds()),
        },
    ).all()
    buckets = [Bucket(start=since + row.i * width, events=row.events) for row in rows]
    return Overview(
        since=since,
        until=until,
        events=sum(b.events for b in buckets),
        open_alerts=rows[0].open_alerts,
        active_incidents=rows[0].active_incidents,
        buckets=buckets,
    )
