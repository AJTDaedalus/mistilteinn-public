"""Math-fallback P3 (task 13): `reactions.py`, the transformative, additive and Lunar terms.

The gcsim crossval for the chain is `tests/crossval/test_reaction_crossval.py` (overloaded,
swirl, superconduct, from committed runs). These are the unit checks: the level table against
both oracles' literals, each family's formula written out by hand, and the refusals.
"""

from __future__ import annotations

import pytest

from app.data.snapshot import SnapshotUnavailableError, reaction_level_multiplier
from app.formula.genshin.damage import (
    Amplifying,
    DamageInputError,
    Hit,
    compute_damage,
    def_multiplier,
)
from app.formula.genshin.reactions import (
    ADDITIVE,
    LUNAR,
    REFUSED,
    TRANSFORMATIVE,
    Additive,
    Lunar,
    Transformative,
    additive_flat,
    lunar_damage,
    transformative_damage,
    transformative_element,
)

#: Anchors of the level table in both oracles at their pins, **as each writes it**: gcsim
#: `pkg/core/combat/reaction.dm.go` line `level + 5` (b107b5dc), GO
#: `libs/gi/keymap/src/StatConstants.ts` line `level + 159` (2c13fc40). The two write the same
#: decimals; the committed snapshot holds the game's float32 they were rounded from.
ORACLE_LEVEL_BASE = {
    1: 17.165606, 20: 80.58478, 40: 207.38205, 60: 492.8849, 70: 765.64026,
    80: 1077.4437, 90: 1446.8535, 95: 1561.468, 100: 1674.8092,
}


@pytest.mark.parametrize("level", sorted(ORACLE_LEVEL_BASE))
def test_the_level_table_is_the_one_both_oracles_were_generated_from(level: int):
    # float32 against a 7-significant-digit decimal: under 5e-8 everywhere (measured 4.6e-8
    # at worst over levels 1-100 against gcsim's whole table).
    assert reaction_level_multiplier(level) == pytest.approx(ORACLE_LEVEL_BASE[level], rel=5e-8)


def test_a_level_the_table_does_not_carry_is_refused():
    with pytest.raises(SnapshotUnavailableError, match="level 0"):
        reaction_level_multiplier(0)
    with pytest.raises(SnapshotUnavailableError, match="caller bug"):
        reaction_level_multiplier(10_000)


def _hand_transformative(multiplier: float, em: float, bonus: float, res: float) -> float:
    return multiplier * reaction_level_multiplier(90) * (1 + 16 * em / (2000 + em) + bonus) * res


@pytest.mark.parametrize(("reaction", "multiplier"), [
    (Transformative.OVERLOADED, 2.75), (Transformative.ELECTRO_CHARGED, 2.0),
    (Transformative.SUPERCONDUCT, 1.5), (Transformative.SHATTERED, 3.0),
    (Transformative.BURNING, 0.25), (Transformative.BLOOM, 2.0),
    (Transformative.HYPERBLOOM, 3.0), (Transformative.BURGEON, 3.0),
])
def test_each_transformative_reaction_by_hand(reaction: Transformative, multiplier: float):
    got = transformative_damage(reaction, character_level=90, elemental_mastery=800,
                                resistance=0.1, reaction_bonus=0.4)
    assert got.expected == pytest.approx(_hand_transformative(multiplier, 800, 0.4, 0.9))
    assert TRANSFORMATIVE[reaction].multiplier == multiplier


def test_a_swirl_carries_the_swirled_element_and_no_other():
    assert transformative_element(Transformative.SWIRL, "hydro") == "hydro"
    with pytest.raises(DamageInputError, match="swirl carries one of"):
        transformative_element(Transformative.SWIRL, "dendro")
    with pytest.raises(DamageInputError, match="swirl carries one of"):
        transformative_element(Transformative.SWIRL)
    with pytest.raises(DamageInputError, match="only a swirl"):
        transformative_element(Transformative.OVERLOADED, "pyro")
    assert transformative_element(Transformative.SHATTERED) == "physical"


