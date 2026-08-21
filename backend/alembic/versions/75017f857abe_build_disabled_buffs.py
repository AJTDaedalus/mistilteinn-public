"""build disabled_buffs

Revision ID: 75017f857abe
Revises: 5991595532c1
Create Date: 2026-04-27 11:19:41.642553

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '75017f857abe'
down_revision: str | None = '5991595532c1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "builds",
        sa.Column(
            "disabled_buffs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("builds", "disabled_buffs")
