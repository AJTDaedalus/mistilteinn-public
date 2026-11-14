"""Math-fallback P2, task 11 (fifth batch): GO fixtures for the next popular DPS characters.

Kept beside `test_go_formula_fixtures.py`, as `go_fixtures_batch4.py` is, and imported by its
`build()`. The method is unchanged: each figure is worked by hand from Genshin Optimizer's formula
at `2c13fc40` with **our** numbers — talent rows verbatim from the seeded catalogue (nanoka
7.2.51, level 10 unless said), constellation and passive lists the sheets' pins, stated builds.
Each subject resolves its own sheet against its base stats, as the third batch's fixtures do; a
teammate giver's stats are written out as their pass-1 numbers.

Nothing here is a test by itself; its fixtures are checked by `test_go_formula_fixtures.py` (and
`test_formula_sheets_dps2.py`) and by `npm run formula:verify`.
"""

from __future__ import annotations

from typing import Any

from app.formula.genshin import sheets
from tests.unit import go_fixtures_batch4 as b4
from tests.unit import test_go_formula_fixtures as base

FORMULA = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
PANDO = "libs/gi/formula/src/data/char/"


def _subject(name: str, constellation: int,
             talent_levels: dict[str, int] | None = None) -> dict[str, Any]:
    giver: dict[str, Any] = {"name": name, "constellation": constellation, "ascension_phase": 6}
    if talent_levels:
        giver["talent_levels"] = talent_levels
    giver["stats"] = "the optimized character"
    return giver


def _own(name: str, nanoka_id: str, constellation: int, stats: dict[str, float],
         rows: dict[tuple[str, int], tuple[list[str], list[float]]] | None = None
         ) -> sheets.Giver:
    """A subject at A6 with the sheet's pinned lists and the stated talent rows."""
    cons, pas = base._pinned(nanoka_id)
    return base._ungated_giver(
        name, nanoka_id, constellation=constellation,
        talent_levels=dict((rows or {}).keys()),
        talent_rows={k: sheets.TalentRow(*v) for k, v in (rows or {}).items()},
        cons=cons, passives=pas, stats=stats)


def _hit(stats: dict[str, float], *, base_damage: float, flat: float = 0.0, channel: str,
         extra_dmg: float = 0.0, extra_cr: float = 0.0, extra_cd: float = 0.0,
         res: float = 0.1) -> float:
    return b4._go_hit(base_damage=base_damage, flat=flat,
                      dmg_bonus=stats.get(f"{channel}_dmg_bonus", 0.0) + extra_dmg,
                      crit_rate=stats["crit_rate"] + extra_cr,
                      crit_dmg=stats["crit_dmg"] + extra_cd, res=res)


# ── Hu Tao ──────────────────────────────────────────────────────────────────────────────────

HU_TAO_BLOSSOM = ("Blood Blossom DMG|{param3:P}", [0.3, 0.06256, 1.152])
HU_TAO_BASE = base._base_stats(base_atk=715.0, base_hp=15552.0, base_def=876.0, crit_dmg=0.884)
HU_TAO_ARTIFACTS = {"hp_pct": 0.466, "flat_hp": 4780.0, "flat_atk": 311.0,
                    "pyro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}


def _hu_tao(_: float) -> float:
    """**Hu Tao, C2, on her own Blood Blossom**, her HP at or below 50% (A4, set by the user —
    situational). Paramita Papilio is off in both figures: its ATK is the capped conversion the
    sheet does not model (DECISIONS §39).

    GO: `dmg('skill', info, 'atk', dm.skill.dmg, 'skill')` (`pando HuTao.ts:165`); C2
    `ownBuff.formula.base.skill` = `prod(percent(constellation2), own.premod.hp)` (`:74-76,
    119-126,151`); A4 `ownBuff.premod.dmg_.pyro` = `passive2.pyroDmgInc` (`:70-73,116-118,
    150`)."""
    stats = base._stats(HU_TAO_BASE, HU_TAO_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(HU_TAO_BLOSSOM) * base._total(stats, "atk"),
                flat=0.1 * base._total(stats, "hp"), channel="pyro", extra_dmg=0.33)


# ── Arlecchino ──────────────────────────────────────────────────────────────────────────────

ARLE_NORMAL_LABELS = [
    "Masque of the Red Death Increase|{param12:F2P}", "1-Hit DMG|{param1:F1P}",
    "2-Hit DMG|{param2:F1P}", "3-Hit DMG|{param3:F1P}", "4-Hit DMG|{param4:F1P}+{param4:F1P}",
    "5-Hit DMG|{param5:F1P}", "6-Hit DMG|{param6:F1P}", "Charged Attack DMG|{param7:F1P}",
    "Charged Attack Stamina Cost|{param8:F1}", "High-Speed Movement Stamina Cost|{param15:F1}/s",
    "Plunge DMG|{param9:F1P}", "Low/High Plunge DMG|{param10:F1P}/{param11:F1P}"]
ARLE_NORMAL_10 = [0.938961, 1.029996, 1.29251, 0.734264, 1.383358, 1.687709, 1.7952, 25.0,
                  1.26378, 2.527025, 3.15639, 2.38, 0.075, 0.3, 40.0]
ARLE_NA_1 = ("1-Hit DMG|{param1:F1P}", ARLE_NORMAL_10)
ARLE_BASE = base._base_stats(base_atk=1016.0, base_hp=13103.0, base_def=763.0, crit_dmg=0.884)
ARLE_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466,
                  "crit_rate": 0.3, "crit_dmg": 0.6}
