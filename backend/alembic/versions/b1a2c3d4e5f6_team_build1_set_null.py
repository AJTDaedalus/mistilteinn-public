"""team build1_id nullable + SET NULL (Decision D-IM1)

`Team.build1_id` was `ondelete="CASCADE"` and NOT NULL — the only slot not
already converted by `0ffce792bc1e`. That meant deleting a Build sitting in a
team's slot 1 cascaded `Build -> Team -> Combo`, silently destroying saved
teams and combos (live prod bug, see DECISIONS.md D-IM1). Symmetric with
slots 2/3: a build delete now degrades a team instead of destroying it. The
>=1-member invariant moves entirely to the application save path — no DB
CHECK is added, since a `num_nonnulls(...) >= 1` constraint would make the
FK's own SET NULL action fail when the last slot empties.

Revision ID: b1a2c3d4e5f6
Revises: a7b8c9d0e1f2
Create Date: 2026-07-09
"""

import sqlalchemy as sa

from alembic import op

revision = "b1a2c3d4e5f6"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old FK constraint (CASCADE), add nullable column + SET NULL FK.
    # PostgreSQL requires DROP CONSTRAINT before ALTER COLUMN.
    with op.batch_alter_table("teams") as batch_op:
        batch_op.drop_constraint("teams_build1_id_fkey", type_="foreignkey")
        batch_op.alter_column("build1_id", existing_type=sa.String(), nullable=True)
        batch_op.create_foreign_key(
            "teams_build1_id_fkey", "builds", ["build1_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("teams") as batch_op:
        batch_op.drop_constraint("teams_build1_id_fkey", type_="foreignkey")
        batch_op.alter_column("build1_id", existing_type=sa.String(), nullable=False)
        batch_op.create_foreign_key(
            "teams_build1_id_fkey", "builds", ["build1_id"], ["id"], ondelete="CASCADE"
        )
