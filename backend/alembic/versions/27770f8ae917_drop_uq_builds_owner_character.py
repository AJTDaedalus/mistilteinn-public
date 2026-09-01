"""drop uq_builds_owner_character — a user may own several builds of one character

`uq_builds_owner_character` was inherited verbatim from fairy's `uq_builds_owner_agent` and
kept pending an owner decision. It forbade saving a C0 and a C6 of the same character side by
side, or a Physical Eula against a Cryo one, which are ordinary things to want to compare in
this game. Dropped by owner decision, 2026-08-24 (T.1a).

**The rule moved rather than vanished.** gcsim refuses a party holding the same character
twice — `pkg/simulation/setup.go:94` at pin `3647a07` returns `duplicated character %v` — so
two builds of one character can coexist in a collection and cannot coexist on a team.
`app/api/v1/teams.py` enforces that instead.

**Reaffirmed 2026-09-01** (`docs/DECISIONS.md` §31). `BACKLOG_frontend.md` §3 asked to
reinstate the constraint five days after this migration; the owner declined — *"each user's
account only has one of each character"*, so two builds of one character are hypotheticals
about a single owned character rather than two things that can be equipped at once.

Revision ID: 27770f8ae917
Revises: b82d4f1a6c73
Create Date: 2026-08-24 06:17:04.824758
"""

from collections.abc import Sequence

from alembic import op

revision: str = "27770f8ae917"
down_revision: str | None = "b82d4f1a6c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        op.f("uq_builds_owner_character"),
        table_name="builds",
        postgresql_where="(owner_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Recreate the unique index.

    **This fails if any user has since saved two builds of one character**, which is the
    whole point of the upgrade. That is correct rather than unfortunate: silently keeping one
    build and discarding the other would delete a user's work to make a migration succeed.
    Deduplicate first if this ever needs to run.
    """
    op.create_index(
        op.f("uq_builds_owner_character"),
        "builds",
        ["owner_id", "character_id"],
        unique=True,
        postgresql_where="(owner_id IS NOT NULL)",
    )
