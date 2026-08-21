"""build supports

Revision ID: 54789a496796
Revises: 385b2aefc79f
Create Date: 2026-04-26 00:48:21.463250

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '54789a496796'
down_revision: str | None = '385b2aefc79f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('builds', sa.Column('support1_agent_id', sa.String(), nullable=True))
    op.add_column('builds', sa.Column('support2_agent_id', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_builds_support1_agent', 'builds', 'agents',
        ['support1_agent_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_builds_support2_agent', 'builds', 'agents',
        ['support2_agent_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_builds_support2_agent', 'builds', type_='foreignkey')
    op.drop_constraint('fk_builds_support1_agent', 'builds', type_='foreignkey')
    op.drop_column('builds', 'support2_agent_id')
    op.drop_column('builds', 'support1_agent_id')
