"""Index project events in the order used by bounded retention jobs."""

from alembic import op

revision = "0011_event_retention"
down_revision = "0010_incident_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_events_project_receipt", "security_events", ["project_id", "received_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_events_project_receipt", table_name="security_events")
