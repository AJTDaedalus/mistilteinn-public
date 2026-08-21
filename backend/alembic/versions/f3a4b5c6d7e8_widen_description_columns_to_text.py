"""widen description columns to text

Skill/core/mindscape description columns were String(2000); long agent kits
(e.g. Velina, Promeia) hit the cap and silently lost the tail of the text
(Abloom MV clauses fell off the end). Widen to TEXT. See DECISIONS.md D-C8.6.

Revision ID: f3a4b5c6d7e8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-31

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("agent_skills", "core_skills", "mindscapes")


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "description",
            existing_type=sa.String(length=2000),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "description",
            existing_type=sa.Text(),
            type_=sa.String(length=2000),
            existing_nullable=False,
        )
