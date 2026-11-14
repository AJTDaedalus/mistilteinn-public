"""Math-fallback P2, task 11 (fourth batch): GO fixtures for Nahida and the next buffers.

Kept beside `test_go_formula_fixtures.py` rather than inside it, and imported by its `build()`,
so the batch reads as one block. The method is that file's, unchanged: each figure is worked by
hand from Genshin Optimizer's formula at `2c13fc40` with **our** numbers — talent rows verbatim
from the seeded catalogue (nanoka 7.2.51), constellation and passive lists the sheets' pins,
stated builds — and a teammate giver's stats are written out as their pass-1 numbers.

Nothing here is a test by itself (the module name does not start with `test_`); its fixtures are
checked by `test_go_formula_fixtures.py` and by `npm run formula:verify`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from app.formula.genshin import sheets
from app.schemas.formula import FormulaBonusRead
from tests.unit import test_go_formula_fixtures as base

FORMULA = "libs/gi/wr/src/formula.ts:357,434-453,490-514"
FORMULA_AMP = "libs/gi/wr/src/formula.ts:257,357,434-484,490-514"
PANDO = "libs/gi/formula/src/data/char/"


def _go_def(def_reduction: float = 0.0, def_ignore: float = 0.0) -> float:
    """GO `enemy.def` at level 90 against 100 (`formula.ts:490-510`), DEF reduction capped at
    90%: `190 / (190 + 200 × (1 − defRed) × (1 − defIgn))`. With neither it is `GO_DEF`."""
    reduction = min(def_reduction, 0.9)
    return 190 / (190 + 200 * (1 - reduction) * (1 - def_ignore))


def _go_hit(*, base_damage: float, flat: float = 0.0, dmg_bonus: float, crit_rate: float,
            crit_dmg: float, res: float = 0.1, def_reduction: float = 0.0,
            def_ignore: float = 0.0, amp: float = 1.0) -> float:
    """GO `hit.dmg` (`formula.ts:434-453`) with every term written out."""
    avg_hit = 1 + max(min(crit_rate, 1.0), 0.0) * crit_dmg
    return ((base_damage + flat) * (1 + dmg_bonus) * avg_hit
            * _go_def(def_reduction, def_ignore) * base._res_multiplier(res) * amp)


def _amp(em: float, coefficient: float, *, multiplier: float = 1.5,
         reaction_bonus: float = 0.0) -> float:
    """GO's amplifying term (`formula.ts:257,454-484`)."""
    return multiplier * (1 + coefficient * em / (1400 + em) + reaction_bonus)


def _kit(nanoka_id: str, giver: sheets.Giver, *, subject: bool,
         receiver_element: str | None = None, team_elements: list[str] | None = None,
         team_max: dict[str, float] | None = None) -> dict[str, Any]:
    sheet = sheets.sheet_for(nanoka_id)
    assert sheet is not None
    kit = sheets.resolve(sheet, giver, giver_is_subject=subject,
                         receiver_element=receiver_element, team_elements=team_elements,
                         team_max=team_max)
    return {"id": kit.source_id, "label": kit.label, "citation": kit.citation,
            "bonus": FormulaBonusRead.of(kit.bonus).model_dump()}


def _with_hit(row: dict[str, Any], talent: str, label: str) -> dict[str, Any]:
    """A fixture row that names its talent row, for a row-scoped kit buff."""
    return {**row, "hit": {"talent": talent, "label": label}}


# ── Nahida ──────────────────────────────────────────────────────────────────────────────────

NAHIDA_BURST_LABELS = ["Pyro: DMG Bonus|1 Character {param1:F1P}",
                       "Pyro: DMG Bonus|2 Characters {param2:F1P}"]
#: Seeded burst row at level 10: the one-Pyro and two-Pyro Tri-Karma DMG Bonus.
NAHIDA_BURST_10 = [0.26784, 0.40176]
#: Seeded skill row at level 13 (stored 10, +3 from C3): Tri-Karma ATK and EM parts.
TRI_KARMA_13 = ("Tri-Karma Purification DMG|{param3:F1P} ATK+{param4:F1P} Elemental Mastery",
                [2.091, 2.771, 2.193, 4.386])
#: A stated Nahida at 90: base ATK character + weapon; her ascension EM 115.2 is base.
NAHIDA_BASE = base._base_stats(base_atk=841.0, base_hp=10360.0, base_def=630.0,
                               elemental_mastery=115.2)
