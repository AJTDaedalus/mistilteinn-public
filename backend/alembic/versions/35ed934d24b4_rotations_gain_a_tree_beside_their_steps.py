"""rotations gain a tree beside their steps

Revision ID: 35ed934d24b4
Revises: ae4b7f29b90e
Create Date: 2026-09-03 08:03:52.882138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '35ed934d24b4'
down_revision: Union[str, None] = 'ae4b7f29b90e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add `rotations.tree`, **nullable and beside `steps`**.

    Nullable on purpose: the read path prefers a tree and falls back to steps, so old rows
    keep working through the rollout and a deploy needs no coordinated backfill. `steps` is
    dropped in a separate migration, only after the equivalence gate has passed on production
    data — `TASKS_rotation_language.md` 4.6.
    """
    op.add_column(
        "rotations",
        sa.Column("tree", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rotations", "tree")
