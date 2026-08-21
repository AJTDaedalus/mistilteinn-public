"""nullable team build2_id and build3_id (Decision D2)

Allows flex teams of 1, 2, or 3 members. build1_id stays required.
build2_id/build3_id become nullable; the ON DELETE action changes from
CASCADE to SET NULL so deleting a build nulls the team slot instead of
cascading the delete to the team row.

Revision ID: 0ffce792bc1e
Revises: fabc169609d6
Create Date: 2026-06-28
"""

import sqlalchemy as sa

from alembic import op

revision = "0ffce792bc1e"
down_revision = "fabc169609d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old FK constraints (CASCADE), add nullable columns + SET NULL FKs.
    # PostgreSQL requires DROP CONSTRAINT before ALTER COLUMN.
    with op.batch_alter_table("teams") as batch_op:
        batch_op.drop_constraint("teams_build2_id_fkey", type_="foreignkey")
        batch_op.drop_constraint("teams_build3_id_fkey", type_="foreignkey")
        batch_op.alter_column("build2_id", existing_type=sa.String(), nullable=True)
        batch_op.alter_column("build3_id", existing_type=sa.String(), nullable=True)
        batch_op.create_foreign_key(
            "teams_build2_id_fkey", "builds", ["build2_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "teams_build3_id_fkey", "builds", ["build3_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("teams") as batch_op:
        batch_op.drop_constraint("teams_build2_id_fkey", type_="foreignkey")
        batch_op.drop_constraint("teams_build3_id_fkey", type_="foreignkey")
        batch_op.alter_column("build2_id", existing_type=sa.String(), nullable=False)
        batch_op.alter_column("build3_id", existing_type=sa.String(), nullable=False)
        batch_op.create_foreign_key(
            "teams_build2_id_fkey", "builds", ["build2_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_foreign_key(
            "teams_build3_id_fkey", "builds", ["build3_id"], ["id"], ondelete="CASCADE"
        )
