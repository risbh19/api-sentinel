"""Store project inventory revisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_api_inventory"
down_revision: str | Sequence[str] | None = "0003_audit_activity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Keep earlier revisions independent of application enums.
PREVIOUS_ACTIONS = (
    "'account.created', 'session.login', 'session.login_failed', 'session.replaced', 'session.logout', "
    "'project.created', 'project.deleted', 'member.added', 'member.role_changed', 'member.removed'"
)


def audit_actions(allowed: str) -> None:
    op.drop_constraint("ck_audit_action", "audit_entries", type_="check")
    op.create_check_constraint("ck_audit_action", "audit_entries", f"action IN ({allowed})")


def upgrade() -> None:
    """Upgrade schema."""
    audit_actions(PREVIOUS_ACTIONS + ", 'inventory.imported'")
    op.create_table(
        "api_imports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=8), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "digest", name="uq_import_digest"),
        sa.UniqueConstraint("project_id", "revision", name="uq_import_revision"),
    )
    op.create_table(
        "api_endpoints",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(length=7), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("operation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "security", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.ForeignKeyConstraint(["import_id"], ["api_imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id", "path", "method", name="uq_import_endpoint"),
    )


def downgrade() -> None:
    """Preserve existing audit facts; the previous schema cannot represent imports."""
    audit_actions(PREVIOUS_ACTIONS)
    op.drop_table("api_endpoints")
    op.drop_table("api_imports")
