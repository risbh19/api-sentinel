from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from api_sentinel.organizations.models import Base


class RuleFinding(Base):
    __tablename__ = "rule_findings"
    __table_args__ = (
        sa.CheckConstraint(
            "threshold > 0 AND window_seconds > 0 AND cardinality(evidence) = threshold",
            name="ck_finding_evidence",
        ),
    )
    event_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("security_events.id", ondelete="CASCADE"), primary_key=True
    )
    rule_key: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    threshold: Mapped[int]
    window_seconds: Mapped[int]
    evidence: Mapped[list[UUID]] = mapped_column(ARRAY(sa.Uuid()))