NAHIDA_ARTIFACTS = {"elemental_mastery": 187.0, "atk_pct": 0.466, "flat_atk": 311.0,
                    "dendro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}
#: Nahida as a teammate: her pass-1 EM, stated, is the party's highest.
NAHIDA_TEAM_MAX = {"elemental_mastery": 880.0}


def _nahida_giver(constellation: int, *, ascension: int = 6) -> sheets.Giver:
    cons, pas = base._pinned("10000073")
    giver = base._ungated_giver(
        "Nahida", "10000073", constellation=constellation,
        talent_levels={"elemental_burst": 10},
        talent_rows={("elemental_burst", 10): sheets.TalentRow(NAHIDA_BURST_LABELS,
                                                               NAHIDA_BURST_10)},
        cons=cons, passives=pas, stats=NAHIDA_BASE)
    return dataclasses.replace(giver, ascension_phase=ascension)


def _nahida_on_xiangling(coefficient: float) -> float:
    """**Nahida C2 as Xiangling's teammate**, both conditions on: her A1 gives the active
    character 25% of the party's highest EM (her own 880 → 220, under the 250 cap), and her C2
    reduces the marked opponent's DEF by 30%. Xiangling's Pyronado, reverse-vaporized.

    GO: `teamBuff.final.eleMas.add(min(prod(percent(0.25), team.premod.eleMas.max), 250))`
    (`pando Nahida.ts:168-182,212`; WR `total.eleMas`, `index.tsx:166-195,362`);
    `enemyDebuff.common.defRed_` 0.3 (`:230-233`; WR `enemyDefRed_`, `:278-283,359`), read by
    `enemy.def` (`formula.ts:490-510`)."""
    totals = base._xiangling_totals(fervent=False, witch_stacks=0)
    em = totals["em"] + min(0.25 * NAHIDA_TEAM_MAX["elemental_mastery"], 250.0)
    return _go_hit(
        base_damage=base._multiplier(base.PYRONADO) * totals["atk"],
        dmg_bonus=base.XIANGLING_ARTIFACTS["pyro_dmg_bonus"], crit_rate=totals["cr"],
        crit_dmg=totals["cd"], def_reduction=0.3, amp=_amp(em, coefficient))


def _nahida_on_herself(_: float) -> float:
    """**Nahida C4 on her own Tri-Karma Purification**, in a team with one Pyro member: the
    Shrine on (her own doing), so the burst's Pyro bonus — read from the **two**-Pyro row,
    because her C1 counts one more — reaches Tri-Karma and not her press; C4 at two opponents,
    +120 EM. Ascension 3, so her A4 (not modelled: the owner's open question, DECISIONS §39) is
    locked in GO's figure too and the comparison is of what the sheet models. Skill at 13 (C3).

    GO: `splitScaleDmg('karma_dmg', ['atk', 'eleMas'], …, ownBuff.premod.dmg_.add(sum(a4,
    burst_karma_dmg_)))` (`pando Nahida.ts:246-255`; WR `triKarmaAddl`, `index.tsx:226-231,
    313-318`); `burst_karma_dmg_` = `cmpEq(pyroLevel, 1, dmg_1, dmg_2)` with `pyroLevel =
    count.pyro + cmpGE(constellation, 1, 1)` (`:120-134`); C4 `subscript(c4Count, [0,
    ...constellation4])` into `premod.eleMas` (`:204-210`)."""
    stats = base._stats(NAHIDA_BASE, NAHIDA_ARTIFACTS)
    atk = base._total(stats, "atk")
    em = stats["elemental_mastery"] + 120.0
    params = TRI_KARMA_13[1]
    return _go_hit(base_damage=params[2] * atk + params[3] * em,
                   dmg_bonus=stats["dendro_dmg_bonus"] + NAHIDA_BURST_10[1],
                   crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


def _fixture(name: str, covers: str, go: list[str], giver: dict[str, Any], team: dict[str, Any],
             base_stats: dict[str, float], artifacts: dict[str, float], channel: str,
             row: dict[str, Any], source: dict[str, Any], conditionals: dict[str, Any],
             figure: Any, divergence: str = "none: no reaction") -> dict[str, Any]:
    return base._buffer(name, covers, go, giver, team, base_stats, artifacts, channel, row,
                        source, conditionals, figure, divergence)


def batch4_fixtures() -> list[dict[str, Any]]:
    """Task 11, fourth batch: one or two fixtures per sheet."""
    xiangling = {"element": "pyro", "weapon_type": "WEAPON_POLE"}
    out: list[dict[str, Any]] = []

    team = ["pyro", "dendro", "hydro", "anemo"]
    out.append(_fixture(
        "nahida_a1_c2_on_xiangling",
        "a value from the party's highest EM, capped (A1); enemy DEF reduction into the chain's "
        "DEF term (C2); into an amplifying reaction",
        [FORMULA_AMP, f"{PANDO}Nahida.ts:79-94,168-182,212,230-233"],
        {"name": "Nahida", "constellation": 2, "ascension_phase": 6, "stats": NAHIDA_TEAM_MAX},
        {**xiangling, "member_elements": team},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro",
        base._row("nado_vape", "Pyronado DMG (vaporize)", "burst", 1, base.PYRONADO,
                  "reverse_vaporize"),
        _kit("10000073", _nahida_giver(2), subject=False, receiver_element="pyro",
             team_elements=team, team_max=NAHIDA_TEAM_MAX),
        {"kit:nahida/a1_field": 1, "kit:nahida/c2_quicken": 1},
        _nahida_on_xiangling,
        "amplifying EM coefficient: 2.78 (gcsim, ours) against GO's 25/9"))

    team = ["dendro", "pyro", "hydro", "anemo"]
    out.append(_fixture(
        "nahida_burst_c4_on_her_own_tri_karma",
        "a talent row chosen by the team's Pyro count with a constellation counting one more, "
        "scoped to one of her own rows; a self EM buff read from a stack table",
        [FORMULA, f"{PANDO}Nahida.ts:59-70,95-97,120-134,204-210,246-255"],
        {"name": "Nahida", "constellation": 4, "ascension_phase": 3,
         "talent_levels": {"elemental_burst": 10, "elemental_skill": 10},
         "stats": "the optimized character"},
        {"element": "dendro", "weapon_type": "WEAPON_CATALYST", "member_elements": team},
        NAHIDA_BASE, NAHIDA_ARTIFACTS, "dendro",
        _with_hit(base._row("karma", "Tri-Karma Purification DMG", "skill", 1, TRI_KARMA_13,
                            None), "elemental_skill", "Tri-Karma Purification DMG"),
        _kit("10000073", _nahida_giver(4, ascension=3), subject=True,
             receiver_element="dendro", team_elements=team),
        {"kit:nahida/c4_count": 2},
        _nahida_on_herself))
    out.extend(_buffers())
    return out


# ── The next buffers ────────────────────────────────────────────────────────────────────────


def _giver(name: str, nanoka_id: str, *, constellation: int,
           rows: dict[tuple[str, int], tuple[list[str], list[float]]] | None = None,
           stats: dict[str, float] | None = None) -> sheets.Giver:
    """A giver at A6 with the sheet's pinned lists, the stated talent rows and stats. The
    levels are the rows' (each is the giver's effective level less its boosts)."""
    cons, pas = base._pinned(nanoka_id)
    sheet = sheets.sheet_for(nanoka_id)
    assert sheet is not None
    levels: dict[str, int] = {}
    for (talent, level) in rows or {}:
        boosts = sum(3 for b in sheet.talent_boosts
                     if b.talent == talent and constellation >= b.constellation)
        levels[talent] = level - boosts
    return base._ungated_giver(
        name, nanoka_id, constellation=constellation, talent_levels=levels,
        talent_rows={k: sheets.TalentRow(*v) for k, v in (rows or {}).items()},
        cons=cons, passives=pas, stats=stats)


def _multi(name: str, covers: str, go: list[str], giver: dict[str, Any], team: dict[str, Any],
           base_stats: dict[str, float], artifacts: dict[str, float], channel: str,
           rows: list[dict[str, Any]], source: dict[str, Any], conditionals: dict[str, Any],
           figure: Any) -> dict[str, Any]:
    """A fixture with several rows (the recipe's weighted total, GO's `sum(...targetNodes)`)."""
    out = base._buffer(name, covers, go, giver, team, base_stats, artifacts, channel, rows[0],
                       source, conditionals, figure)
    return {**out, "rows": rows}


# Kujou Sara, C6, on her own Titanbreaker: burst 13 (C3) and skill 13 (C5), seeded rows.
SARA_BURST_13 = ("Tengu Juurai: Titanbreaker DMG|{param1:F1P}", [8.704, 0.72505, 20.0, 80.0])
SARA_SKILL_13 = (["Tengu Juurai: Ambush DMG|{param1:F1P}", "ATK Bonus Ratio|{param2:P}",
                  "ATK Bonus Duration|{param3:F1}s", "CD|{param4:F1}s"],
                 [2.6724, 0.9129, 6.0, 10.0])
SARA_BASE = base._base_stats(base_atk=760.0, base_hp=9570.0, base_def=628.0)
SARA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "electro_dmg_bonus": 0.466,
                  "crit_rate": 0.3, "crit_dmg": 0.6}


def _sara(_: float) -> float:
    """GO: `teamBuff.premod.atk.add(cmpNE(destIsActive, 0, prod(ambushOn, own.base.atk,
    skill ratio)))` (`pando KujouSara.ts:81-85,100`; WR `total.atk`, `index.tsx:79-94,159`);
    C6 `critDMG_.electro` under ambush and the C6 toggle (`:87-91,101`)."""
    stats = base._stats(SARA_BASE, SARA_ARTIFACTS)
    atk = base._total(stats, "atk") + SARA_SKILL_13[1][1] * stats["base_atk"]
    return _go_hit(base_damage=SARA_BURST_13[1][0] * atk, dmg_bonus=stats["electro_dmg_bonus"],
                   crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"] + 0.6)


# Shenhe, C2, as Ayaka's teammate: her pass-1 ATK stated; skill and burst 10, seeded rows.
SHENHE_SKILL_10 = (["Skill DMG|{param1:P}", "Hold Skill DMG|{param2:F1P}",
                    "DMG Bonus|{param3:F1P} ATK"], [2.5056, 3.3984, 0.821808])
SHENHE_BURST_10 = (["Skill DMG|{param1:P}", "RES Decrease|{param2:F1P}", "DoT|{param3:F1P}"],
                   [1.8144, 0.15, 0.59616])
SHENHE_GIVER_STATS = {"base_atk": 950.0, "atk_pct": 2.1, "flat_atk": 555.0}


def _shenhe_on_ayaka(_: float) -> float:
    """GO: Icy Quill `teamBuff.formula.base.cryo` = Shenhe's ATK × the skill row (`pando
    Shenhe.ts:103-108,147`; WR `cryo_dmgInc`, `index.tsx:93-101,192`); burst Cryo RES (`:109-117,
    148`); A1 Cryo DMG to the active (`:118-121,150`); A4 press Skill/Burst DMG (`:122-126,151`);
    C2 Cryo CRIT DMG 15% (`:132-135,156`, WR `:143-148,201`)."""
    atk = (base.AYAKA_BASE["base_atk"] * (1 + base.AYAKA_ARTIFACTS["atk_pct"])
           + base.AYAKA_ARTIFACTS["flat_atk"])
    return _go_hit(
        base_damage=base._multiplier(base.HYOUKA) * atk,
        flat=SHENHE_SKILL_10[1][2] * base._total(SHENHE_GIVER_STATS, "atk"),
        dmg_bonus=base.AYAKA_ARTIFACTS["cryo_dmg_bonus"] + 0.15 + 0.15,
        crit_rate=base.AYAKA_BASE["crit_rate"] + base.AYAKA_ARTIFACTS["crit_rate"],
        crit_dmg=base.AYAKA_BASE["crit_dmg"] + base.AYAKA_ARTIFACTS["crit_dmg"] + 0.15,
        res=0.1 - SHENHE_BURST_10[1][1])


# Yun Jin, C2, as Xiangling's teammate on her 1-Hit (Physical): pass-1 DEF stated.
XIANGLING_NA_1 = ("1-Hit DMG|{param1:F1P}", [0.8313])
YUN_JIN_BURST_10 = (["Skill DMG|{param1:P}", "DMG Increase|{param2:P} DEF"], [4.392, 0.57888])
YUN_JIN_GIVER_STATS = {"base_def": 734.0, "def_pct": 1.8, "flat_def": 344.8}


def _yun_jin_on_xiangling(_: float) -> float:
    """GO: `teamBuff.formula.base.normal` = Yun Jin's DEF × (burst row + A4 by the distinct
    elements, `subscript(eleCount, [0, ...passive2])`) (`pando YunJin.ts:88-100,119`; WR
    `normal_dmgInc`, `index.tsx:86-109,163`); C2 Normal DMG 15% (`:101-103,120`). Four
    distinct elements: A4's fourth entry."""
    yun = sheets.sheet_for("10000064")
    assert yun is not None
    stats = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)
    flat = base._total(YUN_JIN_GIVER_STATS, "def") * (
        YUN_JIN_BURST_10[1][1] + yun.pins.passives[4][3])
    return _go_hit(base_damage=XIANGLING_NA_1[1][0] * base._total(stats, "atk"), flat=flat,
                   dmg_bonus=0.15, crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


# Gorou, C6, on his own burst in a three-Geo team: skill and burst 13 (C3, C5), seeded rows.
GOROU_SKILL_13 = (["Skill DMG|{param1:F1P}", "DEF Increase|{param2:I}",
                   "Geo DMG Bonus|{param3:P}"], [2.278, 438.09, 0.15])
GOROU_BURST_13 = ("Skill DMG|{param1:P} DEF", [2.08709, 1.302625, 9.0, 20.0, 80.0])
GOROU_BASE = base._base_stats(base_atk=650.0, base_hp=9570.0, base_def=648.0)
GOROU_ARTIFACTS = {"def_pct": 1.166, "flat_def": 58.0, "geo_dmg_bonus": 0.466,
                   "crit_rate": 0.35, "crit_dmg": 0.7}


def _gorou(_: float) -> float:
    """GO: banner flat DEF to the active at one Geo member and Geo DMG at three (`pando
    Gorou.ts:93-102,136-137`; WR `index.tsx:89-105,172-173`); A1 DEF% (`:104-107,138`); A4
    burst `formula.base` 15.6% of his DEF (`:114-118,141`; WR `total.def`, `:119-123,182`); C6
    Geo CRIT DMG at the third Geo entry (`:120-127,139`)."""
    gorou = sheets.sheet_for("10000055")
    assert gorou is not None
    stats = base._stats(GOROU_BASE, GOROU_ARTIFACTS)
    defense = (base._total(stats, "def", extra_pct=gorou.pins.passives[1][0])
               + GOROU_SKILL_13[1][1])
    return _go_hit(
        base_damage=GOROU_BURST_13[1][0] * defense, flat=gorou.pins.passives[4][1] * defense,
        dmg_bonus=stats["geo_dmg_bonus"] + GOROU_SKILL_13[1][2], crit_rate=stats["crit_rate"],
        crit_dmg=stats["crit_dmg"] + gorou.pins.constellations[6][2])


# Xilonen, C4, as Xiangling's teammate: Pyronado and a 1-Hit, pass-1 DEF stated.
XILONEN_SKILL_10 = (["Rush DMG|{param1:F1P} DEF", "Elemental RES Decrease|{param2:F1P}"],
                    [3.2256, 0.36])
XILONEN_GIVER_STATS = {"base_def": 849.0, "def_pct": 2.3, "flat_def": 198.3}
XILONEN_BASE = base._base_stats(base_atk=600.0, base_hp=12405.0, base_def=849.0)
XILONEN_ARTIFACTS = {"def_pct": 1.166, "flat_def": 58.0, "geo_dmg_bonus": 0.466,
                     "crit_rate": 0.3, "crit_dmg": 0.6}


def _xilonen_on_xiangling(_: float) -> float:
    """GO: the Pyro Source Sample's RES decrease (`pando Xilonen.ts:115,205-209`; WR
    `index.tsx:117,129-132,290`); C2 ATK% to a Pyro receiver (`:143-152,212`; WR `:162-176,291`);
    C4 Normal/Charged/Plunging `formula.base` 65% of her DEF (`:175-181,215-217`). Pyronado
    takes the shred and the ATK; the 1-Hit (Physical) the ATK and the flat damage."""
    xil = sheets.sheet_for("10000103")
    assert xil is not None
    stats = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=xil.pins.constellations[2][0])
    nado = _go_hit(base_damage=base._multiplier(base.PYRONADO) * atk,
                   dmg_bonus=stats["pyro_dmg_bonus"], crit_rate=stats["crit_rate"],
                   crit_dmg=stats["crit_dmg"], res=0.1 - XILONEN_SKILL_10[1][1])
    hit = _go_hit(base_damage=XIANGLING_NA_1[1][0] * atk,
                  flat=xil.pins.constellations[4][0] * base._total(XILONEN_GIVER_STATS, "def"),
                  dmg_bonus=0.0, crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])
    return nado + hit


