"""Queue every stored event and backfill earlier deliveries."""

import sqlalchemy as sa
from alembic import op

revision = "0007_event_jobs"
down_revision = "0006_security_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_jobs",
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("security_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("delivery_delay_ms", sa.BigInteger()),
        sa.CheckConstraint(
            "state IN ('pending','running','succeeded','dead')", name="ck_job_state"
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5", name="ck_job_attempts"),
    )
    op.create_index(
        "ix_event_jobs_due",
        "event_jobs",
        ["available_at", "event_id"],
        postgresql_where=sa.text("state IN ('pending','running')"),
    )
    op.execute("""
        CREATE FUNCTION public.queue_event_job() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO public.event_jobs(event_id) VALUES (NEW.id);
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER queue_event_job AFTER INSERT ON security_events
        FOR EACH ROW EXECUTE FUNCTION public.queue_event_job()
    """)
    op.execute("INSERT INTO event_jobs(event_id) SELECT id FROM security_events")


def downgrade() -> None:
    op.execute("DROP TRIGGER queue_event_job ON security_events")
    op.execute("DROP FUNCTION public.queue_event_job()")
    op.drop_table("event_jobs")
