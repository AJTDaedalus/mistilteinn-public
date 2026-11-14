"""A kit's talent-level raise and CRIT from Max HP (owner approval 2026-11-14,
`DECISIONS.md` §42): GO fixtures.

Kept beside `test_go_formula_fixtures.py` as the batch modules are, and imported by its
`build()`. The method is unchanged: each figure is worked by hand from Genshin Optimizer's formula
at `2c13fc40` with **our** numbers — talent rows verbatim from the seeded catalogue (nanoka
7.2.51), constellation lists the sheets' pins, stated builds.

**The talent-level raise.** A fixture whose kit raises a talent carries `raised_talents`: the
subject's rows at the raised level, as `/formula/kit-buffs` publishes them
(`team_talent_levels.raised_talents` over the same verbatim rows, so the Python and the browser
read one parse). The row's own `multiplier` is the **unraised** one — what `/search-context`
gives — and `formula:verify` holds that the figure needs the raise: without `raised_talents`, or
with the row's talent row unnamed, it must miss.

**CRIT from Max HP.** Nilou's and Sigewinne's C6 each have a build below both caps and one past
them (`cap_state`); the CRIT Rate and CRIT DMG caps bind at the same HP (50,000) for each.

Nothing here is a test by itself; its fixtures are checked by `test_go_formula_fixtures.py` and
`test_formula_sheets_talent_crit.py`, and by `npm run formula:verify`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.formula.genshin import sheets
from app.models.enums import TalentType
from app.schemas.formula import FormulaRaisedTalentRead
from app.services.team_talent_levels import raised_talents
from tests.unit import go_fixtures_batch4 as b4
from tests.unit import test_go_formula_fixtures as base

FORMULA = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
PANDO = "libs/gi/formula/src/data/char/"

# Seeded rows (nanoka 7.2.51), verbatim, trailing zero parameters dropped.
FURINA_SKILL_10 = sheets.TalentRow(
    ['Ousia Bubble DMG|{param1:F1P} Max HP', 'Duration|{param2:F1}s',
     'Gentilhomme Usher DMG|{param3:F2P} Max HP',
     'Surintendante Chevalmarin DMG|{param4:F2P} Max HP',
     'Mademoiselle Crabaletta DMG|{param5:F2P} Max HP',
     'Gentilhomme Usher HP Consumption|{param6:F1P} Max HP',
     'Surintendante Chevalmarin HP Consumption|{param7:F1P} Max HP',
     'Mademoiselle Crabaletta HP Consumption|{param8:F1P} Max HP',
     'Singer of Many Waters Healing|{param9:F2P} Max HP+{param10:I}', 'CD|{param11:F1}s'],
    [0.141552, 30.0, 0.10728, 0.058176, 0.149184, 0.024, 0.016, 0.036, 0.0864, 1016.9728,
     20.0],
)
FURINA_SKILL_11 = sheets.TalentRow(
    ['Ousia Bubble DMG|{param1:F1P} Max HP', 'Duration|{param2:F1}s',
     'Gentilhomme Usher DMG|{param3:F2P} Max HP',
     'Surintendante Chevalmarin DMG|{param4:F2P} Max HP',
     'Mademoiselle Crabaletta DMG|{param5:F2P} Max HP',
     'Gentilhomme Usher HP Consumption|{param6:F1P} Max HP',
     'Surintendante Chevalmarin HP Consumption|{param7:F1P} Max HP',
     'Mademoiselle Crabaletta HP Consumption|{param8:F1P} Max HP',
     'Singer of Many Waters Healing|{param9:F2P} Max HP+{param10:I}', 'CD|{param11:F1}s'],
    [0.149416, 30.0, 0.11324, 0.061408, 0.157472, 0.024, 0.016, 0.036, 0.0912, 1097.8734,
     20.0],
)
LOHEN_SKILL_13 = sheets.TalentRow(
    ['1-Hit DMG|{param1:F1P}', '2-Hit DMG|{param2:F1P}', '3-Hit DMG|{param3:F1P}\u00d73',
     '4-Hit DMG|{param4:F1P}', '5-Hit DMG|{param5:F1P}+{param6:F1P}',
     'Charged Attack DMG|{param7:F1P}\u00d72', 'Charged Attack Stamina Cost|{param8:F1}',
     'Plunge DMG|{param9:F1P}', 'Low/High Plunge DMG|{param10:P}/{param11:P}',
     'Masterstroke|{param12:F1}s', 'Etched Into Bone and Soul DMG|{param17:F1P}\u00d74',
     'DMG Increase From Will to Win|{param18:F2P}/Point', 'CD|{param19:F1}s'],
    [1.939933, 2.027998, 0.913342, 2.702885, 1.324312, 1.986468, 2.36694, 10.0, 1.531404,
     3.062159, 3.824802, 13.0, 17.0, 17.0, 10.0, 20.0, 1.275, 0.004, 18.0],
)
LOHEN_SKILL_14 = sheets.TalentRow(
    ['1-Hit DMG|{param1:F1P}', '2-Hit DMG|{param2:F1P}', '3-Hit DMG|{param3:F1P}\u00d73',
     '4-Hit DMG|{param4:F1P}', '5-Hit DMG|{param5:F1P}+{param6:F1P}',
     'Charged Attack DMG|{param7:F1P}\u00d72', 'Charged Attack Stamina Cost|{param8:F1}',
     'Plunge DMG|{param9:F1P}', 'Low/High Plunge DMG|{param10:P}/{param11:P}',
     'Masterstroke|{param12:F1}s', 'Etched Into Bone and Soul DMG|{param17:F1P}\u00d74',
     'DMG Increase From Will to Win|{param18:F2P}/Point', 'CD|{param19:F1}s'],
    [2.052939, 2.146134, 0.966547, 2.860334, 1.401457, 2.102185, 2.50482, 10.0, 1.620612,
     3.240537, 4.047606, 13.0, 17.0, 17.0, 10.0, 20.0, 1.35, 0.004, 18.0],
)
LOHEN_SKILL_15 = sheets.TalentRow(
    ['1-Hit DMG|{param1:F1P}', '2-Hit DMG|{param2:F1P}', '3-Hit DMG|{param3:F1P}\u00d73',
     '4-Hit DMG|{param4:F1P}', '5-Hit DMG|{param5:F1P}+{param6:F1P}',
     'Charged Attack DMG|{param7:F1P}\u00d72', 'Charged Attack Stamina Cost|{param8:F1}',
     'Plunge DMG|{param9:F1P}', 'Low/High Plunge DMG|{param10:P}/{param11:P}',
     'Masterstroke|{param12:F1}s', 'Etched Into Bone and Soul DMG|{param17:F1P}\u00d74',
     'DMG Increase From Will to Win|{param18:F2P}/Point', 'CD|{param19:F1}s'],
    [2.165944, 2.264269, 1.019751, 3.017784, 1.478601, 2.217901, 2.6427, 10.0, 1.70982,
     3.418915, 4.27041, 13.0, 17.0, 17.0, 10.0, 20.0, 1.425, 0.004, 18.0],
)
NILOU_SKILL_13 = sheets.TalentRow(
    ['Skill DMG|{param1:F2P} Max HP',
     'Sword Dance/Whirling Steps 1-Hit DMG|{param6:F2P}/{param2:F2P} Max HP',
     'Sword Dance/Whirling Steps 2-Hit DMG|{param7:F2P}/{param3:F2P} Max HP',
     'Luminous Illusion/Water Wheel DMG|{param4:F2P}/{param5:F2P} Max HP',
     'Pirouette Duration|{param11:F1}s', 'Lunar Prayer Duration|{param10:F1}s',
     'Tranquility Aura Duration|{param8:F1}s', 'CD|{param9:F1}s'],
    [0.070951, 0.069316, 0.08416, 0.152337, 0.107559, 0.09674, 0.10932, 12.0, 18.0, 8.0, 10.0],
)
SIGEWINNE_BURST_13 = sheets.TalentRow(
    ['Skill DMG|{param1:F1P} Max HP', 'Duration|{param4:F1}s', 'CD|{param2:F1}s',
     'Energy Cost|{param3:I}'],
    [0.250129, 18.0, 70.0, 2.5],
)
TARTAGLIA_NA_10 = sheets.TalentRow(
    ['1-Hit DMG|{param1:F1P}', '2-Hit DMG|{param2:F1P}', '3-Hit DMG|{param3:F1P}',
     '4-Hit DMG|{param4:F1P}', '5-Hit DMG|{param5:F1P}', '6-Hit DMG|{param6:F1P}',
     'Aimed Shot|{param7:F1P}', 'Fully-Charged Aimed Shot|{param8:P}',
     'Riptide Flash DMG|{param9:F1P}\u00d73', 'Riptide Burst DMG|{param10:F1P}',
     'Riptide Duration|{param14:F1}s', 'Plunge DMG|{param11:F1P}',
     'Low/High Plunge DMG|{param12:P}/{param13:P}'],
    [0.816, 0.9146, 1.0948, 1.1271, 1.2036, 1.4382, 0.867, 2.232, 0.2232, 1.116, 1.26378,
     2.527025, 3.15639, 10.0],
)
TARTAGLIA_NA_11 = sheets.TalentRow(
    ['1-Hit DMG|{param1:F1P}', '2-Hit DMG|{param2:F1P}', '3-Hit DMG|{param3:F1P}',
     '4-Hit DMG|{param4:F1P}', '5-Hit DMG|{param5:F1P}', '6-Hit DMG|{param6:F1P}',
     'Aimed Shot|{param7:F1P}', 'Fully-Charged Aimed Shot|{param8:P}',
     'Riptide Flash DMG|{param9:F1P}\u00d73', 'Riptide Burst DMG|{param10:F1P}',
     'Riptide Duration|{param14:F1}s', 'Plunge DMG|{param11:F1P}',
     'Low/High Plunge DMG|{param12:P}/{param13:P}'],
    [0.8736, 0.97916, 1.17208, 1.20666, 1.28856, 1.53972, 0.9282, 2.356, 0.2356, 1.178,
     1.352988, 2.705403, 3.379194, 10.0],
)
XIANGLING_NA_10 = sheets.TalentRow(
    ['1-Hit DMG|{param1:F1P}', '2-Hit DMG|{param2:F1P}',
     '3-Hit DMG|{param3:F1P}+{param3:F1P}', '4-Hit DMG|{param4:F1P}*4',
     '5-Hit DMG|{param5:P}', 'Charged Attack DMG|{param6:P}',
     'Charged Attack Stamina Cost|{param7:F1}', 'Plunge DMG|{param8:F1P}',
     'Low/High Plunge DMG|{param9:P}/{param10:P}'],
    [0.8313, 0.833, 0.5151, 0.2788, 1.4042, 2.4055, 25.0, 1.26378, 2.527025, 3.15639],
)
XIANGLING_NA_11 = sheets.TalentRow(
    ['1-Hit DMG|{param1:F1P}', '2-Hit DMG|{param2:F1P}',
     '3-Hit DMG|{param3:F1P}+{param3:F1P}', '4-Hit DMG|{param4:F1P}*4',
     '5-Hit DMG|{param5:P}', 'Charged Attack DMG|{param6:P}',
     'Charged Attack Stamina Cost|{param7:F1}', 'Plunge DMG|{param8:F1P}',
     'Low/High Plunge DMG|{param9:P}/{param10:P}'],
    [0.898537, 0.900375, 0.556762, 0.30135, 1.517775, 2.600062, 25.0, 1.352988, 2.705403,
     3.379194],
)


@dataclass(frozen=True)
class _Scaling:
    level: int
    labels: list[str]
    params: list[float]


@dataclass(frozen=True)
class _Talent:
    talent_type: TalentType
    scalings: list[_Scaling]


@dataclass(frozen=True)
class _Character:
    """The catalogue character `raised_talents` reads: its name and id (for the constellation
    boost table) and the seeded rows of one talent."""

    name: str
    nanoka_id: str
    element: str
    talents: list[_Talent]


def _raised(name: str, nanoka_id: str, element: str, talent: str,
            rows: dict[int, sheets.TalentRow], constellation: int, stored: dict[str, int],
            raise_by: int) -> list[dict[str, Any]]:
    character = _Character(name, nanoka_id, element, [_Talent(TalentType(talent), [
        _Scaling(level, list(row.labels), list(row.params)) for level, row in rows.items()])])
    return [FormulaRaisedTalentRead.of(t).model_dump()
            for t in raised_talents(character, constellation, stored, {talent: raise_by})]


def _named(row: dict[str, Any], talent: str, label: str) -> dict[str, Any]:
    """A fixture row naming its talent row and index, as the panel's rows do."""
    return {**row, "hit": {"talent": talent, "label": label, "index": 0}}


