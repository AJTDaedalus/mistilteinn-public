"""rename optimization_jobs display labels

The last ZZZ vocabulary in `app/models` outside comments: `agent_name` and `combo_name`
were denormalised display labels on the jobs table. B.5 deferred the rename to Chunk G
because it needs a migration; C.9's close-out sweep requires `app/models` and
`app/schemas` to be clean, and doing it now — before D seeds anything — is one
`alter_column` against an empty table instead of a data migration later.

`enemy_name` is unchanged: it was never ZZZ vocabulary.

Revision ID: 48eff150f21a
Revises: 466e02e5181f
Create Date: 2026-08-21 13:41:02.780341

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48eff150f21a'
down_revision: Union[str, None] = '466e02e5181f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("optimization_jobs", "agent_name", new_column_name="character_name")
    op.alter_column("optimization_jobs", "combo_name", new_column_name="rotation_name")


def downgrade() -> None:
    op.alter_column("optimization_jobs", "rotation_name", new_column_name="combo_name")
    op.alter_column("optimization_jobs", "character_name", new_column_name="agent_name")
