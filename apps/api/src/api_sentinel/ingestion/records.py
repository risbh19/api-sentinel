from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .events import MAX_BATCHES_PER_MINUTE, MAX_SOURCES, EventBatch
from .models import EventSource, IngestionState, SecurityEvent
from .privacy import key_version, pseudonym


def ingest(db: Session, project: UUID, batch: EventBatch, key: bytes) -> int:
    # One row serializes all project keys, source quotas and committed pagination order.
    db.execute(insert(IngestionState).values(project_id=project).on_conflict_do_nothing())
    state = db.scalars(
        select(IngestionState).where(IngestionState.project_id == project).with_for_update()
    ).one()
    now = db.scalar(select(func.clock_timestamp()))
    assert isinstance(now, datetime)
    now = now.astimezone(UTC)
    try:
        batch.check_times(now)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    window = int(now.timestamp()) // 60
    if state.window != window:
        state.window, state.batches = window, 0
    if state.batches >= MAX_BATCHES_PER_MINUTE:
        raise HTTPException(429, "Project ingestion limit reached", headers={"Retry-After": "60"})
    state.batches += 1
    source = db.get(EventSource, (project, batch.source_id))
    if source is None:
        count = db.scalar(
            select(func.count()).select_from(EventSource).where(EventSource.project_id == project)
        )
        if count is not None and count >= MAX_SOURCES:
            raise HTTPException(409, "Project source limit reached")
        db.add(EventSource(project_id=project, source_id=batch.source_id))
        db.flush()
    rows = [
        {
            "project_id": project,
            "source_id": batch.source_id,
            "external_event_id": event.event_id,
            "sequence": state.next_sequence + index + 1,
            "occurred_at": event.occurred_at,
            "event_type": event.event_type,
            "method": event.method,
            "route_template": event.route_template,
            "status_code": event.status_code,
            "actor_hash": pseudonym(key, project, "actor", event.actor_token),
            "client_hash": pseudonym(key, project, "client", event.client_token),
            "pseudonym_version": key_version(key),
        }
        for index, event in enumerate(batch.events)
    ]
    accepted = db.scalars(
        insert(SecurityEvent)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_event_delivery")
        .returning(SecurityEvent.id)
    ).all()
    state.next_sequence += len(rows)
    return len(accepted)
