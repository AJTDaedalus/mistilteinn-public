"""add agent_resource_costs

Per-agent priced actions: what a mode costs, out of which bank, per press or per second.
`Agent.ex_energy_cost` holds one scalar for one mode and cannot express Burnice's six
(40 activation / 12.5 per sec / 5 blast, twice over). It is NOT dropped -- ~50 single-mode
agents are served correctly by it and it stays the simulator's fallback.

Additive and empty on upgrade: nothing reads this table until the importer populates it
(Task 4), so a migrated-but-not-re-seeded DB has zero rows here, not wrong ones. That is
the deliberate shape -- the `ex_energy_cost` lesson was a column the migration created and
only the nanoka importer could fill, which read as "cost 0" rather than "not loaded".

docs/DESIGN_resource_costs.md 6, docs/DESIGN_channeled_moves.md 4.5.

Revision ID: b85c4edea065
Revises: a7c31b9e5d40
Create Date: 2026-08-18 15:57:55.400507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b85c4edea065'
down_revision: Union[str, None] = 'a7c31b9e5d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('agent_resource_costs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('agent_id', sa.String(), nullable=False),
    sa.Column('cost_key', sa.String(length=200), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('per_sec', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('resource', sa.String(length=50), server_default='Energy', nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'cost_key', name='uq_agent_resource_costs_agent_key')
    )
    op.create_index(op.f('ix_agent_resource_costs_agent_id'), 'agent_resource_costs', ['agent_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_resource_costs_agent_id'), table_name='agent_resource_costs')
    op.drop_table('agent_resource_costs')