def _param(row: sheets.TalentRow, label: str) -> tuple[str, list[float]]:
    """A row in `base._row`'s `(label, params)` form: the one label, the row's parameters."""
    return next(lab for lab in row.labels if lab.split("|", 1)[0] == label), list(row.params)


def _fx(name: str, covers: str, go: list[str], giver: dict[str, Any], team: dict[str, Any],
        stats: dict[str, float], artifacts: dict[str, float], channel: str,
        row: dict[str, Any], source: dict[str, Any], conditionals: dict[str, Any],
        figure: Any, raised: list[dict[str, Any]] | None = None,
        cap_state: str | None = None) -> dict[str, Any]:
    out = base._buffer(name, covers, go, giver, team, stats, artifacts, channel, row, source,
                       conditionals, figure)
    if raised is not None:
        out["raised_talents"] = raised
    if cap_state is not None:
        out["cap_state"] = cap_state
    return out


def _crit(stats: dict[str, float]) -> tuple[float, float]:
    return stats["crit_rate"], stats["crit_dmg"]


# ── Tartaglia: Master of Weaponry, the party's Normal Attack +1 ─────────────────────────────

#: A stated Tartaglia at 90: base ATK character + weapon, his ascension Hydro DMG 28.8%.
TARTAGLIA_BASE = base._base_stats(base_atk=950.0, base_hp=13103.0, base_def=815.0,
                                  hydro_dmg_bonus=0.288)