def _xilonen_on_herself(_: float) -> float:
    """GO: Rush DMG `dmg('skill', info, 'def', …)` (`pando Xilonen.ts:228`); the Geo sample's RES
    decrease while the Source Samples are on and fewer than three samplers are converted
    (`:110-122,204`; WR `:112-128,289`); C2 DMG Bonus to a Geo receiver (`:131-142,211`)."""
    xil = sheets.sheet_for("10000103")
    assert xil is not None
    stats = base._stats(XILONEN_BASE, XILONEN_ARTIFACTS)
    return _go_hit(base_damage=XILONEN_SKILL_10[1][0] * base._total(stats, "def"),
                   dmg_bonus=stats["geo_dmg_bonus"] + xil.pins.constellations[2][3],
                   crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"],
                   res=0.1 - XILONEN_SKILL_10[1][1])


# Xianyun: C2 as Xiangling's teammate on a high plunge; C6 on her own third Driftcloud Wave.
XIANGLING_HIGH_PLUNGE = ("Low/High Plunge DMG|{param10:P}",
                         [0.8313, 0.833, 0.5151, 0.2788, 1.4042, 2.4055, 25.0, 1.26378,
                          2.527025, 3.15639])
XIANYUN_GIVER_STATS = {"base_atk": 943.0, "atk_pct": 1.9, "flat_atk": 465.3}
XIANYUN_SKILL_13 = (["Skill DMG|{param1:F2P}",
                     "Driftcloud Wave DMG|{param2:F1P}/{param3:F1P}/{param4:F1P}"],
                    [0.527, 2.465, 3.145, 7.174, 12.0])
