"""builds: unique constraint on (owner_id, agent_id)

One build per user per agent. Partial index excludes NULL owner_id rows so
anonymous builds are unaffected. Deduplication step keeps the most-recently-
updated row per (owner_id, agent_id) pair before applying the constraint.

Revision ID: d0e1f2a3b4c5
Revises: c9d8e7f6a5b4
Create Date: 2026-06-27

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d8e7f6a5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Remove duplicate (owner_id, agent_id) rows, keeping the most recently
    # updated build per pair. Safe to run on an empty or clean DB.
    op.execute("""
        DELETE FROM builds
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY owner_id, agent_id
                           ORDER BY updated_at DESC, id DESC
                       ) AS rn
                FROM builds
                WHERE owner_id IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
    """)

    op.create_index(
        "uq_builds_owner_agent",
        "builds",
        ["owner_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text("owner_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_builds_owner_agent", table_name="builds")