#: The Bond of Life the fixture states, in percentage points of her Max HP.
ARLE_BOND = 145


def _arlecchino(_: float) -> float:
    """**Arlecchino, C0, on her own 1-Hit DMG** at 145% Bond of Life (the user's number): the
    Masque adds the row's 238% of her ATK per 100% of Bond, moving with every candidate's ATK;
    her A0 passive's Pyro DMG.

    GO: `dmg('normal_0', info, 'atk', …, 'normal')` (`pando Arlecchino.ts:188-199`); Masque
    `ownBuff.formula.base.normal` = `prod(percent(talent row), final.atk, bondPercent / 100)`
    (`:45-49,119-128,181`); A0 `ownBuff.premod.dmg_.pyro` = `passive3.pyro_dmg_` (`:79-83,129,
    168`)."""
    stats = base._stats(ARLE_BASE, ARLE_ARTIFACTS)
    atk = base._total(stats, "atk")
    return _hit(stats, base_damage=base._multiplier(ARLE_NA_1) * atk,
                flat=ARLE_NORMAL_10[11] * atk * ARLE_BOND / 100, channel="pyro", extra_dmg=0.4)


# ── Clorinde ────────────────────────────────────────────────────────────────────────────────

CLORINDE_BURST = ("Skill DMG|{param1:F1P}\u00d75", [2.28384, 1.2, 15.0, 60.0])
CLORINDE_BASE = base._base_stats(base_atk=1009.0, base_hp=12956.0, base_def=784.0,
                                 crit_rate=0.242)
CLORINDE_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "electro_dmg_bonus": 0.466,
                      "crit_rate": 0.3, "crit_dmg": 0.8}
#: Bond of Life on using her burst, in percentage points (the user's number).
CLORINDE_BOND = 60


def _clorinde(_: float) -> float:
    """**Clorinde, C4, on her own Last Lightfall** (five hits), two A4 stacks (her own doing, the
    default) and 60% Bond of Life (the user's): C4 2% burst DMG per point.

    GO: `dmg('burst', info, 'atk', dm.burst.skillDmg, 'burst')` (`pando Clorinde.ts:204`); A4
    `ownBuff.premod.critRate_` = `prod(a4BondChanges, percent(passive2.critRate_))` (`:68-74,
    147-151,185`); C4 `ownBuff.premod.dmg_.burst` = `prod(percent(constellation4.burst_dmg_),
    c4BondPercent)` (`:85-88,152-156,186`)."""
    stats = base._stats(CLORINDE_BASE, CLORINDE_ARTIFACTS)
    one = _hit(stats, base_damage=base._multiplier(CLORINDE_BURST) * base._total(stats, "atk"),
               channel="electro", extra_dmg=0.02 * CLORINDE_BOND, extra_cr=2 * 0.1)
    return 5 * one


# ── Navia ───────────────────────────────────────────────────────────────────────────────────

NAVIA_SHARDSHOT = ("Rosula Shardshot Base DMG|{param1:F1P}", [7.1064])
NAVIA_TEAM = ["geo", "pyro", "hydro", "anemo"]
NAVIA_BASE = base._base_stats(base_atk=1053.0, base_hp=12650.0, base_def=793.0, crit_dmg=0.884)
NAVIA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "geo_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 0.6}


def _navia(_: float) -> float:
    """**Navia, C0, on her own Rosula Shardshot** with six Crystal Shrapnel (her own doing, the
    default) beside a Pyro and a Hydro member: A4 ATK twice; Skill DMG 15% for each of the three
    beyond three. GO's shots-hit base multiplier is 1 at its default (0 shots), as here.

    GO: `dmg('totalShardDmg', info, 'atk', dm.skill.baseShardDmg, 'skill', {baseMulti: sum(1,
    shotsHit_shot_mult_)})` (`pando Navia.ts:100-110,183-192`); A4 `ownBuff.premod.atk_` =
    `cmpGE(numTeammates, 2, 2 \u00d7 passive2.atk_, …)` (`:70-72,121-132,167`); `ownBuff.premod.
    dmg_.skill` = `prod(sum(skillCharges, -3), percent(skill[1][0]))` (`:51-53,111-115,168`)."""
    stats = base._stats(NAVIA_BASE, NAVIA_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=2 * 0.2)
    return _hit(stats, base_damage=base._multiplier(NAVIA_SHARDSHOT) * atk, channel="geo",
                extra_dmg=3 * 0.15)