XIANYUN_WAVE_3 = ("Driftcloud Wave DMG|{param4:F1P}", XIANYUN_SKILL_13[1])
XIANYUN_BASE = base._base_stats(base_atk=943.0, base_hp=10409.0, base_def=573.0)
XIANYUN_ARTIFACTS = {"atk_pct": 0.932, "flat_atk": 311.0, "anemo_dmg_bonus": 0.466,
                     "crit_rate": 0.3, "crit_dmg": 0.9}


def _xianyun_on_xiangling(_: float) -> float:
    """GO: A1 `plunging_critRate_` at four stacks, the list's fourth entry (`pando
    Xianyun.ts:113-121,171`; WR `index.tsx:111-122,251`); A4 `plunging_impact_dmgInc` =
    `(1 + C2) × 200% × min(total.atk, 4500)` (`:122-134`; WR `:123-145,250`)."""
    xy = sheets.sheet_for("10000093")
    assert xy is not None
    stats = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)
    ratio = (1 + xy.pins.constellations[2][2]) * xy.pins.passives[4][0]
    flat = ratio * min(base._total(XIANYUN_GIVER_STATS, "atk"), xy.pins.passives[4][1])
    return _go_hit(base_damage=XIANGLING_HIGH_PLUNGE[1][9] * base._total(stats, "atk"),
                   flat=flat, dmg_bonus=0.0,
                   crit_rate=stats["crit_rate"] + xy.pins.passives[1][3],
                   crit_dmg=stats["crit_dmg"])


