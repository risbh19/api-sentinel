"""Add project ingestion credentials and key lifecycle audit facts."""

import sqlalchemy as sa
from alembic import op

revision = "0005_ingestion_keys"
down_revision = "0004_api_inventory"
branch_labels = None
depends_on = None

PREVIOUS = (
    "'account.created', 'session.login', 'session.login_failed', 'session.replaced', "
    "'session.logout', 'project.created', 'project.deleted', 'member.added', "
    "'member.role_changed', 'member.removed', 'inventory.imported'"
)


def audit_actions(allowed: str) -> None:
    op.drop_constraint("ck_audit_action", "audit_entries", type_="check")
    op.create_check_constraint("ck_audit_action", "audit_entries", f"action IN ({allowed})")


def upgrade() -> None:
    audit_actions(PREVIOUS + ", 'key.created', 'key.revoked'")
    op.add_column("audit_entries", sa.Column("key_id", sa.Uuid(), nullable=True))
    op.create_table(
        "ingestion_keys",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(48), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("prefix", name="uq_ingestion_key_prefix"),
    )
    op.create_index("ix_ingestion_keys_project_prefix", "ingestion_keys", ["project_id", "prefix"])


def downgrade() -> None:
    # Reject incompatible audit history before removing credential storage.
    audit_actions(PREVIOUS)
    op.drop_column("audit_entries", "key_id")
    op.drop_table("ingestion_keys")
