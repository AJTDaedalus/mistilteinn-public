"""build names, import timestamps and team notes

Revision ID: 479e18bed996
Revises: 29d7b9d77f9b
Create Date: 2026-09-03 11:32:37.781402

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '479e18bed996'
down_revision: Union[str, None] = '29d7b9d77f9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Three small things worth storing — `DESIGN_account_tracking.md` X.2 to X.4.

    Each is one column and each answers a question a user currently cannot:

    - **`builds.name`** — two builds for one character are told apart by their gear, which
      means reading five artifacts to answer "which one is this?".
    - **`users.gear_imported_at`** — a GOOD import replaces an inventory wholesale, and
      knowing when tells a user whether a saved optimization result predates their last
      farming session. That is the commonest reason a stored number stops being true.
    - **`teams.notes`** — a team has no free text at all, and the reason it exists
      ("Furina for the Skirk melt test") is exactly what gets forgotten.
    """
    op.add_column(
        "builds", sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("gear_imported_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "teams",
        sa.Column("notes", sa.String(length=1000), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("teams", "notes")
    op.drop_column("users", "gear_imported_at")
    op.drop_column("builds", "name")
