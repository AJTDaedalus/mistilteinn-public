"""add attacks.select_when

Per-row runtime gate (D-CH5). NULL = unconditional, which is every existing row, so this
lands empty and changes no behaviour: the values are written by the skill-override seeder,
not by the migration. Same shape as `attacks.potential` and for the same reason — NULL must
mean "shared/always", so a DB migrated but not re-seeded degrades to today's behaviour
rather than to silently-dropped rows.


Revision ID: f08082fa6682
Revises: b85c4edea065
Create Date: 2026-08-20 01:25:29.556374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f08082fa6682'
down_revision: Union[str, None] = 'b85c4edea065'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('attacks', sa.Column('select_when', sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column('attacks', 'select_when')
