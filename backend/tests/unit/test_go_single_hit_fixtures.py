"""Math-fallback P0 — single-hit damage for HP, DEF and mixed scalers, against GO's formula.

**Genshin Optimizer is the comparator for formula results** (owner ruling, 2026-11-13), not
gcsim. Each fixture below takes a talent row **verbatim from the seeded catalogue** at talent
level 10 (nanoka 7.0.51 — our numbers, not GO's tables), runs it through this repo's parser
and damage chain, and compares the result with a figure worked out by hand from GO's
formula. GO is MIT-licensed; nothing of its data is copied here, only the shape of its
formula and which stat each talent scales on, each cited to the file and line at GO commit
`2c13fc40c4694fd8beae513493c4c8a7537173c6`.

## GO's formula, as these figures use it

`libs/gi/wr/src/formula.ts:434-452` (`hit.dmg`):

    dmg = (hit.base + hit.dmgInc) * (1 + hit.dmgBonus) * avgHit * enemy.def * resMulti * amp
    avgHit    = 1 + cappedCritRate * critDMG_                          # :442
    enemy.def = (lvl + 100) / ((lvl + 100) + (enemyLvl + 100)(1 - defRed)(1 - defIgn))
                                                                        # :495-503
`hit.base` is `multiplier x stat` for a one-stat talent (`dmgNode`,
`libs/gi/sheets/src/Characters/dataUtil.tsx:165-190`) and **the sum of `multiplier_i x stat_i`**
for a mixed one (`splitScaleDmgNode`, `dataUtil.tsx:193-218`) — one hit whose base has two
terms, which is what the parser now produces and what it used to split into two hits.

Every fixture uses the same build and target, so only the base differs: character level 90
against an enemy at 100 (`enemy.def` = 190 / 390), 10% RES (`resMulti` = 0.9), 46.6% DMG
bonus, 60% crit rate and 120% crit DMG (`avgHit` = 1.72), no reaction, no `dmgInc`.

## What is not here

- **An EM-only hit.** The EM-only rows checked in GO are Lunar reactions there, not direct
  hits — Nefer's Shades are `lunarDmgNode(…, 'eleMas', 'lunarbloom', …)`
  (`Characters/Nefer/index.tsx:256-287`) — so GO's formula for them is a different one, and
  Lunar damage is P3's (`DESIGN` §3). The parser still classifies them as EM;
  `test_talent_scaling_stat.py` covers that.
- **Kit buffs.** GO's sheets also add talent and constellation buffs (Nahida's A4, Furina's
  fanfare). None applies at these inputs, and P0 is the stat a talent scales on, not its kit.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import tags
from app.formula.genshin.damage import Hit, ScalingStat
from app.formula.genshin.explain import ContributionLog
from app.pando.calculator import NodeRegistry
from app.services.damage_calculator import Enemy, evaluate_hit
from app.services.talent_scaling import parse_talent_row

#: GO's `enemy.def` at character 90 vs enemy 100, `formula.ts:495-503`.
GO_DEF = 190 / 390
#: GO's `res()` at 10% RES — `1 - res` below 75%.
GO_RES = 0.9
#: `avgHit`, `formula.ts:442`: 1 + 0.6 x 1.2.
GO_AVG_HIT = 1.72
DMG_BONUS = 0.466

TARGET = Enemy(level=100, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))


def _expected(go_base: float) -> float:
    """GO's `hit.dmg` for this build and target, from its base."""
    return go_base * (1 + DMG_BONUS) * GO_AVG_HIT * GO_DEF * GO_RES


def _damage(row: str, params: list[float], channel: str, scope: str, **stats: float) -> float:
    """Our chain: parse the verbatim row, then score its one hit on these stats."""
    [talent] = parse_talent_row([row], params)
    log = ContributionLog(registry=NodeRegistry())
    for quantity, value in {
        **stats, "crit_rate": 0.6, "crit_dmg": 1.2, tags.dmg_bonus_q(channel): DMG_BONUS,
    }.items():
        log.add(quantity, value, tags.SRC_CHARACTER, "fixture")
    hit = Hit(
        multiplier=talent.multiplier, channel=channel, scope=scope,
        scaling_stat=talent.scaling_stat, extra_terms=talent.extra_terms,
    )
    return evaluate_hit(log.registry, hit, TARGET, character_level=90).expected


def test_neuvillette_burst_scales_off_max_hp() -> None:
    """GO: `skillDmg: dmgNode('hp', dm.burst.skillDmg, 'burst')` —
    `Characters/Neuvillette/index.tsx:160`.

    Our row, burst level 10: `Skill DMG|{param1:F2P} Max HP`, param1 = 0.400641.
    GO base = 0.400641 x 40,000 HP = 16,025.64 -> 17,717.78.
    """
    damage = _damage(
        "Skill DMG|{param1:F2P} Max HP", [0.400641], "hydro", "burst", base_hp=40000.0,
    )

    assert damage == pytest.approx(_expected(0.400641 * 40000))
    assert damage == pytest.approx(17717.78, abs=0.01)


