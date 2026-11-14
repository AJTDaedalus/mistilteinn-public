"""Math-fallback P2, task 11 (eighth batch): GO fixtures for the small sheets of ordinary buffs.

Kept beside `test_go_formula_fixtures.py` as the batch modules are, and imported by its
`build()`. The method is unchanged: each figure is worked by hand from Genshin Optimizer's formula
at `2c13fc40` with **our** numbers — talent rows verbatim from the seeded catalogue (nanoka
7.2.51, level 10 unless said; a constellation's +3 reads the level-13 row), constellation and
passive lists the sheets' pins, stated builds. A subject resolves its own sheet against its base
stats; a teammate giver's stats are written out as their pass-1 numbers (none of these teammates'
buffs reads one). Every fixture states every condition its sources read
(`_states_every_condition`), and a row-scoped buff's row names its talent row (`hit`), so
`formula:verify` also checks that the figure misses unnamed.

Nothing here is a test by itself; its fixtures are checked by `test_go_formula_fixtures.py` and
`test_formula_sheets_batch8.py`, and by `npm run formula:verify`.
"""

from __future__ import annotations

from typing import Any

from tests.unit import go_fixtures_batch4 as b4
from tests.unit import go_fixtures_batch6 as b6
from tests.unit import go_fixtures_batch7 as b7
from tests.unit import test_go_formula_fixtures as base

FORMULA = b7.FORMULA
FORMULA_DEF = b7.FORMULA_DEF
PANDO = b7.PANDO

_subject = b6._subject
_teammate = b6._teammate
_giver = b6._giver
_hit = b7._hit

ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "crit_rate": 0.3, "crit_dmg": 0.6}


def _nahida(*, em: float = 0.0, dmg: float = 0.0) -> float:
    """Nahida's Tri-Karma Purification (level 10, ATK and EM parts) with a teammate's EM or
    Dendro DMG added: GO `splitScaleDmg(['atk', 'eleMas'])` (`pando Nahida.ts:246-255`)."""
    stats = base._stats(b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS)
    params = b6.TRI_KARMA_10[1]
    return _hit(stats, base_damage=params[2] * base._total(stats, "atk")
                + params[3] * (stats["elemental_mastery"] + em), channel="dendro",
                extra_dmg=dmg)


# ── Amber: her burst, A1, A4 and C6 ─────────────────────────────────────────────────────────

#: Her seeded burst row at level 13 (stored 10, +3 from C3).
AMBER_WAVE = ("Fiery Rain DMG Per Wave|{param1:F1P}", [0.5967])
AMBER_BASE = base._base_stats(base_atk=733.0, atk_pct=0.24, base_hp=9461.0, base_def=601.0)
AMBER_ARTIFACTS = {**ARTIFACTS, "pyro_dmg_bonus": 0.466}


def _amber(_: float) -> float:
    """**Amber, C6, on her own Fiery Rain wave** after a weak-spot hit, in her burst: A1's 10%
    burst CRIT Rate, A4's 15% ATK and C6's 15% party ATK.

    GO: `dmgPerWave` (`pando Amber.ts:121`); `premod.critRate_.burst` (`:92-94`), `premod.atk_`
    from A4 (`:95-97`) and from C6 into `teamBuff` (`:101-103`)."""
    stats = base._stats(AMBER_BASE, AMBER_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=0.15 + 0.15)
    return _hit(stats, base_damage=base._multiplier(AMBER_WAVE) * atk, channel="pyro",
                extra_cr=0.1)


# ── Xinyan: her Charged Attack, A4, C4 and C6 ──────────────────────────────────────────────

XINYAN_FINAL = ("Charged Attack Final DMG|{param6:P}",
                [1.513, 1.462, 1.887, 2.2899, 1.236364, 2.2355])
XINYAN_BASE = base._base_stats(base_atk=759.0, atk_pct=0.24, base_hp=11201.0, base_def=799.0)
XINYAN_ARTIFACTS = {**ARTIFACTS, "def_pct": 0.3, "physical_dmg_bonus": 0.583}