# ── Wriothesley ─────────────────────────────────────────────────────────────────────────────

WRIO_NA_1 = ("1-Hit DMG|{param1:F1P}", [1.054782])
WRIO_SKILL_LABELS = ["Enhanced Repelling Fist DMG|{param1:F1P} Normal Attack DMG",
                     "HP Cost|{param2:F1P} Max HP", "Duration|{param3:F1}s", "CD|{param4:F1}s"]
WRIO_SKILL_10 = [1.70312, 0.045, 10.0, 16.0, 0.0, 0.0, 0.0, 0.70312]
WRIO_BASE = base._base_stats(base_atk=1058.0, base_hp=13592.0, base_def=763.0, crit_dmg=0.884)
WRIO_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "cryo_dmg_bonus": 0.466,
                  "crit_rate": 0.3, "crit_dmg": 0.6}


def _wriothesley(_: float) -> float:
    """**Wriothesley, C0, on his own 1-Hit DMG in Chilling Penalty**, five Prosecution Edicts
    (his own doing, the default): the Normal Attack row times the skill's 170.312%, and A4's
    6% ATK per Edict.

    GO: `customDmg('skill_enhanced_0', ele, 'normal', prod(percent(auto row), percent(skill
    fistDmg), final.atk))` (`pando Wriothesley.ts:44-45,192-203`); A4 `ownBuff.premod.atk_` =
    `prod(a4EdictStacks, percent(passive2.atk_))` (`:63-66,126-130,170`)."""
    stats = base._stats(WRIO_BASE, WRIO_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=5 * 0.06)
    return _hit(stats, base_damage=base._multiplier(WRIO_NA_1) * WRIO_SKILL_10[0] * atk,
                channel="cryo")


# ── Lyney ───────────────────────────────────────────────────────────────────────────────────

LYNEY_PYROTECHNIC = ("Pyrotechnic Strike DMG|{param15:F1P}",
                     [0.7667, 0.7514, 0.5389, 0.5389, 1.1254, 1.12336, 2.246244, 2.80568, 0.867,
                      2.232, 3.1104, 0.2, 1.152, 4.0, 3.816])
#: His seeded skill row at 10, so the sheet's Prop Surplus effect resolves (it reaches skill
#: rows only, not this one).
LYNEY_SKILL_LABELS = ["Skill DMG|{param1:F1P}", "Skill DMG Bonus|{param2:F1P} ATK/Stack",
                      "HP Regeneration|{param3:P}/Stack", "CD|{param5:F1}s"]
LYNEY_SKILL_10 = [3.0096, 0.9576, 0.2, 0.0, 15.0]
LYNEY_TEAM = ["pyro", "pyro", "pyro", "anemo"]
LYNEY_BASE = base._base_stats(base_atk=916.0, base_hp=11021.0, base_def=539.0, crit_rate=0.242)
LYNEY_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 0.9}


def _lyney(_: float) -> float:
    """**Lyney, C0, on his own Pyrotechnic Strike** beside two other Pyro members, every
    condition his own doing: A1's 80% of his ATK into the strike's base (that row only), and A4's
    60% DMG plus 20% for each other Pyro member, at most two.

    GO: `dmg('charged_pyrotechnic', …, ownBuff.formula.base.add(a1_hatDmgInc))` with
    `a1_hatDmgInc = prod(percent(passive1.propAddlDmg), final.atk)` (`pando Lyney.ts:63-66,
    108-110,155-163`); A4 `ownBuff.premod.dmg_` = `sum(passive2.dmg_, prod(passive2.extraDmg_,
    min(2, count.pyro - 1)))` (`:67-70,90,111-121,139`)."""
    stats = base._stats(LYNEY_BASE, LYNEY_ARTIFACTS)
    atk = base._total(stats, "atk")
    return _hit(stats, base_damage=LYNEY_PYROTECHNIC[1][14] * atk, flat=0.8 * atk,
                channel="pyro", extra_dmg=0.6 + 2 * 0.2)


# ── Yoimiya ─────────────────────────────────────────────────────────────────────────────────