TARTAGLIA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "hydro_dmg_bonus": 0.466,
                       "crit_rate": 0.3, "crit_dmg": 0.6}


def _xiangling_na(_: float) -> float:
    """**Xiangling, Normal Attack stored 10, Tartaglia in the party**: her 1-Hit DMG (Physical)
    read at level 11, 89.85% where level 10 is 83.13%.

    GO: `teamBuff.char.auto.add(dm.passive.auto_boost)` (`pando Tartaglia.ts:77-79,107-108`;
    WR `teamBuff.premod.autoBoost: nodePassive`, `index.tsx:192,202-206`); the row
    `dmg('normal_0', info, 'atk', arr, 'normal')` reads `talentSubscript(own.char.auto, …)`
    (`char/util.ts:49-51,82-98`), so the receiver's raised level."""
    stats = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)
    cr, cd = _crit(stats)
    return base._go_general(base=XIANGLING_NA_11.params[0] * base._total(stats, "atk"), flat=0.0,
                            dmg_bonus=stats.get("physical_dmg_bonus", 0.0), crit_rate=cr,
                            crit_dmg=cd)


def _tartaglia_flash(_: float) -> float:
    """**Tartaglia, C0, on his own Riptide Flash** (a Normal Attack row): Master of Weaponry
    reaches him too (`teamBuff`), so level 11's 23.56% per hit, not level 10's 22.32%.

    GO: `dmg('riptide_flash', info, 'atk', dm.riptide.flashDmg, 'normal', {ele: 'hydro'})`
    (`pando Tartaglia.ts:119-121`), and the raise as in `_xiangling_na`."""
    stats = base._stats(TARTAGLIA_BASE, TARTAGLIA_ARTIFACTS)
    cr, cd = _crit(stats)
    return base._go_general(base=TARTAGLIA_NA_11.params[8] * base._total(stats, "atk"), flat=0.0,
                            dmg_bonus=stats["hydro_dmg_bonus"], crit_rate=cr, crit_dmg=cd)


