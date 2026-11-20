import asyncio
import hashlib
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api_sentinel.audit.records import Action, record
from api_sentinel.identity.models import Membership, User
from api_sentinel.identity.routes import DB, Principal, authorize
from api_sentinel.identity.security import GRANTS, Permission, Role
from api_sentinel.organizations.models import Project

from .models import Endpoint, ImportRevision
from .parser import MAX_BYTES, InvalidDocument, Security, parse

router = APIRouter(prefix="/api/v1/projects/{project_id}")
Limit = Annotated[int, Query(ge=1, le=100)]
Revision = Annotated[int, Query(gt=0, le=2147483647)]
FORMATS = ("application/json", "application/yaml", "text/yaml")


class RevisionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    revision: int
    version: str
    count: int
    warnings: list[str]
    created_at: datetime


class EndpointInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    method: str
    path: str
    operation_id: str | None
    security: Security | None


class InventoryPage(BaseModel):
    revision: RevisionInfo | None
    entries: list[EndpointInfo]
    next_offset: int | None


def scope(db: Session, user: User, project_id: UUID, permission: Permission) -> UUID:
    org = db.scalar(
        select(Project.organization_id)
        .join(Membership, Membership.organization_id == Project.organization_id)
        .where(Project.id == project_id, Membership.user_id == user.id)
    )
    if org is None:
        raise HTTPException(404, "Project not found")
    authorize(db, user, org, permission)
    # Deletion and role changes use the same organization lock.
    if (
        db.scalar(
            select(Project.id).where(Project.id == project_id, Project.organization_id == org)
        )
        is None
    ):
        raise HTTPException(404, "Project not found")
    return org


async def read_file(request: Request) -> bytes:
    if (
        request.headers.get("content-type", "").split(";")[0].strip().lower() not in FORMATS
        or request.headers.get("content-encoding", "identity").lower() != "identity"
    ):
        raise HTTPException(415, "Send an uncompressed local JSON or YAML file.")
    try:
        async with asyncio.timeout(15):
            content = await request.body()
    except TimeoutError:
        raise HTTPException(408, "Upload timed out.") from None
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "File exceeds the 128 KiB limit.")
    return content


@router.post(
    "/imports",
    status_code=201,
    responses={
        200: {"model": RevisionInfo, "description": "Existing revision for identical bytes"}
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                kind: {"schema": {"type": "string", "format": "binary"}} for kind in FORMATS
            },
        }
    },
)
def import_file(
    project_id: UUID,
    request: Request,
    response: Response,
    content: Annotated[bytes, Depends(read_file)],
    user: Principal,
    db: DB,
) -> RevisionInfo:
    # Admit the parser without taking the organization's write lock. Recheck at persistence.
    role = db.scalar(
        select(Membership.role)
        .join(Project, Project.organization_id == Membership.organization_id)
        .where(Project.id == project_id, Membership.user_id == user.id)
    )
    if role is None:
        raise HTTPException(404, "Project not found")
    if Permission.IMPORT not in GRANTS[Role(role)]:
        raise HTTPException(403, "Insufficient permission")
    try:
        inventory = parse(
            content,
            request.headers["content-type"].split(";")[0].strip().lower() == "application/json",
        )
    except InvalidDocument as exc:
        raise HTTPException(422, str(exc)) from None
    org = scope(db, user, project_id, Permission.IMPORT)
    digest = hashlib.sha256(content).hexdigest()
    query = select(ImportRevision).where(ImportRevision.project_id == project_id)
    existing = db.scalar(query.where(ImportRevision.digest == digest))
    if existing:
        response.status_code = 200
        return RevisionInfo.model_validate(existing)
    latest = db.scalar(
        select(func.max(ImportRevision.revision)).where(ImportRevision.project_id == project_id)
    )
    row = ImportRevision(
        project_id=project_id,
        digest=digest,
        revision=(latest or 0) + 1,
        version=inventory.version,
        count=len(inventory.operations),
        warnings=inventory.warnings,
    )
    db.add(row)
    db.flush()
    for op in inventory.operations:
        db.add(
            Endpoint(
                import_id=row.id,
                method=op.method,
                path=op.path,
                operation_id=op.operation_id,
                security=op.security,
            )
        )
    record(
        db,
        Action.INVENTORY_IMPORTED,
        actor_id=user.id,
        project_id=project_id,
        organization_id=org,
        request_id=request.state.request_id,
    )
    return RevisionInfo.model_validate(row)


@router.get("/imports")
def history(
    project_id: UUID, user: Principal, db: DB, before: Revision | None = None, limit: Limit = 50
) -> list[RevisionInfo]:
    scope(db, user, project_id, Permission.READ_INVENTORY)
    query = select(ImportRevision).where(ImportRevision.project_id == project_id)
    if before is not None:
        query = query.where(ImportRevision.revision < before)
    return [
        RevisionInfo.model_validate(row)
        for row in db.scalars(query.order_by(ImportRevision.revision.desc()).limit(limit))
    ]


@router.get("/endpoints")
def endpoints(
    project_id: UUID,
    user: Principal,
    db: DB,
    revision: Revision | None = None,
    method: Annotated[
        str | None, Query(pattern="^(GET|PUT|POST|DELETE|OPTIONS|HEAD|PATCH|TRACE)$")
    ] = None,
    offset: Annotated[int, Query(ge=0, le=500)] = 0,
    limit: Limit = 50,
) -> InventoryPage:
    scope(db, user, project_id, Permission.READ_INVENTORY)
    revisions = select(ImportRevision).where(ImportRevision.project_id == project_id)
    if revision is not None:
        revisions = revisions.where(ImportRevision.revision == revision)
    row = db.scalar(revisions.order_by(ImportRevision.revision.desc()).limit(1))
    if row is None:
        if revision is not None:
            raise HTTPException(404, "Import revision not found")
        return InventoryPage(revision=None, entries=[], next_offset=None)
    query = select(Endpoint).where(Endpoint.import_id == row.id)
    if method is not None:
        query = query.where(Endpoint.method == method)
    rows = db.scalars(
        query.order_by(Endpoint.path, Endpoint.method).offset(offset).limit(limit + 1)
    ).all()
    return InventoryPage(
        revision=RevisionInfo.model_validate(row),
        entries=[EndpointInfo.model_validate(e) for e in rows[:limit]],
        next_offset=offset + limit if len(rows) > limit else None,
    )