def _xinyan(_: float) -> float:
    """**Xinyan, C6, on her own Charged Attack Final DMG** (Physical), shielded, the opponent hit
    by her swing: A4's 15% Physical DMG, C4's Physical RES -15%, C6's ATK + 50% of her DEF.

    GO: `charged_final` (`pando Xinyan.ts:138`); `teamBuff.premod.dmg_.physical` (`:121-123`);
    `enemyDebuff.common.preRes.physical` (`:127-129`); `ownBuff.premod.atk.add(prod(final.def,
    c6))` (`:108-112,131`)."""
    stats = base._stats(XINYAN_BASE, XINYAN_ARTIFACTS)
    atk = base._total(stats, "atk") + 0.5 * base._total(stats, "def")
    return _hit(stats, base_damage=base._multiplier(XINYAN_FINAL) * atk, channel="physical",
                extra_dmg=0.15, res=0.1 - 0.15)


# ── Yanfei: a three-Seal Charged Attack, her burst, A1 and C2 ──────────────────────────────

YANFEI_CHARGED_3 = ("Charged Attack|{param7:P}",
                    [1.050149, 0.938261, 1.36823, 1.599904, 1.88224, 2.164576, 2.446912])
YANFEI_BURST_LABELS = ["Skill DMG|{param1:P}", "", "Scarlet Seal Grant Interval|{param4:F1}s",
                       "Charged Attack DMG Bonus|{param2:P}", "Duration|{param3:F1}s",
                       "CD|{param5:F1}s", "Energy Cost|{param6:I}"]
YANFEI_BURST_10 = [3.2832, 0.544, 15.0, 1.0, 20.0, 80.0]
YANFEI_BASE = base._base_stats(base_atk=782.0, base_hp=9352.0, base_def=587.0)
YANFEI_BASE["pyro_dmg_bonus"] = 0.24
YANFEI_ARTIFACTS = {**ARTIFACTS, "pyro_dmg_bonus": 0.466}


def _yanfei(_: float) -> float:
    """**Yanfei, C2, on her own three-Seal Charged Attack** after her burst, the opponent below
    half HP: the burst row's 54.4% Charged Attack DMG, A1's 5% Pyro DMG per Seal, C2's 20%
    Charged Attack CRIT Rate.

    GO: `charged_3` (`pando Yanfei.ts:128-132`); `afterBurst_charged_dmg_` (`:101-103,121`);
    `p1_pyro_dmg_ = prod(p1Seals, passive1)` (`:104-108,123`); `c2EnemyHp_critRate_`
    (`:109-111,122`)."""
    stats = base._stats(YANFEI_BASE, YANFEI_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(YANFEI_CHARGED_3) * base._total(stats, "atk"),
                channel="pyro", extra_dmg=0.544 + 3 * 0.05, extra_cr=0.2)


# ── Barbara: C2 on Kokomi ───────────────────────────────────────────────────────────────────


def _barbara_on_kokomi(_: float) -> float:
    """**Barbara's C2 on Kokomi's 1-Hit DMG** (Hydro, no Kokomi kit applied), Kokomi active in
    the Melody Loop: 15% Hydro DMG.

    GO: `teamBuff.premod.dmg_.hydro.add(c2.ifOn(cmpNE(destIsActive, 0, 0.15)))` (`pando
    Barbara.ts:66-69,84-90,104`)."""
    stats = base._stats(b6.KOKOMI_BASE, b6.KOKOMI_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(b6.KOKOMI_NA_1) * base._total(stats, "atk"),
                channel="hydro", extra_dmg=0.15)


# ── Razor: his 1-Hit DMG, C1, C2 and C4 ────────────────────────────────────────────────────

RAZOR_NA_1 = ("1-Hit DMG|{param1:P}", [1.7113])
RAZOR_BASE = base._base_stats(base_atk=842.0, base_hp=11962.0, base_def=751.0)
RAZOR_BASE["physical_dmg_bonus"] = 0.3
RAZOR_ARTIFACTS = {**ARTIFACTS, "physical_dmg_bonus": 0.583}