# ── Skirk: Mutual Weapons Mentorship, the party's Elemental Skill +1 ─────────────────────────


def _furina_usher(_: float) -> float:
    """**Furina, skill stored 10, in a Hydro and Cryo party with Skirk**: Gentilhomme Usher at
    level 11, 11.324% of her Max HP where level 10 is 10.728%. GO's Salon member multiplier is
    1 at its default (no member's HP consumed), as the estimate has it.

    GO: `teamBuff.char.skill.add(a0SkillBoost)`, `a0SkillBoost = cmpGE(count.cryo, 1,
    cmpGE(count.hydro, 1, cmpEq(cryo + hydro, all, 1)))` (`pando Skirk.ts:206-219,290-291`)."""
    stats = base._stats(base.FURINA_BASE, base.FURINA_ARTIFACTS)
    cr, cd = _crit(stats)
    return base._go_general(base=FURINA_SKILL_11.params[2] * base._total(stats, "hp"), flat=0.0,
                            dmg_bonus=stats["hydro_dmg_bonus"], crit_rate=cr, crit_dmg=cd)


# ── Lohen: High Spirits, his own Elemental Skill +1, after C3's +3 ───────────────────────────

LOHEN_BASE = base._base_stats(base_atk=900.0, base_hp=12500.0, base_def=800.0, crit_dmg=0.884)
LOHEN_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "cryo_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 0.6}


