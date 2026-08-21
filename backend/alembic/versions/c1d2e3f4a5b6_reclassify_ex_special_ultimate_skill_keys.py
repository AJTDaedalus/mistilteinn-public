"""reclassify_ex_special_ultimate_skill_keys

Reclassifies rows in `attacks` and `agent_skills` that nanoka imported as
"Special"/"Chain" because SKILL_TYPE_MAP had no EX Special / Ultimate keys.
Rows whose name starts with "EX Special" get skill_key="EXSpecial"; rows
whose name starts with "Ultimate" get skill_key="Ultimate".

Idempotent: the WHERE clause's existing skill_key guard prevents double-application.

Revision ID: c1d2e3f4a5b6
Revises: b8a895be5e9f
Create Date: 2026-05-30 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: str | None = 'b8a895be5e9f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE attacks SET skill_key = 'EXSpecial' "
        "WHERE name LIKE 'EX Special%' AND skill_key = 'Special'"
    )
    op.execute(
        "UPDATE attacks SET skill_key = 'Ultimate' "
        "WHERE name LIKE 'Ultimate%' AND skill_key = 'Chain'"
    )
    op.execute(
        "UPDATE agent_skills SET skill_key = 'EXSpecial' "
        "WHERE name LIKE 'EX Special%' AND skill_key = 'Special'"
    )
    op.execute(
        "UPDATE agent_skills SET skill_key = 'Ultimate' "
        "WHERE name LIKE 'Ultimate%' AND skill_key = 'Chain'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE attacks SET skill_key = 'Special' "
        "WHERE name LIKE 'EX Special%' AND skill_key = 'EXSpecial'"
    )
    op.execute(
        "UPDATE attacks SET skill_key = 'Chain' "
        "WHERE name LIKE 'Ultimate%' AND skill_key = 'Ultimate'"
    )
    op.execute(
        "UPDATE agent_skills SET skill_key = 'Special' "
        "WHERE name LIKE 'EX Special%' AND skill_key = 'EXSpecial'"
    )
    op.execute(
        "UPDATE agent_skills SET skill_key = 'Chain' "
        "WHERE name LIKE 'Ultimate%' AND skill_key = 'Ultimate'"
    )
