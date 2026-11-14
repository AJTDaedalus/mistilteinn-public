"""Math-fallback P2, task 11 (seventh batch): GO fixtures for the commonly played characters next
on the list.

Kept beside `test_go_formula_fixtures.py` as the batch modules are, and imported by its
`build()`. The method is unchanged: each figure is worked by hand from Genshin Optimizer's formula
at `2c13fc40` with **our** numbers — talent rows verbatim from the seeded catalogue (nanoka
7.2.51, level 10 unless said; a constellation's +3 reads the level-13 row), constellation and
passive lists the sheets' pins, stated builds. A subject resolves its own sheet against its base
stats; a teammate giver's stats are written out as their pass-1 numbers. Every fixture states
every condition its sources read (`_states_every_condition`), and a row-scoped buff's row names
its talent row (`hit`), so `formula:verify` also checks that the figure misses unnamed.

Nothing here is a test by itself; its fixtures are checked by `test_go_formula_fixtures.py` and
`test_formula_sheets_batch7.py`, and by `npm run formula:verify`.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch4 as b4
from tests.unit import go_fixtures_batch5 as b5
from tests.unit import go_fixtures_batch6 as b6
from tests.unit import test_go_formula_fixtures as base

FORMULA = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
FORMULA_DEF = "libs/gi/wr/src/formula.ts:357,434-453,490-514"
PANDO = "libs/gi/formula/src/data/char/"

_subject = b6._subject
_teammate = b6._teammate
_giver = b6._giver


def _hit(stats: dict[str, float], *, base_damage: float, flat: float = 0.0, channel: str,
         extra_dmg: float = 0.0, extra_cr: float = 0.0, extra_cd: float = 0.0,
         res: float = 0.1, def_reduction: float = 0.0) -> float:
    return b4._go_hit(base_damage=base_damage, flat=flat,
                      dmg_bonus=stats.get(f"{channel}_dmg_bonus", 0.0) + extra_dmg,
                      crit_rate=stats["crit_rate"] + extra_cr,
                      crit_dmg=stats["crit_dmg"] + extra_cd, res=res,
                      def_reduction=def_reduction)


XIANGLING_TEAM = {"element": "pyro", "weapon_type": "WEAPON_POLE"}
EULA_NA_1 = ("1-Hit DMG|{param1:F1P}", [1.77378])
EULA_TEAM = {"element": "cryo", "weapon_type": "WEAPON_CLAYMORE"}


def _xiangling(row: tuple[str, list[float]], **kw: Any) -> float:
    stats = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(row) * base._total(stats, "atk"),
                channel="pyro", **kw)


def _eula(**kw: Any) -> float:
    stats = base._stats(b5.EULA_BASE, b5.EULA_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(EULA_NA_1) * base._total(stats, "atk"),
                channel="physical", **kw)


# ── Xiao: a Plunge in his burst, its Normal/Charged/Plunging bonus and A1 ───────────────────

XIAO_BURST_LABELS = ["Normal/Charged/Plunging Attack DMG Bonus|{param1:F1P}",
                     "Life Drain|{param2:F1P} Current HP Per Second", "Duration|{param3:F1}s",
                     "CD|{param4:F1}s", "Energy Cost|{param5:I}"]
XIAO_BURST_10 = [0.952, 0.02, 15.0, 18.0, 70.0]
XIAO_PLUNGE = ("Plunge DMG|{param11:P}", [0.49141, 0.49141, 1.01579, 1.22303, 0.67196,
                                          0.67196, 1.27641, 1.70973, 2.16032, 25.0, 1.617638])
XIAO_BASE = base._base_stats(base_atk=957.0, base_hp=12736.0, base_def=799.0, crit_rate=0.242)
XIAO_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "anemo_dmg_bonus": 0.466,
                  "crit_rate": 0.3, "crit_dmg": 0.7}


def _xiao(_: float) -> float:
    """**Xiao, C0, on his own Plunge** in his burst (the Anemo-infused row), five A1 stacks: the
    burst row's 95.2% Normal/Charged/Plunging DMG and A1's 5% per stack.

    GO: `plunging_dmg_anemo` (`pando Xiao.ts:155-161`); `burst_auto_dmg_ = prod(inBurstOn,
    talentSubscript(burst, dmgBonus))` into `premod.dmg_.plunging` (`:97-102,137`); `a1_all_dmg_
    = prod(inBurstOn, passive1 × stacks)` into `premod.dmg_` (`:103-113,138`)."""
    stats = base._stats(XIAO_BASE, XIAO_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(XIAO_PLUNGE) * base._total(stats, "atk"),
                channel="anemo", extra_dmg=0.952 + 5 * 0.05)


# ── Venti: C2 and C6 RES shred on a teammate ────────────────────────────────────────────────

VENTI_TEAM = ["pyro", "anemo"]


def _venti_on_xiangling(_: float) -> float:
    """**Venti's C6 on Xiangling's Pyronado**, his burst having absorbed Pyro: Pyro RES -20%
    (C6's absorbed element; C2's shred is Anemo and Physical, so it misses this row).

    GO: `enemyDebuff.common.preRes[ele].add(prod(c6On, burstAbsorption=ele, -0.2))` (`pando
    Venti.ts:91-95,134,165-178`)."""
    return _xiangling(base.PYRONADO, res=0.1 - 0.2)


# ── Nilou: A1 EM and C2 Dendro RES on Nahida ────────────────────────────────────────────────

NILOU_TEAM = ["dendro", "hydro"]


def _nilou_on_nahida(_: float) -> float:
    """**Nilou's A1 and C2 on Nahida's Tri-Karma Purification**, in a Hydro and Dendro party
    with Golden Chalice's Bounty up: 100 EM to the party (read by the row's EM term) and Dendro
    RES -35%.

    GO: `onlyDendroHydroTeam` and `isGoldenChaliceBountyActive` (`pando Nilou.ts:109-117`);
    `teamBuff.premod.eleMas.add(a1AfterSkillAndHit_eleMas)` (`:119-121,194`);
    `enemyDebuff.common.preRes.dendro.add(-constellation2[1])` (`:153-161,198`); Tri-Karma
    `splitScaleDmg(['atk', 'eleMas'])` (`pando Nahida.ts:246-255`)."""
    stats = base._stats(b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS)
    params = b6.TRI_KARMA_10[1]
    return _hit(stats, base_damage=params[2] * base._total(stats, "atk")
                + params[3] * (stats["elemental_mastery"] + 100.0), channel="dendro",
                res=0.1 - 0.35)


# ── Albedo: his burst, C2's flat damage from his DEF ────────────────────────────────────────

ALBEDO_BURST = ("Burst DMG|{param1:P}", [6.6096])
ALBEDO_BASE = base._base_stats(base_atk=705.0, base_hp=13226.0, base_def=876.0)
ALBEDO_BASE["geo_dmg_bonus"] = 0.288
ALBEDO_ARTIFACTS = {"def_pct": 1.0, "flat_def": 58.0, "geo_dmg_bonus": 0.466,
                    "crit_rate": 0.3, "crit_dmg": 0.6}


def _albedo(_: float) -> float:
    """**Albedo, C2, on his own Burst DMG** at four Fatal Reckoning stacks: 30% of his DEF per
    stack added to the burst's base, per candidate.

    GO: `ownBuff.formula.base.burst.add(prod(c2StackVal, percent(blossomDmgInc), final.def))`
    (`pando Albedo.ts:84-91,135-140,222`); `dmg('burst', …)` (`:250`)."""
    stats = base._stats(ALBEDO_BASE, ALBEDO_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(ALBEDO_BURST) * base._total(stats, "atk"),
                flat=4 * 0.3 * base._total(stats, "def"), channel="geo")


# ── Chiori: a Normal Attack, A4 and C6 ──────────────────────────────────────────────────────

CHIORI_NA_1 = ("1-Hit DMG|{param1:F1P}", [0.976718])
CHIORI_BASE = base._base_stats(base_atk=945.0, base_hp=11437.0, base_def=953.0,
                               crit_rate=0.242)
CHIORI_ARTIFACTS = {"def_pct": 0.874, "flat_def": 58.0, "geo_dmg_bonus": 0.466,
                    "crit_rate": 0.3, "crit_dmg": 0.6}


def _chiori(_: float) -> float:
    """**Chiori, C6, on her own 1-Hit DMG** (Geo, in her A1 infusion), after a Geo construct:
    A4's 20% Geo DMG and C6's 235% of her DEF added to the Normal Attack's base, per candidate.

    GO: `normal_0_geo` (`pando Chiori.ts:122-127`); `ownBuff.premod.dmg_.geo.add(a4Construct)`
    (`:100-102,117`); `ownBuff.formula.base.normal.add(prod(percent(auto_dmgInc_def),
    final.def))` (`:103-108,118`)."""
    stats = base._stats(CHIORI_BASE, CHIORI_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(CHIORI_NA_1) * base._total(stats, "atk"),
                flat=2.35 * base._total(stats, "def"), channel="geo", extra_dmg=0.2)


# ── Sigewinne: A1 and C1 on a teammate's skill ──────────────────────────────────────────────

#: Sigewinne as a teammate: her pass-1 Max HP, 13,348 × 3 + 4,780 = 44,824.
SIGEWINNE_GIVER_STATS = {"base_hp": 13348.0, "hp_pct": 2.0, "flat_hp": 4780.0}


def _sigewinne_on_xiangling(_: float) -> float:
    """**Sigewinne's A1 at C1 on Xiangling's Guoba**: 100 per 1,000 of her Max HP above 30,000
    (80 from A1, 20 more from C1), capped at 3,500 (2,800 + 700), added to the skill's base —
    14,824 above, so 1,482.4.

    GO: `a1Conva_skill_dmgInc = a1Conva.ifOn(min(convaMaxDmgInc, prod(max(0, hp - hpThresh),
    convaDmgInc)))` with C1's `100 / 1000` and `3500` (`pando Sigewinne.ts:64-80,150-169`) into
    `teamBuff.formula.base.skill` (`:212`)."""
    hp = 13348.0 * 3 + 4780.0
    return _xiangling(base.GUOBA, flat=min(3500.0, (hp - 30000.0) * 100 / 1000))


# ── Sethos: a Shadowpiercing Shot, A4, C1, C2 ───────────────────────────────────────────────

SETHOS_BURST_LABELS = ["Dusk Bolt DMG Increase|{param1:F1P} Elemental Mastery",
                       "Twilight Meditation Duration|{param2:F1}s", "CD|{param3:F1}s",
                       "Energy Cost|{param4:I}"]
SETHOS_BURST_10 = [3.53088, 8.0, 15.0, 60.0]
SETHOS_SHADOW = ("Shadowpiercing Shot DMG|{param7:F1P} ATK+{param8:F1P} Elemental Mastery",
                 [1.040043, 0.47039, 0.52598, 1.462527, 0.867, 2.232, 2.52, 2.42208])
SETHOS_BASE = base._base_stats(base_atk=910.0, base_hp=9787.0, base_def=560.0,
                               elemental_mastery=96.0)
SETHOS_ARTIFACTS = {"elemental_mastery": 300.0, "atk_pct": 0.466, "flat_atk": 311.0,
                    "electro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}


def _sethos(_: float) -> float:
    """**Sethos, C2, on his own Shadowpiercing Shot** with Sandshade and two C2 stacks: A4's
    700% of his EM added to the base, per candidate; C1's 15% CRIT Rate on the shot; C2's 15%
    Electro DMG per stack.

    GO: `splitScaleDmg('charged_shadow', ['atk', 'eleMas'], …, ownBuff.formula.base.add(
    a4Sandshade_shadow_dmgInc), ownBuff.premod.critRate_.charged.add(c1))` (`pando Sethos.ts:
    99-106,135-144`); `premod.dmg_.electro` C2 × stacks (`:107-111,123`)."""
    stats = base._stats(SETHOS_BASE, SETHOS_ARTIFACTS)
    params = SETHOS_SHADOW[1]
    em = stats["elemental_mastery"]
    return _hit(stats, base_damage=params[6] * base._total(stats, "atk") + params[7] * em,
                flat=7.0 * em, channel="electro", extra_dmg=2 * 0.15, extra_cr=0.15)


# ── Shikanoin Heizou: his skill at Conviction, C6 ───────────────────────────────────────────

#: His seeded skill row at level 13 (stored 10, +3 from C3).
HEIZOU_SKILL_LABELS = ["Skill DMG|{param1:F1P}", "Declension DMG Bonus|{param2:F1P}/stack",
                       "Conviction DMG Bonus|{param3:F1P}", "Declension Duration|{param5:F1}s",
                       "CD|{param4:F1}s"]
HEIZOU_SKILL_13 = [4.8348, 1.2087, 2.4174, 10.0, 60.0]
HEIZOU_SKILL = ("Skill DMG|{param1:F1P}", HEIZOU_SKILL_13)
HEIZOU_BASE = base._base_stats(base_atk=966.0, base_hp=10657.0, base_def=684.0)
HEIZOU_BASE["anemo_dmg_bonus"] = 0.24
HEIZOU_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "anemo_dmg_bonus": 0.466,
                    "crit_rate": 0.3, "crit_dmg": 0.6}


def _heizou(_: float) -> float:
    """**Shikanoin Heizou, C6, on his own skill** at four Declension stacks (Conviction): the
    skill's multiplier plus four Declension rows and the Conviction row, all of ATK (the extra
    parts written as flat damage from his ATK, per candidate); C6's 4% CRIT Rate per stack and
    32% CRIT DMG at four.

    GO: `skillMv = sum(skill.dmg, prod(stacks, declension_dmg_), cmpEq(stacks, 4,
    conviction_dmg_))`, `customDmg('skill', 'anemo', 'skill', prod(skillMv, final.atk))` (`pando
    ShikanoinHeizou.ts:89-100,135`); C6 `premod.critRate_.skill` / `critDMG_.skill`
    (`:105-115,124-125`)."""
    stats = base._stats(HEIZOU_BASE, HEIZOU_ARTIFACTS)
    atk = base._total(stats, "atk")
    return _hit(stats, base_damage=4.8348 * atk, flat=(4 * 1.2087 + 2.4174) * atk,
                channel="anemo", extra_cr=4 * 0.04, extra_cd=0.32)


# ── Freminet: a Level 4 Shattering Pressure, A4, C1, C4, C6 ─────────────────────────────────

#: His seeded skill row at level 13 (stored 10, +3 from C5).
FREMINET_LEVEL_4 = ("Level 4 Shattering Pressure DMG|{param11:F1P}",
                    [1.7646, 0.306, 0.15215, 4.2602, 2.1301, 1.03462, 1.49107, 1.810585,
                     0.85204, 2.58655, 5.1731])
FREMINET_BASE = base._base_stats(base_atk=960.0, base_hp=12071.0, base_def=704.0,
                                 atk_pct=0.24)
FREMINET_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "physical_dmg_bonus": 0.583,
                      "crit_rate": 0.3, "crit_dmg": 0.6}


def _freminet(_: float) -> float:
    """**Freminet, C6, on his own Level 4 Shattering Pressure** (Physical) after a Shatter, three
    C4/C6 stacks: A4's 40% DMG and C1's 15% CRIT Rate on the pressure rows; C4's 9% ATK per
    stack, at most two (18%); C6's 12% CRIT DMG per stack.

    GO: `level4Dmg` with `pressureExtras` (`pando Freminet.ts:122-125,214-222`); A4 (`:100-102`),
    C1 (`:103-107`); `prod(atk_, min(stacks, maxStacks))` (`:108-115,134`); C6 (`:116-121,
    135`)."""
    stats = base._stats(FREMINET_BASE, FREMINET_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=2 * 0.09)
    return _hit(stats, base_damage=base._multiplier(FREMINET_LEVEL_4) * atk,
                channel="physical", extra_dmg=0.4, extra_cr=0.15, extra_cd=3 * 0.12)


# ── Rosaria: A4 and C6 on Eula ──────────────────────────────────────────────────────────────

#: Rosaria as a teammate: her pass-1 CRIT Rate (5% base, 19.2% ascension, 55.8% artifacts).
ROSARIA_GIVER_STATS = {"crit_rate": 0.8}


def _rosaria_on_eula(_: float) -> float:
    """**Rosaria's A4 and C6 on Eula's 1-Hit DMG**: 15% of Rosaria's 80% CRIT Rate (12%, under
    the 15% cap) and Physical RES -20%.

    GO: `notOwnBuff.premod.critRate_.add(RosariaA4.ifOn(min(prod(percent(crBonus),
    own.premod.critRate_), percent(maxBonus))))` (`pando Rosaria.ts:63-67,99-110`);
    `enemyDebuff.common.preRes.physical.add(-physShred)` (`:73-76,119-121`)."""
    return _eula(extra_cr=0.15 * 0.8, res=0.1 - 0.2)


# ── Candace: her burst and A4 on Kokomi ─────────────────────────────────────────────────────

CANDACE_BURST_LABELS = ["Skill DMG|{param1:F1P} Max HP", "Duration|{param2:F1}s",
                        "DMG Bonus|{param3:F1P}", "Wave Impact DMG|{param4:F1P} Max HP",
                        "Wave Instances|{param5:I}", "CD|{param6:F1}s",
                        "Energy Cost|{param7:I}"]
CANDACE_BURST_10 = [0.118987, 9.0, 0.2, 0.118987, 3.0, 15.0, 60.0]
#: Candace as a teammate: her pass-1 Max HP, 10,875 × 2.5 + 4,780 = 31,967.5.
CANDACE_GIVER_STATS = {"base_hp": 10875.0, "hp_pct": 1.5, "flat_hp": 4780.0}


def _candace_on_kokomi(_: float) -> float:
    """**Candace's burst and A4 on Kokomi's 1-Hit DMG** (Hydro, no Kokomi kit applied): 20%
    elemental Normal Attack DMG and 0.5% per 1,000 of Candace's Max HP.

    GO: `teamBuff.premod.dmg_.normal[ele].add(sum(afterBurst(dmg_bonus_), a4))` with `a4 =
    afterBurst(prod(percent(normalEle_dmg_), final.hp, 1 / 1000))` (`pando Candace.ts:51-62,
    81-89,104-106`)."""
    hp = 10875.0 * 2.5 + 4780.0
    stats = base._stats(b6.KOKOMI_BASE, b6.KOKOMI_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(b6.KOKOMI_NA_1) * base._total(stats, "atk"),
                channel="hydro", extra_dmg=0.2 + 0.005 * hp / 1000)


# ── Mika: A1 and C6 on Eula ─────────────────────────────────────────────────────────────────


def _mika_on_eula(_: float) -> float:
    """**Mika's A1 and C6 on Eula's 1-Hit DMG** in Soulwind: five Detector stacks (three, A4's
    one, C6's one) of 10% Physical DMG, and C6's 60% Physical CRIT DMG.

    GO: `detectorMax = sum(3, cmpGE(ascension, 4, 1), cmpGE(constellation, 6, 1))`,
    `teamBuff.premod.dmg_.physical` per stack (`pando Mika.ts:90-108,125`); `critDMG_.physical`
    (`:109-115,126`)."""
    return _eula(extra_dmg=5 * 0.1, extra_cd=0.6)


# ── Diluc: a Normal Attack in his infusion, A4, C1, C2, C6 ──────────────────────────────────

DILUC_NA_1 = ("1-Hit DMG|{param1:P}", [1.7731])
DILUC_BASE = base._base_stats(base_atk=943.0, base_hp=12981.0, base_def=784.0, crit_rate=0.242)
DILUC_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466,
                   "crit_rate": 0.3, "crit_dmg": 0.7}


def _diluc(_: float) -> float:
    """**Diluc, C6, on his own 1-Hit DMG** in his burst's infusion (Pyro), after his skill, the
    opponent above half HP, three C2 stacks: A4's 20% Pyro DMG, C1's 15% DMG, C2's 10% ATK per
    stack, C6's 30% Normal Attack DMG.

    GO: `normal_0_pyro` (`pando Diluc.ts:139-145`); A4 (`:102-104,133`), C1 (`:105-107,136`), C2
    (`:108-112,134`), C6 (`:118-120,137`)."""
    stats = base._stats(DILUC_BASE, DILUC_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=3 * 0.1)
    return _hit(stats, base_damage=base._multiplier(DILUC_NA_1) * atk, channel="pyro",
                extra_dmg=0.2 + 0.15 + 0.3)


# ── Klee: a Charged Attack with Explosive Spark, C2, C6 ─────────────────────────────────────

KLEE_CHARGED = ("Charged Attack DMG|{param4:P}", [1.29888, 1.1232, 1.61856, 2.83248])
KLEE_BASE = base._base_stats(base_atk=919.0, base_hp=10287.0, base_def=615.0)
KLEE_BASE["pyro_dmg_bonus"] = 0.288
KLEE_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466,
                  "crit_rate": 0.3, "crit_dmg": 0.6}


def _klee(_: float) -> float:
    """**Klee, C6, on her own Charged Attack** consuming Explosive Spark, during her burst, the
    opponent hit by her mines: A1's 50% Charged Attack DMG, C6's 10% party Pyro DMG, C2's 23%
    DEF reduction.

    GO: `dmg('a1_charged', …, ownBuff.premod.dmg_.charged.add(percent(0.5)))` (`pando Klee.ts:
    67-69,163-174`); C2 `enemyDebuff.common.defRed_` (`:84-86,125-127,148`); C6
    `teamBuff.premod.dmg_.pyro` with Hexerei off (`:91-96,128-130,150`)."""
    stats = base._stats(KLEE_BASE, KLEE_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(KLEE_CHARGED) * base._total(stats, "atk"),
                channel="pyro", extra_dmg=0.5 + 0.1, def_reduction=0.23)


# ── Lisa, Ningguang, Chongyun: one buff each, on a teammate ─────────────────────────────────


def _lisa_on_xiangling(_: float) -> float:
    """**Lisa's A4 on Xiangling's Pyronado**: opponent DEF -15% after her burst hits.

    GO: `enemyDebuff.common.defRed_.add(LisaA4.ifOn(percent(defShred)))` (`pando Lisa.ts:60-63,
    72,82-84`)."""
    return _xiangling(base.PYRONADO, def_reduction=0.15)


def _ningguang_on_chiori(_: float) -> float:
    """**Ningguang's A4 on Chiori's 1-Hit DMG** (Geo, no Chiori kit applied): 12% party Geo DMG
    after passing through the Jade Screen.

    GO: `teamBuff.premod.dmg_.geo.add(Ascension4.ifOn(percent(geoDmgBonus_)))` (`pando
    Ningguang.ts:49-52,61,70-72`)."""
    stats = base._stats(CHIORI_BASE, CHIORI_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(CHIORI_NA_1) * base._total(stats, "atk"),
                channel="geo", extra_dmg=0.12)


def _chongyun_on_ayaka(_: float) -> float:
    """**Chongyun's A4 on Ayaka's skill**: opponent Cryo RES -10%.

    GO: `enemyDebuff.common.preRes.cryo.add(cmpGE(ascension, 4, asc4.map({ hit: -0.1 })))`
    (`pando Chongyun.ts:88,102,117`); his seeded A4 list carries the same -0.1."""
    stats = base._stats(base.AYAKA_BASE, base.AYAKA_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(base.HYOUKA) * base._total(stats, "atk"),
                channel="cryo", res=0.1 - 0.1)


def batch7_fixtures() -> list[dict[str, Any]]:
    """Task 11, seventh batch: one fixture per sheet on its main damage effect."""
    fx = base._buffer
    out: list[dict[str, Any]] = []
    nado = base._row("nado", "Pyronado DMG", "burst", 1, base.PYRONADO, None)
    guoba = base._row("guoba", "Flame DMG", "skill", 1, base.GUOBA, None)
    eula_na = base._row("na1", "1-Hit DMG", "normal", 1, EULA_NA_1, None)

    out.append(fx(
        "xiao_burst_a1_on_his_own_plunge",
        "a self Normal/Charged/Plunging DMG bonus from a talent row during his burst, and a DMG "
        "bonus per stack (A1) gated on the same toggle",
        [FORMULA, f"{PANDO}Xiao.ts:46-55,81-89,97-113,135-138,155-161"],
        _subject("Xiao", 0, {"elemental_burst": 10}),
        {"element": "anemo", "weapon_type": "WEAPON_POLE", "member_elements": ["anemo", "pyro"]},
        XIAO_BASE, XIAO_ARTIFACTS, "anemo",
        base._row("plunge", "Plunge DMG", "plunge", 1, XIAO_PLUNGE, None),
        b4._kit("10000026", _giver("Xiao", "10000026", 0, XIAO_BASE,
                                   levels={"elemental_burst": 10},
                                   rows={("elemental_burst", 10): (XIAO_BURST_LABELS,
                                                                   XIAO_BURST_10)}),
                subject=True),
        {"kit:xiao/in_burst": 1, "kit:xiao/a1_stacks": 5, "kit:xiao/a4_stacks": 0}, _xiao))

    out.append(fx(
        "venti_c2_c6_on_xiangling",
        "an enemy RES decrease on the element a teammate's burst absorbed (C6, a choice that "
        "follows the receiver), beside a shred of other elements that misses the row (C2)",
        [FORMULA, f"{PANDO}Venti.ts:80-95,106-109,114-135,163-178"],
        _teammate("Venti", 6, {}),
        {**XIANGLING_TEAM, "member_elements": VENTI_TEAM},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro", nado,
        b4._kit("10000022", _giver("Venti", "10000022", 6, {}), subject=False,
                receiver_element="pyro", team_elements=VENTI_TEAM),
        {"kit:venti/c2_state": "hit", "kit:venti/c4_pickup": 1, "kit:venti/c6_hit": 1,
         "kit:venti/c6_absorbed": "pyro"}, _venti_on_xiangling))

    out.append(fx(
        "nilou_a1_c2_on_nahida",
        "a party EM buff and an enemy RES decrease that hold only in a Hydro and Dendro party "
        "(a team gate), read by a mixed ATK and EM row",
        [FORMULA, f"{PANDO}Nilou.ts:67-71,81-85,104-121,144-161,194-198",
         f"{PANDO}Nahida.ts:246-255"],
        _teammate("Nilou", 2, {}),
        {"element": "dendro", "weapon_type": "WEAPON_CATALYST", "member_elements": NILOU_TEAM},
        b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS, "dendro",
        base._row("karma", "Tri-Karma Purification DMG", "skill", 1, b6.TRI_KARMA_10, None),
        b4._kit("10000070", _giver("Nilou", "10000070", 2, {}), subject=False,
                receiver_element="dendro", team_elements=NILOU_TEAM),
        {"kit:nilou/bounty": 1, "kit:nilou/a1_core": 1, "kit:nilou/c2_hydro": 1,
         "kit:nilou/c2_dendro": 1, "kit:nilou/c4_hit": 0}, _nilou_on_nahida))

    out.append(fx(
        "albedo_c2_on_his_own_burst",
        "self flat damage from his own DEF per stack on his burst (C2), per candidate",
        [FORMULA, f"{PANDO}Albedo.ts:84-91,120,135-140,222,250"],
        _subject("Albedo", 2),
        {"element": "geo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["geo", "pyro"]},
        ALBEDO_BASE, ALBEDO_ARTIFACTS, "geo",
        base._row("burst", "Burst DMG", "burst", 1, ALBEDO_BURST, None),
        b4._kit("10000038", _giver("Albedo", "10000038", 2, ALBEDO_BASE), subject=True),
        {"kit:albedo/low_hp": 0, "kit:albedo/burst_used": 1, "kit:albedo/c2_stacks": 4,
         "kit:albedo/in_field": 1, "kit:albedo/c6_shield": 0}, _albedo))

    out.append(fx(
        "chiori_a4_c6_on_her_own_normal",
        "self flat damage from her own DEF on her Normal Attacks (C6), per candidate, and a "
        "situational Geo DMG bonus (A4) stated on",
        [FORMULA, f"{PANDO}Chiori.ts:61-64,80-83,92,100-108,117-127"],
        _subject("Chiori", 6),
        {"element": "geo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["geo", "geo"]},
        CHIORI_BASE, CHIORI_ARTIFACTS, "geo",
        base._row("na1", "1-Hit DMG", "normal", 1, CHIORI_NA_1, None),
        b4._kit("10000094", _giver("Chiori", "10000094", 6, CHIORI_BASE), subject=True),
        {"kit:chiori/construct": 1}, _chiori))

    out.append(fx(
        "sigewinne_a1_c1_on_xiangling",
        "a party skill flat damage from a teammate's Max HP above a threshold, capped, written "
        "as A1 plus C1's raise of both the share and the cap",
        [FORMULA, f"{PANDO}Sigewinne.ts:64-80,150-169,212"],
        _teammate("Sigewinne", 1, SIGEWINNE_GIVER_STATS),
        {**XIANGLING_TEAM, "member_elements": ["pyro", "hydro"]},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro", guoba,
        b4._kit("10000095", _giver("Sigewinne", "10000095", 1, SIGEWINNE_GIVER_STATS),
                subject=False),
        {"kit:sigewinne/bed_rest": 1, "kit:sigewinne/conva": 1,
         "kit:sigewinne/bubble_tier": 2, "kit:sigewinne/c2_hit": 0},
        _sigewinne_on_xiangling))

    out.append(fx(
        "sethos_a4_c1_c2_on_his_own_shadowpiercing",
        "self flat damage from his own EM scoped to one Normal Attack-talent row GO deals as a "
        "Charged Attack (A4), per candidate, over a mixed ATK and EM row; a CRIT Rate on that "
        "row (C1); an Electro DMG per stack (C2)",
        [FORMULA, f"{PANDO}Sethos.ts:64-77,92-111,123,135-144"],
        _subject("Sethos", 2, {"elemental_burst": 10}),
        {"element": "electro", "weapon_type": "WEAPON_BOW",
         "member_elements": ["electro", "dendro"]},
        SETHOS_BASE, SETHOS_ARTIFACTS, "electro",
        b4._with_hit(base._row("shadow", "Shadowpiercing Shot DMG", "charged", 1, SETHOS_SHADOW,
                               None),
                     "normal_attack", "Shadowpiercing Shot DMG"),
        b4._kit("10000097", _giver("Sethos", "10000097", 2, SETHOS_BASE,
                                   levels={"elemental_burst": 10},
                                   rows={("elemental_burst", 10): (SETHOS_BURST_LABELS,
                                                                   SETHOS_BURST_10)}),
                subject=True),
        {"kit:sethos/twilight": 1, "kit:sethos/sandshade": 1, "kit:sethos/c2_stacks": 2,
         "kit:sethos/c4_two": 0}, _sethos))

    out.append(fx(
        "heizou_declension_c6_on_his_own_skill",
        "a skill multiplier raised per stack by its own talent rows, written as flat damage from "
        "his own ATK on that row (per candidate); a CRIT Rate per stack and a CRIT DMG at four "
        "(C6); a level-13 row (C3)",
        [FORMULA, f"{PANDO}ShikanoinHeizou.ts:46-52,75-78,86-115,124-125,135"],
        _subject("Shikanoin Heizou", 6, {"elemental_skill": 10}),
        {"element": "anemo", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["anemo", "electro"]},
        HEIZOU_BASE, HEIZOU_ARTIFACTS, "anemo",
        b4._with_hit(base._row("skill", "Skill DMG", "skill", 1, HEIZOU_SKILL, None),
                     "elemental_skill", "Skill DMG"),
        b4._kit("10000059", _giver("Shikanoin Heizou", "10000059", 6, HEIZOU_BASE,
                                   levels={"elemental_skill": 10},
                                   rows={("elemental_skill", 13): (HEIZOU_SKILL_LABELS,
                                                                   HEIZOU_SKILL_13)}),
                subject=True),
        {"kit:shikanoin_heizou/declension": 4, "kit:shikanoin_heizou/skill_hit": 1}, _heizou))

    out.append(fx(
        "freminet_a4_c1_c4_c6_on_his_own_pressure",
        "self DMG and CRIT Rate scoped to his Shattering Pressure rows (A4, C1); an ATK% per "
        "stack capped at two stacks of a three-stack condition (C4, two gated effects); a CRIT "
        "DMG per "
        "stack (C6); a level-13 row (C5)",
        [FORMULA, f"{PANDO}Freminet.ts:66-88,96-125,134-135,214-222"],
        _subject("Freminet", 6, {"elemental_skill": 10}),
        {"element": "cryo", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["cryo", "electro"]},
        FREMINET_BASE, FREMINET_ARTIFACTS, "physical",
        b4._with_hit(base._row("level4", "Level 4 Shattering Pressure DMG", "skill", 1,
                               FREMINET_LEVEL_4, None),
                     "elemental_skill", "Level 4 Shattering Pressure DMG"),
        b4._kit("10000085", _giver("Freminet", "10000085", 6, FREMINET_BASE), subject=True),
        {"kit:freminet/stalk": 1, "kit:freminet/shatter": 1, "kit:freminet/c4c6_stacks": 3},
        _freminet))

    out.append(fx(
        "rosaria_a4_c6_on_eula",
        "a CRIT Rate share of a teammate's own CRIT Rate to the others, capped (A4); an enemy "
        "Physical RES decrease (C6)",
        [FORMULA, f"{PANDO}Rosaria.ts:63-67,73-76,84,99-110,119-121"],
        _teammate("Rosaria", 6, ROSARIA_GIVER_STATS),
        {**EULA_TEAM, "member_elements": ["cryo", "cryo"]},
        b5.EULA_BASE, b5.EULA_ARTIFACTS, "physical", eula_na,
        b4._kit("10000045", _giver("Rosaria", "10000045", 6, ROSARIA_GIVER_STATS),
                subject=False),
        {"kit:rosaria/a1_behind": 1, "kit:rosaria/a4_share": 1, "kit:rosaria/c1_crit": 1,
         "kit:rosaria/c6_hit": 1}, _rosaria_on_eula))

    out.append(fx(
        "candace_burst_a4_on_kokomi",
        "a party elemental Normal Attack DMG from a talent row and per 1,000 of a teammate's Max "
        "HP (a cited unit), on a Hydro Normal Attack",
        [FORMULA, f"{PANDO}Candace.ts:51-62,81-89,104-106"],
        _teammate("Candace", 0, CANDACE_GIVER_STATS, {"elemental_burst": 10}),
        {"element": "hydro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["hydro", "hydro"]},
        b6.KOKOMI_BASE, b6.KOKOMI_ARTIFACTS, "hydro",
        base._row("na1", "1-Hit DMG", "normal", 1, b6.KOKOMI_NA_1, None),
        b4._kit("10000072", _giver("Candace", "10000072", 0, CANDACE_GIVER_STATS,
                                   levels={"elemental_burst": 10},
                                   rows={("elemental_burst", 10): (CANDACE_BURST_LABELS,
                                                                   CANDACE_BURST_10)}),
                subject=False),
        {"kit:candace/after_burst": 1, "kit:candace/c2_hit": 0}, _candace_on_kokomi))

    out.append(fx(
        "mika_a1_c6_on_eula",
        "a Physical DMG per stack to the active character, the stack maximum raised by C6 (A1); "
        "a Physical-only CRIT DMG (C6)",
        [FORMULA, f"{PANDO}Mika.ts:62-73,82-115,125-126"],
        _teammate("Mika", 6, {}),
        {**EULA_TEAM, "member_elements": ["cryo", "cryo"]},
        b5.EULA_BASE, b5.EULA_ARTIFACTS, "physical", eula_na,
        b4._kit("10000080", _giver("Mika", "10000080", 6, {}), subject=False),
        {"kit:mika/soulwind": 1, "kit:mika/detector": 5}, _mika_on_eula))

    out.append(fx(
        "diluc_a4_c1_c2_c6_on_his_own_normal",
        "self Pyro DMG in his infusion (A4), a situational DMG (C1) and ATK per stack (C2) stated "
        "on, and a Normal Attack DMG after his skill (C6)",
        [FORMULA, f"{PANDO}Diluc.ts:64-86,93-124,133-145"],
        _subject("Diluc", 6),
        {"element": "pyro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["pyro", "hydro"]},
        DILUC_BASE, DILUC_ARTIFACTS, "pyro",
        base._row("na1", "1-Hit DMG", "normal", 1, DILUC_NA_1, None),
        b4._kit("10000016", _giver("Diluc", "10000016", 6, DILUC_BASE), subject=True),
        {"kit:diluc/infusion": 1, "kit:diluc/c1_above": 1, "kit:diluc/c2_stacks": 3,
         "kit:diluc/c4_rhythm": 1, "kit:diluc/c6_after": 1}, _diluc))

    out.append(fx(
        "klee_a1_c2_c6_on_her_own_charged",
        "a cited Charged Attack DMG (A1), an enemy DEF reduction (C2) and a party Pyro DMG (C6), "
        "all constants GO writes and the seeded lists do not carry",
        [FORMULA_DEF, f"{PANDO}Klee.ts:67-69,84-96,104,125-130,148-151,163-174"],
        _subject("Klee", 6),
        {"element": "pyro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["pyro", "pyro"]},
        KLEE_BASE, KLEE_ARTIFACTS, "pyro",
        base._row("charged", "Charged Attack DMG", "charged", 1, KLEE_CHARGED, None),
        b4._kit("10000029", _giver("Klee", "10000029", 6, KLEE_BASE), subject=True),
        {"kit:klee/spark": 1, "kit:klee/c2_frags": 1, "kit:klee/c6_delight": 1}, _klee))
    out.append(fx(
        "lisa_a4_on_xiangling",
        "an enemy DEF reduction from a teammate's ascension passive (A4)",
        [FORMULA_DEF, f"{PANDO}Lisa.ts:60-63,72,82-84"],
        _teammate("Lisa", 0, {}),
        {**XIANGLING_TEAM, "member_elements": ["pyro", "electro"]},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro", nado,
        b4._kit("10000006", _giver("Lisa", "10000006", 0, {}), subject=False),
        {"kit:lisa/a4_hit": 1}, _lisa_on_xiangling))

    out.append(fx(
        "ningguang_a4_on_chiori",
        "a party Geo DMG from a teammate's ascension passive (A4)",
        [FORMULA, f"{PANDO}Ningguang.ts:49-52,61,70-72"],
        _teammate("Ningguang", 0, {}),
        {"element": "geo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["geo", "geo"]},
        CHIORI_BASE, CHIORI_ARTIFACTS, "geo",
        base._row("na1", "1-Hit DMG", "normal", 1, CHIORI_NA_1, None),
        b4._kit("10000027", _giver("Ningguang", "10000027", 0, {}), subject=False),
        {"kit:ningguang/screen": 1}, _ningguang_on_chiori))

    out.append(fx(
        "chongyun_a4_on_ayaka",
        "an enemy Cryo RES decrease from a teammate's ascension passive (A4), a seeded "
        "parameter published negative",
        [FORMULA, f"{PANDO}Chongyun.ts:61-65,88,102,117"],
        _teammate("Chongyun", 0, {}),
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "cryo"]},
        base.AYAKA_BASE, base.AYAKA_ARTIFACTS, "cryo",
        base._row("press", "Skill DMG", "skill", 1, base.HYOUKA, None),
        b4._kit("10000036", _giver("Chongyun", "10000036", 0, {}), subject=False),
        {"kit:chongyun/a4_hit": 1, "kit:chongyun/c6_lower": 0}, _chongyun_on_ayaka))
    return out
