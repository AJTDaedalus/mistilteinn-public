"""artifacts remember the lock the export carried

Revision ID: 29d7b9d77f9b
Revises: 53e610e77d29
Create Date: 2026-09-03 11:30:34.141000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29d7b9d77f9b'
down_revision: Union[str, None] = '53e610e77d29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add `artifacts.locked`, the flag a GOOD export already carries.

    `DESIGN_account_tracking.md` §"What else is worth storing", X.1. The importer has parsed
    `lock` since it was written and this schema dropped it — so the optimizer can currently
    recommend a build around a piece the user has locked for somebody else, which is advice
    they cannot take.

    Defaults false, which is what an unlocked piece is and what every existing row was
    imported as.
    """
    op.add_column(
        "artifacts",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("artifacts", "locked")
