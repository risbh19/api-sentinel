from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from api_sentinel.organizations.models import Base


class RuleFinding(Base):
    __tablename__ = "rule_findings"
    __table_args__ = (
        sa.Index("ix_finding_alert", "alert_id"),
        sa.CheckConstraint(
            "threshold > 0 AND window_seconds > 0 AND cardinality(evidence) = threshold",
            name="ck_finding_evidence",
        ),
    )
    alert_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("alerts.id", name="fk_finding_alert", ondelete="CASCADE"),
        server_default=sa.FetchedValue(),
    )
    event_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("security_events.id", ondelete="CASCADE"), primary_key=True
    )
    rule_key: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    threshold: Mapped[int]
    window_seconds: Mapped[int]
    evidence: Mapped[list[UUID]] = mapped_column(ARRAY(sa.Uuid()))


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "id", name="uq_alert_project_id"),
        sa.CheckConstraint("severity IN ('medium','low')", name="ck_alert_severity"),
        sa.CheckConstraint("status IN ('open','acknowledged','resolved')", name="ck_alert_status"),
        sa.Index("ix_alert_project_bucket", "project_id", "bucket_start", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(sa.String(64))
    rule_key: Mapped[str] = mapped_column(sa.Text())
    version: Mapped[int]
    threshold: Mapped[int]
    window_seconds: Mapped[int]
    bucket_start: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(sa.String(64), unique=True)
    severity: Mapped[str] = mapped_column(sa.Text())
    status: Mapped[str] = mapped_column(sa.Text(), server_default=sa.text("'open'"))


class AlertEvidence(Base):
    __tablename__ = "alert_evidence"
    alert_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("security_events.id", ondelete="CASCADE"), primary_key=True
    )