def _lohen_attack(_: float) -> float:
    """**Lohen, C3, skill stored 10, in High Spirits**: his Masterstroke 1-Hit DMG (a skill row
    dealt as a Normal Attack) at level **14** — 10, +3 from C3, +1 from High Spirits — 205.29%
    where 13 is 193.99%.

    GO: `ownBuff.char.skill.add(cmpGE(constellation, 3, 3))` and `ownBuff.char.skill.add(
    a0HighSpirits.ifOn(1))` (`pando Lohen.ts:197-199`), summed into `own.char.skill`; the row
    reads `talentSubscript(skill, …)` (`:177-200,218-222`)."""
    stats = base._stats(LOHEN_BASE, LOHEN_ARTIFACTS)
    cr, cd = _crit(stats)
    return base._go_general(base=LOHEN_SKILL_14.params[0] * base._total(stats, "atk"), flat=0.0,
                            dmg_bonus=stats["cryo_dmg_bonus"], crit_rate=cr, crit_dmg=cd)


# ── Nilou: C6, CRIT Rate and CRIT DMG from her Max HP, capped ───────────────────────────────

#: A stated Nilou at 90: her ascension HP% 28.8%.
NILOU_BASE = base._base_stats(base_atk=230.0, base_hp=15185.0, base_def=727.0, hp_pct=0.288)
NILOU_BELOW = {"hp_pct": 1.0, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466, "crit_rate": 0.3,
               "crit_dmg": 0.6}
NILOU_PAST = {"hp_pct": 2.4, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466, "crit_rate": 0.3,
              "crit_dmg": 0.6}
#: Her C6 list: `[0]` CRIT Rate and `[1]` CRIT DMG per 1,000 Max HP, `[2]`/`[3]` their caps.
NILOU_C6 = (0.006, 0.012, 0.3, 0.6)


def _nilou(artifacts: dict[str, float]) -> float:
    stats = base._stats(NILOU_BASE, artifacts)
    hp = base._total(stats, "hp")
    cr, cd = _crit(stats)
    return base._go_general(
        base=NILOU_SKILL_13.params[0] * hp, flat=0.0, dmg_bonus=stats["hydro_dmg_bonus"],
        crit_rate=cr + min(NILOU_C6[0] * hp / 1000, NILOU_C6[2]),
        crit_dmg=cd + min(NILOU_C6[1] * hp / 1000, NILOU_C6[3]))


