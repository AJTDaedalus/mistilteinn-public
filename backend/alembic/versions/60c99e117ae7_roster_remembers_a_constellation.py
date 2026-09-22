"""roster remembers a constellation

Revision ID: 60c99e117ae7
Revises: 852589346580

A GOOD export carries a constellation for every character the account owns, but only
characters holding a weapon or an artifact become builds, so for an owned-but-unequipped
character it was parsed and discarded. That is most of a 4-star roster, and the starglitter
refund turns on exactly those characters. `docs/DESIGN_wish_planner.md` section 9.4.

**Nullable, with no backfill.** Existing rows get NULL — "nobody has said" — rather than 0,
because an unknown constellation and a C0 one produce different refund figures and only one
of them is a claim. The next import fills them in.

Autogenerate also offered an `optimization_runs.visibility` enum change and its index; both
were stripped as pre-existing drift unrelated to this change, exactly as in 852589346580.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '60c99e117ae7'
down_revision: Union[str, None] = '852589346580'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'character_roster',
        sa.Column('constellation', sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        'ck_character_roster_constellation',
        'character_roster',
        'constellation IS NULL OR constellation BETWEEN 0 AND 6',
    )


def downgrade() -> None:
    op.drop_constraint('ck_character_roster_constellation', 'character_roster', type_='check')
    op.drop_column('character_roster', 'constellation')
