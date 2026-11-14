"""Capped self-conversions (owner ruling 2026-11-14, `DECISIONS.md` §40): GO fixtures.

Kept beside `test_go_formula_fixtures.py` as the batch modules are, and imported by its
`build()`. The method is unchanged: each figure is worked by hand from Genshin Optimizer's formula
at `2c13fc40` with **our** numbers — talent rows verbatim from the seeded catalogue (nanoka
7.2.51, level 10 unless said), constellation and passive lists the sheets' pins, stated builds.

**Every capped conversion has a build below its cap and one past it** (`cap_state`), and
`npm run formula:verify` holds both ways: ignoring the cap must fail the past-cap figure and
leave the below-cap one alone, and freezing the stat at the zero-artifact build must fail both.
Alhaitham and Tighnari, whose sheets are new here, also have a teammate fixture for their team
buff, into Xiangling's reverse-vaporized Pyronado (so the 2.78 / 25/9 EM gap applies there).

Nothing here is a test by itself; its fixtures are checked by `test_go_formula_fixtures.py` and
`test_formula_sheets_capped.py`, and by `npm run formula:verify`.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch4 as b4
from tests.unit import go_fixtures_batch5 as b5
from tests.unit import test_go_formula_fixtures as base

FORMULA = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
AMP = "libs/gi/wr/src/formula.ts:257,357,434-484"
PANDO = "libs/gi/formula/src/data/char/"
EM_GAP = "amplifying EM coefficient: 2.78 (gcsim, ours) against GO's 25/9"


def _capped(fixture: dict[str, Any], state: str) -> dict[str, Any]:
    return {**fixture, "cap_state": state}


# ── Hu Tao: ATK from her Max HP, capped at 400% of her base ATK ──────────────────────────────

#: Her skill row at 10 is `go_fixtures_batch5.HU_TAO_SKILL_10`. An HP-stacked build: HP
#: sands, goblet and circlet, and HP% substats.
HU_TAO_HP_STACKED = {"hp_pct": 1.998, "flat_hp": 4780.0, "flat_atk": 311.0,
                     "crit_rate": 0.3, "crit_dmg": 0.6}


def _hu_tao_paramita(artifacts: dict[str, float]) -> float:
    stats = base._stats(b5.HU_TAO_BASE, artifacts)
    hp = base._total(stats, "hp")
    atk = base._total(stats, "atk") + min(b5.HU_TAO_SKILL_10[1] * hp,
                                          b5.HU_TAO_SKILL_10[6] * b5.HU_TAO_BASE["base_atk"])
    return b5._hit(stats, base_damage=base._multiplier(b5.HU_TAO_BLOSSOM) * atk, channel="pyro")


def _hu_tao_below(_: float) -> float:
    """**Hu Tao, C0, on her own Blood Blossom in Paramita Papilio** (her own doing, the default):
    6.256% of 27,579 HP is 1,725 ATK, below the cap of 4 × 715 = 2,860.

    GO: `ownBuff.premod.atk.add(skillAtkFromHp)`, `skillAtkFromHp = ifOn(min(prod(percent(
    atkInc), own.premod.hp), prod(percent(maxAtkInc), own.base.atk)))` (`pando HuTao.ts:48-56,
    103-112,144`); the hit `dmg('skill', info, 'atk', dm.skill.dmg, 'skill')` (`:165`)."""
    return _hu_tao_paramita(b5.HU_TAO_ARTIFACTS)


def _hu_tao_past(_: float) -> float:
    """**Hu Tao, C0, HP-stacked, on her own Blood Blossom in Paramita Papilio**: 6.256% of
    51,405 HP would be 3,216 ATK; the cap gives 2,860. Same GO lines as `_hu_tao_below`."""
    return _hu_tao_paramita(HU_TAO_HP_STACKED)


# ── Clorinde: A1 flat damage from her ATK per stack, the total capped ───────────────────────

#: A heavily ATK-buffed build, so that C2's 30% × 3 stacks of her ATK passes its 2,700 cap.
CLORINDE_ATK_STACKED = {"atk_pct": 1.7, "flat_atk": 311.0, "electro_dmg_bonus": 0.466,
                        "crit_rate": 0.3, "crit_dmg": 0.8}


def _clorinde_a1(artifacts: dict[str, float], *, ratio: float, cap: float) -> float:
    stats = base._stats(b5.CLORINDE_BASE, artifacts)
    atk = base._total(stats, "atk")
    one = b5._hit(stats, base_damage=base._multiplier(b5.CLORINDE_BURST) * atk,
                  flat=min(ratio * atk * 3, cap), channel="electro", extra_cr=2 * 0.1)
    return 5 * one


def _clorinde_below(_: float) -> float:
    """**Clorinde, C0, on her own Last Lightfall** (five hits), three A1 stacks (set by the user:
    the party's Electro reactions are situational) and A4's two stacks (her own, the default):
    20% × 3 of 1,790 ATK is 1,074 flat damage per hit, below A1's 1,800.

    GO: `ownBuff.formula.base.burst.add(a1DmgInc)`, `a1DmgInc = cmpGE(ascension, 1, min(
    a1MaxDmgInc, prod(a1AtkRatio, final.atk, a1Reactions)))`, the ratio and cap `cmpGE(
    constellation, 2, c2, a1)` (`pando Clorinde.ts:62-67,81-84,129-146,184`); A4 `:68-74,147-151,
    185`; the hit `:204`."""
    return _clorinde_a1(b5.CLORINDE_ARTIFACTS, ratio=0.2, cap=1800.0)


def _clorinde_past(_: float) -> float:
    """**Clorinde, C2, ATK-stacked, on her own Last Lightfall**, three A1 stacks: C2's 30% × 3 of
    3,035 ATK would be 2,732 per hit; C2's cap gives 2,700. Same GO lines as `_clorinde_below`.
    C2 also replaces A1's numbers, never adds to them (`cmpGE(constellation, 2, c2, a1)`)."""
    return _clorinde_a1(CLORINDE_ATK_STACKED, ratio=0.3, cap=2700.0)


# ── Nahida: A4, DMG% and CRIT Rate from EM above 200, at most 800 counted ────────────────────

#: Her seeded skill row at 10: Tri-Karma is `param3` ATK + `param4` EM.
TRI_KARMA_10 = ("Tri-Karma Purification DMG|{param3:F1P} ATK+{param4:F1P} Elemental Mastery",
                [1.7712, 2.3472, 1.8576, 3.7152])
NAHIDA_EM_LOW = {"elemental_mastery": 487.0, "atk_pct": 0.466, "flat_atk": 311.0,
                 "dendro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}
NAHIDA_EM_HIGH = {"elemental_mastery": 1000.0, "flat_atk": 311.0, "crit_rate": 0.3,
                  "crit_dmg": 0.6}
#: No Pyro member, so her burst's Tri-Karma bonus (a count of Pyro members) is 0.
NAHIDA_TEAM = ["dendro", "hydro", "electro"]


def _nahida_a4(artifacts: dict[str, float]) -> float:
    stats = base._stats(b4.NAHIDA_BASE, artifacts)
    em = stats["elemental_mastery"]
    counted = min(max(em - 200.0, 0.0), 800.0)
    return b5._hit(stats, base_damage=TRI_KARMA_10[1][2] * base._total(stats, "atk")
                   + TRI_KARMA_10[1][3] * em, channel="dendro",
                   extra_dmg=0.001 * counted, extra_cr=0.0003 * counted)


def _nahida_below(_: float) -> float:
    """**Nahida, C0, on her own Tri-Karma Purification** with 602.2 EM: 402.2 counted, 40.2% DMG
    and 12.1% CRIT Rate.

    GO: `splitScaleDmg('karma_dmg', …, ownBuff.premod.dmg_.add(sum(a4Karma_dmg_, …)),
    ownBuff.premod.critRate_.add(a4Karma_critRate_))`, `passive2Elemas = min(max(sum(
    final.eleMas, -eleMas_min), 0), eleMas_maxCounted)` (`pando Nahida.ts:83-87,184-197,
    246-255`)."""
    return _nahida_a4(NAHIDA_EM_LOW)


def _nahida_past(_: float) -> float:
    """**Nahida, C0, EM-stacked, on her own Tri-Karma Purification** with 1,115.2 EM: 915.2 above
    200, 800 counted — 80% DMG and 24% CRIT Rate. Same GO lines as `_nahida_below`."""
    return _nahida_a4(NAHIDA_EM_HIGH)


# ── Furina: A4, Salon members' DMG from her Max HP, capped at 28% ───────────────────────────

#: Her seeded skill row at 10: Gentilhomme Usher is `param3` of her Max HP.
USHER_10 = ("Gentilhomme Usher DMG|{param3:F2P} Max HP", [0.141552, 30.0, 0.10728])
FURINA_HP_STACKED = {"hp_pct": 1.4, "flat_hp": 4780.0, "hydro_dmg_bonus": 0.466,
                     "crit_rate": 0.3, "crit_dmg": 0.9}


def _furina_a4(artifacts: dict[str, float]) -> float:
    stats = base._stats(base.FURINA_BASE, artifacts)
    hp = base._total(stats, "hp")
    return b5._hit(stats, base_damage=USHER_10[1][2] * hp, channel="hydro",
                   extra_dmg=min(hp / 1000 * 0.007, 0.28))


def _furina_below(_: float) -> float:
    """**Furina, C0, on her own Gentilhomme Usher**, Fanfare at 0 (set by the user): 0.7% per
    1,000 of 34,353 HP is 24.0%, below 28%. GO's Salon member multiplier is 1 at its default
    (no member's HP consumed), as the estimate has it.

    GO: `salonMember(…)` → `dmg(name, info, 'hp', table, 'skill', {baseMulti: member_mult_},
    ownBuff.premod.dmg_.skill.add(a4Member_dmg_))`, `a4Member_dmg_ = cmpGE(ascension, 4, min(
    prod(final.hp, 1 / 1000, percent(member_dmg_)), percent(max_member_dmg_)))` (`pando
    Furina.ts:73-77,128,143-150,180-191,250`)."""
    return _furina_a4(base.FURINA_ARTIFACTS)


def _furina_past(_: float) -> float:
    """**Furina, C0, HP-stacked, on her own Gentilhomme Usher**, Fanfare at 0: 41,517 HP would
    be 29.1%; the cap gives 28%. Same GO lines as `_furina_below`."""
    return _furina_a4(FURINA_HP_STACKED)


# ── Alhaitham ───────────────────────────────────────────────────────────────────────────────

#: A stated Alhaitham at 90: base ATK character + weapon; his ascension Dendro DMG 28.8%.
ALHAITHAM_BASE = base._base_stats(base_atk=855.0, base_hp=13348.0, base_def=782.0,
                                  dendro_dmg_bonus=0.288)
ALHAITHAM_EM_LOW = {"elemental_mastery": 400.0, "atk_pct": 0.466, "flat_atk": 311.0,
                    "dendro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}
ALHAITHAM_EM_HIGH = {"elemental_mastery": 900.0, "flat_atk": 311.0,
                     "dendro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}
#: His seeded skill row at 10: one mirror's Projection Attack, `param4` ATK + `param5` EM.
PROJECTION_10 = ("1-Mirror Projection Attack DMG|{param4:F1P} ATK+{param5:F1P} Elemental Mastery",
                 [3.4848, 2.78784, 1.6, 1.2096, 2.4192])
#: His seeded burst row at 13 (stored 10, +3 from C5): `param1` ATK + `param2` EM.
FETTERS_13 = ("Single-Instance DMG|{param1:F1P} ATK+{param2:F1P} Elemental Mastery",
              [2.584, 2.0672])
ALHAITHAM_TEAM = ["dendro", "electro"]


def _alhaitham_below(_: float) -> float:
    """**Alhaitham, C2, on his own 1-Mirror Projection Attack**, four Debate stacks (his own,
    the default): 400 + 200 EM, A4 0.1% per point is 60%, below its 100%.

    GO: `splitScaleDmg('skill_mirrorDmg1', …, ownBuff.premod.dmg_.skill.add(a4_skill_dmg_))`,
    `a4_skill_dmg_ = cmpGE(ascension, 4, min(prod(percent(dmgInc), final.eleMas),
    percent(maxDmgInc)))` (`pando Alhaitham.ts:69-72,112-119,198-206`); C2 `ownBuff.premod.
    eleMas` = `prod(debateStacks, constellation2.eleMas)` (`:77-81,121-125,162`)."""
    stats = base._stats(ALHAITHAM_BASE, ALHAITHAM_EM_LOW)
    em = stats["elemental_mastery"] + 4 * 50.0
    return b5._hit(stats, base_damage=PROJECTION_10[1][3] * base._total(stats, "atk")
                   + PROJECTION_10[1][4] * em, channel="dendro", extra_dmg=min(0.001 * em, 1.0))


def _alhaitham_past(_: float) -> float:
    """**Alhaitham, C6, on his own Particular Field** (burst at 13), four Debate stacks and an
    excess mirror (both his own, the default): 900 + 200 EM, A4 would be 110%, capped at 100%;
    C6's 10% CRIT Rate and 70% CRIT DMG. C4's mirrors consumed at 0 (situational): no C4 buff.

    GO: `splitScaleDmg('burst_instanceDmg', …, ownBuff.premod.dmg_.burst.add(a4_burst_dmg_))`
    (`pando Alhaitham.ts:112-120,207-215`); C6 `:88-92,148-153,166-167`; C5 `:158,160`."""
    stats = base._stats(ALHAITHAM_BASE, ALHAITHAM_EM_HIGH)
    em = stats["elemental_mastery"] + 4 * 50.0
    return b5._hit(stats, base_damage=FETTERS_13[1][0] * base._total(stats, "atk")
                   + FETTERS_13[1][1] * em, channel="dendro", extra_dmg=min(0.001 * em, 1.0),
                   extra_cr=0.1, extra_cd=0.7)


def _alhaitham_on_xiangling(coefficient: float) -> float:
    """**Alhaitham, C4, as Xiangling's teammate**, his burst having consumed three mirrors (set by
    the user — situational): 30 EM per mirror to the other party members, into her reverse
    vaporize.

    GO: `teamBuff.premod.eleMas.add(c4MirrorsConsumed_eleMas)`, WR `unequal(activeCharKey,
    key)`, `prod(mirrorsConsumed, constellation4.eleMas)` (`pando Alhaitham.ts:82-87,126-130,
    163-164`); amp `formula.ts:257,454-484`."""
    totals = base._xiangling_totals(fervent=False, witch_stacks=0)
    totals["pyro"] -= 0.15  # no Crimson Witch here: `_xiangling_totals` adds its 2-piece
    em = totals["em"] + 3 * 30.0
    return base._go_hit(multiplier=base._multiplier(base.PYRONADO), atk=totals["atk"],
                        dmg_bonus=totals["pyro"], crit_rate=totals["cr"],
                        crit_dmg=totals["cd"], em=em, amp_base=1.5, reaction_bonus=0.0,
                        em_coefficient=coefficient)


# ── Tighnari ────────────────────────────────────────────────────────────────────────────────

#: A stated Tighnari at 90: base ATK character + weapon; his ascension Dendro DMG 28.8%.
TIGHNARI_BASE = base._base_stats(base_atk=876.0, base_hp=10850.0, base_def=630.0,
                                 dendro_dmg_bonus=0.288)
TIGHNARI_EM_LOW = {"elemental_mastery": 500.0, "atk_pct": 0.466, "flat_atk": 311.0,
                   "dendro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}
TIGHNARI_EM_HIGH = {"elemental_mastery": 1050.0, "flat_atk": 311.0,
                    "dendro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}
#: His seeded Normal Attack row at 10: the Wreath Arrow is `param7`.
WREATH_10 = ("Wreath Arrow DMG|{param7:F1P}",
             [0.8823, 0.8296, 0.52275, 1.3566, 0.867, 2.232, 1.5696])
TIGHNARI_TEAM = ["dendro", "electro"]


def _tighnari_below(_: float) -> float:
    """**Tighnari, C0, on his own Wreath Arrow** (a Charged Attack), after firing one (A1, his
    own, the default): 500 + 50 EM, A4 0.06% per point is 33%, below 60%.

    GO: `dmg('charged_wreath', …, 'charged', {ele: 'dendro'})` (`pando Tighnari.ts:143-145`);
    A1 `ownBuff.premod.eleMas` (`:58-61,92-94,127`); A4 `ownBuff.premod.dmg_.charged` =
    `min(prod(percent(charged_burst_dmg_), final.eleMas), percent(maxDmg_))` (`:62-65,95-102,
    128`)."""
    stats = base._stats(TIGHNARI_BASE, TIGHNARI_EM_LOW)
    em = stats["elemental_mastery"] + 50.0
    return b5._hit(stats, base_damage=WREATH_10[1][6] * base._total(stats, "atk"),
                   channel="dendro", extra_dmg=min(0.0006 * em, 0.6))


def _tighnari_past(_: float) -> float:
    """**Tighnari, C2, on his own Wreath Arrow**, after firing one and an opponent in his field
    (set by the user — situational): 1,050 + 50 EM, A4 would be 66%, capped at 60%; C1's 15%
    Charged Attack CRIT Rate; C2's 20% Dendro DMG. Same GO lines, and C1 `:66-68,103-107,130`,
    C2 `:69-72,108-110,131`."""
    stats = base._stats(TIGHNARI_BASE, TIGHNARI_EM_HIGH)
    em = stats["elemental_mastery"] + 50.0
    return b5._hit(stats, base_damage=WREATH_10[1][6] * base._total(stats, "atk"),
                   channel="dendro", extra_dmg=min(0.0006 * em, 0.6) + 0.2, extra_cr=0.15)


def _tighnari_on_xiangling(coefficient: float) -> float:
    """**Tighnari, C4, as Xiangling's teammate**, his burst having triggered a reaction (set by
    the user — situational): 60 EM, and 60 more (GO `react: eleMas * 2`), into her reverse
    vaporize.

    GO: `teamBuff.premod.eleMas.add(c4_eleMas)`, `c4.map({after: eleMas, react: eleMas * 2})`
    (`pando Tighnari.ts:73-76,111-118,132`); amp `formula.ts:257,454-484`."""
    totals = base._xiangling_totals(fervent=False, witch_stacks=0)
    totals["pyro"] -= 0.15
    em = totals["em"] + 2 * 60.0
    return base._go_hit(multiplier=base._multiplier(base.PYRONADO), atk=totals["atk"],
                        dmg_bonus=totals["pyro"], crit_rate=totals["cr"],
                        crit_dmg=totals["cd"], em=em, amp_base=1.5, reaction_bonus=0.0,
                        em_coefficient=coefficient)


def capped_fixtures() -> list[dict[str, Any]]:
    """One fixture below and one past each capped conversion's cap, and Alhaitham's and
    Tighnari's team buffs."""
    out: list[dict[str, Any]] = []
    fx = base._buffer
    sub = b5._subject
    own = b5._own
    hu_go = [FORMULA, f"{PANDO}HuTao.ts:48-56,103-112,144,165"]

    for name, artifacts, figure, state in [
        ("hu_tao_paramita_below_cap_on_her_own_blossom", b5.HU_TAO_ARTIFACTS, _hu_tao_below,
         "below"),
        ("hu_tao_paramita_past_cap_on_her_own_blossom", HU_TAO_HP_STACKED, _hu_tao_past, "past"),
    ]:
        out.append(_capped(fx(
            name,
            "self flat ATK from her own Max HP, capped at a multiple of her base ATK (a talent "
            "row's unnamed parameter), per candidate",
            hu_go, sub("Hu Tao", 0, {"elemental_skill": 10}),
            {"element": "pyro", "weapon_type": "WEAPON_POLE",
             "member_elements": ["pyro", "hydro"]},
            b5.HU_TAO_BASE, artifacts, "pyro",
            base._row("blossom", "Blood Blossom DMG", "skill", 1, b5.HU_TAO_BLOSSOM, None),
            b4._kit("10000046", own("Hu Tao", "10000046", 0, b5.HU_TAO_BASE, b5.HU_TAO_ROWS),
                    subject=True),
            {}, figure), state))

    clorinde_go = [FORMULA, f"{PANDO}Clorinde.ts:62-74,81-84,129-151,184-185,204"]
    for name, cons, artifacts, figure, state in [
        ("clorinde_a1_below_cap_on_her_own_burst", 0, b5.CLORINDE_ARTIFACTS, _clorinde_below,
         "below"),
        ("clorinde_c2_a1_past_cap_on_her_own_burst", 2, CLORINDE_ATK_STACKED, _clorinde_past,
         "past"),
    ]:
        out.append(_capped(fx(
            name,
            "self flat damage from her own ATK per stack, the stacked total capped (A1, raised "
            "and replaced by C2), per candidate; over a five-hit row",
            clorinde_go, sub("Clorinde", cons),
            {"element": "electro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
             "member_elements": ["electro", "pyro"]},
            b5.CLORINDE_BASE, artifacts, "electro",
            base._row("burst", "Skill DMG", "burst", 5, b5.CLORINDE_BURST, None),
            b4._kit("10000098", own("Clorinde", "10000098", cons, b5.CLORINDE_BASE),
                    subject=True),
            {"kit:clorinde/a1_stacks": 3}, figure), state))

    nahida_go = [FORMULA, f"{PANDO}Nahida.ts:83-87,184-197,246-255"]
    for name, artifacts, figure, state in [
        ("nahida_a4_below_cap_on_her_own_tri_karma", NAHIDA_EM_LOW, _nahida_below, "below"),
        ("nahida_a4_past_cap_on_her_own_tri_karma", NAHIDA_EM_HIGH, _nahida_past, "past"),
    ]:
        out.append(_capped(fx(
            name,
            "self DMG% and CRIT Rate from her own EM above a threshold, the counted EM capped "
            "(A4), each priced alone per candidate, on one of her rows",
            nahida_go, sub("Nahida", 0, {"elemental_burst": 10}),
            {"element": "dendro", "weapon_type": "WEAPON_CATALYST",
             "member_elements": NAHIDA_TEAM},
            b4.NAHIDA_BASE, artifacts, "dendro",
            b4._with_hit(base._row("karma", "Tri-Karma Purification DMG", "skill", 1,
                                   TRI_KARMA_10, None),
                         "elemental_skill", "Tri-Karma Purification DMG"),
            b4._kit("10000073", own("Nahida", "10000073", 0, b4.NAHIDA_BASE, {
                ("elemental_burst", 10): (b4.NAHIDA_BURST_LABELS, b4.NAHIDA_BURST_10)}),
                subject=True, receiver_element="dendro", team_elements=NAHIDA_TEAM),
            {}, figure), state))

    furina_go = [FORMULA, f"{PANDO}Furina.ts:73-77,128,143-150,180-191,250"]
    for name, artifacts, figure, state in [
        ("furina_a4_below_cap_on_her_own_usher", base.FURINA_ARTIFACTS, _furina_below, "below"),
        ("furina_a4_past_cap_on_her_own_usher", FURINA_HP_STACKED, _furina_past, "past"),
    ]:
        out.append(_capped(fx(
            name,
            "self DMG% from her own Max HP per 1,000 (a cited unit), capped (A4), per "
            "candidate, on her Salon members' rows only",
            furina_go, sub("Furina", 0, {"elemental_burst": 10}),
            {"element": "hydro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
             "member_elements": ["hydro", "pyro"]},
            base.FURINA_BASE, artifacts, "hydro",
            b4._with_hit(base._row("usher", "Gentilhomme Usher DMG", "skill", 1, USHER_10, None),
                         "elemental_skill", "Gentilhomme Usher DMG"),
            b4._kit("10000089", own("Furina", "10000089", 0, base.FURINA_BASE, {
                ("elemental_burst", 10): (base.FURINA_BURST_LABELS, base.FURINA_BURST_10)}),
                subject=True),
            {"kit:furina/fanfare": 0}, figure), state))

    out.append(_capped(fx(
        "alhaitham_a4_c2_below_cap_on_his_own_projection",
        "self DMG% from his own EM, capped (A4), per candidate, on his Projection Attack rows; "
        "a self EM buff per stack (C2) that the conversion reads",
        [FORMULA, f"{PANDO}Alhaitham.ts:69-72,77-81,112-125,162,198-206"],
        sub("Alhaitham", 2),
        {"element": "dendro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ALHAITHAM_TEAM},
        ALHAITHAM_BASE, ALHAITHAM_EM_LOW, "dendro",
        b4._with_hit(base._row("mirror", "1-Mirror Projection Attack DMG", "skill", 1,
                               PROJECTION_10, None),
                     "elemental_skill", "1-Mirror Projection Attack DMG"),
        b4._kit("10000078", own("Alhaitham", "10000078", 2, ALHAITHAM_BASE), subject=True,
                receiver_element="dendro", team_elements=ALHAITHAM_TEAM),
        {}, _alhaitham_below), "below"))

    out.append(_capped(fx(
        "alhaitham_a4_past_cap_c6_on_his_own_burst",
        "self DMG% from his own EM past its cap (A4) on his burst; C6's CRIT Rate and DMG; a "
        "boosted burst row (C5)",
        [FORMULA, f"{PANDO}Alhaitham.ts:69-72,77-92,112-125,148-153,158-167,207-215"],
        sub("Alhaitham", 6),
        {"element": "dendro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ALHAITHAM_TEAM},
        ALHAITHAM_BASE, ALHAITHAM_EM_HIGH, "dendro",
        base._row("fetters", "Single-Instance DMG", "burst", 1, FETTERS_13, None),
        b4._kit("10000078", own("Alhaitham", "10000078", 6, ALHAITHAM_BASE), subject=True,
                receiver_element="dendro", team_elements=ALHAITHAM_TEAM),
        {}, _alhaitham_past), "past"))

    out.append(fx(
        "alhaitham_c4_on_xiangling",
        "a teammate EM buff per a user-set count, to the others only (C4), into an amplifying "
        "reaction",
        [AMP, f"{PANDO}Alhaitham.ts:82-87,126-130,163-164"],
        {"name": "Alhaitham", "constellation": 4, "ascension_phase": 6, "stats": {}},
        {"element": "pyro", "weapon_type": "WEAPON_POLE",
         "member_elements": ["pyro", "dendro", "hydro"]},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro",
        base._row("nado_vape", "Pyronado DMG (vaporize)", "burst", 1, base.PYRONADO,
                  "reverse_vaporize"),
        b4._kit("10000078", own("Alhaitham", "10000078", 4, {}), subject=False,
                receiver_element="pyro", team_elements=["pyro", "dendro", "hydro"]),
        {"kit:alhaitham/mirrors_consumed": 3}, _alhaitham_on_xiangling, EM_GAP))

    out.append(_capped(fx(
        "tighnari_a1_a4_below_cap_on_his_own_wreath",
        "self DMG% from his own EM, capped (A4), per candidate, on his Charged Attacks; a self "
        "EM buff (A1) that the conversion reads",
        [FORMULA, f"{PANDO}Tighnari.ts:58-65,92-102,127-128,143-145"],
        sub("Tighnari", 0),
        {"element": "dendro", "weapon_type": "WEAPON_BOW", "member_elements": TIGHNARI_TEAM},
        TIGHNARI_BASE, TIGHNARI_EM_LOW, "dendro",
        base._row("wreath", "Wreath Arrow DMG", "charged", 1, WREATH_10, None),
        b4._kit("10000069", own("Tighnari", "10000069", 0, TIGHNARI_BASE), subject=True,
                receiver_element="dendro", team_elements=TIGHNARI_TEAM),
        {}, _tighnari_below), "below"))

    out.append(_capped(fx(
        "tighnari_a4_past_cap_c2_on_his_own_wreath",
        "self DMG% from his own EM past its cap (A4); a Charged Attack CRIT Rate (C1); a "
        "situational Dendro DMG buff (C2)",
        [FORMULA, f"{PANDO}Tighnari.ts:58-72,92-110,127-131,143-145"],
        sub("Tighnari", 2),
        {"element": "dendro", "weapon_type": "WEAPON_BOW", "member_elements": TIGHNARI_TEAM},
        TIGHNARI_BASE, TIGHNARI_EM_HIGH, "dendro",
        base._row("wreath", "Wreath Arrow DMG", "charged", 1, WREATH_10, None),
        b4._kit("10000069", own("Tighnari", "10000069", 2, TIGHNARI_BASE), subject=True,
                receiver_element="dendro", team_elements=TIGHNARI_TEAM),
        {"kit:tighnari/enemy_in_field": 1}, _tighnari_past), "past"))

    out.append(fx(
        "tighnari_c4_react_on_xiangling",
        "a party EM buff by a user-set choice, the second option applying the parameter twice "
        "(C4), into an amplifying reaction",
        [AMP, f"{PANDO}Tighnari.ts:73-76,111-118,132"],
        {"name": "Tighnari", "constellation": 4, "ascension_phase": 6, "stats": {}},
        {"element": "pyro", "weapon_type": "WEAPON_POLE",
         "member_elements": ["pyro", "dendro", "hydro"]},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro",
        base._row("nado_vape", "Pyronado DMG (vaporize)", "burst", 1, base.PYRONADO,
                  "reverse_vaporize"),
        b4._kit("10000069", own("Tighnari", "10000069", 4, {}), subject=False,
                receiver_element="pyro", team_elements=["pyro", "dendro", "hydro"]),
        {"kit:tighnari/c4": "react"}, _tighnari_on_xiangling, EM_GAP))
    return out
