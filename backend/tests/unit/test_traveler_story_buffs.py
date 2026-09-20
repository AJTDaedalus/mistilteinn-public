"""A Traveler carries their story-quest buffs, and nobody else does.

Owner ruling, 2026-09-19: **match gcsim**, which applies all three by default
(`internal/characters/traveler/common/storybuffs.go:26-57` at the pin). Until this landed,
`/explain` and a gcsim run disagreed on every Traveler build.

**The expected numbers here were measured, not read.** Running gcsim's own
`aetheranemo` at 90/90 with a Dull Blade, once with the default params and once with all
three set to 0, the snapshot moves by exactly:

    BaseATK +10   BaseHP +50   EM +75   CR +0.1   CD +0.2   ER +0.2
    and ATK, HP and DEF each up by 20 % of their base

which is the table in `formula/genshin/story_buffs.py` and nothing else.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import tags
from app.formula.genshin.explain import ContributionLog
from app.formula.genshin.story_buffs import TRAVELER_STORY_BUFFS
from app.pando.calculator import NodeRegistry
from app.services.stat_calculator import CharacterStats, add_character
from app.services.traveler import is_traveler

#: A Traveler-shaped row. The numbers are irrelevant to what is asserted — every test here
#: compares a build against *itself* with the flag flipped, so nothing rests on them.
_CURVES = {
    "FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_S4",
    "FIGHT_PROP_BASE_ATTACK": "GROW_CURVE_ATTACK_S4",
    "FIGHT_PROP_BASE_DEFENSE": "GROW_CURVE_HP_S4",
}


def _character(*, traveler: bool) -> CharacterStats:
    return CharacterStats(
        name="Traveler",
        base_hp=912.0,
        base_atk=18.0,
        base_def=57.0,
        prop_curves=_CURVES,
        ascension_rows=[],
        elemental_mastery=0.0,
        crit_rate=0.05,
        crit_dmg=0.5,
        is_traveler=traveler,
    )


def _log(*, traveler: bool) -> ContributionLog:
    log = ContributionLog(registry=NodeRegistry())
    add_character(log, _character(traveler=traveler), level=90, ascension_phase=0)
    return log


def _totals(*, traveler: bool) -> dict[str, float]:
    """Every quantity's summed contributions, by quantity."""
    totals: dict[str, float] = {}
    for c in _log(traveler=traveler).contributions:
        totals[c.quantity] = totals.get(c.quantity, 0.0) + c.value
    return totals


def _delta() -> dict[str, float]:
    on, off = _totals(traveler=True), _totals(traveler=False)
    return {
        q: round(on.get(q, 0.0) - off.get(q, 0.0), 9)
        for q in set(on) | set(off)
        if abs(on.get(q, 0.0) - off.get(q, 0.0)) > 1e-9
    }


def test_the_buffs_are_exactly_what_gcsim_applies():
    """Measured against gcsim, one stat at a time — see the module docstring."""
    assert _delta() == {
        tags.Q_BASE_ATK: 10.0,     # 3 (Sumeru) + 7 (Skirk's quest)
        tags.Q_BASE_HP: 50.0,
        tags.Q_ELEMENTAL_MASTERY: 75.0,   # 15 + 60
        tags.Q_CRIT_RATE: 0.1,
        tags.Q_CRIT_DMG: 0.2,
        tags.Q_ENERGY_RECHARGE: 0.2,
        tags.Q_ATK_PCT: 0.2,
        tags.Q_HP_PCT: 0.2,
        tags.Q_DEF_PCT: 0.2,
    }


def test_a_character_who_is_not_a_traveler_gets_nothing():
    """The half that makes the other half meaningful."""
    assert _totals(traveler=False).get(tags.Q_CRIT_DMG) == pytest.approx(0.5)


def test_the_base_bonuses_land_in_base_and_not_in_flat():
    """+3 base ATK is multiplied by every ATK % the build has; +3 flat ATK is not.

    The difference is invisible on a naked Traveler and grows with the build, so it would
    have surfaced as a drift against gcsim that looked like a formula error.
    """
    delta = _delta()

    assert tags.Q_BASE_ATK in delta
    assert tags.Q_FLAT_ATK not in delta
    assert tags.Q_BASE_HP in delta
    assert tags.Q_FLAT_HP not in delta


def test_each_buff_says_which_quest_it_came_from():
    """`/explain` has to name the source, or a user cannot check it."""
    reasons = {
        c.note for c in _log(traveler=True).contributions
        if c.source == tags.SRC_STORY_QUEST
    }

    assert len(reasons) == len(TRAVELER_STORY_BUFFS)
    assert any("Sumeru" in r for r in reasons)
    assert any("Skirk" in r for r in reasons)
    assert any("True Moon" in r for r in reasons)


def test_the_predicate_needs_both_the_name_and_the_art():
    """A future character called "Traveler" must not start collecting quest rewards."""
    assert is_traveler(name="Traveler", icon="UI_AvatarIcon_PlayerGirl")
    assert not is_traveler(name="Traveler", icon="UI_AvatarIcon_SomebodyElse")
    assert not is_traveler(name="Kamisato Ayaka", icon="UI_AvatarIcon_Ayaka")
