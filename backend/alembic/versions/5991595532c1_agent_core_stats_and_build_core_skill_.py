"""agent core_stats and build core_skill_level

Revision ID: 5991595532c1
Revises: d5369b2a8ba7
Create Date: 2026-04-27 04:17:37.651590

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5991595532c1'
down_revision: str | None = 'd5369b2a8ba7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "core_stats",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "builds",
        sa.Column(
            "core_skill_level",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
    )


def downgrade() -> None:
    op.drop_column("builds", "core_skill_level")
    op.drop_column("agents", "core_stats")
