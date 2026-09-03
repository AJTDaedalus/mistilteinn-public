"""saved optimization runs

Revision ID: 20cdff369d94
Revises: e7a2192a7a44
Create Date: 2026-09-03 11:00:16.642926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20cdff369d94'
down_revision: Union[str, None] = 'e7a2192a7a44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A user's saved optimization runs, shareable like a published rotation.

    **Snapshots, not foreign keys.** `objective` and `snapshot` record what the search was
    asked and what it was run against, because a build changes: a shared result that silently
    re-read today's gear would show a number that no longer matches what actually ran. That is
    the recipe cache's own lesson (`DESIGN_account_tracking.md`, OQ-A1).

    `visibility` reuses the rotation library's enum rather than inventing a second sharing
    model — private by default, because a private thing becoming visible is not a mistake
    anyone can take back.
    """
    op.create_table(
        "optimization_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(length=16), nullable=False,
                  server_default="private"),
        sa.Column("share_key", sa.String(length=32), nullable=True, unique=True),
        # What the search was asked: sets, weapons, energy model, enemy, iterations.
        sa.Column("objective", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # What it ran against, frozen: build, artifacts with their substats, rotation.
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # What it concluded.
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        # How far ahead of the runner-up. "It won by 0.3%" and "by 12%" are different claims.
        sa.Column("margin", sa.Float(), nullable=True),
        sa.Column("iterations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        # A different simulator is a different result, and this is the one that would
        # otherwise go unnoticed for months.
        sa.Column("gcsim_pin", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("character_id", sa.String(length=36),
                  sa.ForeignKey("characters.id", ondelete="SET NULL"), nullable=True,
                  index=True),
        sa.Column("rotation_id", sa.String(length=36),
                  sa.ForeignKey("rotations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rotation_signature", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    # The list is ordered by recency and filtered by owner, which is one index.
    op.create_index(
        "ix_optimization_runs_owner_created",
        "optimization_runs", ["owner_id", "created_at"],
    )
    op.create_index(
        "ix_optimization_runs_visibility", "optimization_runs", ["visibility"],
    )


def downgrade() -> None:
    op.drop_index("ix_optimization_runs_visibility", table_name="optimization_runs")
    op.drop_index("ix_optimization_runs_owner_created", table_name="optimization_runs")
    op.drop_table("optimization_runs")