def _nilou_below(_: float) -> float:
    """**Nilou, C6, on her own Skill DMG** (skill 13: stored 10, +3 from C5) with 39,523 Max HP:
    CRIT Rate +23.7% and CRIT DMG +47.4%, below 30% and 60%.

    GO: `ownBuff.premod.critRate_.add(c6_critRate_)`, `c6_critRate_ = cmpGE(constellation, 6,
    min(prod(percent(c6.critRate_), final.hp, 1 / 1000), percent(c6.maxCritRate_)))`, and the
    same for CRIT DMG (`pando Nilou.ts:91-96,167-182,191-192`)."""
    return _nilou(NILOU_BELOW)


def _nilou_past(_: float) -> float:
    """**Nilou, C6, HP-stacked, on her own Skill DMG** with 60,782 Max HP: 36.5% and 72.9%
    would be past both caps, so 30% and 60%. Same GO lines as `_nilou_below`."""
    return _nilou(NILOU_PAST)


# ── Sigewinne: C6, her burst's CRIT Rate and CRIT DMG from her Max HP, capped ───────────────

#: A stated Sigewinne at 90: her ascension HP% 28.8%.
SIGEWINNE_BASE = base._base_stats(base_atk=202.0, base_hp=13348.0, base_def=499.0, hp_pct=0.288)
SIGEWINNE_BELOW = {"hp_pct": 1.2, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 0.6}
SIGEWINNE_PAST = {"hp_pct": 2.8, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466,
                  "crit_rate": 0.3, "crit_dmg": 0.6}
#: Her C6 list: `[0]` CRIT Rate, `[1]` CRIT DMG per 1,000 Max HP, `[3]`/`[4]` their caps.
SIGEWINNE_C6 = (0.004, 0.022, 0.2, 1.1)


def _sigewinne(artifacts: dict[str, float]) -> float:
    stats = base._stats(SIGEWINNE_BASE, artifacts)
    hp = base._total(stats, "hp")
    cr, cd = _crit(stats)
    return base._go_general(
        base=SIGEWINNE_BURST_13.params[0] * hp, flat=0.0, dmg_bonus=stats["hydro_dmg_bonus"],
        crit_rate=cr + min(SIGEWINNE_C6[0] * hp / 1000, SIGEWINNE_C6[2]),
        crit_dmg=cd + min(SIGEWINNE_C6[1] * hp / 1000, SIGEWINNE_C6[3]))


def _sigewinne_below(_: float) -> float:
    """**Sigewinne, C6, on her own Super Saturated Syringing** (burst 13: stored 10, +3 from C5)
    after she heals, with 37,990 Max HP: burst CRIT Rate +15.2% and CRIT DMG +83.6%, below 20%
    and 110%.

    GO: `ownBuff.premod.critRate_.burst.add(c6AfterHeal_burst_critRate_)`, `cmpGE(
    constellation, 6, min(prod(final.hp, 1 / 1000, percent(c6.critRate_)), percent(
    c6.maxCritRate_)))`, and the same for CRIT DMG (`pando Sigewinne.ts:89-95,182-197,209-210`;
    WR applies it at C6 without reading its toggle, `index.tsx:180-197,254-255`)."""
    return _sigewinne(SIGEWINNE_BELOW)


def _sigewinne_past(_: float) -> float:
    """**Sigewinne, C6, HP-stacked, on her own burst** with 59,347 Max HP: 23.7% and 130.6%
    would be past both caps, so 20% and 110%. Same GO lines as `_sigewinne_below`."""
    return _sigewinne(SIGEWINNE_PAST)


