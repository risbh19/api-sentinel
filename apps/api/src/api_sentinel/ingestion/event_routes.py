import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import select

from api_sentinel.identity.routes import DB, Principal, project_scope
from api_sentinel.identity.security import Permission

from .events import MAX_AGE, EventBatch, EventType, Source
from .models import IngestionState, SecurityEvent
from .privacy import decode_cursor, encode_cursor, secret
from .records import ingest
from .routes import authenticate, bearer

router = APIRouter(prefix="/api/v1")


class BatchResult(BaseModel):
    project_id: UUID
    accepted: int
    duplicate: int
    rejected: int = 0


class EventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_id: str
    occurred_at: datetime
    received_at: datetime
    event_type: EventType
    method: str
    route_template: str
    status_code: int


class EventDetail(EventSummary):
    external_event_id: str
    actor_hash: str | None
    client_hash: str | None
    pseudonym_version: str


class EventPage(BaseModel):
    entries: list[EventSummary]
    next_cursor: str | None


@router.post("/ingest/events", status_code=200)
def submit(
    request: Request,
    batch: EventBatch,
    db: DB,
    credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> BatchResult:
    if (
        request.headers.get("content-encoding")
        or request.headers.get("content-type", "").split(";")[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(415, "Send uncompressed application/json")
    project = authenticate(db, request, credential)
    accepted = ingest(db, project, batch, secret())
    return BatchResult(
        project_id=project, accepted=accepted, duplicate=len(batch.events) - accepted
    )


@router.get("/projects/{project_id}/events")
def events(
    project_id: UUID,
    user: Principal,
    db: DB,
    since: AwareDatetime,
    until: AwareDatetime,
    source: Source | None = None,
    event_type: EventType | None = None,
    status_code: Annotated[int | None, Query(ge=100, le=599)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    after: Annotated[
        str | None, Query(min_length=1, max_length=768, pattern=r"^[A-Za-z0-9_-]+$")
    ] = None,
) -> EventPage:
    project_scope(db, user, project_id, Permission.READ_EVENTS)
    since, until = since.astimezone(UTC), until.astimezone(UTC)
    if not timedelta(0) <= until - since <= MAX_AGE:
        raise HTTPException(422, "Choose an ordered time range of at most 30 days")
    filters = hashlib.sha256(
        json.dumps(
            [since.isoformat(), until.isoformat(), source, event_type, status_code]
        ).encode()
    ).hexdigest()
    maximum = (
        db.scalar(
            select(IngestionState.next_sequence).where(IngestionState.project_id == project_id)
        )
        or 0
    )
    before = maximum + 1
    if after:
        cursor = decode_cursor(after)
        if (
            set(cursor) != {"project", "filters", "maximum", "before"}
            or cursor["project"] != str(project_id)
            or cursor["filters"] != filters
            or type(cursor["maximum"]) is not int
            or type(cursor["before"]) is not int
            or not 0 < cursor["before"] <= cursor["maximum"] <= maximum
        ):
            raise HTTPException(400, "Invalid event cursor for this query")
        maximum, before = cursor["maximum"], cursor["before"]
    query = select(SecurityEvent).where(
        SecurityEvent.project_id == project_id,
        SecurityEvent.occurred_at >= since,
        SecurityEvent.occurred_at <= until,
        SecurityEvent.sequence <= maximum,
        SecurityEvent.sequence < before,
    )
    if source is not None:
        query = query.where(SecurityEvent.source_id == source)
    if event_type is not None:
        query = query.where(SecurityEvent.event_type == event_type)
    if status_code is not None:
        query = query.where(SecurityEvent.status_code == status_code)
    rows = db.scalars(query.order_by(SecurityEvent.sequence.desc()).limit(limit + 1)).all()
    next_cursor = None
    if len(rows) > limit:
        next_cursor = encode_cursor(
            {
                "project": str(project_id),
                "filters": filters,
                "maximum": maximum,
                "before": rows[limit - 1].sequence,
            }
        )
    return EventPage(
        entries=[EventSummary.model_validate(row) for row in rows[:limit]], next_cursor=next_cursor
    )


@router.get("/projects/{project_id}/events/{event_id}")
def detail(project_id: UUID, event_id: UUID, user: Principal, db: DB) -> EventDetail:
    project_scope(db, user, project_id, Permission.READ_EVENT_DETAILS)
    event = db.scalar(
        select(SecurityEvent).where(
            SecurityEvent.project_id == project_id, SecurityEvent.id == event_id
        )
    )
    if event is None:
        raise HTTPException(404, "Event not found")
    return EventDetail.model_validate(event)
