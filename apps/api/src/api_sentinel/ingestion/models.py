from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from api_sentinel.organizations.models import Base

from .events import METHODS, TYPES


class IngestionKey(Base):
    __tablename__ = "ingestion_keys"
    __table_args__ = (
        sa.UniqueConstraint("prefix", name="uq_ingestion_key_prefix"),
        sa.Index("ix_ingestion_keys_project_prefix", "project_id", "prefix"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(sa.String(48))
    prefix: Mapped[str] = mapped_column(sa.String(20))
    key_hash: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class IngestionState(Base):
    __tablename__ = "ingestion_state"
    __table_args__ = (
        sa.CheckConstraint("next_sequence >= 0 AND batches >= 0", name="ck_ingestion_counters"),
    )
    project_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    next_sequence: Mapped[int] = mapped_column(sa.BigInteger(), server_default=sa.text("0"))
    window: Mapped[int] = mapped_column(sa.BigInteger(), server_default=sa.text("0"))
    batches: Mapped[int] = mapped_column(server_default=sa.text("0"))


class EventSource(Base):
    __tablename__ = "event_sources"
    project_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["project_id", "source_id"],
            ["event_sources.project_id", "event_sources.source_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "project_id", "source_id", "external_event_id", name="uq_event_delivery"
        ),
        sa.UniqueConstraint("project_id", "sequence", name="uq_event_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_event_sequence"),
        sa.CheckConstraint("status_code BETWEEN 100 AND 599", name="ck_event_status"),
        sa.CheckConstraint(f"method IN ({METHODS})", name="ck_event_method"),
        sa.CheckConstraint(f"event_type IN ({TYPES})", name="ck_event_type"),
        sa.CheckConstraint(
            "(event_type <> 'authentication_failure' OR status_code = 401) AND "
            "(event_type <> 'authorization_denial' OR status_code = 403)",
            name="ck_event_failure_status",
        ),
        sa.Index("ix_events_project_time", "project_id", "occurred_at"),
        sa.Index(
            "ix_event_auth_window",
            "project_id",
            "source_id",
            "actor_hash",
            "occurred_at",
            "external_event_id",
            postgresql_where=sa.text("event_type = 'authentication_failure'"),
        ),
        sa.Index(
            "ix_event_denial_window",
            "project_id",
            "source_id",
            "actor_hash",
            "method",
            "route_template",
            "occurred_at",
            "external_event_id",
            postgresql_where=sa.text("event_type = 'authorization_denial'"),
        ),
        sa.Index(
            "ix_event_client_window",
            "project_id",
            "source_id",
            "client_hash",
            "occurred_at",
            "external_event_id",
            postgresql_where=sa.text("client_hash IS NOT NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    project_id: Mapped[UUID] = mapped_column()
    source_id: Mapped[str] = mapped_column(sa.String(64))
    external_event_id: Mapped[str] = mapped_column(sa.String(96))
    sequence: Mapped[int] = mapped_column(sa.BigInteger())
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()")
    )
    event_type: Mapped[str] = mapped_column(sa.String(32))
    method: Mapped[str] = mapped_column(sa.String(8))
    route_template: Mapped[str] = mapped_column(sa.String(512))
    status_code: Mapped[int] = mapped_column()
    actor_hash: Mapped[str | None] = mapped_column(sa.String(64))
    client_hash: Mapped[str | None] = mapped_column(sa.String(64))
    pseudonym_version: Mapped[str] = mapped_column(sa.String(16))


class EventJob(Base):
    __tablename__ = "event_jobs"
    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('pending','running','succeeded','dead')", name="ck_job_state"
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5", name="ck_job_attempts"),
        sa.Index(
            "ix_event_jobs_due",
            "available_at",
            "event_id",
            postgresql_where=sa.text("state IN ('pending','running')"),
        ),
    )
    event_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("security_events.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(sa.Text(), server_default=sa.text("'pending'"))
    attempts: Mapped[int] = mapped_column(server_default=sa.text("0"))
    queued_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    available_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    last_error_code: Mapped[str | None] = mapped_column(sa.Text())
    delivery_delay_ms: Mapped[int | None] = mapped_column(sa.BigInteger())