def _xianyun_on_herself(_: float) -> float:
    """GO: `leapDmg` — the wave row × total ATK as `plunging_impact`, with C6's
    `plunging_critDMG_` at three Skyladder uses (`WR index.tsx:154-183`; pando `:138-158`); A1's
    `plunging_critRate_` at four stacks (`:113-121,171`); C2 ATK% after her skill
    (`:135-137,169`). A4 off (GO's default; the sheet withholds it on her, a capped own-ATK
    conversion). Skill at 13 (C5)."""
    xy = sheets.sheet_for("10000093")
    assert xy is not None
    stats = base._stats(XIANYUN_BASE, XIANYUN_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=xy.pins.constellations[2][0])
    return _go_hit(base_damage=XIANYUN_SKILL_13[1][3] * atk,
                   dmg_bonus=stats["anemo_dmg_bonus"],
                   crit_rate=stats["crit_rate"] + xy.pins.passives[1][3],
                   crit_dmg=stats["crit_dmg"] + xy.pins.constellations[6][2])


# Mona, C4 (burst 13 from C3), as Xiangling's teammate on a reverse-vaporized Pyronado.
MONA_BURST_13 = (["Illusory Bubble Duration|{param1:F1}s",
                  "Illusory Bubble Explosion DMG|{param2:P}", "DMG Bonus|{param10:P}"],
                 [8.0, 9.401, -0.6, 5.0, 15.0, 60.0, 0.0, 0.0, 0.0, 0.6])


def _mona_on_xiangling(coefficient: float) -> float:
    """GO: Omen `teamBuff.premod.dmg_` = the burst row (`pando Mona.ts:130,232`; WR `all_dmg_`,
    `index.tsx:129-134,388`); C1 `vaporize_dmg_` (`:140-142,251-258`); C4 `critRate_` = |C4[0]|
    (`:103,146-148,233`; WR `:117,163-167,401`)."""
    mona = sheets.sheet_for("10000041")
    assert mona is not None
    stats = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)
    return _go_hit(
        base_damage=base._multiplier(base.PYRONADO) * base._total(stats, "atk"),
        dmg_bonus=stats["pyro_dmg_bonus"] + MONA_BURST_13[1][9],
        crit_rate=stats["crit_rate"] + abs(mona.pins.constellations[4][0]),
        crit_dmg=stats["crit_dmg"],
        amp=_amp(stats["elemental_mastery"], coefficient,
                 reaction_bonus=mona.pins.constellations[1][1]))


# Raiden Shogun: C2 on her own Musou no Hitotachi; C4 as Xiangling's teammate. Seeded rows at 10.
RAIDEN_SKILL_10 = (["Skill DMG|{param1:F1P}", "Coordinated ATK DMG|{param2:F1P}",
                    "Duration|{param3:F1}s", "Elemental Burst DMG Bonus|{param4:F2P} Per Energy"],
                   [2.1096, 0.756, 25.0, 0.003])
