"""F.4-F.6 — one fully specified build, from committed data to a damage figure.

Ayaka at 90/6 with Aquila Favonia and a five-piece artifact set, hitting an ordinary
level-90 enemy with her burst. Every input traces to something committed: the character and
weapon payloads (D.2), the growth curves and artifact value tables (E.5), and the formula
(gcsim, at the pin). This is the shape F.8's crossval case will take, minus the oracle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.formula.genshin import stats, tags
from app.formula.genshin.damage import Amplifying, Hit
from app.pando.calculator import Calculator, NodeRegistry
from app.services.damage_calculator import Enemy, evaluate_hit
from app.services.stat_calculator import (
    ArtifactStats,
    CharacterStats,
    WeaponStats,
    add_artifact,
    add_character,
    add_weapon,
    build_log,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"


def _payload(name: str) -> dict:
    return json.loads((_FIX / f"{name}.json").read_text(encoding="utf-8"))


def _build():
    """Ayaka + Aquila + five artifacts, all at max."""
    character = _payload("character_10000002")
    modifier = character["stats_modifier"]
    weapon = _payload("weapon_11501")

    log = build_log(NodeRegistry())
    add_character(log, CharacterStats(
        name=character["name"],
        base_hp=character["base_hp"],
        base_atk=character["base_atk"],
        base_def=character["base_def"],
        prop_curves={e["type"]: e["grow_curve"] for e in modifier["prop_grow_curves"]},
        ascension_rows=modifier["ascension"],
        elemental_mastery=character["elemental_mastery"],
        crit_rate=character["crit_rate"],
        crit_dmg=character["crit_dmg"],
    ), level=90, ascension_phase=6)
    add_weapon(log, WeaponStats(
        name=weapon["name"], props=weapon["weapon_prop"], ascension=weapon["ascension"],
    ), level=90, ascension_phase=6)

    for slot, main in (
        ("equip_bracer", "FIGHT_PROP_HP"),
        ("equip_necklace", "FIGHT_PROP_ATTACK"),
        ("equip_shoes", "FIGHT_PROP_ATTACK_PERCENT"),
        ("equip_ring", "FIGHT_PROP_ICE_ADD_HURT"),
        ("equip_dress", "FIGHT_PROP_CRITICAL_HURT"),
    ):
        add_artifact(log, ArtifactStats(slot=slot, rarity=5, level=20, main_stat=main))
    return log


_ORDINARY_ENEMY = Enemy(level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))
#: Ayaka's burst, "Kamisato Art: Soumetsu" — cutting DMG at talent level 1, from the
#: committed payload's `skills[3].promote["0"]`: `desc[0]` is `"Cutting DMG|{param1:P}"`
#: and `param[0]` is the multiplier. Read, not remembered.
_BURST_CUTTING_MULTIPLIER = _payload("character_10000002")["skills"][3]["promote"]["0"]["param"][0]


def test_the_talent_multiplier_is_read_from_the_payload():
    """The number the hit scales by is data, not a constant in a test.

    112.3% at talent level 1 — talent multipliers routinely exceed 100%, which is exactly
    why they are read rather than assumed to be fractions below one.
    """
    assert round(_BURST_CUTTING_MULTIPLIER, 3) == 1.123


def test_a_fully_specified_build_produces_a_damage_figure_that_explains_itself():
    log = _build()
    hit = Hit(
        multiplier=_BURST_CUTTING_MULTIPLIER, channel="cryo", scope="burst",
    )

    result = evaluate_hit(log.registry, hit, _ORDINARY_ENEMY, character_level=90)
    account = result.explain()

    assert result.non_crit > 0
    assert result.non_crit < result.expected < result.crit
    # The account names every multiplier that applied, in order.
    for term in ("base", "dmg bonus", "def", "res"):
        assert term in account


def test_the_numbers_the_chain_used_are_the_ones_the_stat_layer_resolved():
    """The join is the thing most likely to go quietly wrong, so it is asserted directly."""
    log = _build()
    calculator = Calculator(registry=log.registry)

    total_atk = calculator.compute(stats.ATK_NODE)
    cryo_bonus = calculator.compute(stats.scoped(stats.hit_dmg_bonus_node("cryo"), "burst"))
    crit_dmg = calculator.compute(stats.CRIT_DMG_NODE)

    # Ayaka 342 + Aquila 674 base, x (1 + 46.6% sands) + 311 plume.
    assert total_atk == pytest.approx((342 + 674) * 1.466 + 311, abs=2.0)
    # A goblet of Cryo DMG at +20 is 46.6%.
    assert cryo_bonus == pytest.approx(0.466, abs=0.001)
    # Base 50% + 38.4% from ascension + 62.2% from the circlet.
    assert crit_dmg == pytest.approx(0.5 + 0.384 + 0.622, abs=0.001)

    result = evaluate_hit(
        log.registry,
        Hit(multiplier=1.0, channel="cryo", scope="burst"),
        _ORDINARY_ENEMY,
        character_level=90,
    )
    assert result.non_crit == pytest.approx(total_atk * (1 + cryo_bonus) * 0.5 * 0.9, rel=1e-6)


def test_melting_the_same_hit_doubles_it_before_the_em_bonus():
    log = _build()
    plain = evaluate_hit(
        log.registry, Hit(multiplier=1.0, channel="cryo", scope="burst"),
        _ORDINARY_ENEMY, character_level=90,
    )
    # Cryo onto a Pyro aura is the *reverse* direction: 1.5, not 2.0.
    melted = evaluate_hit(
        log.registry,
        Hit(multiplier=1.0, channel="cryo", scope="burst",
            amplifying=Amplifying.REVERSE_MELT),
        _ORDINARY_ENEMY,
        character_level=90,
    )

    assert melted.non_crit == pytest.approx(plain.non_crit * 1.5, rel=1e-6)
