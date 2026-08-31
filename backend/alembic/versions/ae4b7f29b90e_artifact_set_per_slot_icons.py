"""artifact set per-slot icons

Revision ID: ae4b7f29b90e
Revises: 5f5a5f5543b7
Create Date: 2026-08-31 09:25:56.241129

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ae4b7f29b90e'
down_revision: str | None = '5f5a5f5543b7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Per-slot artifact art.

    nanoka publishes one icon per set and five more under `parts`, one per slot. Only the
    first was ever seeded, so every artifact card drew a flower whatever slot it was.

    Nullable and unbacked: a database seeded before this migration has the column empty until
    `seed_db` runs again, and every reader falls back to the set icon. Nothing breaks in the
    gap; the art is simply the old art.
    """
    op.add_column(
        "artifact_sets",
        sa.Column("part_icons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("artifact_sets", "part_icons")
