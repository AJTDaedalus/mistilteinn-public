"""build w_engine_level

Revision ID: d5369b2a8ba7
Revises: bd059cdbba4b
Create Date: 2026-04-26 22:31:40.542565

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd5369b2a8ba7'
down_revision: str | None = 'bd059cdbba4b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "builds",
        sa.Column(
            "w_engine_level", sa.Integer(),
            nullable=False, server_default="60",
        ),
    )


def downgrade() -> None:
    op.drop_column("builds", "w_engine_level")
