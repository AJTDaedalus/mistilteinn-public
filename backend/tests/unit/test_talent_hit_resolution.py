"""M.2 — resolving a hit from the build's own character.

`HitSpec` has said this since Chunk F:

    Deriving a talent's multiplier, scaling stat and damage channel from a character's stored
    talent rows is the kit corpus's job (Chunk H), and this repo has no kit corpus. […]
    […] a `talent` field that resolves this from the build's own character replaces it.

(Quoted with its marker removed, so a repo-wide search for open work counts open work rather
than notes about work that is done.)

Chunk H is closed. M.1 parses the rows and M.4 checked the parse against gcsim across 105
characters, so the field can exist — and "the caller states the hit" can stop meaning "the
user types 1.2091".

**The channel is still the caller's.** The published table gives a multiplier and nothing
about which element the hit lands as; a normal attack is physical for most characters and not
for a catalyst user, and infusions move it. Deriving it would be inventing a rule the data
does not state, which is the whole failure this parser was written to avoid.
"""

from __future__ import annotations

import pytest

from app.models.enums import TalentType
from app.services.talent_hits import (
    TalentHitUnavailableError,
    available_hits,
    resolve_talent_hit,
)


class _Scaling:
    def __init__(self, level: int, labels: list, params: list) -> None:
        self.level = level
        self.labels = labels
        self.params = params


class _Talent:
    def __init__(self, talent_type: TalentType, scalings: list[_Scaling]) -> None:
        self.talent_type = talent_type
        self.scalings = scalings


class _Character:
    def __init__(self, talents: list[_Talent], name: str = "Kamisato Ayaka") -> None:
        self.name = name
        self.talents = talents


BURST_LABELS = ["Cutting DMG|{param1:P}", "Bloom DMG|{param2:P}", "Energy Cost|{param5:I}"]


def _ayaka() -> _Character:
    """Ayaka's burst, at three levels. Level 1 is 1.123, level 9 is 1.9091 — from the
    committed payload, and confirmed against gcsim's `burstCut` in M.4."""
    return _Character([
        _Talent(TalentType.ELEMENTAL_BURST, [
            _Scaling(1, BURST_LABELS, [1.123, 1.6845, 0, 0, 80]),
            _Scaling(2, BURST_LABELS, [1.207225, 1.8108, 0, 0, 80]),
            _Scaling(9, BURST_LABELS, [1.9091, 2.86365, 0, 0, 80]),
        ]),
    ])


def test_a_hit_resolves_from_the_talent_row() -> None:
    hit = resolve_talent_hit(
        _ayaka(), {"elemental_burst": 1}, TalentType.ELEMENTAL_BURST, "Cutting DMG",
    )

    assert hit.multiplier == pytest.approx(1.123)


def test_the_builds_talent_level_is_used_not_level_one() -> None:
    """The bug this is most likely to have, and the least visible: a talent-9 burst
    simulated at talent 1 is 59% of its real multiplier, and the number still looks like a
    damage figure."""
    hit = resolve_talent_hit(
        _ayaka(), {"elemental_burst": 9}, TalentType.ELEMENTAL_BURST, "Cutting DMG",
    )

    assert hit.multiplier == pytest.approx(1.9091)


def test_a_missing_talent_level_is_refused_rather_than_assumed() -> None:
    """A build that never set a level has none, and defaulting to 1 would quietly report a
    weaker number than the user's character actually has."""
    with pytest.raises(TalentHitUnavailableError, match="no level"):
        resolve_talent_hit(_ayaka(), {}, TalentType.ELEMENTAL_BURST, "Cutting DMG")


def test_a_level_the_talent_has_no_row_for_is_refused() -> None:
    """Constellations raise the cap, so a level can exceed what the table publishes. Falling
    back to the nearest row would be a multiplier for a different talent level."""
    with pytest.raises(TalentHitUnavailableError, match="level 13"):
        resolve_talent_hit(
            _ayaka(), {"elemental_burst": 13}, TalentType.ELEMENTAL_BURST, "Cutting DMG",
        )


def test_a_character_without_that_talent_is_refused() -> None:
    with pytest.raises(TalentHitUnavailableError, match="elemental_skill"):
        resolve_talent_hit(
            _ayaka(), {"elemental_skill": 9}, TalentType.ELEMENTAL_SKILL, "Skill DMG",
        )


def test_an_unknown_label_says_what_is_available() -> None:
    """A caller that mistyped should be told what the talent has, not only that they erred."""
    with pytest.raises(TalentHitUnavailableError) as raised:
        resolve_talent_hit(
            _ayaka(), {"elemental_burst": 1}, TalentType.ELEMENTAL_BURST, "Slashing DMG",
        )

    assert "Cutting DMG" in str(raised.value)


def test_alternatives_are_picked_by_index_not_silently_collapsed() -> None:
    """`Low/High Plunge DMG` is two hits under one label. Returning the first would make the
    high plunge unreachable and look like a complete answer."""
    character = _Character([
        _Talent(TalentType.NORMAL_ATTACK, [
            _Scaling(1, ["Low/High Plunge DMG|{param1:P}/{param2:P}"], [1.278377, 1.596762]),
        ]),
    ])

    low = resolve_talent_hit(character, {"normal_attack": 1}, TalentType.NORMAL_ATTACK,
                             "Low/High Plunge DMG")
    high = resolve_talent_hit(character, {"normal_attack": 1}, TalentType.NORMAL_ATTACK,
                              "Low/High Plunge DMG", index=1)

    assert low.multiplier == pytest.approx(1.278377)
    assert high.multiplier == pytest.approx(1.596762)


def test_an_index_past_the_end_is_refused() -> None:
    with pytest.raises(TalentHitUnavailableError, match="index"):
        resolve_talent_hit(
            _ayaka(), {"elemental_burst": 1}, TalentType.ELEMENTAL_BURST,
            "Cutting DMG", index=4,
        )


# ── what a page offers ───────────────────────────────────────────────────────


def test_the_available_hits_are_what_resolve_accepts() -> None:
    """The picker-matches-validator guarantee, one more time.

    A page offering a label `resolve_talent_hit` would refuse tells a user their own
    selection is invalid, so the list comes from the same parse the resolution uses.
    """
    character = _ayaka()
    offered = available_hits(character, {"elemental_burst": 9})

    assert offered, "an empty list would pass this vacuously"
    for entry in offered:
        resolved = resolve_talent_hit(
            character, {"elemental_burst": 9}, entry.talent, entry.label, index=entry.index,
        )
        assert resolved.multiplier > 0


def test_only_talents_the_build_has_a_level_for_are_offered() -> None:
    """Offering a hit whose level is unset would produce a refusal the moment it is picked."""
    assert available_hits(_ayaka(), {}) == []