def _razor(_: float) -> float:
    """**Razor, C4, on his own 1-Hit DMG** (Physical) after an orb, the opponent below 30% HP and
    hit by his pressed skill: C1's 10% DMG, C2's 10% CRIT Rate, C4's DEF -15%.

    GO: `normal_0` (`pando Razor.ts:158`); `all_dmg_` (`:118-120,153`), `critRate_`
    (`:121-123,154`), `enemyDefRed_` into `enemyDebuff.common.defRed_` (`:124-126,156`)."""
    stats = base._stats(RAZOR_BASE, RAZOR_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(RAZOR_NA_1) * base._total(stats, "atk"),
                channel="physical", extra_dmg=0.1, extra_cr=0.1, def_reduction=0.15)


# ── Kaeya and Qiqi: a 1-Hit DMG against a Cryo-affected opponent ───────────────────────────

KAEYA_NA_1 = ("1-Hit DMG|{param1:P}", [1.0625])
KAEYA_BASE = base._base_stats(base_atk=788.0, base_hp=11636.0, base_def=792.0)
QIQI_NA_1 = ("1-Hit DMG|{param1:F1P}", [0.7463])
QIQI_BASE = base._base_stats(base_atk=850.0, base_hp=12368.0, base_def=922.0)
PHYSICAL_ARTIFACTS = {**ARTIFACTS, "physical_dmg_bonus": 0.583}


def _kaeya(_: float) -> float:
    """**Kaeya, C1, on his own 1-Hit DMG** (Physical) against a Cryo-affected opponent: 15%
    CRIT Rate.

    GO: `normal_0` (`pando Kaeya.ts:90-92`); `c1CritRate_` into `premod.critRate_.normal`
    (`:55-57,73-80,86`)."""
    stats = base._stats(KAEYA_BASE, PHYSICAL_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(KAEYA_NA_1) * base._total(stats, "atk"),
                channel="physical", extra_cr=0.15)


def _qiqi(_: float) -> float:
    """**Qiqi, C2, on her own 1-Hit DMG** (Physical) against a Cryo-affected opponent: 15%
    Normal Attack DMG.

    GO: `normal_0` (`pando Qiqi.ts:167-169`); `c2_naCa_dmg_` into `premod.dmg_.normal`
    (`:114,154`)."""
    stats = base._stats(QIQI_BASE, PHYSICAL_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(QIQI_NA_1) * base._total(stats, "atk"),
                channel="physical", extra_dmg=0.15)


# ── Sayu: a held Whirlwind Kick at ten half-seconds (C2) ───────────────────────────────────

SAYU_HOLD = ("Fuufuu Whirlwind Kick Hold DMG|{param4:F1P}", [0.648, 0.3024, 2.8512, 3.9168])
SAYU_BASE = base._base_stats(base_atk=735.0, base_hp=11854.0, base_def=745.0,
                             elemental_mastery=96.0)
SAYU_ARTIFACTS = {**ARTIFACTS, "anemo_dmg_bonus": 0.466}
SAYU_HALF_SECONDS = 10


def _sayu(_: float) -> float:
    """**Sayu, C2, on her own held Whirlwind Kick** after ten half-seconds in the Windwheel: 3.3%
    skill DMG per half-second on that row.

    GO: `kickHoldDmg` with `ownBuff.premod.dmg_.skill.add(prod(c2SkillStack, c2))` inside its own
    formula (`pando Sayu.ts:72-75,101-105,148-156`)."""
    stats = base._stats(SAYU_BASE, SAYU_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(SAYU_HOLD) * base._total(stats, "atk"),
                channel="anemo", extra_dmg=SAYU_HALF_SECONDS * 0.033)


# ── Diona, Collei, Yaoyao on Nahida ────────────────────────────────────────────────────────

NAHIDA_TEAM = {"element": "dendro", "weapon_type": "WEAPON_CATALYST"}


