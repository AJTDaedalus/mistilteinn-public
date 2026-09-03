"""furnishing suites and teapot progress

Revision ID: 53e610e77d29
Revises: 20cdff369d94
Create Date: 2026-09-03 11:19:44.100805

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '53e610e77d29'
down_revision: Union[str, None] = '20cdff369d94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Furnishing sets, who favours them, and which a user has finished.

    `DESIGN_account_tracking.md` Track 3. The catalogue half is seeded from nanoka's
    `suite.json`; `teapot_progress` is per user and is the whole of Seelie's affordance —
    mark it off and it leaves the list.

    `favorite` holds **nanoka character ids**, which `characters.nanoka_id` already uses, so
    the join to a user's owned roster needs no new identifier scheme.
    """
    op.create_table(
        "furnishing_suites",
        sa.Column("id", sa.String(length=36), primary_key=True),
        # nanoka's own key for the suite, so a re-capture updates rather than duplicates.
        sa.Column("nanoka_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        # "I" indoor, "O" outdoor — nanoka's own spelling, uninterpreted.
        sa.Column("placement", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("icon", sa.String(length=200), nullable=False, server_default=""),
        # The constituent furnishings and their counts, as published.
        sa.Column("units", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "furnishing_suite_favorites",
        sa.Column("suite_id", sa.String(length=36),
                  sa.ForeignKey("furnishing_suites.id", ondelete="CASCADE"),
                  primary_key=True),
        # The character's **nanoka** id rather than a foreign key to `characters`: a suite can
        # favour a character this database has not seeded yet, and losing the row would be
        # worse than holding an id that resolves later.
        sa.Column("character_nanoka_id", sa.String(length=32), primary_key=True),
    )
    op.create_index(
        "ix_suite_favorites_character",
        "furnishing_suite_favorites", ["character_nanoka_id"],
    )

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


def downgrade() -> None:
    op.drop_table("teapot_progress")
    op.drop_index("ix_suite_favorites_character", table_name="furnishing_suite_favorites")
    op.drop_table("furnishing_suite_favorites")
    op.drop_table("furnishing_suites")
