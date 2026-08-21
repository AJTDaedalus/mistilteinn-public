"""Task 19d — `split_moves`: lift a row out into a move of its own (D-CH6).

For a row whose trigger the engine cannot evaluate at all. Trigger's `Counter` fires on an
automatic Perfect Dodge — i.e. on the **enemy attacking** — and this simulator has no enemy
attack model, so there is no state to gate on and no honest role to give it. The owner's
ruling: make it selectable, because the player knows whether they got a counter and the engine
never will.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.data.loaders.skill_overrides import MoveOverride, load_skill_overrides
from app.models.enums import HitMode


def test_a_split_renames_to_a_distinct_move() -> None:
    ov = MoveOverride(
        hit_mode=HitMode.CHANNEL,
        split_moves={"Counter DMG Multiplier": "Basic Attack: Silenced Shot - Counter"},
    )
    assert ov.split_moves == {
        "Counter DMG Multiplier": "Basic Attack: Silenced Shot - Counter"
    }


def test_two_rows_may_not_split_to_the_same_name() -> None:
    """That silently merges them, which is the opposite of splitting."""
    with pytest.raises(ValidationError, match="same move name"):
        MoveOverride(
            hit_mode=HitMode.CHANNEL,
            split_moves={"A DMG Multiplier": "New Move", "B DMG Multiplier": "New Move"},
        )


def test_an_empty_target_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        MoveOverride(hit_mode=HitMode.ATOMIC, split_moves={"A": "  "})


def test_absent_is_distinguishable_from_empty() -> None:
    assert MoveOverride(hit_mode=HitMode.ATOMIC).split_moves is None


def test_only_triggers_counter_splits_a_row() -> None:
    """The ledger, same contract as the channel and row-condition ones.

    A split rewrites a move key — what L4 validates and what saved combos reference — so one
    appearing without a decision must fail a test rather than pass one.

    One entry: Trigger's `Counter` (D-CH6, Task 19c). A second appearing without a decision must
    fail here rather than pass.
    """
    split = {
        f"{stem}:{name}:{param}"
        for stem, agent in load_skill_overrides().items()
        for name, entry in agent.moves.items()
        for param in (entry.split_moves or {})
    }
    assert split == {"trigger:Basic Attack: Silenced Shot:Counter DMG Multiplier"}
