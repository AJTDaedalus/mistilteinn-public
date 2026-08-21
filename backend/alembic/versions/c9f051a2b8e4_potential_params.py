"""agents.potential_params — the per-level Potential value ramps (#90 Track 2)

A list of params per agent, each a six-element ramp indexed by
``builds.potential_rank - 1`` (index 0 = Level I, which grants the kit variant and no
value bonus, so it is 0 for every param).

Populated by the nanoka importer from ``potential_detail[<aid>01..05].desc``, NOT by this
migration — there is no source for it in the DB. An upgraded-but-not-re-seeded DB reads
NULL everywhere, which is the same "cannot check" state the rest of #90 guards against.

Revision ID: c9f051a2b8e4
Revises: b8d42e17c093
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9f051a2b8e4"
down_revision: str | None = "b8d42e17c093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("potential_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "potential_params")
