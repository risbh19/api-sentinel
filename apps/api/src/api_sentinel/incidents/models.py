from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from api_sentinel.organizations.models import Base


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "id", name="uq_incident_project_id"),
        sa.UniqueConstraint("project_id", "creator_id", "request_key", name="uq_incident_request"),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','investigating','resolved','reopened')",
            name="ck_incident_status",
        ),
        sa.CheckConstraint("priority IN ('low','medium','high')", name="ck_incident_priority"),
        sa.CheckConstraint("(status='resolved') = (resolved_at IS NOT NULL)", name="ck_resolved"),
        sa.Index("ix_incidents_assignee", "assignee_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id"))
    creator_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"))
    request_key: Mapped[UUID | None]
    creation_digest: Mapped[str] = mapped_column(sa.String(64))
    title: Mapped[str] = mapped_column(sa.String(120))
    priority: Mapped[str] = mapped_column(sa.String(8))
    status: Mapped[str] = mapped_column(sa.String(16))
    version: Mapped[int]
    assignee_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    opened_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class IncidentAlert(Base):
    __tablename__ = "incident_alerts"
    __table_args__ = (
        sa.ForeignKeyConstraint(["project_id", "incident_id"], ["incidents.project_id", "incidents.id"]),
        sa.ForeignKeyConstraint(["project_id", "alert_id"], ["alerts.project_id", "alerts.id"]),
        sa.UniqueConstraint("alert_id", name="uq_incident_alert"),
    )
    project_id: Mapped[UUID]
    incident_id: Mapped[UUID] = mapped_column(primary_key=True)
    alert_id: Mapped[UUID] = mapped_column(primary_key=True)


class IncidentActivity(Base):
    __tablename__ = "incident_activity"
    incident_id: Mapped[UUID] = mapped_column(sa.ForeignKey("incidents.id"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(sa.String(24))
    old_value: Mapped[str | None] = mapped_column(sa.String(36))
    new_value: Mapped[str | None] = mapped_column(sa.String(36))
    note: Mapped[str | None] = mapped_column(sa.String(2000))
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