def _diona_on_nahida(_: float) -> float:
    """**Diona's C6 on Nahida's Tri-Karma Purification**, Nahida above half HP in the field:
    200 EM to the active character, read by the row's EM term.

    GO: `teamBuff.premod.eleMas.add(cmpNE(destIsActive, 0, Constellation6.map({higher: 200})))`
    (`pando Diona.ts:82-87,142-150,181`)."""
    return _nahida(em=200.0)


def _collei_on_nahida(_: float) -> float:
    """**Collei's C4 on Nahida's Tri-Karma Purification** after Collei's burst: 60 EM to the
    others.

    GO: `notOwnBuff.premod.eleMas.add(afterBurst.ifOn(c4))` (`pando Collei.ts:71-74,
    100-102`)."""
    return _nahida(em=60.0)


def _yaoyao_on_nahida(_: float) -> float:
    """**Yaoyao's C1 on Nahida's Tri-Karma Purification**, a radish exploded on Nahida: 15%
    Dendro DMG to the active character.

    GO: `teamBuff.premod.dmg_.dendro.add(cmpNE(destIsActive, 0, c1Explode.ifOn(c1)))` (`pando
    Yaoyao.ts:71-76,106-108,130-132`)."""
    return _nahida(dmg=0.15)


# ── Gaming: Charmed Cloudstrider, A4, C2 and C6 ────────────────────────────────────────────

#: His seeded skill row at level 13 (stored 10, +3 from C3).
GAMING_CLOUD = ("Plunging Attack: Charmed Cloudstrider DMG|{param1:F1P}", [4.896])
GAMING_BASE = base._base_stats(base_atk=843.0, atk_pct=0.24, base_hp=11419.0, base_def=703.0)
GAMING_ARTIFACTS = {**ARTIFACTS, "pyro_dmg_bonus": 0.466}


def _gaming(_: float) -> float:
    """**Gaming, C6, on his own Charmed Cloudstrider** at 50% HP or more, after overflowing
    healing: A4's 20% DMG on that row, C2's 20% ATK, C6's 20% CRIT Rate and 40% CRIT DMG on
    that row.

    GO: `skill_cloudstrider` with A4 and C6 inside its formula (`pando Gaming.ts:95-109,
    133-144`); `premod.atk_` from C2 (`:121-123`)."""
    stats = base._stats(GAMING_BASE, GAMING_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=0.2)
    return _hit(stats, base_damage=base._multiplier(GAMING_CLOUD) * atk, channel="pyro",
                extra_dmg=0.2, extra_cr=0.2, extra_cd=0.4)


# ── Fischl: Summoning DMG with C2 ──────────────────────────────────────────────────────────

FISCHL_SUMMON = ("Summoning DMG|{param2:P}", [1.5984, 2.07792])
FISCHL_BASE = base._base_stats(base_atk=754.0, atk_pct=0.24, base_hp=9189.0, base_def=594.0)
FISCHL_ARTIFACTS = {**ARTIFACTS, "electro_dmg_bonus": 0.466}


def _fischl(_: float) -> float:
    """**Fischl, C2, on her own Summoning DMG**: 200% of her ATK added to the row's multiplier.

    GO: `skill_summon = prod(sum(summonDmg, cmpGE(constellation, 2, c2)), final.atk)` (`pando
    Fischl.ts:73-75,136-146`)."""
    stats = base._stats(FISCHL_BASE, FISCHL_ARTIFACTS)
    atk = base._total(stats, "atk")
    return _hit(stats, base_damage=base._multiplier(FISCHL_SUMMON) * atk, flat=2.0 * atk,
                channel="electro")


# ── Mualani: a Surging Bite, the first of her skill (C1) ───────────────────────────────────

MUALANI_SKILL_LABELS = ["Sharky's Bite Base DMG|{param1:F2P} Max HP",
                        "Wave Momentum DMG Bonus|{param2:F2P} Max HP/Stack",
                        "Sharky's Surging Bite Additional DMG Bonus|{param3:F2P} Max HP",
                        "Sharky's Bite CD|{param4:F1}s", "Nightsoul Point Limit|{param5:F1}",
                        "CD|{param6:F1}s"]
