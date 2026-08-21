"""F.5 — the join: a build's registered contributions become a damage figure.

The chain's arithmetic is tested term by term elsewhere. What is under test here is the
plumbing that decides *which* numbers reach it — above all the scope gate, which is the
mechanism DESIGN §1 A6 rests on: a buff that names an attack must reach that attack and no
other, with no per-character code anywhere in the path.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import tags
from app.formula.genshin.damage import Amplifying, DamageInputError, Hit, ScalingStat
from app.formula.genshin.explain import ContributionLog
from app.pando.calculator import NodeRegistry
from app.services.damage_calculator import Enemy, enemy_from_profile, evaluate_hit

#: An ordinary enemy: 10% in every channel, the value D.6 found on every unarmoured monster.
ORDINARY = Enemy(level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))


def _build(**contributions: float) -> ContributionLog:
    log = ContributionLog(registry=NodeRegistry())
    for quantity, value in contributions.items():
        log.add(quantity, value, tags.SRC_CHARACTER, "test")
    return log


def _damage(log: ContributionLog, hit: Hit, enemy: Enemy = ORDINARY) -> float:
    return evaluate_hit(log.registry, hit, enemy, character_level=90).non_crit


def test_a_hit_reads_the_totals_the_stat_graph_resolved():
    log = _build(base_atk=1000.0, atk_pct=1.0)

    damage = _damage(log, Hit(multiplier=2.0, channel="cryo", scope="burst"))

    # (1000 * 2) * 2.0 multiplier * 0.5 def * 0.9 res
    assert damage == pytest.approx(2000 * 2.0 * 0.5 * 0.9)


def test_a_hit_scaling_off_hp_reads_hp():
    log = _build(base_hp=30000.0, base_atk=1000.0)

    damage = _damage(log, Hit(
        multiplier=1.0, channel="hydro", scope="skill", scaling_stat=ScalingStat.HP,
    ))

    assert damage == pytest.approx(30000 * 0.5 * 0.9)


# ---- The scope gate -------------------------------------------------------

def test_a_scope_gated_buff_reaches_only_the_attack_it_names():
    """The whole point of the tag mechanism, end to end and with no character code."""
    log = _build(base_atk=1000.0)
    log.add(
        tags.Q_DMG_BONUS, 1.0, tags.SRC_CONSTELLATION, "C2: charged attacks",
        tag=tags.scoped_stat_tag(tags.Q_DMG_BONUS, "charged"),
    )

    charged = _damage(log, Hit(multiplier=1.0, channel="cryo", scope="charged"))
    burst = _damage(log, Hit(multiplier=1.0, channel="cryo", scope="burst"))

    assert charged == pytest.approx(burst * 2.0)


def test_the_channels_own_bonus_and_the_generic_one_add_once_each():
    """gcsim `damage.go:47`: `elePer + Stats[DmgP]`. Both apply; neither twice."""
    log = _build(base_atk=1000.0, cryo_dmg_bonus=0.5, dmg_bonus=0.25)

    damage = _damage(log, Hit(multiplier=1.0, channel="cryo", scope="burst"))

    assert damage == pytest.approx(1000 * 1.75 * 0.5 * 0.9)


def test_another_channels_bonus_does_not_apply():
    log = _build(base_atk=1000.0, pyro_dmg_bonus=1.0)

    damage = _damage(log, Hit(multiplier=1.0, channel="cryo", scope="burst"))

    assert damage == pytest.approx(1000 * 0.5 * 0.9)


# ---- Resistance -----------------------------------------------------------

def test_registered_shred_is_subtracted_from_the_enemys_own_resistance():
    """Deepwood's 4pc is a negative contribution to the same pool the enemy writes to."""
    log = _build(base_atk=1000.0)
    log.add(tags.res_q("dendro"), -0.3, tags.SRC_ARTIFACT_SET, "Deepwood 4pc")

    shredded = _damage(log, Hit(multiplier=1.0, channel="dendro", scope="skill"))
    plain = _damage(_build(base_atk=1000.0), Hit(
        multiplier=1.0, channel="dendro", scope="skill",
    ))

    # 10% - 30% = -20% RES, which is `1 - (-0.2)/2` = 1.10, against 0.90 unshredded.
    assert shredded == pytest.approx(plain * (1.1 / 0.9))


def test_an_enemy_with_no_entry_for_a_channel_refuses_rather_than_assuming_zero():
    """Silently treating an unlisted channel as 0% RES overstates every hit by ~10%."""
    partial = Enemy(level=90, resistances={"pyro": 0.1})
    log = _build(base_atk=1000.0)

    with pytest.raises(DamageInputError, match="does not give a cryo resistance"):
        _damage(log, Hit(multiplier=1.0, channel="cryo", scope="burst"), partial)


def test_a_profile_naming_a_channel_that_does_not_exist_is_rejected():
    with pytest.raises(DamageInputError, match="not damage channels"):
        enemy_from_profile(90, {"quantum": 0.1})


def test_enemy_from_profile_accepts_the_eight_stored_columns():
    enemy = enemy_from_profile(
        90, dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1), def_reduction=0.2,
    )

    assert enemy.resistance_for("geo") == pytest.approx(0.1)
    assert enemy.def_reduction == pytest.approx(0.2)


# ---- Crit and reactions through the join ----------------------------------

def test_crit_comes_from_the_builds_own_totals():
    log = _build(base_atk=1000.0, crit_rate=0.5, crit_dmg=1.0)

    result = evaluate_hit(
        log.registry, Hit(multiplier=1.0, channel="cryo", scope="burst"),
        ORDINARY, character_level=90,
    )

    assert result.expected == pytest.approx(result.non_crit * 1.5)


def test_an_amplifying_hit_reads_the_builds_elemental_mastery():
    log = _build(base_atk=1000.0, elemental_mastery=200.0)

    result = evaluate_hit(
        log.registry,
        Hit(multiplier=1.0, channel="pyro", scope="skill", amplifying=Amplifying.MELT),
        ORDINARY,
        character_level=90,
    )
    plain = _damage(_build(base_atk=1000.0), Hit(
        multiplier=1.0, channel="pyro", scope="skill",
    ))

    assert result.non_crit == pytest.approx(
        plain * 2.0 * (1 + (2.78 * 200) / (1400 + 200)),
    )


def test_the_enemys_def_modifiers_reach_the_chain():
    shredded = Enemy(
        level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1), def_reduction=0.5,
    )
    log = _build(base_atk=1000.0)

    assert _damage(log, Hit(multiplier=1.0, channel="cryo", scope="burst"), shredded) > _damage(
        log, Hit(multiplier=1.0, channel="cryo", scope="burst"),
    )
