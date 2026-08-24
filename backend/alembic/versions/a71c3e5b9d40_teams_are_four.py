"""Genshin parties are four, not three — add the fourth team slot.

Revision ID: a71c3e5b9d40
Revises: d5f1a7c3e920

The fork inherited a three-slot `teams` table because a ZZZ squad is three agents. A Genshin
party is **four**, and nothing had needed the fourth until rotations did — a rotation for a
four-character team cannot be expressed against three slots at all.

This is the leaked-shape hazard `CLAUDE.md` names as the fork strategy's main long-term risk:
*"no column that exists because its ZZZ counterpart did."* It survived four chunks because
the table was never exercised beyond CRUD.

**Additive and null-safe.** Existing teams keep their three builds and gain an empty fourth
slot, so no data is touched and the downgrade loses only a column that was empty until this
migration shipped — unless someone has filled it, which is why the downgrade says so.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a71c3e5b9d40"
down_revision = "d5f1a7c3e920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the fourth slot, matching the other three exactly."""
    op.add_column("teams", sa.Column("build4_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_teams_build4_id_builds",
        "teams",
        "builds",
        ["build4_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Drop the fourth slot. **Any build assigned to it is forgotten**, not moved."""
    op.drop_constraint("fk_teams_build4_id_builds", "teams", type_="foreignkey")
    op.drop_column("teams", "build4_id")
