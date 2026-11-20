from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from api_sentinel.organizations.models import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    email: Mapped[str] = mapped_column(sa.String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    active: Mapped[bool] = mapped_column(server_default=sa.true())


class Membership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        sa.CheckConstraint(
            "role IN ('owner','analyst','developer','viewer')", name="ck_membership_role"
        ),
        sa.Index("ix_memberships_user", "user_id"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("organizations.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(sa.String(12))


class WebSession(Base):
    __tablename__ = "web_sessions"
    token_hash: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)


class LoginWindow(Base):
    """Fixed slots cap storage even during floods of invented usernames."""

    __tablename__ = "login_windows"
    slot: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=False)
    window: Mapped[int] = mapped_column(sa.BigInteger)
    attempts: Mapped[int] = mapped_column(sa.Integer)
