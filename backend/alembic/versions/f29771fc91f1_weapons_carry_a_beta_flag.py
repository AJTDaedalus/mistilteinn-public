"""weapons carry a beta flag

The twin of `ca71ae2b952a`. Weapons kept the "beta content must not reach the app" ruling when
characters stopped, because a beta weapon in the build editor's picker is the leak #271 was
reported about. The owner extended the planner exception to them: a character and their
signature weapon are one decision, and pricing half of it is not much use.

The picker is still the line, not the database. `WeaponRepository` hides these unless a caller
asks, and only the planner asks.

Revision ID: f29771fc91f1
Revises: ca71ae2b952a
Create Date: 2026-09-07 19:41:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f29771fc91f1'
down_revision: Union[str, None] = 'ca71ae2b952a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Only this column. Autogenerate also proposes re-typing `optimization_runs.visibility` and
    # indexing it, which is pre-existing drift on a table nothing here touches, and not this
    # migration's to carry. Same note as `ca71ae2b952a`.
    op.add_column(
        'weapons',
        sa.Column('is_beta', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('weapons', 'is_beta')