MUALANI_SKILL_10 = [0.15624, 0.07812, 0.3906, 1.8, 60.0, 6.0]
MUALANI_BITE = ("Sharky's Bite Base DMG|{param1:F2P} Max HP", [0.15624])
MUALANI_BASE = base._base_stats(base_atk=616.0, base_hp=15185.0, base_def=569.0,
                                crit_rate=0.242)
MUALANI_ARTIFACTS = {"hp_pct": 0.932, "flat_hp": 4780.0, "flat_atk": 311.0,
                     "hydro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}


def _mualani(_: float) -> float:
    """**Mualani, C1, on her own Sharky's Bite** at three Wave Momentum stacks (a Surging
    Bite), the first of her skill: 7.812% of her Max HP per stack, the Surging Bite's 39.06%,
    and C1's 66%, all added to the bite's base.

    GO: `sharkBite('skill_surgingDmg', surging_bite_dmgInc)` with `surging_bite_dmgInc =
    sum(prod(3, wave), prod(surgingDmgBonus, final.hp))` (`pando Mualani.ts:88-96,122-132,155`);
    the C1 row adds `prod(c1, final.hp)` to it (`:111-115,156-163`)."""
    stats = base._stats(MUALANI_BASE, MUALANI_ARTIFACTS)
    hp = base._total(stats, "hp")
    return _hit(stats, base_damage=base._multiplier(MUALANI_BITE) * hp,
                flat=(3 * 0.07812 + 0.3906 + 0.66) * hp, channel="hydro")


# ── Flins: a Manifest Flame 1-Hit, C2 and C4 ───────────────────────────────────────────────

FLINS_NA_1 = ("1-Hit DMG|{param1:F1P}", [1.048464])
FLINS_BASE = base._base_stats(base_atk=1018.0, base_hp=12491.0, base_def=809.0,
                              crit_dmg=0.884)
FLINS_ARTIFACTS = {**ARTIFACTS, "electro_dmg_bonus": 0.466}


def _flins(_: float) -> float:
    """**Flins, C4, on his own Manifest Flame 1-Hit DMG** (a skill row GO deals as an Electro
    Normal Attack), the opponent hit by his Electro DMG under Ascendant Gleam: C2's Electro RES
    -25%, C4's 20% ATK.

    GO: `skill_na1` (`pando Flins.ts:193-200`); `c2_electro_enemyRes_` (`:81-86,124-130,176`);
    `c4_atk_` (`:87-91,131,177`)."""
    stats = base._stats(FLINS_BASE, FLINS_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(FLINS_NA_1)
                * base._total(stats, "atk", extra_pct=0.2), channel="electro", res=0.1 - 0.25)


def batch8_fixtures() -> list[dict[str, Any]]:
    """Task 11, eighth batch: one fixture per sheet on its main damage effect."""
    fx = base._buffer
    out: list[dict[str, Any]] = []
    karma = base._row("karma", "Tri-Karma Purification DMG", "skill", 1, b6.TRI_KARMA_10, None)

    out.append(fx(
        "amber_a1_a4_c6_on_her_own_burst",
        "a self burst CRIT Rate (A1), a self ATK% after a weak-spot hit (A4) and a party ATK% "
        "(C6) on her own level-13 burst row (C3)",
        [FORMULA, f"{PANDO}Amber.ts:56-62,70-74,83,88-103,121"],
        _subject("Amber", 6, {"elemental_burst": 10}),
        {"element": "pyro", "weapon_type": "WEAPON_BOW", "member_elements": ["pyro", "hydro"]},
        AMBER_BASE, AMBER_ARTIFACTS, "pyro",
        base._row("wave", "Fiery Rain DMG Per Wave", "burst", 1, AMBER_WAVE, None),
        b4._kit("10000021", _giver("Amber", "10000021", 6, AMBER_BASE), subject=True),
        {"kit:amber/a4_weak": 1, "kit:amber/c2_manual": 0, "kit:amber/c6_rain": 1}, _amber))

    out.append(fx(
        "xinyan_a4_c4_c6_on_her_own_charged",
        "a party Physical DMG while shielded (A4), an enemy Physical RES decrease published "
        "negative (C4), and ATK from her own DEF on her Charged Attacks, per candidate (C6)",
        [FORMULA, f"{PANDO}Xinyan.ts:69-71,80-87,96,108-112,121-131,138"],
        _subject("Xinyan", 6),
        {"element": "pyro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["pyro", "cryo"]},
        XINYAN_BASE, XINYAN_ARTIFACTS, "physical",
        base._row("final", "Charged Attack Final DMG", "charged", 1, XINYAN_FINAL, None),
        b4._kit("10000044", _giver("Xinyan", "10000044", 6, XINYAN_BASE), subject=True),
        {"kit:xinyan/shielded": 1, "kit:xinyan/c4_hit": 1}, _xinyan))

    out.append(fx(
        "yanfei_burst_a1_c2_on_her_own_charged",
        "a self Charged Attack DMG from a talent row (burst), a Pyro DMG per Seal consumed (A1) "
        "and a situational Charged Attack CRIT Rate stated on (C2)",
        [FORMULA, f"{PANDO}Yanfei.ts:62-83,98-111,121-132"],
        _subject("Yanfei", 2, {"elemental_burst": 10}),
        {"element": "pyro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["pyro", "electro"]},
        YANFEI_BASE, YANFEI_ARTIFACTS, "pyro",
        base._row("charged", "Charged Attack", "charged", 1, YANFEI_CHARGED_3, None),
        b4._kit("10000048", _giver("Yanfei", "10000048", 2, YANFEI_BASE,
                                   levels={"elemental_burst": 10},
                                   rows={("elemental_burst", 10): (YANFEI_BURST_LABELS,
                                                                   YANFEI_BURST_10)}),
                subject=True),
        {"kit:yanfei/after_burst": 1, "kit:yanfei/seals": 3, "kit:yanfei/c2_low": 1}, _yanfei))

    out.append(fx(
        "barbara_c2_on_kokomi",
        "a Hydro DMG to the active character in a teammate's skill, a constant GO and gcsim "
        "write and the seeded list does not carry (C2)",
        [FORMULA, f"{PANDO}Barbara.ts:66-69,78,84-90,104"],
        _teammate("Barbara", 2, {}),
        {"element": "hydro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["hydro", "hydro"]},
        b6.KOKOMI_BASE, b6.KOKOMI_ARTIFACTS, "hydro",
        base._row("na1", "1-Hit DMG", "normal", 1, b6.KOKOMI_NA_1, None),
        b4._kit("10000014", _giver("Barbara", "10000014", 2, {}), subject=False),
        {"kit:barbara/c2_skill": 1}, _barbara_on_kokomi))

    out.append(fx(
        "razor_c1_c2_c4_on_his_own_normal",
        "a self DMG bonus (C1), a situational CRIT Rate stated on (C2) and an enemy DEF "
        "reduction (C4), each a constant the seeded lists do not carry",
        [FORMULA_DEF, f"{PANDO}Razor.ts:80-91,107-109,118-126,153-158"],
        _subject("Razor", 4),
        {"element": "electro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["electro", "electro"]},
        RAZOR_BASE, RAZOR_ARTIFACTS, "physical",
        base._row("na1", "1-Hit DMG", "normal", 1, RAZOR_NA_1, None),
        b4._kit("10000020", _giver("Razor", "10000020", 4, RAZOR_BASE), subject=True),
        {"kit:razor/c1_orb": 1, "kit:razor/c2_low": 1, "kit:razor/c4_press": 1}, _razor))

    out.append(fx(
        "kaeya_c1_on_his_own_normal",
        "a Normal and Charged Attack CRIT Rate against a Cryo-affected opponent, a constant the "
        "seeded list does not carry (C1)",
        [FORMULA, f"{PANDO}Kaeya.ts:55-57,71-80,86-92"],
        _subject("Kaeya", 1),
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "hydro"]},
        KAEYA_BASE, PHYSICAL_ARTIFACTS, "physical",
        base._row("na1", "1-Hit DMG", "normal", 1, KAEYA_NA_1, None),
        b4._kit("10000015", _giver("Kaeya", "10000015", 1, KAEYA_BASE), subject=True),
        {"kit:kaeya/cryo": 1}, _kaeya))

    out.append(fx(
        "qiqi_c2_on_her_own_normal",
        "a Normal and Charged Attack DMG against a Cryo-affected opponent, GO's literal beside "
        "a seeded list that carries the Hexerei ATK instead (C2)",
        [FORMULA, f"{PANDO}Qiqi.ts:103-105,114,154-155,167-169"],
        _subject("Qiqi", 2),
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "hydro"]},
        QIQI_BASE, PHYSICAL_ARTIFACTS, "physical",
        base._row("na1", "1-Hit DMG", "normal", 1, QIQI_NA_1, None),
        b4._kit("10000035", _giver("Qiqi", "10000035", 2, QIQI_BASE), subject=True),
        {"kit:qiqi/cryo": 1}, _qiqi))

    out.append(fx(
        "sayu_c2_on_her_own_hold_kick",
        "a self skill DMG per half-second held, scoped to the held kick's rows (C2)",
        [FORMULA, f"{PANDO}Sayu.ts:72-75,94,101-105,148-156"],
        _subject("Sayu", 2),
        {"element": "anemo", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["anemo", "pyro"]},
        SAYU_BASE, SAYU_ARTIFACTS, "anemo",
        b4._with_hit(base._row("hold", "Fuufuu Whirlwind Kick Hold DMG", "skill", 1, SAYU_HOLD,
                               None),
                     "elemental_skill", "Fuufuu Whirlwind Kick Hold DMG"),
        b4._kit("10000053", _giver("Sayu", "10000053", 2, SAYU_BASE), subject=True),
        {"kit:sayu/hold": SAYU_HALF_SECONDS}, _sayu))

    out.append(fx(
        "diona_c6_on_nahida",
        "an EM buff to the active character in a teammate's field (C6), read by a mixed ATK and "
        "EM row",
        [FORMULA, f"{PANDO}Diona.ts:82-87,97,142-150,181", f"{PANDO}Nahida.ts:246-255"],
        _teammate("Diona", 6, {}),
        {**NAHIDA_TEAM, "member_elements": ["dendro", "cryo"]},
        b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS, "dendro", karma,
        b4._kit("10000039", _giver("Diona", "10000039", 6, {}), subject=False),
        {"kit:diona/c6_above": 1}, _diona_on_nahida))

    out.append(fx(
        "collei_c4_on_nahida",
        "an EM buff to the others after a teammate's burst (C4), read by a mixed ATK and EM row",
        [FORMULA, f"{PANDO}Collei.ts:71-74,86,100-102", f"{PANDO}Nahida.ts:246-255"],
        _teammate("Collei", 4, {}),
        {**NAHIDA_TEAM, "member_elements": ["dendro", "dendro"]},
        b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS, "dendro", karma,
        b4._kit("10000067", _giver("Collei", "10000067", 4, {}), subject=False),
        {"kit:collei/after_burst": 1}, _collei_on_nahida))

    out.append(fx(
        "yaoyao_c1_on_nahida",
        "a Dendro DMG to the active character when a teammate's radish explodes on them (C1)",
        [FORMULA, f"{PANDO}Yaoyao.ts:71-76,98,106-108,130-132", f"{PANDO}Nahida.ts:246-255"],
        _teammate("Yaoyao", 1, {}),
        {**NAHIDA_TEAM, "member_elements": ["dendro", "dendro"]},
        b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS, "dendro", karma,
        b4._kit("10000077", _giver("Yaoyao", "10000077", 1, {}), subject=False),
        {"kit:yaoyao/c1_radish": 1}, _yaoyao_on_nahida))

    out.append(fx(
        "gaming_a4_c2_c6_on_his_own_cloudstrider",
        "a skill-talent row GO deals as a Plunging Attack (a row move), with a DMG bonus (A4) "
        "and CRIT Rate and CRIT DMG (C6) scoped to it, both situational ones stated on, a self "
        "ATK% (C2), on his level-13 row (C3)",
        [FORMULA, f"{PANDO}Gaming.ts:60-78,87-109,121-123,133-144"],
        _subject("Gaming", 6, {"elemental_skill": 10}),
        {"element": "pyro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["pyro", "anemo"]},
        GAMING_BASE, GAMING_ARTIFACTS, "pyro",
        b4._with_hit(base._row("cloud", "Plunging Attack: Charmed Cloudstrider DMG", "plunge", 1,
                               GAMING_CLOUD, None),
                     "elemental_skill", "Plunging Attack: Charmed Cloudstrider DMG"),
        b4._kit("10000092", _giver("Gaming", "10000092", 6, GAMING_BASE), subject=True),
        {"kit:gaming/a4_hp": 1, "kit:gaming/c2_overheal": 1}, _gaming))

    out.append(fx(
        "fischl_c2_on_her_own_summoning",
        "self flat damage from her own ATK scoped to one skill row (C2), per candidate",
        [FORMULA, f"{PANDO}Fischl.ts:73-75,136-146"],
        _subject("Fischl", 2),
        {"element": "electro", "weapon_type": "WEAPON_BOW",
         "member_elements": ["electro", "pyro"]},
        FISCHL_BASE, FISCHL_ARTIFACTS, "electro",
        b4._with_hit(base._row("summon", "Summoning DMG", "skill", 1, FISCHL_SUMMON, None),
                     "elemental_skill", "Summoning DMG"),
        b4._kit("10000031", _giver("Fischl", "10000031", 2, FISCHL_BASE), subject=True),
        {}, _fischl))

    out.append(fx(
        "mualani_momentum_surging_c1_on_her_own_bite",
        "three flat damages from her own Max HP on one skill row GO deals as a Normal Attack "
        "(a row move): per Wave Momentum stack (talent row), at three stacks (talent row) and "
        "on the first bite (C1), per candidate",
        [FORMULA, f"{PANDO}Mualani.ts:42-45,68-71,88-96,111-115,122-132,152-163"],
        _subject("Mualani", 1, {"elemental_skill": 10}),
        {"element": "hydro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["hydro", "pyro"]},
        MUALANI_BASE, MUALANI_ARTIFACTS, "hydro",
        b4._with_hit(base._row("bite", "Sharky's Bite Base DMG", "normal", 1, MUALANI_BITE,
                               None),
                     "elemental_skill", "Sharky's Bite Base DMG"),
        b4._kit("10000102", _giver("Mualani", "10000102", 1, MUALANI_BASE,
                                   levels={"elemental_skill": 10},
                                   rows={("elemental_skill", 10): (MUALANI_SKILL_LABELS,
                                                                   MUALANI_SKILL_10)}),
                subject=True),
        {"kit:mualani/momentum": 3, "kit:mualani/c1_first": 1, "kit:mualani/puffer": 0},
        _mualani))

    out.append(fx(
        "flins_c2_c4_on_his_own_manifest_flame",
        "a self ATK% (C4) and an enemy Electro RES decrease published positive and negated, "
        "behind two conditions, one a party composition stated on (C2), on a skill row GO deals "
        "as a Normal Attack",
        [FORMULA, f"{PANDO}Flins.ts:81-91,104-105,124-131,176-177,193-200"],
        _subject("Flins", 4),
        {"element": "electro", "weapon_type": "WEAPON_POLE",
         "member_elements": ["electro", "hydro"]},
        FLINS_BASE, FLINS_ARTIFACTS, "electro",
        base._row("na1", "1-Hit DMG", "normal", 1, FLINS_NA_1, None),
        b4._kit("10000120", _giver("Flins", "10000120", 4, FLINS_BASE), subject=True),
        {"kit:flins/c2_hit": 1, "kit:flins/moonsign": 1}, _flins))
    return out
