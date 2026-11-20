from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (sa.CheckConstraint("name ~ '[^[:space:]]'", name="ck_organizations_name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(sa.String(120))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "slug", name="uq_projects_organization_slug"),
        sa.CheckConstraint("name ~ '[^[:space:]]'", name="ck_projects_name"),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_projects_slug"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(sa.String(120))
    slug: Mapped[str] = mapped_column(sa.String(80))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
