from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from api_sentinel.identity.routes import DB, Principal, project_scope
from api_sentinel.identity.security import Permission

router = APIRouter(prefix="/api/v1/projects/{project_id}/alerts")
PageSize = Annotated[int, Query(ge=1, le=100)]
Status = Literal["open", "acknowledged", "resolved"]


class AlertSummary(BaseModel):
    id: UUID
    source_id: str
    rule_key: str
    version: int
    threshold: int
    window_seconds: int
    bucket_start: datetime
    severity: str
    status: Status
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int


class AlertPage(BaseModel):
    entries: list[AlertSummary]
    next_cursor: UUID | None


class AlertDetail(AlertSummary):
    explanation: str
    caveat: str
    evidence: list[UUID]
    next_evidence_cursor: UUID | None


# Rules and explanations are versioned together. Existing alerts retain their interpretation.
EXPLANATIONS = {
    ("authentication_failures", 1): (
        "Authentication failures for one actor",
        "A client may be retrying expired credentials.",
    ),
    ("authorization_denials", 1): (
        "Authorization denials for one actor, HTTP method and route",
        "A client may have an outdated role or route configuration.",
    ),
    ("high_request_volume", 1): (
        "Reported requests for one client",
        "A scheduled batch or legitimate traffic spike can reach this threshold.",
    ),
}


@router.get("")
def alerts(
    project_id: UUID,
    user: Principal,
    db: DB,
    status: Status | None = None,
    limit: PageSize = 25,
    after: UUID | None = None,
) -> AlertPage:
    project_scope(db, user, project_id, Permission.READ_EVENTS)
    query = "SELECT * FROM alert_summaries WHERE project_id=:project"
    params: dict[str, object] = {"project": project_id, "limit": limit + 1}
    if status is not None:
        query += " AND status=:status"
        params["status"] = status
    if after is not None:
        bucket = db.scalar(
            text(
                "SELECT bucket_start FROM alert_summaries WHERE project_id=:project AND id=:id AND (CAST(:status AS text) IS NULL OR status=:status)"
            ),
            {"project": project_id, "id": after, "status": status},
        )
        if bucket is None:
            raise HTTPException(400, "Invalid alert cursor for this query")
        query += " AND (bucket_start,id)<(:bucket,:after)"
        params.update(bucket=bucket, after=after)
    rows = (
        db.execute(text(query + " ORDER BY bucket_start DESC,id DESC LIMIT :limit"), params)
        .mappings()
        .all()
    )
    return AlertPage(
        entries=[AlertSummary.model_validate(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1]["id"] if len(rows) > limit else None,
    )


@router.get("/{alert_id}")
def detail(
    project_id: UUID,
    alert_id: UUID,
    user: Principal,
    db: DB,
    limit: PageSize = 50,
    after: UUID | None = None,
) -> AlertDetail:
    project_scope(db, user, project_id, Permission.READ_EVENT_DETAILS)
    # One snapshot for the summary, cursor validation and page, even during retention.
    query = text("""
        WITH evidence AS NOT MATERIALIZED (
            SELECT ae.event_id FROM alert_evidence ae
            JOIN security_events e ON e.id=ae.event_id
            WHERE ae.alert_id=:alert AND e.project_id=:project
        )
        SELECT a.*,
            CAST(:after AS uuid) IS NULL OR EXISTS (
                SELECT 1 FROM evidence WHERE event_id=:after
            ) AS valid_cursor,
            ARRAY(SELECT event_id FROM evidence
                  WHERE CAST(:after AS uuid) IS NULL OR event_id>:after
                  ORDER BY event_id LIMIT :limit) AS ids
        FROM alert_summaries a WHERE a.project_id=:project AND a.id=:alert
    """)
    row = (
        db.execute(
            query, {"project": project_id, "alert": alert_id, "after": after, "limit": limit + 1}
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, "Alert not found")
    if not row["valid_cursor"]:
        raise HTTPException(400, "Invalid evidence cursor for this alert")
    ids = row["ids"]
    label, caveat = EXPLANATIONS.get(
        (row["rule_key"], row["version"]),
        (
            "Matching observations",
            "Review the rule version and supporting events to interpret this alert.",
        ),
    )
    return AlertDetail(
        **AlertSummary.model_validate(row).model_dump(),
        explanation=f"{label}: at least {row['threshold']} observations in {row['window_seconds']} seconds.",
        caveat=caveat,
        evidence=list(ids[:limit]),
        next_evidence_cursor=ids[limit - 1] if len(ids) > limit else None,
    )
