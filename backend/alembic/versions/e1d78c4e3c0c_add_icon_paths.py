"""add_icon_paths

Revision ID: e1d78c4e3c0c
Revises: 2f50b175f401
Create Date: 2026-05-21 17:40:34.055809

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e1d78c4e3c0c'
down_revision: str | None = '77fac5558a5b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'agents', sa.Column('icon_path', sa.String(length=500), server_default='', nullable=False),
    )
    op.add_column(
        'w_engines',
        sa.Column('icon_path', sa.String(length=500), server_default='', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('w_engines', 'icon_path')
    op.drop_column('agents', 'icon_path')
