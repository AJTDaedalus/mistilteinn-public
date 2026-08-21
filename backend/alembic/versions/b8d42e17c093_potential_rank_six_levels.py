"""Widen potential_rank to 0..6 — Potential Vision has SIX levels (#90)

Corrects an off-by-one in the original `a7c31f0b9d24` domain (`0..5`, default 5).

nanoka's `potential_detail` carries six separately-purchasable nodes per agent,
displayed in-game as Level I..VI ("Shark's Rage I".."VI" for Ellen), each with its own
`potential_materials`. So the real state space is SEVEN, not six:

    0   -> no Potential Vision at all      -> base kit
    1   -> Level I   (node <aid>00)        -> unlocked kit, NO value bonus
    2-6 -> Levels II..VI (<aid>01..<aid>05) -> unlocked kit + ramp step

Level I is the discriminator that was missing. Its `ability_list` is `[<kit ability>]`
alone, while Levels II-VI are `[<kit ability>, <ramp ability N>]` — i.e. Level I buys the
kit variant and nothing else. Under the old `0..5` domain a player at Level I had no
correct value to enter: 0 gave them the base kit (wrong moves), 1 gave them the kit plus
Level II's bonus (over-credited by a step).

This also corrects the reading recorded for open question O-1. The 6-element ramp's
index 0 is **Level I**, not "locked" — ZO's own generator prepends that zero row after
dropping node <aid>00, which is exactly Level I's no-bonus state. Ellen's ramp
`[0, 0.016, 0.024, 0.032, 0.04, 0.048]` lines up against Levels I..VI term for term. So
Track 2 indexes `ramp[potential_rank - 1]`, and rank 0 never indexes the ramp at all.

Kit selection is unaffected: the predicate is `potential_rank >= 1` either way, which is
why Track 1 shipped correct despite the wrong ceiling.

The default moves 5 -> 6 for the same reason it was 5 before: it must mean "fully
unlocked", which is Level VI. Existing rows written under the old default read 5, which
now means Level V — one step short of maximum. They are re-defaulted here, because 5 was
never a value any UI could produce: the build editor writes only the two extremes.

Revision ID: b8d42e17c093
Revises: a7c31f0b9d24
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8d42e17c093"
down_revision: str | None = "a7c31f0b9d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_builds_potential_rank_range", "builds", type_="check")
    op.alter_column("builds", "potential_rank", server_default=sa.text("6"))
    # 5 meant "fully unlocked" under the old domain and means Level V under the new one.
    # No UI could ever write it (the editor writes 0 or the maximum), so every 5 in the
    # table is the old default rather than a user's choice.
    op.execute("UPDATE builds SET potential_rank = 6 WHERE potential_rank = 5")
    op.create_check_constraint(
        "ck_builds_potential_rank_range",
        "builds",
        "potential_rank BETWEEN 0 AND 6",
    )


def downgrade() -> None:
    op.drop_constraint("ck_builds_potential_rank_range", "builds", type_="check")
    op.execute("UPDATE builds SET potential_rank = 5 WHERE potential_rank > 5")
    op.alter_column("builds", "potential_rank", server_default=sa.text("5"))
    op.create_check_constraint(
        "ck_builds_potential_rank_range",
        "builds",
        "potential_rank BETWEEN 0 AND 5",
    )
