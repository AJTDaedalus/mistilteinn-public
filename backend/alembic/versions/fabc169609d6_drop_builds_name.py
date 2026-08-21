"""drop builds.name column (Decision D1)

The `name` column was a vestigial free-text field defaulting to "".
Imported builds never set it (eZOD importer left it empty → "Untitled" in
UI). Agent identity comes from the `agents` FK, not this column.

Revision ID: fabc169609d6
Revises: e1179be7cafb
Create Date: 2026-06-28
"""

import sqlalchemy as sa

from alembic import op

revision = "fabc169609d6"
down_revision = "e1179be7cafb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("builds", "name")


def downgrade() -> None:
    op.add_column(
        "builds",
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
    )
