"""User-authored rotations (R.1).

Revision ID: b82d4f1a6c73
Revises: a71c3e5b9d40

A rotation is a name, a team and an ordered list of steps. See `app/models/rotation.py` for
why it hangs off a team rather than a build, and why a step names a character rather than a
slot or a build.

`team_id` cascades: a rotation without its team is an ordered list of characters nobody can
place, not a partial rotation.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "b82d4f1a6c73"
down_revision = "a71c3e5b9d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the rotations table."""
    op.create_table(
        "rotations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "owner_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "team_id", sa.String(), sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("steps", JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_rotations_owner_id", "rotations", ["owner_id"])
    op.create_index("ix_rotations_team_id", "rotations", ["team_id"])
    op.create_index("ix_rotations_owner_team", "rotations", ["owner_id", "team_id"])


def downgrade() -> None:
    """Drop the table. **Authored rotations are lost**, not archived."""
    op.drop_index("ix_rotations_owner_team", table_name="rotations")
    op.drop_index("ix_rotations_team_id", table_name="rotations")
    op.drop_index("ix_rotations_owner_id", table_name="rotations")
    op.drop_table("rotations")
