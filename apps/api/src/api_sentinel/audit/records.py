"""Append audit facts within the transaction that performed the operation."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from api_sentinel.identity.security import Role
from api_sentinel.organizations.models import Base


class Action(StrEnum):
    ACCOUNT_CREATED = "account.created"
    INCIDENT_CHANGED = "incident.changed"
    LOGIN = "session.login"
    LOGIN_FAILED = "session.login_failed"
    SESSION_REPLACED = "session.replaced"
    LOGOUT = "session.logout"
    KEY_CREATED = "key.created"
    KEY_REVOKED = "key.revoked"
    INVENTORY_IMPORTED = "inventory.imported"
    PROJECT_CREATED = "project.created"
    PROJECT_DELETED = "project.deleted"
    MEMBER_ADDED = "member.added"
    ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    __table_args__ = (
        sa.Index("ix_audit_org_page", "organization_id", "occurred_at", "id"),
        sa.Index("ix_audit_project_page", "organization_id", "project_id", "occurred_at", "id"),
        sa.Index(
            "ix_audit_account_page",
            "subject_user_id",
            "occurred_at",
            "id",
            postgresql_where=sa.text("organization_id IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()")
    )
    action: Mapped[Action] = mapped_column(
        sa.Enum(
            Action,
            values_callable=lambda members: [item.value for item in members],
            native_enum=False,
            create_constraint=True,
            name="ck_audit_action",
        )
    )
    organization_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    actor_id: Mapped[UUID | None]
    incident_id: Mapped[UUID | None]
    incident_version: Mapped[int | None]
    key_id: Mapped[UUID | None]
    subject_user_id: Mapped[UUID | None]
    old_role: Mapped[Role | None] = mapped_column(
        sa.Enum(
            Role,
            values_callable=lambda members: [item.value for item in members],
            native_enum=False,
            create_constraint=True,
            name="ck_audit_old_role",
        )
    )
    new_role: Mapped[Role | None] = mapped_column(
        sa.Enum(
            Role,
            values_callable=lambda members: [item.value for item in members],
            native_enum=False,
            create_constraint=True,
            name="ck_audit_new_role",
        )
    )
    request_id: Mapped[str | None] = mapped_column(sa.String(32))


def record(
    db: Session,
    action: Action,
    *,
    request_id: str | None = None,
    actor_id: UUID | None = None,
    organization_id: UUID | None = None,
    project_id: UUID | None = None,
    incident_id: UUID | None = None,
    incident_version: int | None = None,
    key_id: UUID | None = None,
    subject_user_id: UUID | None = None,
    old_role: Role | None = None,
    new_role: Role | None = None,
) -> None:
    db.add(
        AuditEntry(
            action=action,
            request_id=request_id,
            actor_id=actor_id,
            organization_id=organization_id,
            project_id=project_id,
            incident_id=incident_id,
            incident_version=incident_version,
            key_id=key_id,
            subject_user_id=subject_user_id,
            old_role=old_role,
            new_role=new_role,
        )
    )
