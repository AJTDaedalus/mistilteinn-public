"""track which furnishing sets a user has built

Revision ID: aa024ff55891
Revises: e8a9fe8d7464
Create Date: 2026-09-03 13:50:29.408946

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa024ff55891'
down_revision: Union[str, None] = 'e8a9fe8d7464'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Which sets a user has actually built.

    Owner, 2026-09-03: *"give users the way to mark sets 'complete' as having been built, it
    takes time and effort to build them so that's different from the invites."*

    **A different axis from `teapot_progress`, not a summary of it.** Building a set costs
    materials and time; inviting a character to one you have already built costs a walk. So a
    built set with three characters still to invite is *cheaper* than an unbuilt set with
    three, for the same 60 primogems — and the tracker cannot say that without knowing which
    is which.
    """
    op.create_table(
        "teapot_built",
        sa.Column("owner_id", sa.String(length=36),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("suite_id", sa.String(length=36),
                  sa.ForeignKey("furnishing_suites.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("built_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("teapot_built")
