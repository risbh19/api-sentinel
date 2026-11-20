import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api_sentinel.audit.records import Action, record
from api_sentinel.database import transaction
from api_sentinel.organizations.models import Organization, Project
from api_sentinel.organizations.records import OrganizationRecords

from .models import Membership, User, WebSession
from .security import (
    COOKIE,
    COOKIE_PATH,
    DUMMY_HASH,
    GRANTS,
    HASHER,
    SESSION_SECONDS,
    Permission,
    Role,
    allow_login,
    csrf_token,
    digest,
    display_name,
    normalized_email,
)

router = APIRouter(prefix="/api/v1")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Slug = Annotated[
    str, StringConstraints(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
]


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return normalized_email(value)


class OrganizationInfo(BaseModel):
    id: UUID
    name: str
    role: Role


class Identity(BaseModel):
    id: UUID
    email: str
    organizations: list[OrganizationInfo]
    csrf_token: str


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    slug: Slug

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return display_name(value)


class ProjectInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    organization_id: UUID


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


def engine_for(request: Request) -> Engine:
    engine: Engine | None = request.app.state.access_engine
    if engine is None:
        raise HTTPException(503, "Account storage is unavailable")
    return engine


def session_for(request: Request) -> Iterator[Session]:
    with transaction(engine_for(request)) as session:
        yield session


DB = Annotated[Session, Depends(session_for, scope="function")]


def trusted_origin(request: Request) -> None:
    if request.headers.get("origin") != request.app.state.web_origin:
        raise HTTPException(403, "Untrusted request origin")


def current_user(request: Request, db: DB) -> User:
    token = request.cookies.get(COOKIE, "")
    if len(token) != 43 or not token.isascii():
        raise HTTPException(401, "Sign in required")
    user = db.scalar(
        select(User)
        .join(WebSession, WebSession.user_id == User.id)
        .where(
            WebSession.token_hash == digest(token),
            WebSession.expires_at > func.now(),
            User.active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(401, "Sign in required")
    if request.method not in {"GET", "HEAD"}:
        trusted_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied.isascii() or not secrets.compare_digest(supplied, csrf_token(token)):
            raise HTTPException(403, "Invalid request token")
    return user


Principal = Annotated[User, Depends(current_user)]


def identity(db: Session, user: User, token: str) -> Identity:
    rows = db.execute(
        select(Organization.id, Organization.name, Membership.role)
        .join(Membership)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name, Organization.id)
    )
    return Identity(
        id=user.id,
        email=user.email,
        csrf_token=csrf_token(token),
        organizations=[OrganizationInfo(id=i, name=n, role=Role(r)) for i, n, r in rows],
    )


def authorize(db: Session, user: User, org_id: UUID, permission: Permission) -> None:
    stmt = (
        select(Membership.role)
        .join(Organization)
        .where(Membership.organization_id == org_id, Membership.user_id == user.id)
    )
    if permission != Permission.READ:
        # Serialize role changes and writes within an organization, then reread membership.
        locked = db.scalar(
            select(Organization.id)
            .where(
                Organization.id == org_id,
                Organization.id.in_(
                    select(Membership.organization_id).where(Membership.user_id == user.id)
                ),
            )
            .with_for_update(read=permission in (Permission.READ_AUDIT, Permission.READ_INVENTORY))
        )
        if locked is None:
            raise HTTPException(404, "Organization not found")
    role = db.scalar(stmt)
    if role is None:
        raise HTTPException(404, "Organization not found")
    if permission not in GRANTS[Role(role)]:
        raise HTTPException(403, "Insufficient permission")


@router.post("/auth/login", response_model=Identity)
def login(body: Credentials, request: Request, response: Response, db: DB) -> Identity | Response:
    trusted_origin(request)
    if not allow_login(engine_for(request), body.email):
        raise HTTPException(429, "Too many sign-in attempts", headers={"Retry-After": "60"})
    user = db.scalar(select(User).where(User.email == body.email))
    verified: bool
    try:
        verified = HASHER.verify(
            user.password_hash if user is not None else DUMMY_HASH,
            body.password.get_secret_value(),
        )
    except VerifyMismatchError:
        verified = False
    if not verified or user is None or not user.active:
        # Return normally so the anonymized failure commits before the 401 is sent.
        record(db, Action.LOGIN_FAILED, request_id=request.state.request_id)
        return JSONResponse({"detail": "Invalid sign-in details"}, status_code=401)
    old = request.cookies.get(COOKIE)
    if old:
        previous_user = db.scalar(
            delete(WebSession)
            .where(WebSession.token_hash == digest(old), WebSession.expires_at > func.now())
            .returning(WebSession.user_id)
        )
        if previous_user is not None:
            # Switching accounts must not reveal the new identity in the old account's feed.
            record(
                db,
                Action.SESSION_REPLACED,
                subject_user_id=previous_user,
                request_id=request.state.request_id,
            )
    db.execute(delete(WebSession).where(WebSession.expires_at <= func.now()))
    token = secrets.token_urlsafe(32)
    db.add(
        WebSession(
            token_hash=digest(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(seconds=SESSION_SECONDS),
        )
    )
    record(
        db,
        Action.LOGIN,
        actor_id=user.id,
        subject_user_id=user.id,
        request_id=request.state.request_id,
    )
    response.set_cookie(
        COOKIE,
        token,
        path=COOKIE_PATH,
        max_age=SESSION_SECONDS,
        secure=request.app.state.web_origin.startswith("https://"),
        httponly=True,
        samesite="strict",
    )
    return identity(db, user, token)


@router.get("/auth/me")
def me(request: Request, user: Principal, db: DB) -> Identity:
    return identity(db, user, request.cookies[COOKIE])


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, user: Principal, db: DB) -> None:
    revoked_user = db.scalar(
        delete(WebSession)
        .where(WebSession.token_hash == digest(request.cookies[COOKIE]))
        .returning(WebSession.user_id)
    )
    if revoked_user is not None:
        record(
            db,
            Action.LOGOUT,
            actor_id=user.id,
            subject_user_id=revoked_user,
            request_id=request.state.request_id,
        )
    response.delete_cookie(
        COOKIE,
        path=COOKIE_PATH,
        secure=request.app.state.web_origin.startswith("https://"),
        httponly=True,
        samesite="strict",
    )


@router.get("/organizations/{org_id}/projects")
def projects(
    org_id: UUID, user: Principal, db: DB, after_slug: Slug | None = None
) -> list[ProjectInfo]:
    authorize(db, user, org_id, Permission.READ)
    return [
        ProjectInfo.model_validate(p)
        for p in OrganizationRecords(db, org_id).projects(after_slug=after_slug)
    ]


@router.post("/organizations/{org_id}/projects", status_code=201)
def create_project(
    org_id: UUID, request: Request, body: ProjectInput, user: Principal, db: DB
) -> ProjectInfo:
    authorize(db, user, org_id, Permission.EDIT_PROJECT)
    try:
        project = OrganizationRecords(db, org_id).create_project(body.name, body.slug)
    except IntegrityError:
        raise HTTPException(409, "Project conflicts with an existing record") from None
    record(
        db,
        Action.PROJECT_CREATED,
        organization_id=org_id,
        project_id=project.id,
        actor_id=user.id,
        request_id=request.state.request_id,
    )
    return ProjectInfo.model_validate(project)


@router.get("/projects/{project_id}")
def project_detail(project_id: UUID, user: Principal, db: DB) -> ProjectInfo:
    project = db.scalar(
        select(Project)
        .join(Membership, Membership.organization_id == Project.organization_id)
        .where(Project.id == project_id, Membership.user_id == user.id)
    )
    if project is None:
        raise HTTPException(404, "Project not found")
    return ProjectInfo.model_validate(project)


@router.delete("/organizations/{org_id}/projects/{project_id}", status_code=204)
def remove_project(
    org_id: UUID, project_id: UUID, request: Request, user: Principal, db: DB
) -> None:
    authorize(db, user, org_id, Permission.DELETE_PROJECT)
    if not OrganizationRecords(db, org_id).delete_project(project_id):
        raise HTTPException(404, "Project not found")

    record(
        db,
        Action.PROJECT_DELETED,
        organization_id=org_id,
        project_id=project_id,
        actor_id=user.id,
        request_id=request.state.request_id,
    )


def preserve_owner(db: Session, org_id: UUID, target: UUID, new_role: Role | None) -> None:
    current = db.get(Membership, (org_id, target))
    if current and current.role == Role.OWNER and new_role != Role.OWNER:
        owners = db.scalar(
            select(func.count())
            .select_from(Membership)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == org_id,
                Membership.role == Role.OWNER,
                Membership.user_id != target,
                User.active.is_(True),
            )
        )
        if not owners:
            raise HTTPException(409, "An organization requires at least one owner")


@router.put("/organizations/{org_id}/members/{target}", status_code=204)
def set_member(
    org_id: UUID, target: UUID, request: Request, body: MemberInput, user: Principal, db: DB
) -> None:
    authorize(db, user, org_id, Permission.MANAGE_MEMBERS)
    if db.scalar(select(User.id).where(User.id == target, User.active.is_(True))) is None:
        raise HTTPException(404, "User not found")
    current = db.get(Membership, (org_id, target))
    previous_role = Role(current.role) if current else None
    if previous_role == body.role:
        return
    preserve_owner(db, org_id, target, body.role)
    db.execute(
        insert(Membership)
        .values(organization_id=org_id, user_id=target, role=body.role)
        .on_conflict_do_update(
            index_elements=[Membership.organization_id, Membership.user_id],
            set_={"role": body.role},
        )
    )

    record(
        db,
        Action.MEMBER_ADDED if previous_role is None else Action.ROLE_CHANGED,
        organization_id=org_id,
        actor_id=user.id,
        subject_user_id=target,
        old_role=previous_role,
        new_role=body.role,
        request_id=request.state.request_id,
    )


@router.delete("/organizations/{org_id}/members/{target}", status_code=204)
def remove_member(org_id: UUID, target: UUID, request: Request, user: Principal, db: DB) -> None:
    authorize(db, user, org_id, Permission.MANAGE_MEMBERS)
    preserve_owner(db, org_id, target, None)
    old_role = db.scalar(
        delete(Membership)
        .where(Membership.organization_id == org_id, Membership.user_id == target)
        .returning(Membership.role)
    )
    if old_role is None:
        raise HTTPException(404, "Membership not found")
    record(
        db,
        Action.MEMBER_REMOVED,
        organization_id=org_id,
        actor_id=user.id,
        subject_user_id=target,
        old_role=Role(old_role),
        request_id=request.state.request_id,
    )
