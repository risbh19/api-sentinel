"""Record security activity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_audit_activity"
down_revision: str | Sequence[str] | None = "0002_project_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.Enum(
                "account.created",
                "session.login",
                "session.login_failed",
                "session.replaced",
                "session.logout",
                "project.created",
                "project.deleted",
                "member.added",
                "member.role_changed",
                "member.removed",
                name="ck_audit_action",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("subject_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "old_role",
            sa.Enum(
                "owner",
                "analyst",
                "developer",
                "viewer",
                name="ck_audit_old_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "new_role",
            sa.Enum(
                "owner",
                "analyst",
                "developer",
                "viewer",
                name="ck_audit_new_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_account_page",
        "audit_entries",
        ["subject_user_id", "occurred_at", "id"],
        unique=False,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "ix_audit_org_page",
        "audit_entries",
        ["organization_id", "occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_project_page",
        "audit_entries",
        ["organization_id", "project_id", "occurred_at", "id"],
        unique=False,
    )

    op.execute("""
        CREATE FUNCTION reject_audit_rewrite() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Audit entries are append-only' USING ERRCODE = '55000';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER audit_entries_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_entries
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_rewrite()
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_audit_project_page", table_name="audit_entries")
    op.drop_index("ix_audit_org_page", table_name="audit_entries")
    op.drop_index(
        "ix_audit_account_page",
        table_name="audit_entries",
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.drop_table("audit_entries")
    op.execute("DROP FUNCTION reject_audit_rewrite()")
