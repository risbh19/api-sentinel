"""Create organizations and organization-owned projects."""

import sqlalchemy as sa
from alembic import op

revision = "0001_project_records"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("name ~ '[^[:space:]]'", name="ck_organizations_name"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("organization_id", "slug", name="uq_projects_organization_slug"),
        sa.CheckConstraint("name ~ '[^[:space:]]'", name="ck_projects_name"),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_projects_slug"),
    )


def downgrade() -> None:
    op.drop_table("projects")
    op.drop_table("organizations")
