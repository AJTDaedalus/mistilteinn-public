"""characters carry a beta flag

Beta characters — the ids the manifest's `gi.new` names — used to be refused entry by the
importer under a standing ruling that beta content must not reach the app. The owner reopened
that for the planner (2026-09-07), so the rows are seeded and marked instead of held back.

**Nothing is hidden by this column alone.** `CharacterRepository.list` hides beta rows unless a
caller opts in, so the catalogue browser, the build editor and the optimizer behind it keep the
behaviour they had. Only `/planner` asks for them.

Revision ID: ca71ae2b952a
Revises: d2a8c3871a85
Create Date: 2026-09-07 18:01:49.608660

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ca71ae2b952a'
down_revision: Union[str, None] = 'd2a8c3871a85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # **Only this column.** Autogenerate also proposed re-typing `optimization_runs.visibility`
    # and indexing it — pre-existing drift between that model and the database, unrelated to
    # this change and not this migration's to carry. Bundling it would make a one-column
    # migration silently rewrite an enum on a table nothing here touches.
    op.add_column(
        'characters',
        sa.Column('is_beta', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('characters', 'is_beta')
