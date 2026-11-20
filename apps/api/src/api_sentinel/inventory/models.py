from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api_sentinel.organizations.models import Base


class ImportRevision(Base):
    __tablename__ = "api_imports"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "revision", name="uq_import_revision"),
        sa.UniqueConstraint("project_id", "digest", name="uq_import_digest"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id", ondelete="CASCADE"))
    revision: Mapped[int]
    digest: Mapped[str] = mapped_column(sa.String(64))
    version: Mapped[str] = mapped_column(sa.String(8))
    count: Mapped[int]
    warnings: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()")
    )


class Endpoint(Base):
    __tablename__ = "api_endpoints"
    __table_args__ = (
        sa.UniqueConstraint("import_id", "path", "method", name="uq_import_endpoint"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    import_id: Mapped[UUID] = mapped_column(sa.ForeignKey("api_imports.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(sa.String(7))
    path: Mapped[str] = mapped_column(sa.String(512))
    operation_id: Mapped[str | None] = mapped_column(sa.String(128))
    security: Mapped[list[dict[str, list[str]]] | None] = mapped_column(JSONB(none_as_null=True))