RAIDEN_BURST_10_LABELS = [
    "Musou no Hitotachi Base DMG|{param1:P}",
    "Resolve Bonus|{param2:F2P} Initial/{param3:F2P} ATK DMG Per Stack",
    "Resolve Stacks Gained|{param4:F2} Per Energy Consumed", "Energy Cost|{param20:I}"]
RAIDEN_BURST_10_PARAMS = [7.2144, 0.069984, 0.013071, 0.2, 0.798157, 0.784215, 0.960228,
                          0.55107, 0.55264, 1.319224, 1.099, 1.32665, 20.0, 1.26378, 2.527025,
                          3.15639, 2.5, 7.0, 18.0, 90.0]
RAIDEN_INITIAL = ("Musou no Hitotachi Base DMG|{param1:P}", RAIDEN_BURST_10_PARAMS)
RAIDEN_BASE = base._base_stats(base_atk=945.0, base_hp=12907.0, base_def=789.0)
RAIDEN_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "electro_dmg_bonus": 0.466,
                    "crit_rate": 0.3, "crit_dmg": 0.8}


def _raiden_on_herself(_: float) -> float:
    """GO: `musou('burst', dm.burst.dmg, true)` = `(row + resolveBonus1 × stacks) × final.atk`
    as burst DMG (`pando RaidenShogun.ts:131-134,167-182,209`; WR `burstResolve`,
    `index.tsx:160-192,235`); the Eye on herself `prod(skillEyeOn, enerCost, ratio)` into
    `burst_dmg_` (`:103-113,190`; WR `:101-112,272`); C2 `enemyDefIgn_` 60% (`:159-161,195`; WR
    `:113-118,274`). Sixty Resolve stacks. Ascension 3, so her A4 (not modelled: a second
    Energy Recharge conversion) is locked in GO's figure too."""
    rd = sheets.sheet_for("10000052")
    assert rd is not None
    stats = base._stats(RAIDEN_BASE, RAIDEN_ARTIFACTS)
    mv = RAIDEN_BURST_10_PARAMS[0] + 60 * RAIDEN_BURST_10_PARAMS[1]
    return _go_hit(base_damage=mv * base._total(stats, "atk"),
                   dmg_bonus=stats["electro_dmg_bonus"] + RAIDEN_SKILL_10[1][3] * 90.0,
                   crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"],
                   def_ignore=rd.pins.constellations[2][0])


