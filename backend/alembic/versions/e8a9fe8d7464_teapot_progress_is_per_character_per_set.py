"""teapot progress is per character per set

Revision ID: e8a9fe8d7464
Revises: 479e18bed996
Create Date: 2026-09-03 13:31:44.034163

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8a9fe8d7464'
down_revision: Union[str, None] = '479e18bed996'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """`teapot_progress` gains the character, because the reward is per character per set.

    Owner's correction, 2026-09-03: *"Once per character per set, not once per set."*

    A set favoured by three characters you own is worth three separate invitations and three
    separate rewards. The old key `(owner, suite)` could only say a whole set was finished, so
    a user who had invited two of the three had **nowhere to record it** — the tracker would
    either show the set as done and lose 20 primogems, or as untouched and ask them to repeat
    work they had already done.

    **The table is recreated rather than altered.** Adding a column to a composite primary key
    means rewriting the key anyway, and this shipped hours ago with no rows anyone has entered
    — so there is nothing to migrate and pretending otherwise would be ceremony.
    """
    op.drop_table("teapot_progress")
    op.create_table(
        "teapot_progress",
        sa.Column("owner_id", sa.String(length=36),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("suite_id", sa.String(length=36),
                  sa.ForeignKey("furnishing_suites.id", ondelete="CASCADE"),
                  primary_key=True),
        # The character invited **to this set**. Not a foreign key to `characters`, for the
        # reason `furnishing_suite_favorites` gives: a favourite can name a character this
        # database has not seeded yet.
        sa.Column("character_nanoka_id", sa.String(length=32), primary_key=True),
        sa.Column("done_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("teapot_progress")
    op.create_table(
        "teapot_progress",
        sa.Column("owner_id", sa.String(length=36),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("suite_id", sa.String(length=36),
                  sa.ForeignKey("furnishing_suites.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("done_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
