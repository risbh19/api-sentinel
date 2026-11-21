"""Preserve incident investigations and project-scoped alert links."""

import sqlalchemy as sa
from alembic import op

revision = "0010_incident_workflows"
down_revision = "0009_alert_correlation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_alert_project_id", "alerts", ["project_id", "id"])
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("priority", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "id", name="uq_incident_project_id"),
        sa.CheckConstraint("status IN ('open','acknowledged','investigating','resolved','reopened')", name="ck_incident_status"),
        sa.CheckConstraint("priority IN ('low','medium','high')", name="ck_incident_priority"),
        sa.CheckConstraint("(status='resolved') = (resolved_at IS NOT NULL)", name="ck_resolved"),
    )
    op.create_index("ix_incidents_assignee", "incidents", ["assignee_id"])
    op.create_table(
        "incident_alerts",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), primary_key=True),
        sa.Column("alert_id", sa.Uuid(), primary_key=True),
        sa.ForeignKeyConstraint(["project_id", "incident_id"], ["incidents.project_id", "incidents.id"]),
        sa.ForeignKeyConstraint(["project_id", "alert_id"], ["alerts.project_id", "alerts.id"]),
        sa.UniqueConstraint("alert_id", name="uq_incident_alert"),
    )
    op.create_table(
        "incident_activity",
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("incidents.id"), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("old_value", sa.String(36)),
        sa.Column("new_value", sa.String(36)),
        sa.Column("note", sa.String(2000)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.execute("LOCK TABLE incidents IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM incidents)")):
        raise RuntimeError("Downgrade would discard incident history")
    op.drop_table("incident_activity")
    op.drop_table("incident_alerts")
    op.drop_table("incidents")
    op.drop_constraint("uq_alert_project_id", "alerts", type_="unique")
