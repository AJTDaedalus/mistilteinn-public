"""team_combo_replace — drop Combo.build_id, add Combo.team_id

Revision ID: f0a1b2c3d4e5
Revises: 0ffce792bc1e
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "0ffce792bc1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All existing combos are per-build; intentional data loss.
    op.execute("DELETE FROM combos")

    op.drop_constraint("combos_build_id_fkey", "combos", type_="foreignkey")
    op.drop_index("ix_combos_build_id", table_name="combos")
    op.drop_column("combos", "build_id")

    op.add_column("combos", sa.Column("team_id", sa.String(), nullable=False))
    op.create_foreign_key(
        None, "combos", "teams", ["team_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_combos_team_id", "combos", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_combos_team_id", table_name="combos")
    op.drop_constraint(None, "combos", type_="foreignkey")
    op.drop_column("combos", "team_id")

    op.add_column("combos", sa.Column("build_id", sa.String(), nullable=False))
    op.create_foreign_key(
        "combos_build_id_fkey", "combos", "builds", ["build_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_combos_build_id", "combos", ["build_id"])
