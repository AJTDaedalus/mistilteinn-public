"""merge_team_decoupling_into_mainline

Merges the team-decoupling branch (d0e1f2a3b4c5) into the mainline
(e459468895fd) to establish a single head going forward.

Revision ID: e1179be7cafb
Revises: d0e1f2a3b4c5, e459468895fd
Create Date: 2026-06-28

"""
from collections.abc import Sequence

revision: str = "e1179be7cafb"
down_revision: tuple[str, str] = ("d0e1f2a3b4c5", "e459468895fd")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
