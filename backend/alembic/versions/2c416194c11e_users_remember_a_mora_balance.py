"""users remember a mora balance

The one planner quantity no GOOD export carries, so the only one that was retyped into every
plan request and thrown away. `docs/DESIGN_planner_materials.md` §8 OQ-M1.

**Nullable, and null is not zero.** "Has not said" and "holds none" are different answers and
the planner already distinguishes them — a shortfall computed against a number nobody gave is
a number nobody should act on.

**Autogenerate also proposed converting `optimization_runs.visibility` from a native
PostgreSQL enum to a varchar one, plus an index for it. That is pre-existing drift between
the model and this database and has nothing to do with mora, so it is not in here** — a
migration that quietly carries someone else's schema change is the one nobody can revert
cleanly.

Revision ID: 2c416194c11e
Revises: f29771fc91f1
Create Date: 2026-09-20 12:01:46.585447

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2c416194c11e'
down_revision: Union[str, None] = 'f29771fc91f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('mora', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'mora')
