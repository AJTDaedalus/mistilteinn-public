"""F.1 — the DAG vocabulary and the database vocabulary must not drift apart.

`app/formula/` deliberately does not import `app/models/` — the DAG stays decoupled from the
ORM, which is fairy's convention and a good one. The cost of that decoupling is two spellings
of the same vocabulary, and the payment is this file: a test that fails when a stat exists on
one side and not the other.

Without it, C.2 could add a `StatType` member and the damage chain would quietly never read
it — a stat that exists in the database, imports correctly, and contributes nothing.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import tags
from app.models.enums import Element, StatType

#: `StatType` member → the DAG quantity it corresponds to. Every member must appear, which
#: is what makes this table a check rather than a convenience.
#:
#: The four `FIGHT_PROP_*_SUB_HURT` members map to resistance quantities: C.2 added them
#: because artifact affixes shred RES, and the DAG treats shred as a negative contribution
#: to the enemy's own pool (see `stats.res_node`).
_EXPECTED: dict[StatType, str] = {
    StatType.HP_FLAT: tags.Q_FLAT_HP,
    StatType.HP_PCT: tags.Q_HP_PCT,
    StatType.ATK_FLAT: tags.Q_FLAT_ATK,
    StatType.ATK_PCT: tags.Q_ATK_PCT,
    StatType.DEF_FLAT: tags.Q_FLAT_DEF,
    StatType.DEF_PCT: tags.Q_DEF_PCT,
    StatType.BASE_HP: tags.Q_BASE_HP,
    StatType.BASE_ATK: tags.Q_BASE_ATK,
    StatType.BASE_DEF: tags.Q_BASE_DEF,
    StatType.ELEMENTAL_MASTERY: tags.Q_ELEMENTAL_MASTERY,
    StatType.ENERGY_RECHARGE: tags.Q_ENERGY_RECHARGE,
    StatType.CRIT_RATE: tags.Q_CRIT_RATE,
    StatType.CRIT_DMG: tags.Q_CRIT_DMG,
    StatType.HEALING_BONUS: tags.Q_HEALING_BONUS,
    StatType.INCOMING_HEALING_BONUS: tags.Q_INCOMING_HEALING_BONUS,
    StatType.SHIELD_STRENGTH: tags.Q_SHIELD_STRENGTH,
    StatType.ANEMO_DMG_BONUS: tags.dmg_bonus_q("anemo"),
    StatType.CRYO_DMG_BONUS: tags.dmg_bonus_q("cryo"),
    StatType.DENDRO_DMG_BONUS: tags.dmg_bonus_q("dendro"),
    StatType.ELECTRO_DMG_BONUS: tags.dmg_bonus_q("electro"),
    StatType.GEO_DMG_BONUS: tags.dmg_bonus_q("geo"),
    StatType.HYDRO_DMG_BONUS: tags.dmg_bonus_q("hydro"),
    StatType.PYRO_DMG_BONUS: tags.dmg_bonus_q("pyro"),
    StatType.PHYSICAL_DMG_BONUS: tags.dmg_bonus_q("physical"),
    StatType.ELECTRO_RES: tags.res_q("electro"),
    StatType.PYRO_RES: tags.res_q("pyro"),
}


def test_every_stat_type_has_a_dag_quantity():
    """A member added to `StatType` without a quantity here would import fine and be read
    by nothing — a stat that exists in the database and contributes zero."""
    missing = [member.name for member in StatType if member not in _EXPECTED]

    assert missing == []


def test_every_mapped_quantity_is_one_the_vocabulary_declares():
    unknown = sorted({q for q in _EXPECTED.values() if q not in tags.ALL_QUANTITIES})

    assert unknown == []


def test_the_mapping_is_one_to_one():
    """Two stats sharing a quantity would silently pool together."""
    quantities = list(_EXPECTED.values())

    assert len(quantities) == len(set(quantities))


def test_every_vision_is_a_damage_channel_with_a_bonus_stat():
    """`Element` has seven members and each needs somewhere for its DMG bonus to land."""
    for element in Element:
        channel = element.value.lower()
        bonus_stat = StatType.dmg_bonus_for(element)
        assert channel in tags.VISIONS
        assert bonus_stat in _EXPECTED
        assert _EXPECTED[bonus_stat] == tags.dmg_bonus_q(channel)


@pytest.mark.parametrize("channel", tags.DAMAGE_CHANNELS)
def test_each_channel_has_both_a_bonus_and_a_resistance_quantity(channel: str):
    assert tags.dmg_bonus_q(channel) in tags.ALL_QUANTITIES
    assert tags.res_q(channel) in tags.ALL_QUANTITIES


def test_the_two_res_stat_types_are_a_subset_of_the_channels():
    """C.2 only observed Electro and Pyro RES shred on affixes; the DAG has all eight, which
    is the right direction for the asymmetry — a new shred affix needs no DAG change."""
    res_quantities = {tags.res_q(channel) for channel in tags.DAMAGE_CHANNELS}

    assert {_EXPECTED[StatType.ELECTRO_RES], _EXPECTED[StatType.PYRO_RES]} <= res_quantities
