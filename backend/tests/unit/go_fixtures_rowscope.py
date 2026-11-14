"""Row-scoped kit buffs and per-row moves (owner ruling 2026-11-14, `DECISIONS.md` §40 (iv)):
GO fixtures.

Kept beside `test_go_formula_fixtures.py` as the batch modules are, and imported by its
`build()`. The method is unchanged: each figure is worked by hand from Genshin Optimizer's formula
at `2c13fc40` with **our** numbers — talent rows verbatim from the seeded catalogue (nanoka
7.2.51, level 10 unless said), constellation and passive lists the sheets' pins, stated builds.

Every row here **names its talent row** (`hit`), because each fixture's buff reaches that row
alone, as GO's does: `npm run formula:verify` checks that the figure misses when the row is left
unnamed. Each states every condition it reads (`_states_every_condition`).

Nothing here is a test by itself; its fixtures are checked by `test_go_formula_fixtures.py` and
`test_formula_sheets_rowscope.py`, and by `npm run formula:verify`.
"""

from __future__ import annotations

from typing import Any

from app.formula.genshin import sheets
from tests.unit import go_fixtures_batch4 as b4
from tests.unit import test_go_formula_fixtures as base

FORMULA = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
PANDO = "libs/gi/formula/src/data/char/"
NONE = "none: no reaction"


def _subject(name: str, constellation: int, talent_levels: dict[str, int] | None = None,
             ) -> dict[str, Any]:
    giver: dict[str, Any] = {"name": name, "constellation": constellation, "ascension_phase": 6}
    if talent_levels:
        giver["talent_levels"] = talent_levels
    giver["stats"] = "the optimized character"
    return giver


# ── Skirk: a Seven-Phase Flash attack, a skill-talent row dealt as a Normal Attack ───────────

#: Her seeded skill row at 10: the Seven-Phase Flash 1-Hit DMG.
SKIRK_FLASH_1 = ("1-Hit DMG|{param1:F1P}", [2.625599])


