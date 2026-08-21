"""drop build support columns

Removes support1/2_build_id and support1/2_agent_id from builds.
Team context is now carried by the caller, not embedded in Build rows.

Revision ID: c9d8e7f6a5b4
Revises: a1b2c3d4e5f6
Create Date: 2026-06-27

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9d8e7f6a5b4"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop FK constraints before dropping columns
    op.drop_constraint("fk_builds_support1_build_id", "builds", type_="foreignkey")
    op.drop_constraint("fk_builds_support2_build_id", "builds", type_="foreignkey")
    op.drop_constraint("fk_builds_support1_agent", "builds", type_="foreignkey")
    op.drop_constraint("fk_builds_support2_agent", "builds", type_="foreignkey")

    op.drop_column("builds", "support1_build_id")
    op.drop_column("builds", "support2_build_id")
    op.drop_column("builds", "support1_agent_id")
    op.drop_column("builds", "support2_agent_id")


def downgrade() -> None:
    op.add_column("builds", sa.Column("support2_agent_id", sa.String(), nullable=True))
    op.add_column("builds", sa.Column("support1_agent_id", sa.String(), nullable=True))
    op.add_column("builds", sa.Column("support2_build_id", sa.String(), nullable=True))
    op.add_column("builds", sa.Column("support1_build_id", sa.String(), nullable=True))

    op.create_foreign_key(
        "fk_builds_support1_agent", "builds", "agents",
        ["support1_agent_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_builds_support2_agent", "builds", "agents",
        ["support2_agent_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_builds_support1_build_id", "builds", "builds",
        ["support1_build_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_builds_support2_build_id", "builds", "builds",
        ["support2_build_id"], ["id"], ondelete="SET NULL",
    )
