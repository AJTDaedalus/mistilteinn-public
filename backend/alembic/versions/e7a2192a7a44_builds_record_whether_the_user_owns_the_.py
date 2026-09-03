"""builds record whether the user owns the character

Revision ID: e7a2192a7a44
Revises: 35ed934d24b4
Create Date: 2026-09-03 10:52:36.187918

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a2192a7a44'
down_revision: Union[str, None] = '35ed934d24b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add `builds.owned`, **not null with a server default of true**.

    True rather than false, and the default matters twice. An import is how nearly every build
    arrives — a GOOD export is a record of gear the player actually has — so true is the
    honest default for the commoner case. It also makes this migration a **no-op for existing
    rows**, which are all real builds: nobody's inventory is reclassified as a test build by
    deploying this.

    `TASKS_account_tracking.md` 1.1.
    """
    op.add_column(
        "builds",
        sa.Column("owned", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("builds", "owned")
