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
#: The `FIGHT_PROP_*_SUB_HURT` members map to the **wearer's own** resistance, not to enemy
#: shred. C.2 read them off artifact affixes and described them as "RES shred"; the PR #7
#: review established they are a defensive stat (a Pyro-resistant character, not a
#: Pyro-vulnerable enemy). Enemy shred has its own `*_res_shred` pool, which no importable
#: `FIGHT_PROP` writes to — a shred effect is kit text, and therefore Chunk H's.
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
    StatType.ELECTRO_RES: tags.self_res_q("electro"),
    StatType.PYRO_RES: tags.self_res_q("pyro"),
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
def test_each_channel_has_a_bonus_a_shred_and_a_self_resistance_quantity(channel: str):
    assert tags.dmg_bonus_q(channel) in tags.ALL_QUANTITIES
    assert tags.res_shred_q(channel) in tags.ALL_QUANTITIES
    assert tags.self_res_q(channel) in tags.ALL_QUANTITIES


def test_enemy_shred_and_the_wearers_own_resistance_are_different_pools():
    """The distinction the PR #7 review drew: mapping `*_SUB_HURT` into the shred pool made
    a Pyro-resistant character deal *less* Pyro damage."""
    for channel in tags.DAMAGE_CHANNELS:
        assert tags.res_shred_q(channel) != tags.self_res_q(channel)

    stat_types = {_EXPECTED[StatType.ELECTRO_RES], _EXPECTED[StatType.PYRO_RES]}
    shred = {tags.res_shred_q(channel) for channel in tags.DAMAGE_CHANNELS}

    assert stat_types.isdisjoint(shred)
