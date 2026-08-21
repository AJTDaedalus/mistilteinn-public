"""`attacks.select_when` — per-row runtime gating (Task 17a, D-CH5).

The mechanism only: Norma is authored in 17d, and until then nothing sets a condition. These
pin the *shape* — that NULL keeps meaning unconditional, that an unknown condition cannot
load, and that the shipped corpus has not quietly started using it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.data.loaders.skill_overrides import MoveOverride, load_skill_overrides
from app.models.enums import HitMode, RowCondition


def test_only_the_two_stun_conditions_exist() -> None:
    """Deliberately minimal. A member nothing evaluates is worse than no member at all."""
    assert {c.value for c in RowCondition} == {"enemy_stunned", "enemy_not_stunned"}


def test_an_unknown_condition_cannot_load() -> None:
    with pytest.raises(ValidationError):
        MoveOverride(hit_mode=HitMode.CHANNEL, row_conditions={"Shot": "when_convenient"})


def test_row_conditions_default_to_absent_not_empty() -> None:
    """Absent must be distinguishable from "declared and empty" for the same reason
    `potential` NULL is: a move that has never been considered reads differently from one
    considered and found unconditional."""
    assert MoveOverride(hit_mode=HitMode.ATOMIC).row_conditions is None


def test_only_normas_warheads_are_gated() -> None:
    """A ledger of every row gate in the corpus, not a vibe.

    Was "nothing gates a row yet" while 17a was mechanism-only; Task 17d authored the first
    four. A gate appearing without touching this test is a gate nobody decided on — the same
    contract as `test_no_shipped_move_binds_a_cost_yet`.
    """
    gated = {
        f"{stem}:{name}:{param}"
        for stem, agent in load_skill_overrides().items()
        for name, entry in agent.moves.items()
        for param in (entry.row_conditions or {})
    }
    move = "avatar_female_size01_norma:EX Special Attack: En-Nah Barrage"
    assert gated == {
        f"{move}:Armor-Piercing Warhead DMG Multiplier",
        f"{move}:High-Explosive Warhead DMG Multiplier",
        f"{move}:Extended Shot Armor-Piercing Warhead DMG Multiplier Per Sec",
        f"{move}:Extended Shot High-Explosive Warhead DMG Multiplier Per Sec",
    }
