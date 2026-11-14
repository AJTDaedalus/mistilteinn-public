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
    return out