def _skirk_flash(_: float) -> float:
    """**Skirk, C2, on her own Seven-Phase Flash 1-Hit DMG**: three Void Rifts absorbed (the
    burst row's 20%, GO `premod.dmg_.normal`), three A4 stacks (×1.7, the Seven-Phase Flash
    normal attacks only) and C2's 70% ATK after her burst (her ordinary attacks and her burst
    have it removed in GO, so it reaches only these rows).

    GO: `skillHit('skill_0', …, 'normal', a4DeathStacks_skillNormal_mult_)` = `prod(talent,
    final.atk, 1 + subscript(stacks, [0, …passive2.normal_mult_]))` (`pando Skirk.ts:146-151,
    246-262,298-302`); `ownBuff.premod.atk_.add(c2_atk_)` (`:192-195,287`, inverted in
    `autoHit`/`burstHit`, `:223-243,264-274`); `ownBuff.premod.dmg_.normal.add(void)`
    (`:173-190,289`)."""
    stats = base._stats(base.SKIRK_BASE, base.SKIRK_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=0.7)
    return base._go_general(base=base._multiplier(SKIRK_FLASH_1) * atk * (1 + 0.7), flat=0.0,
                            dmg_bonus=stats["cryo_dmg_bonus"] + 0.2,
                            crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


# ── Mavuika: a Flamestrider Normal Attack, its Fighting Spirit bonus and C2's ────────────────

#: Her seeded skill row at 10: the Flamestrider Normal Attack 1-Hit DMG.
MAVUIKA_FLAME_1 = ("Flamestrider Normal Attack 1-Hit DMG|{param4:F1P}",
                   [1.3392, 2.304, 2.0, 1.131979])


def _mavuika_flame(_: float) -> float:
    """**Mavuika, C2, on her own Flamestrider Normal Attack 1-Hit DMG**, in Flamestrider form at
    200 Fighting Spirit: the burst row's 0.51% ATK per point and C2's 60% ATK as flat damage on
    the Flamestrider normal attacks alone; A1's and C1's ATK, C2's base ATK, A4's DMG at 200.

    GO: `customDmg('skill_normal_0', 'pyro', 'normal', prod(talent, final.atk), undefined,
    flameNormalBase)` (`pando Mavuika.ts:258-268`), `flameNormalBase = formula.base.add(sum(
    prod(final.atk, burst row, spirit), c2FlameForm prod(final.atk, constellation2[2])))`
    (`:137-141,185-191,217-219`); base ATK, ATK% and A4 as in `mavuika_c2_on_her_own_burst`."""
    stats = base._stats(base.MAVUIKA_BASE, base.MAVUIKA_ARTIFACTS)
    atk = (base.MAVUIKA_BASE["base_atk"] + 200.0) * (1 + stats["atk_pct"] + 0.3 + 0.4) \
        + stats["flat_atk"]
    return base._go_general(base=base._multiplier(MAVUIKA_FLAME_1) * atk,
                            flat=(200 * 0.0051 + 0.6) * atk,
                            dmg_bonus=stats["pyro_dmg_bonus"] + 200 * 0.002,
                            crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


# ── Linnea: Lumi's Million Ton Crush and its C2 CRIT DMG ─────────────────────────────────────

#: Her seeded skill row at 10 (C2, so no C3 boost).
LINNEA_CRUSH = ("Lumi Million Ton Crush DMG|{param3:F1P} DEF", [1.728, 1.8, 7.2])


def _linnea_crush(_: float) -> float:
    """**Linnea, C2, on Lumi's Million Ton Crush** in Moondrift with Lumi present: C2's 150% CRIT
    DMG on that hit alone, beside its 40% to a Geo party member (her), and A1's Geo RES -15%.
    GO's C1 Lunar-Crystallize terms on the hit are zero at its default of no stacks.

    GO: `customDmg('skill_crushDmg', ele, 'skill', prod(final.def, talent), undefined, …,
    ownBuff.premod.critDMG_.add(c2Lumi_critDMG_))` (`pando Linnea.ts:280-290`), `c2Lumi =
    c2Moondrift.ifOn(constellation2[2])` (`:84-88,209-211`); C2's party CRIT DMG (`:199-208,
    252`); A1 (`:121-132,255`)."""
    stats = base._stats(base.LINNEA_BASE, base.LINNEA_ARTIFACTS)
    return base._go_general(base=base._multiplier(LINNEA_CRUSH) * base._total(stats, "def"),
                            flat=0.0, dmg_bonus=stats["geo_dmg_bonus"],
                            crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"] + 0.4 + 1.5,
                            res_shred=-0.15)


# ── Valeriy: the Thunderburst Shell and C6 ──────────────────────────────────────────────────

VALERIY_SHELL = ("Thunderburst Shell DMG|{param2:F1P}", [2.43216, 0.56736])


def _valeriy_shell(_: float) -> float:
    """**Valeriy, C6, on his own Thunderburst Shell**, no Offensive Directive consumed: C6's
    Thunderburst Shell DMG +100%, on that row alone.

    GO WR: `shellDmg: dmgNode('atk', dm.burst.shellDmg, 'burst', {premod: {burst_dmg_:
    c6_shell_dmg_}})` (`Valeriy/index.tsx:101-105,233,271-273`)."""
    stats = base._stats(base.VALERIY_BASE, base.VALERIY_ARTIFACTS)
    return base._go_general(base=base._multiplier(VALERIY_SHELL) * base._total(stats, "atk"),
                            flat=0.0, dmg_bonus=stats["electro_dmg_bonus"] + 1.0,
                            crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


# ── Xiangling: C6 on her own third swing, the one burst row GO leaves it on ──────────────────

XIANGLING_SWING_3 = ("3-Hit Swing DMG|{param3:P}", [1.296, 1.584, 1.9728])


def _xiangling_swing(_: float) -> float:
    """**Xiangling, C6, on her own Pyronado 3-Hit Swing** during Pyronado: C6's 15% Pyro DMG,
    which GO's `antiC6` takes back from the 1-hit and 2-hit swings and the spin, not this one.

    GO: `dmg('burst_dmg3', info, 'atk', dm.burst.dmg3, 'burst')` with no `antiC6` (`pando
    Xiangling.ts:97-98,128-150`); `teamBuff.premod.dmg_.pyro` C6 (`:73-74,94-96,109`)."""
    atk = (base.XIANGLING_BASE["base_atk"] * (1 + base.XIANGLING_ARTIFACTS["atk_pct"])
           + base.XIANGLING_ARTIFACTS["flat_atk"])
    return base._go_general(base=base._multiplier(XIANGLING_SWING_3) * atk, flat=0.0,
                            dmg_bonus=base.XIANGLING_ARTIFACTS["pyro_dmg_bonus"] + 0.15,
                            crit_rate=base.XIANGLING_BASE["crit_rate"]
                            + base.XIANGLING_ARTIFACTS["crit_rate"],
                            crit_dmg=base.XIANGLING_BASE["crit_dmg"]
                            + base.XIANGLING_ARTIFACTS["crit_dmg"])


# ── Lohen: C6's CRIT DMG on the Etched hit ──────────────────────────────────────────────────

#: His seeded skill row at 10 (param17 is the Etched hit's 108%).
LOHEN_ETCH = ("Etched Into Bone and Soul DMG|{param17:F1P}\u00d74",
              [1.600915, 1.67359, 0.753729, 2.230536, 1.092879, 1.639319, 1.9533, 10.0,
               1.26378, 2.527025, 3.15639, 13.0, 17.0, 17.0, 10.0, 20.0, 1.08])
LOHEN_BASE = base._base_stats(base_atk=900.0, base_hp=12500.0, base_def=800.0, crit_dmg=0.884)
LOHEN_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "cryo_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 0.6}


def _lohen_etch(_: float) -> float:
    """**Lohen, C6, on his own Etched Into Bone and Soul hit**, no Will to Win consumed (GO's
    default, so its base multiplier is 1): C6's 175% CRIT DMG on that hit alone.

    GO: `dmg('skill_etchDmg', info, 'atk', dm.skill.etchDmg, 'skill', {baseMulti: 1 + will *
    …}, ownBuff.premod.critDMG_.add(c6Etch_critDMG_))` (`pando Lohen.ts:112-115,146-149,
    168-172,223-231`). One hit: the row's `×4` is its count."""
    stats = base._stats(LOHEN_BASE, LOHEN_ARTIFACTS)
    return base._go_general(base=base._multiplier(LOHEN_ETCH) * base._total(stats, "atk"),
                            flat=0.0, dmg_bonus=stats["cryo_dmg_bonus"],
                            crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"] + 1.75)


# ── Vodyanitsa's A4: flat damage from her Max HP above a threshold, capped (§40 (vi)) ────────

#: A stated base for her HP-stacked builds; the skill row is the seeded one at 10.
VODYANITSA_HP_BASE = base._base_stats(base_atk=520.0, base_hp=15000.0, hp_pct=0.24,
                                      base_def=455.0)
VODYANITSA_BELOW = {"hp_pct": 2.0, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466,
                    "crit_rate": 0.3, "crit_dmg": 0.8}
VODYANITSA_PAST = {"hp_pct": 3.2, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 0.8}
#: Her seeded A4 list: `[2]` the 40,000 threshold, `[4]` 140 per 1,000 HP, `[6]` the 3,500 cap.
VODYANITSA_A4 = (40000.0, 140.0, 3500.0)
#: Her pass-1 HP as a teammate's giver: 15,000 × (1 + 0.24 + 2.6) + 4,780 = 62,380.
VODYANITSA_GIVER = {**VODYANITSA_HP_BASE, "hp_pct": 0.24 + 2.6, "flat_hp": 4780.0}


def _dirge(hp: float) -> float:
    """GO `a4HydrocryoDmgInc` = `min(max(prod(sum(final.hp, -hpThresh), 1 / 1000,
    hydrocryo_dmgInc), 0), maxHydrocryo_dmgInc)` (`pando Vodyanitsa.ts:134-145`)."""
    threshold, per, cap = VODYANITSA_A4
    return min(max((hp - threshold) / 1000 * per, 0.0), cap)


def _vodyanitsa_skill(artifacts: dict[str, float]) -> float:
    """**Vodyanitsa, C0, on her own Skill DMG** as Lead Vocal: her A4's flat Hydro damage from
    her own Max HP, per candidate, through its threshold and cap.

    GO: `dmg('skill', info, 'hp', dm.skill.skillDmg, 'skill')` (`pando Vodyanitsa.ts:307`);
    `teamBuff.formula.base.hydro.add(a4LeadVocal × destIsActive × a4HydrocryoDmgInc)`
    (`:161-163,178-182,281-283`)."""
    stats = base._stats(VODYANITSA_HP_BASE, artifacts)
    hp = base._total(stats, "hp")
    return base._go_general(base=base._multiplier(base.VODYANITSA_SKILL) * hp, flat=_dirge(hp),
                            dmg_bonus=stats["hydro_dmg_bonus"], crit_rate=stats["crit_rate"],
                            crit_dmg=stats["crit_dmg"])


def _vodyanitsa_on_skirk(_: float) -> float:
    """**Vodyanitsa's A4 on Skirk's Final Slash**, Skirk the active character and Vodyanitsa
    Lead Vocal: a number from Vodyanitsa's own pass-1 HP (62,380: 22.38 × 140 = 3,133.2, below
    the 3,500 cap), into Skirk's Cryo hit's base. Skirk's own kit is not a source here."""
    stats = base._stats(base.SKIRK_BASE, base.SKIRK_ARTIFACTS)
    giver_hp = base._total(VODYANITSA_GIVER, "hp")
    return base._go_general(base=base._multiplier(base.SKIRK_FINAL) * base._total(stats, "atk"),
                            flat=_dirge(giver_hp), dmg_bonus=stats["cryo_dmg_bonus"],
                            crit_rate=stats["crit_rate"], crit_dmg=stats["crit_dmg"])


def _vodyanitsa_fixture(name: str, state: str, artifacts: dict[str, float]) -> dict[str, Any]:
    cons, pas = base._pinned("10000140")
    out = base._buffer(
        name,
        "flat damage from her own Max HP above a threshold, capped, per candidate "
        f"({state} its cap)",
        [FORMULA, f"{PANDO}Vodyanitsa.ts:73-80,134-145,161-163,178-182,281-283,307"],
        _subject("Vodyanitsa", 0, {"elemental_skill": 10}),
        {"element": "hydro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["hydro", "cryo"]},
        VODYANITSA_HP_BASE, artifacts, "hydro",
        base._row("skill", "Skill DMG", "skill", 1, base.VODYANITSA_SKILL, None),
        base._kit_source("10000140", base._ungated_giver(
            "Vodyanitsa", "10000140", talent_levels={"elemental_skill": 10},
            talent_rows={("elemental_skill", 10): sheets.TalentRow(
                base.VODYANITSA_SKILL_LABELS, base.VODYANITSA_SKILL_10)},
            cons=cons, passives=pas, stats=VODYANITSA_HP_BASE), subject=True),
        {"kit:vodyanitsa/skill_hit": 0, "kit:vodyanitsa/a1_vortex": 0,
         "kit:vodyanitsa/a4_lead_vocal": 1},
        lambda _: _vodyanitsa_skill(artifacts))
    return {**out, "cap_state": state}


def vodyanitsa_fixtures() -> list[dict[str, Any]]:
    """Her A4 below its cap and past it on herself, and as a teammate's number."""
    cons, pas = base._pinned("10000140")
    return [
        _vodyanitsa_fixture("vodyanitsa_a4_below_cap_on_her_own_skill", "below",
                            VODYANITSA_BELOW),
        _vodyanitsa_fixture("vodyanitsa_a4_past_cap_on_her_own_skill", "past", VODYANITSA_PAST),
        base._buffer(
            "vodyanitsa_a4_on_skirks_final_slash",
            "a teammate's flat damage from her own Max HP above a threshold, capped: a number "
            "from her pass-1 HP",
            [FORMULA, f"{PANDO}Vodyanitsa.ts:73-80,134-145,161-163,178-182,281-286",
             f"{PANDO}Skirk.ts:265-278,308"],
            {"name": "Vodyanitsa", "constellation": 0, "ascension_phase": 6,
             "stats": VODYANITSA_GIVER},
            {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
             "member_elements": ["cryo", "hydro"]},
            base.SKIRK_BASE, base.SKIRK_ARTIFACTS, "cryo",
            base._row("final", "Final Slash DMG", "burst", 1, base.SKIRK_FINAL, None),
            base._kit_source("10000140", base._ungated_giver(
                "Vodyanitsa", "10000140", cons=cons, passives=pas, stats=VODYANITSA_GIVER),
                subject=False),
            {"kit:vodyanitsa/a1_vortex": 0, "kit:vodyanitsa/a4_lead_vocal": 1},
            _vodyanitsa_on_skirk),
    ]


def rowscope_fixtures() -> list[dict[str, Any]]:
    """One fixture per sheet that gained a row-scoped buff (§40 (iv))."""
    out: list[dict[str, Any]] = []

    cons, pas = base._pinned("10000114")
    out.append(base._buffer(
        "skirk_a4_c2_void_on_her_own_seven_phase_flash",
        "a skill-talent row dealt as a Normal Attack (its move from the sheet); A4's base "
        "multiplier and C2's ATK scoped to the Seven-Phase Flash rows, the Void Rift bonus by "
        "move",
        [FORMULA, f"{PANDO}Skirk.ts:146-151,173-195,223-262,287-302"],
        _subject("Skirk", 2, {"elemental_burst": 10}),
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "hydro", "hydro", "cryo"]},
        base.SKIRK_BASE, base.SKIRK_ARTIFACTS, "cryo",
        b4._with_hit(base._row("flash_1", "1-Hit DMG", "normal", 1, SKIRK_FLASH_1, None),
                     "elemental_skill", "1-Hit DMG"),
        base._kit_source("10000114", base._ungated_giver(
            "Skirk", "10000114", constellation=2, talent_levels={"elemental_burst": 10},
            talent_rows={("elemental_burst", 10): sheets.TalentRow(base.SKIRK_BURST_LABELS,
                                                                   base.SKIRK_BURST_10)},
            cons=cons, passives=pas, stats=base.SKIRK_BASE), subject=True),
        {"kit:skirk/serpent_over": 12, "kit:skirk/void_rifts": "3", "kit:skirk/a4_stacks": 3,
         "kit:skirk/c2_after_burst": 1},
        _skirk_flash))

    cons, pas = base._pinned("10000106")
    out.append(base._buffer(
        "mavuika_flamestrider_on_her_own_normal",
        "flat damage from her own ATK per Fighting Spirit (a burst row) and from C2, scoped to "
        "the Flamestrider Normal Attack rows of her skill talent",
        [FORMULA, f"{PANDO}Mavuika.ts:67,78-96,125-176,185-191,217-219,231-242,258-268"],
        _subject("Mavuika", 2, {"elemental_burst": 10}),
        {"element": "pyro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["pyro", "pyro", "cryo", "anemo"]},
        base.MAVUIKA_BASE, base.MAVUIKA_ARTIFACTS, "pyro",
        b4._with_hit(base._row("flame_1", "Flamestrider Normal Attack 1-Hit DMG", "normal", 1,
                               MAVUIKA_FLAME_1, None),
                     "elemental_skill", "Flamestrider Normal Attack 1-Hit DMG"),
        base._kit_source("10000106", base._ungated_giver(
            "Mavuika", "10000106", constellation=2, talent_levels={"elemental_burst": 10},
            talent_rows={("elemental_burst", 10): sheets.TalentRow(base.MAVUIKA_BURST_LABELS,
                                                                   base.MAVUIKA_BURST_10)},
            cons=cons, passives=pas, stats=base.MAVUIKA_BASE), subject=True),
        {"kit:mavuika/fighting_spirit": 200, "kit:mavuika/a1_nightsoul_burst": 1,
         "kit:mavuika/a4_after_burst": 1, "kit:mavuika/c1_gain_spirit": 1,
         "kit:mavuika/c2_form": 1, "kit:mavuika/c2_flamestrider": 1},
        _mavuika_flame))

    cons, pas = base._pinned("10000130")
    out.append(base._buffer(
        "linnea_c2_on_lumis_million_ton_crush",
        "a CRIT DMG buff scoped to one talent row (C2 on Million Ton Crush), beside the same "
        "constellation's party buff",
        [FORMULA, f"{PANDO}Linnea.ts:84-88,121-132,199-211,252,255,280-290"],
        _subject("Linnea", 2),
        {"element": "geo", "weapon_type": "WEAPON_BOW", "member_elements": ["geo", "hydro"]},
        base.LINNEA_BASE, base.LINNEA_ARTIFACTS, "geo",
        b4._with_hit(base._row("crush", "Lumi Million Ton Crush DMG", "skill", 1, LINNEA_CRUSH,
                               None),
                     "elemental_skill", "Lumi Million Ton Crush DMG"),
        base._kit_source("10000130", base._ungated_giver(
            "Linnea", "10000130", constellation=2, cons=cons, passives=pas,
            stats=base.LINNEA_BASE), subject=True, receiver_element="geo",
            team_elements=["geo", "hydro"]),
        {"kit:linnea/lumi_present": 1, "kit:linnea/moonsign_gleam": 0,
         "kit:linnea/subject_moonsign": 0, "kit:linnea/c2_moondrift": 1},
        _linnea_crush))

    cons, pas = base._pinned("10000137")
    out.append(base._buffer(
        "valeriy_c6_on_his_own_shell",
        "a DMG buff scoped to one burst row (C6 on the Thunderburst Shell)",
        [FORMULA, "libs/gi/sheets/src/Characters/Valeriy/index.tsx:101-105,233,271-273"],
        _subject("Valeriy", 6),
        {"element": "electro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["electro", "pyro"]},
        base.VALERIY_BASE, base.VALERIY_ARTIFACTS, "electro",
        b4._with_hit(base._row("shell", "Thunderburst Shell DMG", "burst", 1, VALERIY_SHELL,
                               None),
                     "elemental_burst", "Thunderburst Shell DMG"),
        base._kit_source("10000137", base._ungated_giver(
            "Valeriy", "10000137", constellation=6, cons=cons, passives=pas,
            stats=base.VALERIY_BASE), subject=True),
        {"kit:valeriy/charged_offensive": 0, "kit:valeriy/stellar_radiance": 0,
         "kit:valeriy/momentum": 0, "kit:valeriy/c2_skill": 0, "kit:valeriy/c6_hit": 0},
        _valeriy_shell))

    cons, pas = base._pinned("10000023")
    out.append(base._buffer(
        "xiangling_c6_on_her_own_third_swing",
        "a constellation's self buff on the one burst row GO does not take it back from",
        [FORMULA, f"{PANDO}Xiangling.ts:73-74,94-98,109,113-150"],
        _subject("Xiangling", 6),
        {"element": "pyro", "weapon_type": "WEAPON_POLE",
         "member_elements": ["pyro", "hydro", "cryo"]},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro",
        b4._with_hit(base._row("swing_3", "3-Hit Swing DMG", "burst", 1, XIANGLING_SWING_3,
                               None),
                     "elemental_burst", "3-Hit Swing DMG"),
        base._kit_source("10000023", base._ungated_giver(
            "Xiangling", "10000023", constellation=6, cons=cons, passives=pas,
            stats=base.XIANGLING_BASE), subject=True),
        {"kit:xiangling/after_chili": 0, "kit:xiangling/after_guoba_hit": 0,
         "kit:xiangling/pyronado": 1},
        _xiangling_swing))

    cons, pas = base._pinned("10000129")
    out.append(base._buffer(
        "lohen_c6_on_his_own_etch",
        "a CRIT DMG buff scoped to one skill row (C6 on the Etched hit), beside skill-talent "
        "rows dealt as Normal Attacks",
        [FORMULA, f"{PANDO}Lohen.ts:112-115,146-149,168-172,218-231"],
        _subject("Lohen", 6),
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "hydro"]},
        LOHEN_BASE, LOHEN_ARTIFACTS, "cryo",
        b4._with_hit(base._row("etch", "Etched Into Bone and Soul DMG", "skill", 1, LOHEN_ETCH,
                               None),
                     "elemental_skill", "Etched Into Bone and Soul DMG"),
        base._kit_source("10000129", base._ungated_giver(
            "Lohen", "10000129", constellation=6, cons=cons, passives=pas, stats=LOHEN_BASE),
            subject=True),
        {"kit:lohen/a4_master_cryo": 0, "kit:lohen/c2_blade": 0,
         "kit:lohen/c6_burst_master": 0},
        _lohen_etch))
    return out
