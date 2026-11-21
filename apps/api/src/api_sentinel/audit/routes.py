from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import ColumnElement, select, tuple_
from sqlalchemy.orm import Session

from api_sentinel.identity.routes import DB, Principal, authorize
from api_sentinel.identity.security import Permission, Role

from .records import Action, AuditEntry

router = APIRouter(prefix="/api/v1")
Limit = Annotated[int, Query(ge=1, le=100)]


class Entry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    occurred_at: datetime
    action: Action
    organization_id: UUID | None
    project_id: UUID | None
    actor_id: UUID | None
    incident_id: UUID | None
    incident_version: int | None
    key_id: UUID | None
    subject_user_id: UUID | None
    old_role: Role | None
    new_role: Role | None
    request_id: str | None


class AuditPage(BaseModel):
    entries: list[Entry]
    next_cursor: UUID | None


def page(
    db: Session, scope: list[ColumnElement[bool]], before: UUID | None, limit: int
) -> AuditPage:
    query = select(AuditEntry).where(*scope)
    if before is not None:
        stamp = db.scalar(select(AuditEntry.occurred_at).where(*scope, AuditEntry.id == before))
        if stamp is None:
            raise HTTPException(400, "Invalid audit cursor")
        query = query.where(tuple_(AuditEntry.occurred_at, AuditEntry.id) < (stamp, before))
    rows = db.scalars(
        query.order_by(AuditEntry.occurred_at.desc(), AuditEntry.id.desc()).limit(limit + 1)
    ).all()
    return AuditPage(
        entries=[Entry.model_validate(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.get("/auth/activity")
def own_activity(
    user: Principal, db: DB, before: UUID | None = None, limit: Limit = 50
) -> AuditPage:
    return page(
        db,
        [AuditEntry.organization_id.is_(None), AuditEntry.subject_user_id == user.id],
        before,
        limit,
    )


@router.get("/organizations/{org_id}/audit")
def organization_activity(
    org_id: UUID,
    user: Principal,
    db: DB,
    project_id: UUID | None = None,
    before: UUID | None = None,
    limit: Limit = 50,
) -> AuditPage:
    authorize(db, user, org_id, Permission.READ_AUDIT)
    scope = [AuditEntry.organization_id == org_id]
    if project_id is not None:
        scope.append(AuditEntry.project_id == project_id)
    return page(db, scope, before, limit)