def test_furina_ousia_bubble_scales_off_max_hp() -> None:
    """GO: `bubbleDmg: dmgNode('hp', dm.skill.bubbleDmg, 'skill')` —
    `Characters/Furina/index.tsx:287`.

    Our row, skill level 10: `Ousia Bubble DMG|{param1:F1P} Max HP`, param1 = 0.141552.
    GO base = 0.141552 x 40,000 = 5,662.08 -> 6,259.94.
    """
    damage = _damage(
        "Ousia Bubble DMG|{param1:F1P} Max HP", [0.141552], "hydro", "skill",
        base_hp=40000.0,
    )

    assert damage == pytest.approx(6259.94, abs=0.01)


def test_noelle_skill_scales_off_def() -> None:
    """GO: `dmg: dmgNode('def', dm.skill.skillDmg, 'skill')` — `Characters/Noelle/index.tsx:162`.

    Our row, skill level 10: `Skill DMG|{param6:P} DEF`, param6 = 2.16.
    GO base = 2.16 x 2,500 DEF = 5,400 -> 5,970.18.
    """
    damage = _damage(
        "Skill DMG|{param6:P} DEF", [2.88, 0.38304, 0.59, 12, 24, 2.16], "geo", "skill",
        base_def=2500.0, base_atk=900.0,
    )

    assert damage == pytest.approx(5970.18, abs=0.01)


def test_nahida_tri_karma_is_one_hit_of_atk_plus_em() -> None:
    """GO: `karmaDmg: splitScaleDmgNode(['atk', 'eleMas'], [karmaAtkDmg, karmaEleMasDmg],
    'skill', …)` — `Characters/Nahida/index.tsx:313-318`. One hit, base the sum of both.

    Our row, skill level 10: `Tri-Karma Purification DMG|{param3:F1P} ATK+{param4:F1P}
    Elemental Mastery`, param3 = 1.8576, param4 = 3.7152.
    GO base = 1.8576 x 1,500 ATK + 3.7152 x 900 EM = 2,786.4 + 3,343.68 = 6,130.08 -> 6,777.35.

    **The parse this replaced** made it two hits, each scored off the caller's one stat:
    with ATK, 1.8576 x 1,500 + 3.7152 x 1,500 = 8,359.2 of base, 36% over.
    """
    damage = _damage(
        "Tri-Karma Purification DMG|{param3:F1P} ATK+{param4:F1P} Elemental Mastery",
        [1.7712, 2.3472, 1.8576, 3.7152], "dendro", "skill",
        base_atk=1500.0, elemental_mastery=900.0,
    )

    assert damage == pytest.approx(_expected(1.8576 * 1500 + 3.7152 * 900))
    assert damage == pytest.approx(6777.35, abs=0.01)


def test_chiori_tamoto_is_one_hit_of_atk_plus_def() -> None:
    """GO: `turretDmg` is `splitScaleDmgNode(['atk', 'def'], [turretDmg_atk, turretDmg_def],
    'skill', …)` — `Characters/Chiori/index.tsx:129-133`.

    Our row, skill level 10: `Tamoto DMG|{param1:P} ATK+{param2:P} DEF`, param1 = 1.47744,
    param2 = 1.8468. GO base = 1.47744 x 1,800 + 1.8468 x 2,500 = 7,276.39 -> 8,044.70.
    """
    damage = _damage(
        "Tamoto DMG|{param1:P} ATK+{param2:P} DEF", [1.47744, 1.8468], "geo", "skill",
        base_atk=1800.0, base_def=2500.0,
    )

    assert damage == pytest.approx(8044.70, abs=0.01)


def test_the_fixtures_would_catch_the_old_atk_reading() -> None:
    """Guards the guard: the same Neuvillette row scored off ATK, as the page used to ask,
    lands nowhere near GO's figure — so the fixtures above are not passing by accident."""
    [talent] = parse_talent_row(["Skill DMG|{param1:F2P} Max HP"], [0.400641])
    log = ContributionLog(registry=NodeRegistry())
    for quantity, value in {
        "base_hp": 40000.0, "base_atk": 900.0, "crit_rate": 0.6, "crit_dmg": 1.2,
        "hydro_dmg_bonus": DMG_BONUS,
    }.items():
        log.add(quantity, value, tags.SRC_CHARACTER, "fixture")
    as_atk = evaluate_hit(log.registry, Hit(
        multiplier=talent.multiplier, channel="hydro", scope="burst",
        scaling_stat=ScalingStat.ATK,
    ), TARGET, character_level=90).expected

    assert as_atk != pytest.approx(17717.78, rel=0.01)
