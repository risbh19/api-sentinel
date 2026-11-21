import hashlib
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api_sentinel.audit.records import Action, record
from api_sentinel.identity.models import Membership, User
from api_sentinel.identity.routes import DB, Principal, project_scope
from api_sentinel.identity.security import GRANTS, Permission, Role
from api_sentinel.organizations.models import Project

from .models import Incident, IncidentActivity, IncidentAlert

router = APIRouter(prefix="/api/v1/projects/{project_id}/incidents")
Status = Literal["open", "acknowledged", "investigating", "resolved", "reopened"]
Priority = Literal["low", "medium", "high"]
Limit = Annotated[int, Query(ge=1, le=100)]
TRANSITIONS = {
    "open": {"acknowledged"},
    "acknowledged": {"investigating"},
    "investigating": {"resolved"},
    "resolved": {"reopened"},
    "reopened": {"investigating"},
}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Create(Input):
    request_key: UUID | None = None
    title: str = Field(min_length=1, max_length=120)
    priority: Priority = "medium"
    alert_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def printable_title(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("Use a single printable line")
        return value


class Change(Input):
    version: int = Field(ge=1)


class Update(Change):
    status: Status | None = None
    assignee_id: UUID | None = None


class Note(Change):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def printable_note(cls, value: str) -> str:
        if not all(char.isprintable() or char == "\n" for char in value):
            raise ValueError("Use printable text or newlines")
        return value


class Summary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    priority: str
    status: str
    version: int
    opened_at: datetime
    resolved_at: datetime | None


class Activity(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: int
    actor_id: UUID
    action: str
    old_value: str | None
    new_value: str | None
    note: str | None
    occurred_at: datetime


class Detail(Summary):
    title: str
    assignee_id: UUID | None
    timeline: list[Activity]
    next_version: int | None


def activity(
    db: Session,
    incident: Incident,
    actor: UUID,
    action: str,
    *,
    old: str | None = None,
    new: str | None = None,
    note: str | None = None,
) -> None:
    incident.version += 1
    record(db, Action.INCIDENT_CHANGED,
           organization_id=db.scalar(select(Project.organization_id).where(Project.id == incident.project_id)),
           project_id=incident.project_id, actor_id=actor, incident_id=incident.id,
           incident_version=incident.version, request_id=db.info.get("request_id"))
    db.add(IncidentActivity(
        incident_id=incident.id, version=incident.version, actor_id=actor,
        action=action, old_value=old, new_value=new, note=note,
    ))
    db.flush()


def scoped(db: Session, project: UUID, incident_id: UUID) -> Incident:
    incident = db.scalar(select(Incident).where(Incident.project_id == project, Incident.id == incident_id))
    if incident is None:
        raise HTTPException(404, "Incident not found")
    return incident


def editable(db: Session, user: User, project: UUID, incident_id: UUID, version: int) -> Incident:
    project_scope(db, user, project, Permission.INVESTIGATE)
    incident = scoped(db, project, incident_id)
    if version != incident.version:
        raise HTTPException(409, "Incident changed; reload and retry")
    return incident


def link(db: Session, incident: Incident, alert_id: UUID, actor: UUID) -> None:
    found = db.scalar(text("SELECT id FROM alert_summaries WHERE project_id=:project AND id=:id"),
                      {"project": incident.project_id, "id": alert_id})
    if found is None:
        raise HTTPException(404, "Alert not found")
    if db.scalar(select(IncidentAlert.incident_id).where(IncidentAlert.project_id == incident.project_id, IncidentAlert.alert_id == alert_id)):
        raise HTTPException(409, "Alert already linked to an incident")
    db.add(IncidentAlert(project_id=incident.project_id, incident_id=incident.id, alert_id=alert_id))
    activity(db, incident, actor, "alert_linked", new=str(alert_id))


@router.post("", status_code=201)
def create(project_id: UUID, body: Create, response: Response, user: Principal, db: DB) -> Summary:
    project_scope(db, user, project_id, Permission.INVESTIGATE)
    digest = hashlib.sha256(body.model_dump_json(exclude={"request_key"}).encode()).hexdigest()
    if body.request_key is not None:
        previous = db.scalar(select(Incident).where(Incident.project_id == project_id,
                             Incident.creator_id == user.id, Incident.request_key == body.request_key))
        if previous is not None:
            if previous.creation_digest != digest:
                raise HTTPException(409, "Creation key already used with different inputs")
            response.status_code = 200
            return Summary.model_validate(previous)
    incident = Incident(creator_id=user.id, request_key=body.request_key, creation_digest=digest, id=uuid4(), project_id=project_id, title=body.title, priority=body.priority,
                        status="open", version=0)
    db.add(incident)
    db.flush()
    activity(db, incident, user.id, "opened", new="open")
    if body.alert_id is not None:
        link(db, incident, body.alert_id, user.id)
    return Summary.model_validate(incident)


@router.get("")
def incidents(project_id: UUID, user: Principal, db: DB, status: Status | None = None,
              after: UUID | None = None, limit: Limit = 25) -> list[Summary]:
    project_scope(db, user, project_id, Permission.READ_EVENTS)
    query = select(Incident).where(Incident.project_id == project_id)
    if status is not None:
        query = query.where(Incident.status == status)
    if after is not None:
        query = query.where(Incident.id > after)
    return [Summary.model_validate(i) for i in db.scalars(query.order_by(Incident.id).limit(limit))]


@router.get("/{incident_id}", response_model=Detail | Summary)
def detail(project_id: UUID, incident_id: UUID, user: Principal, db: DB,
           after_version: Annotated[int, Query(ge=0)] = 0, limit: Limit = 50) -> Detail | Summary:
    org = project_scope(db, user, project_id, Permission.READ_EVENTS)
    incident = scoped(db, project_id, incident_id)
    summary = Summary.model_validate(incident)
    member = db.get(Membership, (org, user.id))
    if member is None or Permission.INVESTIGATE not in GRANTS[Role(member.role)]:
        return summary
    rows = db.scalars(select(IncidentActivity).where(IncidentActivity.incident_id == incident_id,
                      IncidentActivity.version > after_version)
                      .order_by(IncidentActivity.version).limit(limit + 1)).all()
    return Detail(**summary.model_dump(), title=incident.title, assignee_id=incident.assignee_id,
                  timeline=[Activity.model_validate(row) for row in rows[:limit]],
                  next_version=rows[limit-1].version if len(rows) > limit else None)


@router.patch("/{incident_id}")
def update(project_id: UUID, incident_id: UUID, body: Update, user: Principal, db: DB) -> Summary:
    incident = editable(db, user, project_id, incident_id, body.version)
    changes = body.model_fields_set - {"version"}
    if changes == {"status"} and body.status is not None:
        if body.status not in TRANSITIONS[incident.status]:
            raise HTTPException(409, "Invalid incident status transition")
        previous, incident.status = incident.status, body.status
        incident.resolved_at = datetime.now(UTC) if body.status == "resolved" else None
        activity(db, incident, user.id, "status_changed", old=previous, new=body.status)
    elif changes == {"assignee_id"}:
        target = body.assignee_id
        if target is not None:
            eligible = db.scalar(select(User.id).join(Membership).join(
                Project, Project.organization_id == Membership.organization_id
            ).where(Project.id == project_id, User.id == target, User.active.is_(True),
                    Membership.role.in_((Role.OWNER, Role.ANALYST))))
            if eligible is None:
                raise HTTPException(422, "Choose an active investigator in this project")
        if target != incident.assignee_id:
            prior = str(incident.assignee_id) if incident.assignee_id else None
            incident.assignee_id = target
            activity(db, incident, user.id, "assigned", old=prior, new=str(target) if target else None)
    else:
        raise HTTPException(422, "Change one status or assignment at a time")
    return Summary.model_validate(incident)


@router.post("/{incident_id}/notes", status_code=201)
def add_note(project_id: UUID, incident_id: UUID, body: Note, user: Principal, db: DB) -> Summary:
    incident = editable(db, user, project_id, incident_id, body.version)
    activity(db, incident, user.id, "note_added", note=body.text)
    return Summary.model_validate(incident)


@router.put("/{incident_id}/alerts/{alert_id}")
def attach(project_id: UUID, incident_id: UUID, alert_id: UUID, body: Change, user: Principal, db: DB) -> Summary:
    incident = editable(db, user, project_id, incident_id, body.version)
    link(db, incident, alert_id, user.id)
    return Summary.model_validate(incident)
