"""Piper's `Special Attack: One Trillion Tons` is three charge levels, not three hits (Task 1).

Fired as `atomic` this move dealt all three levels on every press — 43,169 bp of buildup against
Level-3's 23,500, a 1.84x over-count. The re-tag is a behaviour change on a shipped agent, so the
authored numbers are pinned rather than left to the gate to notice.
"""

from __future__ import annotations

from app.data.loaders.moves import load_agent_moves
from app.data.loaders.skill_overrides import load_skill_overrides
from app.models.enums import HitMode

_MOVE = "Special Attack: One Trillion Tons"


def test_the_move_is_a_variant_with_three_charge_levels() -> None:
    override = load_skill_overrides()["piper"].moves[_MOVE]
    assert override.hit_mode == HitMode.VARIANT
    assert [v.label for v in override.variants] == ["Level-1", "Level-2", "Level-3"]


def test_each_level_selects_exactly_one_row() -> None:
    """Mutual exclusivity is the whole claim; overlap would re-create the over-count."""
    override = load_skill_overrides()["piper"].moves[_MOVE]
    indices = [i for v in override.variants for i in v.hit_indices]
    assert indices == [0, 1, 2]
    assert len(set(indices)) == len(indices)
    assert all(len(v.hit_indices) == 1 for v in override.variants)


def test_buildup_is_one_level_not_the_sum() -> None:
    """23500 is Level-3. 43169 was 9333 + 10336 + 23500 — the bug, encoded as data."""
    move = load_agent_moves()["piper"].moves[_MOVE]
    assert move.buildup == 23500
    assert move.buildup != 43169
    assert move.hits == 1


def test_it_is_not_tagged_as_a_channel() -> None:
    """The word "hold" appears in the skill text, and the levels are still DISCRETE.

    `variant` is the axis for mutually-exclusive rows; `channel` is the axis for a continuously
    scaled hold. Piper is the first, and the Task 2 sweep found six more moves whose wording
    invites the same confusion.
    """
    move = load_agent_moves()["piper"].moves[_MOVE]
    assert move.channel is None