def _raiden_on_xiangling(_: float) -> float:
    """GO: the Eye to a teammate, `prod(energy, ratio)` into `burst_dmg_` for the 80-Energy
    Pyronado (`pando RaidenShogun.ts:105-108,114-122,193`; WR `index.tsx:125-147,279`); C4 ATK%
    to the others (`:162-165,197`; WR `:210-219,278`)."""
    rd = sheets.sheet_for("10000052")
    assert rd is not None
    stats = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=rd.pins.constellations[4][0])
    return _go_hit(base_damage=base._multiplier(base.PYRONADO) * atk,
                   dmg_bonus=stats["pyro_dmg_bonus"] + RAIDEN_SKILL_10[1][3] * 80.0,
                   crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


def _raiden_fixtures() -> list[dict[str, Any]]:
    team = ["electro", "pyro", "hydro", "anemo"]
    rows = {("elemental_skill", 10): RAIDEN_SKILL_10,
            ("elemental_burst", 10): (RAIDEN_BURST_10_LABELS, RAIDEN_BURST_10_PARAMS)}
    own = _giver("Raiden Shogun", "10000052", constellation=2, rows=rows, stats=RAIDEN_BASE)
    own = dataclasses.replace(own, ascension_phase=3)
    return [
        _fixture(
            "raiden_shogun_eye_resolve_c2_on_her_own_burst",
            "a self DMG buff from one talent row times another, Resolve as flat damage from her "
            "own ATK per stack on one row (a row's second parameter), and DEF ignore",
            [FORMULA, f"{PANDO}RaidenShogun.ts:50,55-56,73,81,98-113,123-138,159-182,190-195"],
            {"name": "Raiden Shogun", "constellation": 2, "ascension_phase": 3,
             "talent_levels": {"elemental_skill": 10, "elemental_burst": 10},
             "stats": "the optimized character: her ATK is the candidate's"},
            {"element": "electro", "weapon_type": "WEAPON_POLE", "member_elements": team},
            RAIDEN_BASE, RAIDEN_ARTIFACTS, "electro",
            _with_hit(base._row("initial", "Musou no Hitotachi Base DMG", "burst", 1,
                                RAIDEN_INITIAL, None),
                      "elemental_burst", "Musou no Hitotachi Base DMG"),
            _kit("10000052", own, subject=True, receiver_element="electro", team_elements=team),
            {"kit:raiden_shogun/resolve": 60}, _raiden_on_herself),
        _fixture(
            "raiden_shogun_eye_c4_on_a_teammate",
            "a teammate's burst DMG per Energy of their own cost (a number the user states), "
            "and ATK% to the others",
            [FORMULA, f"{PANDO}RaidenShogun.ts:50,84,100-122,162-165,193,197"],
            {"name": "Raiden Shogun", "constellation": 4, "ascension_phase": 6,
             "talent_levels": {"elemental_skill": 10}, "stats": {}},
            {"element": "pyro", "weapon_type": "WEAPON_POLE",
             "member_elements": ["pyro", "electro", "hydro", "anemo"]},
            base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro",
            base._row("nado", "Pyronado DMG", "burst", 1, base.PYRONADO, None),
            _kit("10000052", _giver("Raiden Shogun", "10000052", constellation=4,
                                    rows={("elemental_skill", 10): RAIDEN_SKILL_10}),
                 subject=False, receiver_element="pyro",
                 team_elements=["pyro", "electro", "hydro", "anemo"]),
            {"kit:raiden_shogun/eye_energy": 80, "kit:raiden_shogun/c4_after_burst": 1},
            _raiden_on_xiangling),
    ]


def _buffers() -> list[dict[str, Any]]:
    xiangling = {"element": "pyro", "weapon_type": "WEAPON_POLE"}
    nado = base._row("nado", "Pyronado DMG", "burst", 1, base.PYRONADO, None)
    na1 = base._row("na1", "1-Hit DMG", "normal", 1, XIANGLING_NA_1, None)
    out: list[dict[str, Any]] = []

    out.append(_fixture(
        "kujou_sara_ambush_c6_on_her_own_burst",
        "flat ATK from the giver's base ATK at her boosted skill level, and a two-condition "
        "CRIT DMG buff",
        [FORMULA, f"{PANDO}KujouSara.ts:45,63,72-101"],
        {"name": "Kujou Sara", "constellation": 6, "ascension_phase": 6,
         "talent_levels": {"elemental_skill": 10}, "stats": "the optimized character"},
        {"element": "electro", "weapon_type": "WEAPON_BOW",
         "member_elements": ["electro", "pyro"]},
        SARA_BASE, SARA_ARTIFACTS, "electro",
        base._row("titan", "Tengu Juurai: Titanbreaker DMG", "burst", 1, SARA_BURST_13, None),
        _kit("10000056", _giver("Kujou Sara", "10000056", constellation=6,
                                rows={("elemental_skill", 13): SARA_SKILL_13},
                                stats=SARA_BASE), subject=True),
        {}, _sara))

    team = ["cryo", "cryo", "hydro", "anemo"]
    out.append(_fixture(
        "shenhe_quill_burst_a1_a4_c2_on_ayaka",
        "a teammate's Cryo flat damage from her ATK, RES shred from a talent row, element- and "
        "move-scoped DMG, and a cited CRIT DMG constant",
        [FORMULA, f"{PANDO}Shenhe.ts:48,58,65,68,103-135,147-156"],
        {"name": "Shenhe", "constellation": 2, "ascension_phase": 6,
         "talent_levels": {"elemental_skill": 10, "elemental_burst": 10},
         "stats": SHENHE_GIVER_STATS},
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND", "member_elements": team},
        base.AYAKA_BASE, base.AYAKA_ARTIFACTS, "cryo",
        base._row("press", "Skill DMG", "skill", 1, base.HYOUKA, None),
        _kit("10000063", _giver("Shenhe", "10000063", constellation=2,
                                rows={("elemental_skill", 10): SHENHE_SKILL_10,
                                      ("elemental_burst", 10): SHENHE_BURST_10},
                                stats=SHENHE_GIVER_STATS),
             subject=False, receiver_element="cryo", team_elements=team),
        {"kit:shenhe/quill": 1, "kit:shenhe/burst_field": 1, "kit:shenhe/a1_field": 1,
         "kit:shenhe/a4_press": 1},
        _shenhe_on_ayaka))

    team = ["pyro", "geo", "hydro", "cryo"]
    out.append(_fixture(
        "yun_jin_flying_cloud_on_a_teammate",
        "a teammate's Normal Attack flat damage from her DEF, part read from a table by the "
        "party's distinct elements",
        [FORMULA, f"{PANDO}YunJin.ts:59,66,69,85-103,119-120"],
        {"name": "Yun Jin", "constellation": 2, "ascension_phase": 6,
         "talent_levels": {"elemental_burst": 10}, "stats": YUN_JIN_GIVER_STATS},
        {**xiangling, "member_elements": team},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "physical", na1,
        _kit("10000064", _giver("Yun Jin", "10000064", constellation=2,
                                rows={("elemental_burst", 10): YUN_JIN_BURST_10},
                                stats=YUN_JIN_GIVER_STATS),
             subject=False, receiver_element="pyro", team_elements=team),
        {"kit:yun_jin/flying_cloud": 1}, _yun_jin_on_xiangling))

    team = ["geo", "geo", "geo", "pyro"]
    out.append(_fixture(
        "gorou_banner_a1_a4_c6_on_his_own_burst",
        "flat DEF and a Geo DMG buff gated on the Geo count, DEF%, self flat damage from his "
        "own DEF per candidate, and CRIT DMG from a clamped Geo-count table",
        [FORMULA, f"{PANDO}Gorou.ts:45-46,59-76,86-141"],
        {"name": "Gorou", "constellation": 6, "ascension_phase": 6,
         "talent_levels": {"elemental_skill": 10, "elemental_burst": 10},
         "stats": "the optimized character: his DEF is the candidate's"},
        {"element": "geo", "weapon_type": "WEAPON_BOW", "member_elements": team},
        GOROU_BASE, GOROU_ARTIFACTS, "geo",
        base._row("burst", "Skill DMG", "burst", 1, GOROU_BURST_13, None),
        _kit("10000055", _giver("Gorou", "10000055", constellation=6,
                                rows={("elemental_skill", 13): GOROU_SKILL_13},
                                stats=GOROU_BASE),
             subject=True, receiver_element="geo", team_elements=team),
        {}, _gorou))

    team = ["pyro", "geo", "hydro", "cryo"]
    out.append(_multi(
        "xilonen_samples_c2_c4_on_a_pyro_teammate",
        "a RES shred gated on a member of the element, an ATK% for receivers of one element, "
        "and Normal Attack flat damage from her DEF; two rows",
        [FORMULA, f"{PANDO}Xilonen.ts:53,81,89,106-181,205-217"],
        {"name": "Xilonen", "constellation": 4, "ascension_phase": 6,
         "talent_levels": {"elemental_skill": 10}, "stats": XILONEN_GIVER_STATS},
        {**xiangling, "member_elements": team},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro",
        [nado, {**na1, "channel": "physical"}],
        _kit("10000103", _giver("Xilonen", "10000103", constellation=4,
                                rows={("elemental_skill", 10): XILONEN_SKILL_10},
                                stats=XILONEN_GIVER_STATS),
             subject=False, receiver_element="pyro", team_elements=team),
        {"kit:xilonen/source_active": 1, "kit:xilonen/c4_blooming": 1},
        _xilonen_on_xiangling))

    team = ["geo", "pyro", "geo", "anemo"]
    out.append(_fixture(
        "xilonen_geo_sample_on_herself",
        "the Geo sample's RES shred while fewer than three samplers are converted, and C2's DMG "
        "Bonus to a Geo receiver",
        [FORMULA, f"{PANDO}Xilonen.ts:53,84,110-142,204,211,228"],
        {"name": "Xilonen", "constellation": 2, "ascension_phase": 6,
         "talent_levels": {"elemental_skill": 10}, "stats": "the optimized character"},
        {"element": "geo", "weapon_type": "WEAPON_SWORD_ONE_HAND", "member_elements": team},
        XILONEN_BASE, XILONEN_ARTIFACTS, "geo",
        base._row("rush", "Rush DMG", "skill", 1,
                  ("Rush DMG|{param1:F1P} DEF", XILONEN_SKILL_10[1]), None),
        _kit("10000103", _giver("Xilonen", "10000103", constellation=2,
                                rows={("elemental_skill", 10): XILONEN_SKILL_10},
                                stats=XILONEN_BASE),
             subject=True, receiver_element="geo", team_elements=team),
        {}, _xilonen_on_herself))

    team = ["pyro", "anemo", "hydro", "cryo"]
    out.append(_fixture(
        "xianyun_a1_a4_c2_on_a_plunging_teammate",
        "a stack table into plunge CRIT Rate, and plunge flat damage from the giver's ATK "
        "capped before it is multiplied, raised by C2",
        [FORMULA, f"{PANDO}Xianyun.ts:70-86,109-134,171"],
        {"name": "Xianyun", "constellation": 2, "ascension_phase": 6,
         "stats": XIANYUN_GIVER_STATS},
        {**xiangling, "member_elements": team},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "physical",
        base._row("high", "Low/High Plunge DMG (high)", "plunge", 1, XIANGLING_HIGH_PLUNGE,
                  None),
        _kit("10000093", _giver("Xianyun", "10000093", constellation=2,
                                stats=XIANYUN_GIVER_STATS),
             subject=False, receiver_element="pyro", team_elements=team),
        {"kit:xianyun/a1_stacks": 4, "kit:xianyun/a4_stacks": 1},
        _xianyun_on_xiangling))

    team = ["anemo", "pyro", "hydro", "cryo"]
    out.append(_fixture(
        "xianyun_a1_c6_on_her_own_wave",
        "row-scoped CRIT Rate and CRIT DMG from stack tables on her own Driftcloud Wave, and a "
        "self ATK%",
        [FORMULA, "libs/gi/sheets/src/Characters/Xianyun/index.tsx:111-122,147-183,243-251"],
        {"name": "Xianyun", "constellation": 6, "ascension_phase": 6,
         "talent_levels": {"elemental_skill": 10}, "stats": "the optimized character"},
        {"element": "anemo", "weapon_type": "WEAPON_CATALYST", "member_elements": team},
        XIANYUN_BASE, XIANYUN_ARTIFACTS, "anemo",
        _with_hit(base._row("wave3", "Driftcloud Wave DMG", "skill", 1, XIANYUN_WAVE_3, None),
                  "elemental_skill", "Driftcloud Wave DMG"),
        _kit("10000093", _giver("Xianyun", "10000093", constellation=6,
                                rows={("elemental_skill", 13): XIANYUN_SKILL_13},
                                stats=XIANYUN_BASE),
             subject=True, receiver_element="anemo", team_elements=team),
        {}, _xianyun_on_herself))

    team = ["pyro", "hydro", "anemo", "cryo"]
    out.append(_fixture(
        "mona_omen_c1_c4_on_xiangling",
        "a party DMG buff from a talent row at the giver's boosted level, a reaction bonus, and "
        "a CRIT Rate the seeded list publishes negated",
        [FORMULA_AMP, f"{PANDO}Mona.ts:61,86,103,118-148,227-258"],
        {"name": "Mona", "constellation": 4, "ascension_phase": 6,
         "talent_levels": {"elemental_burst": 10}, "stats": {}},
        {**xiangling, "member_elements": team},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro",
        base._row("nado_vape", "Pyronado DMG (vaporize)", "burst", 1, base.PYRONADO,
                  "reverse_vaporize"),
        _kit("10000041", _giver("Mona", "10000041", constellation=4,
                                rows={("elemental_burst", 13): MONA_BURST_13}),
             subject=False, receiver_element="pyro", team_elements=team),
        {"kit:mona/omen": 1, "kit:mona/c1_omen": 1}, _mona_on_xiangling,
        "amplifying EM coefficient: 2.78 (gcsim, ours) against GO's 25/9"))
    out.extend(_raiden_fixtures())
    return out