def test_reaction_crit_reaches_only_a_reaction_that_can_crit():
    """GO `canCrit` (`StatConstants.ts:29-131`): bloom crits from Nahida's C2-style stats,
    overloaded never does. A CRIT for overloaded is refused, not silently ignored."""
    bloom = transformative_damage(Transformative.BLOOM, character_level=90,
                                  elemental_mastery=1000, resistance=0.1,
                                  crit_rate=0.2, crit_dmg=1.0)
    assert bloom.expected == pytest.approx(bloom.non_crit * 1.2)
    with pytest.raises(DamageInputError, match="cannot crit"):
        transformative_damage(Transformative.OVERLOADED, character_level=90,
                              elemental_mastery=0, resistance=0.1, crit_rate=0.2)


def test_the_character_level_is_what_moves_the_base():
    lv80 = transformative_damage(Transformative.BLOOM, character_level=80,
                                 elemental_mastery=0, resistance=0.0)
    assert lv80.expected == pytest.approx(2.0 * reaction_level_multiplier(80))


def test_additive_flat_by_hand():
    em = 300.0
    for reaction, k in ((Additive.SPREAD, 1.25), (Additive.AGGRAVATE, 1.15)):
        assert ADDITIVE[reaction].multiplier == k
        got = additive_flat(reaction, character_level=90, elemental_mastery=em,
                            reaction_bonus=0.2)
        assert got == pytest.approx(
            k * reaction_level_multiplier(90) * (1 + 5 * em / (1200 + em) + 0.2),
        )


def test_an_additive_reaction_enters_the_hit_before_its_dmg_bonus():
    """gcsim adds the catalyze damage to `FlatDmg` (`catalyze.go:24`), which sits inside the
    base and so under DMG%, DEF, RES and crit (`damage.go:59-60`)."""
    hit = Hit(multiplier=1.5, channel="electro", scope="skill",
              additive=Additive.AGGRAVATE, reaction_bonus=0.2)
    got = compute_damage(hit, scaling_value=2000, dmg_bonus=0.466, crit_rate=0.6,
                         crit_dmg=1.2, elemental_mastery=300, character_level=90,
                         enemy_level=100, resistance=0.1)
    flat = additive_flat(Additive.AGGRAVATE, character_level=90, elemental_mastery=300,
                         reaction_bonus=0.2)
    expected = (1.5 * 2000 + flat) * 1.466 * def_multiplier(90, 100) * 0.9 * (1 + 0.6 * 1.2)
    assert got.expected == pytest.approx(expected)
    assert "aggravate" in got.steps[0].detail


def test_a_hit_cannot_amplify_and_catalyze_at_once():
    hit = Hit(multiplier=1.0, channel="pyro", scope="skill",
              amplifying=Amplifying.VAPORIZE, additive=Additive.SPREAD)
    with pytest.raises(DamageInputError, match="not both"):
        compute_damage(hit, scaling_value=1000, dmg_bonus=0, crit_rate=0, crit_dmg=0,
                       elemental_mastery=0, character_level=90, enemy_level=90,
                       resistance=0.1)


def test_lunar_by_hand_and_with_the_characters_crit():
    em = 600.0
    for reaction, k in ((Lunar.LUNAR_CHARGED, 3.0), (Lunar.LUNAR_CRYSTALLIZE, 1.6)):
        assert LUNAR[reaction].multiplier == k
        got = lunar_damage(reaction, character_level=90, elemental_mastery=em,
                           resistance=0.1, crit_rate=0.7, crit_dmg=1.4,
                           reaction_bonus=0.1, base_dmg_bonus=0.2)
        non_crit = (k * reaction_level_multiplier(90) * (1 + 6 * em / (2000 + em) + 0.1)
                    * 1.2 * 0.9)
        assert got.non_crit == pytest.approx(non_crit)
        assert got.expected == pytest.approx(non_crit * (1 + 0.7 * 1.4))


def test_the_reactions_neither_oracle_triggers_are_refused_by_name():
    assert set(REFUSED) == {"lunar_bloom", "stellar_conduct", "stellar_swirl"}
    for reaction in REFUSED:
        assert reaction not in {*Transformative, *Additive, *Lunar}


def test_negative_em_is_refused():
    with pytest.raises(DamageInputError, match="negative"):
        additive_flat(Additive.SPREAD, character_level=90, elemental_mastery=-1)
