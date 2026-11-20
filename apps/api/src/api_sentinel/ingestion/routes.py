import re
import secrets
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from api_sentinel.audit.records import Action, record
from api_sentinel.identity.routes import DB, Principal, project_scope
from api_sentinel.identity.security import Permission, digest

from .models import IngestionKey

router = APIRouter(prefix="/api/v1/projects/{project_id}/ingestion-keys")
bearer = HTTPBearer(auto_error=False, scheme_name="IngestionKey")
Label = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=48,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$",
    ),
]


class CreateKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Label


class KeyInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    label: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class IssuedKey(BaseModel):
    key: KeyInfo
    secret: str


class KeyPage(BaseModel):
    entries: list[KeyInfo]
    next_cursor: str | None


def issue(
    db: Session, project: UUID, label: str, org: UUID, actor: UUID, request_id: str
) -> IssuedKey:
    prefix = "asi_" + secrets.token_hex(8)
    token = prefix + "." + secrets.token_urlsafe(32)
    key = IngestionKey(project_id=project, label=label, prefix=prefix, key_hash=digest(token))
    db.add(key)
    db.flush()
    record(
        db,
        Action.KEY_CREATED,
        organization_id=org,
        project_id=project,
        key_id=key.id,
        actor_id=actor,
        request_id=request_id,
    )
    return IssuedKey(key=KeyInfo.model_validate(key), secret=token)


@router.post("", status_code=201)
def create(
    project_id: UUID, body: CreateKey, user: Principal, db: DB, request: Request
) -> IssuedKey:
    org = project_scope(db, user, project_id, Permission.MANAGE_KEYS)
    return issue(db, project_id, body.label, org, user.id, request.state.request_id)


@router.get("")
def list_keys(
    project_id: UUID,
    user: Principal,
    db: DB,
    after: Annotated[str | None, Query(pattern=r"^asi_[0-9a-f]{16}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> KeyPage:
    project_scope(db, user, project_id, Permission.READ_KEYS)
    query = select(IngestionKey).where(IngestionKey.project_id == project_id)
    if after is not None:
        cursor = db.scalar(
            select(IngestionKey.id).where(
                IngestionKey.project_id == project_id, IngestionKey.prefix == after
            )
        )
        if cursor is None:
            raise HTTPException(400, "Invalid ingestion key cursor")
        query = query.where(IngestionKey.prefix > after)
    rows = db.scalars(query.order_by(IngestionKey.prefix).limit(limit + 1)).all()
    return KeyPage(
        entries=[KeyInfo.model_validate(k) for k in rows[:limit]],
        next_cursor=rows[limit - 1].prefix if len(rows) > limit else None,
    )


def retire(
    db: Session, project: UUID, key_id: UUID, org: UUID, actor: UUID, request_id: str
) -> IngestionKey:
    key = db.scalar(
        select(IngestionKey)
        .where(IngestionKey.project_id == project, IngestionKey.id == key_id)
        .with_for_update()
    )
    if key is None:
        raise HTTPException(404, "Ingestion key not found")
    if key.revoked_at is not None:
        raise HTTPException(409, "Ingestion key already revoked")
    db.execute(
        update(IngestionKey)
        .where(IngestionKey.id == key.id)
        .values(revoked_at=func.clock_timestamp())
    )
    record(
        db,
        Action.KEY_REVOKED,
        organization_id=org,
        project_id=project,
        key_id=key_id,
        actor_id=actor,
        request_id=request_id,
    )
    return key


@router.post("/{key_id}/revoke", status_code=204)
def revoke(project_id: UUID, key_id: UUID, user: Principal, db: DB, request: Request) -> None:
    org = project_scope(db, user, project_id, Permission.MANAGE_KEYS)
    retire(db, project_id, key_id, org, user.id, request.state.request_id)


@router.post("/{key_id}/rotate", status_code=201)
def rotate(project_id: UUID, key_id: UUID, user: Principal, db: DB, request: Request) -> IssuedKey:
    org = project_scope(db, user, project_id, Permission.MANAGE_KEYS)
    old = retire(db, project_id, key_id, org, user.id, request.state.request_id)
    return issue(db, project_id, old.label, org, user.id, request.state.request_id)


@router.post("/check", status_code=204)
def check(
    project_id: UUID,
    request: Request,
    db: DB,
    credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Response:
    token = (
        credential.credentials
        if credential and len(request.headers.getlist("authorization")) == 1
        else ""
    )
    if re.fullmatch(r"asi_[0-9a-f]{16}\.[A-Za-z0-9_-]{43}", token):
        # PostgreSQL rechecks the live-row condition after concurrent revocation.
        key_id = db.scalar(
            update(IngestionKey)
            .where(
                IngestionKey.prefix == token[:20],
                IngestionKey.key_hash == digest(token),
                IngestionKey.project_id == project_id,
                IngestionKey.revoked_at.is_(None),
            )
            .values(last_used_at=func.clock_timestamp())
            .returning(IngestionKey.id)
        )
        if key_id is not None:
            return Response(status_code=204)
    raise HTTPException(
        401, "Invalid ingestion credential", headers={"WWW-Authenticate": "Bearer"}
    )