YOIMIYA_NA_1 = ("1-Hit DMG|{param1:F1P}\u00d72", [0.63585])
YOIMIYA_SKILL_LABELS = ["Blazing Arrow DMG|{param4:F1P} Normal Attack DMG",
                        "Duration|{param2:F1}s", "CD|{param3:F1}s"]
YOIMIYA_SKILL_10 = [0.61744, 10.0, 18.0, 1.61744]
YOIMIYA_BASE = base._base_stats(base_atk=1134.0, base_hp=10164.0, base_def=615.0,
                                crit_rate=0.242)
YOIMIYA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466,
                     "crit_rate": 0.3, "crit_dmg": 0.9}


def _yoimiya(_: float) -> float:
    """**Yoimiya, C0, on her own 1-Hit DMG (two arrows) in Niwabi Fire-Dance**, ten A1 stacks,
    both her own doing: the row times the skill's 161.744%, and 2% Pyro DMG per stack.

    GO: `dmg('normal_0_pyro', info, 'atk', arr, 'normal', {ele: 'pyro', baseMulti:
    skillMult})` (`pando Yoimiya.ts:95-97,135-142`); A1 `ownBuff.premod.dmg_.pyro` = `prod(skillOn,
    prod(percent(passive1.pyro_dmg_), a1))` (`:54-58,98-101,131`)."""
    stats = base._stats(YOIMIYA_BASE, YOIMIYA_ARTIFACTS)
    one = _hit(stats, base_damage=base._multiplier(YOIMIYA_NA_1) * YOIMIYA_SKILL_10[3]
               * base._total(stats, "atk"), channel="pyro", extra_dmg=10 * 0.02)
    return 2 * one


def _yoimiya_on_xiangling(_: float) -> float:
    """**Yoimiya, as Xiangling's teammate, A4 after her burst** (set by the user — situational
    for a teammate), with her ten A1 stacks: ATK 10% + 1% per stack.

    GO: `notOwnBuff.premod.atk_` = `burst.ifOn(sum(percent(passive2.fixed_atk_),
    prod(percent(passive2.var_atk_), a1)))` (`pando Yoimiya.ts:59-63,102-111,133`)."""
    totals = base._xiangling_totals(fervent=False, witch_stacks=0)
    atk = (base.XIANGLING_BASE["base_atk"]
           * (1 + base.XIANGLING_ARTIFACTS["atk_pct"] + 0.1 + 10 * 0.01)
           + base.XIANGLING_ARTIFACTS["flat_atk"])
    return b4._go_hit(base_damage=base._multiplier(base.PYRONADO) * atk,
                      dmg_bonus=base.XIANGLING_ARTIFACTS["pyro_dmg_bonus"],
                      crit_rate=totals["cr"], crit_dmg=totals["cd"])


# ── Ganyu ───────────────────────────────────────────────────────────────────────────────────

GANYU_BLOOM = ("Frostflake Arrow Bloom DMG|{param10:P}",
               [0.6273, 0.7038, 0.8993, 0.8993, 0.9537, 1.139, 0.867, 2.232, 2.304, 3.9168])
GANYU_BASE = base._base_stats(base_atk=1101.0, base_hp=9797.0, base_def=630.0, crit_dmg=0.884)
GANYU_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "cryo_dmg_bonus": 0.466,
                   "crit_rate": 0.25, "crit_dmg": 0.7}


def _ganyu(_: float) -> float:
    """**Ganyu, C0, on her own Frostflake Arrow Bloom**, after firing a Frostflake Arrow (A1,
    her own) and in her own Celestial Shower (A4, her own as the subject).

    GO: `dmg('charged_frostflakeBloom', …, ownBuff.premod.critRate_.add(a1))` (`pando
    Ganyu.ts:61-64,83-85,127-135`); A4 `teamBuff.premod.dmg_.cryo` = `prod(destIsActive,
    passive2.cryoDmgBonus)` (`:65-67,86-89,102`)."""
    stats = base._stats(GANYU_BASE, GANYU_ARTIFACTS)
    return _hit(stats, base_damage=GANYU_BLOOM[1][9] * base._total(stats, "atk"),
                channel="cryo", extra_dmg=0.2, extra_cr=0.2)


# ── Eula ────────────────────────────────────────────────────────────────────────────────────

EULA_BURST_LABELS = ["Skill DMG|{param1:P}", "Lightfall Sword Base DMG|{param2:F1P}",
                     "DMG Per Stack|{param3:F1P}", "Maximum Stacks|{param4:I}", "CD|{param5:F1}s",
                     "Energy Cost|{param6:I}"]
