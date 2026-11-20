"""Store bounded rule evidence and schedule previously processed events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0008_detection_rules"
down_revision = "0007_event_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_findings",
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("security_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("rule_key", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("evidence", ARRAY(sa.Uuid()), nullable=False),
        sa.CheckConstraint(
            "threshold > 0 AND window_seconds > 0 AND cardinality(evidence) = threshold",
            name="ck_finding_evidence",
        ),
    )
    for index, dimensions, condition in (
        ("ix_event_auth_window", ["actor_hash"], "event_type = 'authentication_failure'"),
        (
            "ix_event_denial_window",
            ["actor_hash", "method", "route_template"],
            "event_type = 'authorization_denial'",
        ),
        ("ix_event_client_window", ["client_hash"], "client_hash IS NOT NULL"),
    ):
        op.create_index(
            index,
            "security_events",
            ["project_id", "source_id", *dimensions, "occurred_at", "external_event_id"],
            postgresql_where=sa.text(condition),
        )
    op.execute("""UPDATE event_jobs SET state='pending', attempts=0, available_at=now(),
                  queued_at=now(), last_error_code=NULL WHERE state='succeeded'""")


def downgrade() -> None:
    for index in ("ix_event_auth_window", "ix_event_denial_window", "ix_event_client_window"):
        op.drop_index(index, table_name="security_events")
    op.drop_table("rule_findings")
