"""auth tokens carry the password submitted with their registration

Security audit F1: re-registering an unverified address kept the first registrant's
password. The hash now rides on the verification token and is applied when that link is
clicked. Nullable: tokens minted before this revision carry none, and verify then leaves the
account's password as it was — the old behaviour, for links already in inboxes.

Revision ID: 15b772b165f9
Revises: 41bbb85c1ecf
Create Date: 2026-11-12 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '15b772b165f9'
down_revision: Union[str, None] = '41bbb85c1ecf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'auth_tokens', sa.Column('password_hash', sa.String(length=72), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('auth_tokens', 'password_hash')