EULA_BURST_10 = [4.4208, 7.2556, 1.4824, 30.0, 20.0, 80.0]
EULA_LIGHTFALL = ("Lightfall Sword Base DMG|{param2:F1P}", EULA_BURST_10)
EULA_SKILL_LABELS = [
    "#{LAYOUT_MOBILE#Tap}{LAYOUT_PC#Press}{LAYOUT_PS#Press} DMG|{param1:P}",
    "Hold DMG|{param2:P}", "Icewhirl Brand DMG|{param3:P}", "DEF Bonus|{param9:P} Per Stack",
    "Grimheart Duration|{param13:F1}s", "Physical RES Decrease|{param4:P}",
    "Cryo RES Decrease|{param5:P}", "RES Decrease Duration|{param6:F1}s",
    "#{LAYOUT_MOBILE#Tap}{LAYOUT_PC#Press}{LAYOUT_PS#Press} CD|{param7:F1}s",
    "Hold CD|{param8:F1}s"]
EULA_SKILL_10 = [2.6352, 4.4208, 1.728, 0.25, 0.25, 7.0, 4.0, 10.0, 0.3, 14.0, -0.25, -0.25, 18.0]
EULA_BASE = base._base_stats(base_atk=1131.0, base_hp=13226.0, base_def=751.0, crit_dmg=0.884)
EULA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "physical_dmg_bonus": 0.583,
                  "crit_rate": 0.3, "crit_dmg": 0.6}
EULA_STACKS = 30


def _eula(_: float) -> float:
    """**Eula, C0, on her own Lightfall Sword** at 30 stacks (her own doing, the default), with
    Grimheart consumed (her own doing as the subject): the burst's per-stack row times her ATK
    into the sword's base, and the skill's 25% Physical RES decrease.

    GO: `customDmg('burst_lightfall', 'physical', 'burst', prod(sum(lightfallDmg, prod(dmgPerStack,
    stacks)), final.atk))` (`pando Eula.ts:62-69,109-115,142-149`); `enemyDebuff.common.preRes.
    physical` = `grimheartConsumed.ifOn(physResDecNegative)` (`:47-61,100-102,128`)."""
    stats = base._stats(EULA_BASE, EULA_ARTIFACTS)
    atk = base._total(stats, "atk")
    return _hit(stats, base_damage=EULA_BURST_10[1] * atk,
                flat=EULA_BURST_10[2] * EULA_STACKS * atk, channel="physical",
                res=0.1 - EULA_SKILL_10[3])


# ── Arataki Itto ────────────────────────────────────────────────────────────────────────────

ITTO_NORMAL_10 = [1.56621, 1.5096, 1.81152, 2.317236, 1.7884, 1.802, 3.774, 20.0, 1.617638,
                  3.234591, 4.040179, 60.0]
ITTO_FINAL = ("Arataki Kesagiri Final Slash DMG|{param7:F1P}", ITTO_NORMAL_10)
ITTO_BURST_LABELS = ["ATK Bonus|{param2:F1P} DEF", "ATK SPD Bonus|{param1:P}",
                     "Duration|{param4:F1}s", "CD|{param5:F1}s", "Energy Cost|{param6:I}"]
ITTO_BURST_10 = [0.1, 1.0368, 0.2, 11.0, 18.0, 70.0]
ITTO_BASE = base._base_stats(base_atk=885.0, base_hp=12858.0, base_def=959.0, crit_rate=0.242)
ITTO_ARTIFACTS = {"def_pct": 1.166, "flat_def": 39.0, "flat_atk": 311.0, "geo_dmg_bonus": 0.466,
                  "crit_rate": 0.3, "crit_dmg": 0.8}


def _itto(_: float) -> float:
    """**Arataki Itto, C0, on his own Arataki Kesagiri Final Slash in Royal Descent** (his own
    doing): ATK + 103.68% of his DEF (burst 10), and A4's 35% of his DEF into the slash's base,
    both moving with every candidate's DEF.

    GO: `dmg('charged_akFinal', …, ownBuff.formula.base.add(a4KesagiriDmgInc))` with
    `a4KesagiriDmgInc = prod(percent(passive2.def_), own.premod.def)` (`pando AratakiItto.ts:
    65-67,115-120,165-173`); `ownBuff.premod.atk` = `burstCond.ifOn(prod(own.premod.def,
    talentSubscript(burst, defConv)))` (`:53-56,100-106,140`)."""
    stats = base._stats(ITTO_BASE, ITTO_ARTIFACTS)
    defense = base._total(stats, "def")
    atk = base._total(stats, "atk") + ITTO_BURST_10[1] * defense
    return _hit(stats, base_damage=ITTO_NORMAL_10[6] * atk, flat=0.35 * defense, channel="geo")


# ── Cyno ────────────────────────────────────────────────────────────────────────────────────

