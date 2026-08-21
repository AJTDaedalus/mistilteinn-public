"""Potential as a per-build state (#90)

Adds:
  * ``builds.potential_rank``  — 0 = locked, 5 = fully unlocked. Server default 5, so
    every pre-existing build keeps the numbers it had under #85's unconditional
    Potential-unlocked import. No data step by construction.
  * ``potential`` on ``attacks`` / ``agent_skills`` / ``core_skills`` — the three-way
    row tag (NULL = present in both states, 'base', 'unlocked').
  * ``agents.has_potential`` -- whether the agent has a Potential tree at all (11 of
    60). The UI needs it to decide whether to offer the toggle; an inert control on
    the other 49 agents is a support question waiting to happen.
  * ``potential`` joins ``ix_attacks_agent_name_variant``: with both variants imported,
    a base/unlocked pair would otherwise collide under the same
    (agent_id, name, variant_label) prefix.

``has_potential`` and the row tag are populated by the nanoka importer, NOT by this
migration — there is no source for either in the DB. A DB that is upgraded but not
re-seeded therefore has the tag NULL everywhere, which reads as "every row is shared",
and ``has_potential`` false everywhere — the toggle silently does nothing.
``validate_kits --require-db`` treats an all-NULL column on a populated DB as "cannot
check" rather than clean; see docs/DESIGN_potential_toggle.md §7.

Revision ID: a7c31f0b9d24
Revises: 6b497e001038
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c31f0b9d24"
down_revision: str | None = "6b497e001038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TAGGED_TABLES = ("attacks", "agent_skills", "core_skills")


def upgrade() -> None:
    op.add_column(
        "builds",
        sa.Column(
            "potential_rank",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("5"),
        ),
    )
    op.create_check_constraint(
        "ck_builds_potential_rank_range",
        "builds",
        "potential_rank BETWEEN 0 AND 5",
    )

    op.add_column(
        "agents",
        sa.Column(
            "has_potential",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    for table in _TAGGED_TABLES:
        op.add_column(table, sa.Column("potential", sa.String(length=16), nullable=True))

    op.drop_index("ix_attacks_agent_name_variant", table_name="attacks")
    op.create_index(
        "ix_attacks_agent_name_variant",
        "attacks",
        ["agent_id", "name", "variant_label", "potential"],
    )


def downgrade() -> None:
    op.drop_index("ix_attacks_agent_name_variant", table_name="attacks")
    op.create_index(
        "ix_attacks_agent_name_variant",
        "attacks",
        ["agent_id", "name", "variant_label"],
    )

    for table in _TAGGED_TABLES:
        op.drop_column(table, "potential")

    op.drop_column("agents", "has_potential")

    op.drop_constraint("ck_builds_potential_rank_range", "builds", type_="check")
    op.drop_column("builds", "potential_rank")
