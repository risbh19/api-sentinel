"""Persist bounded sources, idempotent security events and project ingestion counters."""

import sqlalchemy as sa
from alembic import op

revision = "0006_security_events"
down_revision = "0005_ingestion_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_state",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("next_sequence", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("window", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("batches", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("next_sequence >= 0 AND batches >= 0", name="ck_ingestion_counters"),
    )
    op.create_table(
        "event_sources",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("source_id", sa.String(64), primary_key=True),
    )
    op.create_table(
        "security_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("external_event_id", sa.String(96), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("route_template", sa.String(512), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("actor_hash", sa.String(64)),
        sa.Column("client_hash", sa.String(64)),
        sa.Column("pseudonym_version", sa.String(16), nullable=False),
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
        sa.CheckConstraint(
            "method IN ('GET','POST','PUT','PATCH','DELETE','OPTIONS','HEAD','TRACE')",
            name="ck_event_method",
        ),
        sa.CheckConstraint(
            "event_type IN ('request','authentication_failure','authorization_denial')",
            name="ck_event_type",
        ),
        sa.CheckConstraint(
            "(event_type <> 'authentication_failure' OR status_code = 401) AND (event_type <> 'authorization_denial' OR status_code = 403)",
            name="ck_event_failure_status",
        ),
    )
    op.create_index("ix_events_project_time", "security_events", ["project_id", "occurred_at"])


def downgrade() -> None:
    # An explicit rollback removes telemetry, never identity, inventory or audit history.
    op.drop_table("security_events")
    op.drop_table("event_sources")
    op.drop_table("ingestion_state")
