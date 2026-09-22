"""wish income per version and tier

Revision ID: 852589346580
Revises: 2c416194c11e
Create Date: 2026-09-22 07:41:08.773800

Autogenerate also offered an `optimization_runs.visibility` enum change and an index to go
with it. **Both were stripped**: they are pre-existing drift between the model and this
machine's database, they have nothing to do with wish income, and CLAUDE.md's rule is that a
commit never bundles unrelated changes. They need their own migration and their own decision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '852589346580'
down_revision: Union[str, None] = '2c416194c11e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wish_income',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('version', sa.String(length=16), nullable=False),
        sa.Column('major', sa.Integer(), nullable=False),
        sa.Column('minor', sa.Integer(), nullable=False),
        sa.Column('tier', sa.String(length=16), nullable=False),
        sa.Column('wishes', sa.Float(), nullable=False),
        sa.Column('is_estimate', sa.Boolean(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_wish_income')),
        sa.UniqueConstraint('version', 'tier', name='uq_wish_income_version_tier'),
    )
    op.create_index(op.f('ix_wish_income_version'), 'wish_income', ['version'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_wish_income_version'), table_name='wish_income')
    op.drop_table('wish_income')
