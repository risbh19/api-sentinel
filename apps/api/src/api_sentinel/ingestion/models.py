from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from api_sentinel.organizations.models import Base


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