def talent_crit_fixtures() -> list[dict[str, Any]]:
    """The talent-level raise (Tartaglia, Skirk, Lohen) and CRIT from Max HP (Nilou, Sigewinne)."""
    out: list[dict[str, Any]] = []
    tartaglia = base._ungated_giver("Tartaglia", "10000033")
    tartaglia_go = f"{PANDO}Tartaglia.ts:77-79,107-108"

    out.append(_fx(
        "tartaglia_a0_on_xiangling_normal_attack",
        "a teammate's raise of the receiver's Normal Attack level (+1, Tartaglia's A0): the row "
        "read at the raised level from `raised_talents`",
        [FORMULA, tartaglia_go, f"{PANDO}util.ts:49-51,82-98"],
        {"name": "Tartaglia", "constellation": 0, "ascension_phase": 6, "stats": {}},
        {"element": "pyro", "weapon_type": "WEAPON_POLE", "member_elements": ["pyro", "hydro"]},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "physical",
        _named(base._row("na1", "1-Hit DMG", "normal", 1, _param(XIANGLING_NA_10, "1-Hit DMG"),
                         None), "normal_attack", "1-Hit DMG"),
        b4._kit("10000033", tartaglia, subject=False, receiver_element="pyro",
                team_elements=["pyro", "hydro"]),
        {}, _xiangling_na,
        raised=_raised("Xiangling", "10000023", "Pyro", "normal_attack",
                       {10: XIANGLING_NA_10, 11: XIANGLING_NA_11}, 0, {"normal_attack": 10}, 1)))

    out.append(_fx(
        "tartaglia_a0_on_his_own_riptide_flash",
        "the same raise reaching its giver (`team` includes him), on a Normal Attack row GO deals "
        "as a Normal Attack",
        [FORMULA, tartaglia_go, f"{PANDO}Tartaglia.ts:119-121"],
        {"name": "Tartaglia", "constellation": 0, "ascension_phase": 6,
         "stats": "the optimized character"},
        {"element": "hydro", "weapon_type": "WEAPON_BOW", "member_elements": ["hydro", "pyro"]},
        TARTAGLIA_BASE, TARTAGLIA_ARTIFACTS, "hydro",
        _named(base._row("flash", "Riptide Flash DMG", "normal", 1,
                         _param(TARTAGLIA_NA_10, "Riptide Flash DMG"), None),
               "normal_attack", "Riptide Flash DMG"),
        b4._kit("10000033", base._ungated_giver("Tartaglia", "10000033", stats=TARTAGLIA_BASE),
                subject=True, receiver_element="hydro", team_elements=["hydro", "pyro"]),
        {}, _tartaglia_flash,
        raised=_raised("Tartaglia", "10000033", "Hydro", "normal_attack",
                       {10: TARTAGLIA_NA_10, 11: TARTAGLIA_NA_11}, 0, {"normal_attack": 10}, 1)))

    out.append(_fx(
        "skirk_a0_on_furina_usher",
        "a raise of the receiver's Elemental Skill level (+1) gated on the party being only Hydro "
        "and Cryo with one of each (Skirk's A0)",
        [FORMULA, f"{PANDO}Skirk.ts:206-219,290-291"],
        {"name": "Skirk", "constellation": 0, "ascension_phase": 6, "stats": {}},
        {"element": "hydro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["hydro", "cryo"]},
        base.FURINA_BASE, base.FURINA_ARTIFACTS, "hydro",
        _named(base._row("usher", "Gentilhomme Usher DMG", "skill", 1,
                         _param(FURINA_SKILL_10, "Gentilhomme Usher DMG"), None),
               "elemental_skill", "Gentilhomme Usher DMG"),
        b4._kit("10000114", base._ungated_giver("Skirk", "10000114"), subject=False,
                receiver_element="hydro", team_elements=["hydro", "cryo"]),
        {}, _furina_usher,
        raised=_raised("Furina", "10000089", "Hydro", "elemental_skill",
                       {10: FURINA_SKILL_10, 11: FURINA_SKILL_11}, 0, {"elemental_skill": 10},
                       1)))

    cons, pas = base._pinned("10000129")
    out.append(_fx(
        "lohen_c3_high_spirits_on_his_own_skill_attack",
        "a conditional raise of his own Elemental Skill level (+1, High Spirits) on top of "
        "C3's +3: level 10 + 3 + 1 = 14, on a skill row dealt as a Normal Attack",
        [FORMULA, f"{PANDO}Lohen.ts:132,177-200,218-222"],
        {"name": "Lohen", "constellation": 3, "ascension_phase": 6,
         "stats": "the optimized character"},
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "hydro"]},
        LOHEN_BASE, LOHEN_ARTIFACTS, "cryo",
        _named(base._row("attack1", "1-Hit DMG", "normal", 1, _param(LOHEN_SKILL_13, "1-Hit DMG"),
                         None), "elemental_skill", "1-Hit DMG"),
        b4._kit("10000129", base._ungated_giver("Lohen", "10000129", constellation=3, cons=cons,
                                                passives=pas, stats=LOHEN_BASE), subject=True,
                receiver_element="cryo", team_elements=["cryo", "hydro"]),
        {"kit:lohen/a4_master_cryo": 0, "kit:lohen/high_spirits": 1},
        _lohen_attack,
        raised=_raised("Lohen", "10000129", "Cryo", "elemental_skill",
                       {13: LOHEN_SKILL_13, 14: LOHEN_SKILL_14, 15: LOHEN_SKILL_15}, 3,
                       {"elemental_skill": 10}, 1)))

    cons, pas = base._pinned("10000070")
    nilou_go = [FORMULA, f"{PANDO}Nilou.ts:91-96,167-182,191-192"]
    for name, artifacts, figure, state in [
        ("nilou_c6_below_cap_on_her_own_skill", NILOU_BELOW, _nilou_below, "below"),
        ("nilou_c6_past_cap_on_her_own_skill", NILOU_PAST, _nilou_past, "past"),
    ]:
        out.append(_fx(
            name,
            "self CRIT Rate and CRIT DMG from her own Max HP per 1,000 (a cited unit), each "
            "capped alone (C6), per candidate, on every hit",
            nilou_go,
            {"name": "Nilou", "constellation": 6, "ascension_phase": 6,
             "stats": "the optimized character"},
            {"element": "hydro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
             "member_elements": ["hydro", "hydro"]},
            NILOU_BASE, artifacts, "hydro",
            base._row("skill", "Skill DMG", "skill", 1, _param(NILOU_SKILL_13, "Skill DMG"), None),
            b4._kit("10000070", base._ungated_giver("Nilou", "10000070", constellation=6,
                                                    cons=cons, passives=pas, stats=NILOU_BASE),
                    subject=True, receiver_element="hydro", team_elements=["hydro", "hydro"]),
            {"kit:nilou/c4_hit": 1}, figure, cap_state=state))

    cons, pas = base._pinned("10000095")
    sige_go = [FORMULA, f"{PANDO}Sigewinne.ts:89-95,182-197,209-210"]
    for name, artifacts, figure, state in [
        ("sigewinne_c6_below_cap_on_her_own_burst", SIGEWINNE_BELOW, _sigewinne_below, "below"),
        ("sigewinne_c6_past_cap_on_her_own_burst", SIGEWINNE_PAST, _sigewinne_past, "past"),
    ]:
        out.append(_fx(
            name,
            "self burst CRIT Rate and CRIT DMG from her own Max HP per 1,000, each capped alone "
            "(C6), per candidate, behind a self toggle",
            sige_go,
            {"name": "Sigewinne", "constellation": 6, "ascension_phase": 6,
             "stats": "the optimized character"},
            {"element": "hydro", "weapon_type": "WEAPON_BOW",
             "member_elements": ["hydro", "pyro"]},
            SIGEWINNE_BASE, artifacts, "hydro",
            base._row("syringe", "Skill DMG", "burst", 1, _param(SIGEWINNE_BURST_13, "Skill DMG"),
                      None),
            b4._kit("10000095", base._ungated_giver("Sigewinne", "10000095", constellation=6,
                                                    cons=cons, passives=pas,
                                                    stats=SIGEWINNE_BASE),
                    subject=True, receiver_element="hydro", team_elements=["hydro", "pyro"]),
            {"kit:sigewinne/bed_rest": 0, "kit:sigewinne/conva": 0,
             "kit:sigewinne/bubble_tier": 0, "kit:sigewinne/c2_hit": 0,
             "kit:sigewinne/c6_after_heal": 1},
            figure, cap_state=state))
    return out