CYNO_BURST_LABELS = [
    "1-Hit DMG|{param1:F1P}", "2-Hit DMG|{param2:F1P}", "3-Hit DMG|{param3:F1P}",
    "4-Hit DMG|{param4:F1P}+{param5:F1P}", "5-Hit DMG|{param6:F1P}",
    "Charged Attack DMG|{param7:F1P}", "Charged Attack Stamina Cost|{param8:F1}",
    "Plunge DMG|{param9:F1P}", "Low/High Plunge DMG|{param10:P}/{param11:P}",
    "Elemental Mastery Bonus|{param12:I}", "Basic Duration|{param13:F1}s", "CD|{param14:F1}s",
    "Energy Cost|{param15:I}"]
CYNO_BURST_10 = [1.547459, 1.630198, 2.068339, 1.021861, 1.021861, 2.586465, 1.9975, 25.0,
                 1.26378, 2.527025, 3.15639, 100.0, 10.0, 20.0, 80.0]
CYNO_NA_1 = ("1-Hit DMG|{param1:F1P}", CYNO_BURST_10)
CYNO_BASE = base._base_stats(base_atk=926.0, base_hp=12491.0, base_def=859.0, crit_dmg=0.884)
CYNO_ARTIFACTS = {"elemental_mastery": 280.0, "atk_pct": 0.466, "flat_atk": 311.0,
                  "electro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}


def _cyno(_: float) -> float:
    """**Cyno, C0, on his own Pactsworn 1-Hit DMG** (a burst-talent row), in Pactsworn
    Pathclearer (his own doing): +100 Elemental Mastery (the burst row), and A4's 150% of his
    Elemental Mastery — the burst's 100 included — into the hit's base, per candidate.

    GO: `burstHit('burst_normal_0', …, 'normal', true)` adding `ownBuff.formula.base` =
    `prod(percent(passive2.burst_normal_dmgInc_), own.premod.eleMas)` (`pando Cyno.ts:83-87,
    134-141,177-190,234-236`); `ownBuff.premod.eleMas` = `afterBurst.ifOn(burst.eleMas)`
    (`:73,130,201`)."""
    stats = base._stats(CYNO_BASE, CYNO_ARTIFACTS)
    em = stats["elemental_mastery"] + CYNO_BURST_10[11]
    return _hit(stats, base_damage=CYNO_BURST_10[0] * base._total(stats, "atk"), flat=1.5 * em,
                channel="electro")


def batch5_fixtures() -> list[dict[str, Any]]:
    """Task 11, fifth batch: one fixture per sheet on its main self buff, and Yoimiya's team
    buff."""
    out: list[dict[str, Any]] = []
    fx = base._buffer

    out.append(fx(
        "hu_tao_a4_c2_on_her_own_blossom",
        "self flat damage from her own Max HP on one move (C2), per candidate; a situational "
        "self DMG buff (A4)",
        [FORMULA, f"{PANDO}HuTao.ts:70-76,116-126,150-151,165"],
        _subject("Hu Tao", 2),
        {"element": "pyro", "weapon_type": "WEAPON_POLE", "member_elements": ["pyro", "hydro"]},
        HU_TAO_BASE, HU_TAO_ARTIFACTS, "pyro",
        base._row("blossom", "Blood Blossom DMG", "skill", 1, HU_TAO_BLOSSOM, None),
        b4._kit("10000046", _own("Hu Tao", "10000046", 2, HU_TAO_BASE), subject=True),
        {"kit:hu_tao/low_hp": 1}, _hu_tao))

    out.append(fx(
        "arlecchino_masque_on_her_own_normal",
        "self flat damage from her own ATK per point of a user-set Bond of Life, counted per 100 "
        "(a talent row), per candidate; a passive held from the start (A0)",
        [FORMULA, f"{PANDO}Arlecchino.ts:45-49,79-83,119-129,168,181,188-199"],
        _subject("Arlecchino", 0, {"normal_attack": 10}),
        {"element": "pyro", "weapon_type": "WEAPON_POLE", "member_elements": ["pyro", "hydro"]},
        ARLE_BASE, ARLE_ARTIFACTS, "pyro",
        base._row("na1", "1-Hit DMG", "normal", 1, ARLE_NA_1, None),
        b4._kit("10000096", _own("Arlecchino", "10000096", 0, ARLE_BASE, {
            ("normal_attack", 10): (ARLE_NORMAL_LABELS, ARLE_NORMAL_10)}), subject=True),
        {"kit:arlecchino/bond": ARLE_BOND}, _arlecchino))

    out.append(fx(
        "clorinde_a4_c4_on_her_own_burst",
        "self CRIT Rate per stack (A4, at its default); burst DMG per point of a user-set Bond of "
        "Life (C4); over a five-hit row",
        [FORMULA, f"{PANDO}Clorinde.ts:68-74,85-88,147-156,185-186,204"],
        _subject("Clorinde", 4),
        {"element": "electro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["electro", "pyro"]},
        CLORINDE_BASE, CLORINDE_ARTIFACTS, "electro",
        base._row("burst", "Skill DMG", "burst", 5, CLORINDE_BURST, None),
        b4._kit("10000098", _own("Clorinde", "10000098", 4, CLORINDE_BASE), subject=True),
        {"kit:clorinde/bond": CLORINDE_BOND}, _clorinde))

    out.append(fx(
        "navia_a4_shrapnel_on_her_own_shardshot",
        "a self ATK buff counted by the team's elements, written as two gated effects (A4); "
        "Skill DMG per charge beyond three, a cited constant",
        [FORMULA, f"{PANDO}Navia.ts:51-53,70-72,100-132,167-168,183-192"],
        _subject("Navia", 0),
        {"element": "geo", "weapon_type": "WEAPON_CLAYMORE", "member_elements": NAVIA_TEAM},
        NAVIA_BASE, NAVIA_ARTIFACTS, "geo",
        base._row("shardshot", "Rosula Shardshot Base DMG", "skill", 1, NAVIA_SHARDSHOT, None),
        b4._kit("10000091", _own("Navia", "10000091", 0, NAVIA_BASE), subject=True,
                receiver_element="geo", team_elements=NAVIA_TEAM),
        {}, _navia))

    out.append(fx(
        "wriothesley_fist_a4_on_his_own_normal",
        "a talent row read as a hit's whole multiplier, written as a base multiplier less 1 "
        "(the skill); self ATK per stack (A4)",
        [FORMULA, f"{PANDO}Wriothesley.ts:44-45,63-66,126-130,170,192-203"],
        _subject("Wriothesley", 0, {"elemental_skill": 10}),
        {"element": "cryo", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["cryo", "hydro"]},
        WRIO_BASE, WRIO_ARTIFACTS, "cryo",
        base._row("na1", "1-Hit DMG", "normal", 1, WRIO_NA_1, None),
        b4._kit("10000086", _own("Wriothesley", "10000086", 0, WRIO_BASE, {
            ("elemental_skill", 10): (WRIO_SKILL_LABELS, WRIO_SKILL_10)}), subject=True),
        {}, _wriothesley))

    out.append(fx(
        "lyney_a1_a4_on_his_own_pyrotechnic",
        "self flat damage from his own ATK scoped to one of his rows (A1), per candidate; a DMG "
        "buff growing with the team's other Pyro members, as gated effects (A4)",
        [FORMULA, f"{PANDO}Lyney.ts:63-70,90,108-121,139,155-163"],
        _subject("Lyney", 0, {"elemental_skill": 10}),
        {"element": "pyro", "weapon_type": "WEAPON_BOW", "member_elements": LYNEY_TEAM},
        LYNEY_BASE, LYNEY_ARTIFACTS, "pyro",
        b4._with_hit(base._row("pyrotechnic", "Pyrotechnic Strike DMG", "charged", 1,
                               LYNEY_PYROTECHNIC, None),
                     "normal_attack", "Pyrotechnic Strike DMG"),
        b4._kit("10000084", _own("Lyney", "10000084", 0, LYNEY_BASE, {
            ("elemental_skill", 10): (LYNEY_SKILL_LABELS, LYNEY_SKILL_10)}), subject=True,
                receiver_element="pyro", team_elements=LYNEY_TEAM),
        {}, _lyney))

    out.append(fx(
        "yoimiya_niwabi_a1_on_her_own_normal",
        "a talent row read as a hit's whole multiplier (the skill, a base multiplier less 1); a "
        "self DMG buff per stack (A1); over a two-arrow row",
        [FORMULA, f"{PANDO}Yoimiya.ts:42-46,54-58,95-101,131,135-142"],
        _subject("Yoimiya", 0, {"elemental_skill": 10}),
        {"element": "pyro", "weapon_type": "WEAPON_BOW", "member_elements": ["pyro", "hydro"]},
        YOIMIYA_BASE, YOIMIYA_ARTIFACTS, "pyro",
        base._row("na1", "1-Hit DMG", "normal", 2, YOIMIYA_NA_1, None),
        b4._kit("10000049", _own("Yoimiya", "10000049", 0, YOIMIYA_BASE, {
            ("elemental_skill", 10): (YOIMIYA_SKILL_LABELS, YOIMIYA_SKILL_10)}), subject=True),
        {}, _yoimiya))

    out.append(fx(
        "yoimiya_a4_on_xiangling",
        "a teammate ATK buff with a fixed part and a part per the giver's own stack count (A4)",
        [FORMULA, f"{PANDO}Yoimiya.ts:54-63,93,102-111,133"],
        {"name": "Yoimiya", "constellation": 0, "ascension_phase": 6, "stats": {}},
        {"element": "pyro", "weapon_type": "WEAPON_POLE", "member_elements": ["pyro", "pyro"]},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro",
        base._row("nado", "Pyronado DMG", "burst", 1, base.PYRONADO, None),
        b4._kit("10000049", _own("Yoimiya", "10000049", 0, {}), subject=False,
                receiver_element="pyro", team_elements=["pyro", "pyro"]),
        {"kit:yoimiya/aurous": 1}, _yoimiya_on_xiangling))

    out.append(fx(
        "ganyu_a1_a4_on_her_own_bloom",
        "a self CRIT Rate scoped by move (A1); a field DMG buff to the active character, hers as "
        "the subject (A4)",
        [FORMULA, f"{PANDO}Ganyu.ts:61-67,83-89,102,127-135"],
        _subject("Ganyu", 0),
        {"element": "cryo", "weapon_type": "WEAPON_BOW", "member_elements": ["cryo", "hydro"]},
        GANYU_BASE, GANYU_ARTIFACTS, "cryo",
        base._row("bloom", "Frostflake Arrow Bloom DMG", "charged", 1, GANYU_BLOOM, None),
        b4._kit("10000037", _own("Ganyu", "10000037", 0, GANYU_BASE), subject=True),
        {}, _ganyu))

    out.append(fx(
        "eula_lightfall_on_her_own_sword",
        "self flat damage from her own ATK per stack scoped to one of her rows (a talent row), "
        "per candidate; a Physical RES decrease from her own skill row",
        [FORMULA, f"{PANDO}Eula.ts:47-69,100-102,109-115,128,142-149"],
        _subject("Eula", 0, {"elemental_burst": 10, "elemental_skill": 10}),
        {"element": "cryo", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["cryo", "electro"]},
        EULA_BASE, EULA_ARTIFACTS, "physical",
        b4._with_hit(base._row("lightfall", "Lightfall Sword Base DMG", "burst", 1,
                               EULA_LIGHTFALL, None),
                     "elemental_burst", "Lightfall Sword Base DMG"),
        b4._kit("10000051", _own("Eula", "10000051", 0, EULA_BASE, {
            ("elemental_burst", 10): (EULA_BURST_LABELS, EULA_BURST_10),
            ("elemental_skill", 10): (EULA_SKILL_LABELS, EULA_SKILL_10)}), subject=True),
        {}, _eula))

    out.append(fx(
        "itto_burst_a4_on_his_own_kesagiri",
        "self ATK from his own DEF (a talent row) and self flat damage from his own DEF scoped to "
        "one of his rows (A4), both per candidate, on one hit",
        [FORMULA, f"{PANDO}AratakiItto.ts:53-56,65-67,100-106,115-120,140,165-173"],
        _subject("Arataki Itto", 0, {"elemental_burst": 10}),
        {"element": "geo", "weapon_type": "WEAPON_CLAYMORE", "member_elements": ["geo", "geo"]},
        ITTO_BASE, ITTO_ARTIFACTS, "geo",
        b4._with_hit(base._row("final", "Arataki Kesagiri Final Slash DMG", "charged", 1,
                               ITTO_FINAL, None),
                     "normal_attack", "Arataki Kesagiri Final Slash DMG"),
        b4._kit("10000057", _own("Arataki Itto", "10000057", 0, ITTO_BASE, {
            ("elemental_burst", 10): (ITTO_BURST_LABELS, ITTO_BURST_10)}), subject=True),
        {}, _itto))

    out.append(fx(
        "cyno_burst_a4_on_his_own_pactsworn_normal",
        "a self EM buff from a talent row, read by self flat damage from his own EM scoped to his "
        "burst-talent Normal Attack rows (A4), per candidate",
        [FORMULA, f"{PANDO}Cyno.ts:73,83-87,130,134-141,177-190,201,234-236"],
        _subject("Cyno", 0, {"elemental_burst": 10}),
        {"element": "electro", "weapon_type": "WEAPON_POLE",
         "member_elements": ["electro", "dendro"]},
        CYNO_BASE, CYNO_ARTIFACTS, "electro",
        b4._with_hit(base._row("na1", "1-Hit DMG", "normal", 1, CYNO_NA_1, None),
                     "elemental_burst", "1-Hit DMG"),
        b4._kit("10000071", _own("Cyno", "10000071", 0, CYNO_BASE, {
            ("elemental_burst", 10): (CYNO_BURST_LABELS, CYNO_BURST_10)}), subject=True),
        {}, _cyno))
    return out
