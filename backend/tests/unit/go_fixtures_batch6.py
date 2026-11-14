"""Math-fallback P2, task 11 (sixth batch): GO fixtures for the fifth batch's leftovers and the
supports and buffers next by use.

Kept beside `test_go_formula_fixtures.py` as the batch modules are, and imported by its
`build()`. The method is unchanged: each figure is worked by hand from Genshin Optimizer's formula
at `2c13fc40` with **our** numbers — talent rows verbatim from the seeded catalogue (nanoka
7.2.51, level 10 unless said; a constellation's +3 reads the level-13 row), constellation and
passive lists the sheets' pins, stated builds. A subject resolves its own sheet against its base
stats; a teammate giver's stats are written out as their pass-1 numbers. Every fixture states
every condition its sources read (`_states_every_condition`), and a row-scoped buff's row names
its talent row (`hit`), so `formula:verify` also checks that the figure misses unnamed.

Nothing here is a test by itself; its fixtures are checked by `test_go_formula_fixtures.py` and
`test_formula_sheets_batch6.py`, and by `npm run formula:verify`.
"""

from __future__ import annotations

from typing import Any

from app.formula.genshin import sheets
from tests.unit import go_fixtures_batch4 as b4
from tests.unit import test_go_formula_fixtures as base

FORMULA = "libs/gi/wr/src/formula.ts:357,434-453,505-514"
FORMULA_DEF = "libs/gi/wr/src/formula.ts:357,434-453,490-514"
PANDO = "libs/gi/formula/src/data/char/"


def _subject(name: str, constellation: int, talent_levels: dict[str, int] | None = None,
             ) -> dict[str, Any]:
    giver: dict[str, Any] = {"name": name, "constellation": constellation, "ascension_phase": 6}
    if talent_levels:
        giver["talent_levels"] = talent_levels
    giver["stats"] = "the optimized character"
    return giver


def _teammate(name: str, constellation: int, stats: dict[str, float],
              talent_levels: dict[str, int] | None = None) -> dict[str, Any]:
    giver: dict[str, Any] = {"name": name, "constellation": constellation, "ascension_phase": 6}
    if talent_levels:
        giver["talent_levels"] = talent_levels
    giver["stats"] = stats
    return giver


def _giver(name: str, nanoka_id: str, constellation: int, stats: dict[str, float], *,
           levels: dict[str, int] | None = None,
           rows: dict[tuple[str, int], tuple[list[str], list[float]]] | None = None,
           ) -> sheets.Giver:
    """A giver at A6 with the sheet's pinned lists; `levels` are the build's **stored** levels
    and `rows` are keyed by the level the sheet reads (stored + its constellation boosts)."""
    cons, pas = base._pinned(nanoka_id)
    return base._ungated_giver(
        name, nanoka_id, constellation=constellation, talent_levels=levels or {},
        talent_rows={k: sheets.TalentRow(*v) for k, v in (rows or {}).items()},
        cons=cons, passives=pas, stats=stats)


def _hit(stats: dict[str, float], *, base_damage: float, flat: float = 0.0, channel: str,
         extra_dmg: float = 0.0, extra_cr: float = 0.0, extra_cd: float = 0.0,
         res: float = 0.1, def_ignore: float = 0.0) -> float:
    return b4._go_hit(base_damage=base_damage, flat=flat,
                      dmg_bonus=stats.get(f"{channel}_dmg_bonus", 0.0) + extra_dmg,
                      crit_rate=stats["crit_rate"] + extra_cr,
                      crit_dmg=stats["crit_dmg"] + extra_cd, res=res, def_ignore=def_ignore)


# ── Chasca: a Shining Shadowhunt Shell, A1 by the absorbable elements (C2 counts one) and C6 ──

#: Her seeded skill row at level 13 (stored 10, +3 from C3).
CHASCA_SHINING = ("Shining Shadowhunt Shell DMG|{param4:F1P}", [1.275, 0.765, 1.037, 3.539655])
CHASCA_BASE = base._base_stats(base_atk=980.0, base_hp=9796.0, base_def=615.0, crit_rate=0.242)
CHASCA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "pyro_dmg_bonus": 0.466,
                    "crit_rate": 0.3, "crit_dmg": 0.6}
#: Two absorbable elements present (Pyro twice, Hydro); her C2 counts one more: three.
CHASCA_TEAM = ["anemo", "pyro", "pyro", "hydro"]


def _chasca(_: float) -> float:
    """**Chasca, C6, on her own Shining Shadowhunt Shell** (a Pyro one), in Multitarget Fire with
    Fatal Rounds: A1's DMG at three absorbable elements (Pyro and Hydro present, her C2's one
    more: `passive1[5]`, 65%), C6's 120% CRIT DMG, both inside that row's formula.

    GO: `customDmg('skill_shiningShellDmg_pyro', 'pyro', 'charged', prod(talent, final.atk),
    undefined, ownBuff.premod.dmg_.charged.add(a1), ownBuff.premod.critDMG_.add(c6))`
    (`pando Chasca.ts:160-173`); `phecElements = min(sum(cmpGE(count[ele], 1, 1)…, cmpGE(
    constellation, 2, 1)), 3)` and `subscript(phec, [-1, …passive1[3..5]])` (`:62-74,104-121`);
    C6 `constellation6[1]` (`:89-92,122-124`)."""
    stats = base._stats(CHASCA_BASE, CHASCA_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(CHASCA_SHINING) * base._total(stats, "atk"),
                channel="pyro", extra_dmg=0.65, extra_cd=1.2)


# ── Kinich: his Scalespiker Cannon, A4's flat damage per stack, C1, C2 ───────────────────────

KINICH_CANNON = ("Scalespiker Cannon DMG|{param2:F1P}", [1.03104, 12.37392])
KINICH_BASE = base._base_stats(base_atk=940.0, base_hp=12991.0, base_def=809.0, crit_dmg=0.884)
KINICH_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "dendro_dmg_bonus": 0.466,
                    "crit_rate": 0.3, "crit_dmg": 0.6}


def _kinich(_: float) -> float:
    """**Kinich, C2, on his own Scalespiker Cannon**, the first of a Blessing, two A4 stacks:
    A4 adds 320% of his ATK per stack to the cannon's base, per candidate; C1's 100% CRIT DMG and
    C2's 100% DMG on the cannon alone; C2's Dendro RES -30% after it hits.

    GO: `dmg('skill_cannon', …, ...cannonExtras)` (`pando Kinich.ts:142-150`), `cannonExtras` =
    `formula.base.add(prod(a4Stacks, percent(passive2[1]), final.atk))`, `premod.critDMG_.skill.
    add(constellation1[2])`, `premod.dmg_.skill.add(c2FirstHit constellation2[2])`
    (`:59-72,93-118`); `enemyDebuff.common.preRes.dendro.add(-constellation2[0])` (`:103-105,
    132`)."""
    stats = base._stats(KINICH_BASE, KINICH_ARTIFACTS)
    atk = base._total(stats, "atk")
    return _hit(stats, base_damage=base._multiplier(KINICH_CANNON) * atk, flat=2 * 3.2 * atk,
                channel="dendro", extra_dmg=1.0, extra_cd=1.0, res=0.1 - 0.3)


# ── Wanderer: a Windfavored Normal Attack, A1 from Pyro and Cryo ─────────────────────────────

WANDERER_NA_1 = ("1-Hit DMG|{param1:F1P}", [1.3583])
WANDERER_SKILL_LABELS = ["Skill DMG|{param1:F1P}",
                         "Kuugo: Fushoudan DMG|{param2:F1P} Normal Attack DMG",
                         "Kuugo: Toufukai DMG|{param3:F1P} Charged Attack DMG",
                         "Initial Kuugoryoku Points|{param4:I}", "CD|{param5:F1}s"]
WANDERER_SKILL_10 = [1.7136, 1.5372, 1.42976, 100.0, 6.0, 0.0, 0.5372, 0.42976]
WANDERER_BASE = base._base_stats(base_atk=870.0, base_hp=10164.0, base_def=607.0,
                                 crit_rate=0.242)
WANDERER_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "anemo_dmg_bonus": 0.466,
                      "crit_rate": 0.3, "crit_dmg": 0.7}
WANDERER_TEAM = ["anemo", "pyro", "cryo", "hydro"]


def _wanderer(_: float) -> float:
    """**Wanderer, C0, on his own 1-Hit DMG** in Windfavored, having absorbed Pyro and Cryo: the
    skill row's 153.72% as the Normal Attack's base multiplier, A1's 30% ATK and 20% CRIT Rate.

    GO: `dmg('normal_0', …, 'normal', { baseMulti: afterSkill.ifOn(percent(talentSubscript(skill,
    normal_mult)), 1) })` (`pando Wanderer.ts:43-46,112-115,177-181`); A1 `premod.atk_` and
    `premod.critRate_` (`:55-61,120-133,170-171`)."""
    stats = base._stats(WANDERER_BASE, WANDERER_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=0.3)
    return _hit(stats, base_damage=base._multiplier(WANDERER_NA_1) * atk * 1.5372,
                channel="anemo", extra_cr=0.2)


# ── Keqing: her burst's Last Attack, A4, C4, C6 ─────────────────────────────────────────────

#: Her seeded burst row at level 13 (stored 10, +3 from C3).
KEQING_LAST = ("Last Attack DMG|{param3:P}", [1.87, 0.51, 4.012])
KEQING_BASE = base._base_stats(base_atk=931.0, base_hp=13103.0, base_def=799.0, crit_dmg=0.884)
KEQING_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "electro_dmg_bonus": 0.466,
                    "crit_rate": 0.3, "crit_dmg": 0.7}


def _keqing(_: float) -> float:
    """**Keqing, C6, on her own Last Attack**, after her burst and an Electro reaction, four C6
    stacks: A4's 15% CRIT Rate, C4's 25% ATK, C6's 6% Electro DMG per stack.

    GO: `dmg('burst_final', …)` (`pando Keqing.ts:152`); `premod.critRate_` A4 (`:61-65,94-98,
    118`), `premod.atk_` C4 (`:69-72,100-104,120`), `premod.dmg_.electro` C6 × stacks
    (`:73-76,105-109,121`)."""
    stats = base._stats(KEQING_BASE, KEQING_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=0.25)
    return _hit(stats, base_damage=base._multiplier(KEQING_LAST) * atk, channel="electro",
                extra_dmg=4 * 0.06, extra_cr=0.15)


# ── Sangonomiya Kokomi: a Normal Attack in her burst, A4 on her innate Healing Bonus ─────────

KOKOMI_NA_1 = ("1-Hit DMG|{param1:F1P}", [1.230768])
KOKOMI_BURST_LABELS = ["Skill DMG|{param1:F1P} Max HP",
                       "Normal Attack DMG Bonus|{param4:F1P} Max HP",
                       "Charged Attack DMG Bonus|{param5:F1P} Max HP",
                       "Bake-Kurage DMG Bonus|{param9:F1P} Max HP"]
KOKOMI_BURST_10 = [0.187488, 0.014544, 169.49507, 0.08712, 0.121968, 10.0, 18.0, 70.0, 0.127734]
KOKOMI_BASE = base._base_stats(base_atk=744.0, base_hp=13471.0, base_def=657.0)
KOKOMI_BASE["hydro_dmg_bonus"] = 0.288
KOKOMI_ARTIFACTS = {"hp_pct": 0.932, "flat_hp": 4780.0, "flat_atk": 311.0,
                    "hydro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}


def _kokomi(_: float) -> float:
    """**Sangonomiya Kokomi, C0, on her own 1-Hit DMG** in Nereid's Ascension: the burst row's
    8.712% of her Max HP and A4's 15% of her innate 25% Healing Bonus, of her Max HP, both added
    to the base per candidate; her innate CRIT Rate -100%, so no hit crits (rate clamped at 0).

    GO: `ownBuff.formula.base.normal.add(burst.ifOn(prod(own.premod.hp, sum(talent nBonus_,
    a4))))`, `a4 = prod(percent(passive2[0]), own.premod.heal_)` with `heal_` 0.25
    (`pando SangonomiyaKokomi.ts:59-65,93-108,141,146`); `premod.critRate_` -1 (`:94,142`);
    `avgHit` clamps the rate (`formula.ts:434-453`)."""
    stats = base._stats(KOKOMI_BASE, KOKOMI_ARTIFACTS)
    hp = base._total(stats, "hp")
    return _hit(stats, base_damage=base._multiplier(KOKOMI_NA_1) * base._total(stats, "atk"),
                flat=(0.08712 + 0.15 * 0.25) * hp, channel="hydro", extra_cr=-1.0)


# ── Yae Miko: a Level 4 Sesshou Sakura, A4 from her EM, C4, C6's DEF ignore ──────────────────

#: Her seeded skill row at level 13 (stored 10, +3 from C3).
YAE_SAKURA_4 = ("Sesshou Sakura DMG: Level 4|{param4:F1P}", [1.28928, 1.6116, 2.0145, 2.518125])
YAE_BASE = base._base_stats(base_atk=882.0, base_hp=10372.0, base_def=569.0, crit_rate=0.242)
YAE_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "electro_dmg_bonus": 0.466,
                 "crit_rate": 0.3, "crit_dmg": 0.7, "elemental_mastery": 187.0}


def _yae(_: float) -> float:
    """**Yae Miko, C6, on her own Level 4 Sesshou Sakura**, its lightning having hit: A4's 0.15%
    skill DMG per point of EM (per candidate), C4's 20% Electro DMG to the party (her included),
    C6's 60% DEF ignore on the Level 2-4 rows.

    GO: `dmg('skill_4', …, enemyDebuff.common.defIgn.add(c6_defIgn_))` (`pando YaeMiko.ts:
    206-214`); A4 `premod.dmg_.skill.add(prod(final.eleMas, percent(passive2[0])))` (`:64-66,
    142-146,171`); C4 `teamBuff.premod.dmg_.electro` (`:89-95,130-134,174`); C6
    `constellation6[0]` (`:96-99,138`); `enemy.def` with `defIgn` (`formula.ts:490-510`)."""
    stats = base._stats(YAE_BASE, YAE_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(YAE_SAKURA_4) * base._total(stats, "atk"),
                channel="electro", extra_dmg=0.2 + 0.0015 * stats["elemental_mastery"],
                def_ignore=0.6)


def _yae_on_raiden(_: float) -> float:
    """**Yae Miko's C4 on Raiden Shogun's Musou no Hitotachi**: 20% Electro DMG to the party.

    GO: `teamBuff.premod.dmg_.electro.add(c4.map({hit: constellation4[0]}))` (`pando YaeMiko.ts:
    89-95,130-134,174`)."""
    stats = base._stats(b4.RAIDEN_BASE, b4.RAIDEN_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(b4.RAIDEN_INITIAL) * base._total(stats, "atk"),
                channel="electro", extra_dmg=0.2)


# ── Kamisato Ayato: a Shunsuiken slash at five Namisen stacks, C2's HP, his burst ───────────

AYATO_SHUN_1 = ("Shunsuiken 1-Hit DMG|{param1:F1P}", [1.0455])
AYATO_SKILL_LABELS = ["Shunsuiken 1-Hit DMG|{param1:F1P}", "Shunsuiken 2-Hit DMG|{param2:F1P}",
                      "Shunsuiken 3-Hit DMG|{param3:F1P}",
                      "Takimeguri Kanka Duration|{param4:F1}s",
                      "Namisen DMG Bonus|{param5:F2P}Max HP/Stack",
                      "Water Illusion DMG|{param6:F1P}", "Water Illusion Duration|{param7:I}s",
                      "CD|{param8:F1}s"]
AYATO_SKILL_10 = [1.0455, 1.1645, 1.2835, 6.0, 0.011091, 2.006, 6.0, 12.0]
AYATO_BURST_LABELS = ["Bloomwater Blade DMG|{param1:F1P}",
                      "Normal Attack DMG Bonus|{param2:F1P}", "Duration|{param3:F1}s",
                      "CD|{param4:F1}s", "Energy Cost|{param5:I}"]
AYATO_BURST_10 = [1.196208, 0.2, 18.0, 20.0, 80.0]
AYATO_BASE = base._base_stats(base_atk=973.0, base_hp=13715.0, base_def=769.0, crit_dmg=0.884)
AYATO_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "hp_pct": 0.2, "flat_hp": 4780.0,
                   "hydro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}


def _ayato(_: float) -> float:
    """**Kamisato Ayato, C2, on his own Shunsuiken 1-Hit DMG** (a skill-talent row GO deals as a
    Normal Attack) at five Namisen stacks (C2 raises the maximum from four): 1.1091% of his Max HP
    per stack added to the base, per candidate; C2's 50% Max HP at three stacks or more; his
    burst's 20% Normal Attack DMG, which reaches him as the active character.

    GO: `customDmg('skill_dmg0', 'hydro', 'normal', prod(talent, final.atk), undefined,
    ownBuff.formula.base.add(prod(namisenStacks, percent(stackHpDmgInc), final.hp)))`
    (`pando KamisatoAyato.ts:100-110,129-141,163-165`), `namisenStacks` 5 only at C2 (`:100-105`);
    C2 `premod.hp_` (`:75-79,114-122,150`); `teamBuff.premod.dmg_.normal` to the active one
    (`:55-60,123-125,152`)."""
    stats = base._stats(AYATO_BASE, AYATO_ARTIFACTS)
    hp = base._total(stats, "hp", extra_pct=0.5)
    return _hit(stats, base_damage=base._multiplier(AYATO_SHUN_1) * base._total(stats, "atk"),
                flat=5 * 0.011091 * hp, channel="hydro", extra_dmg=0.2)


# ── Baizhu's C4 on Nahida's Tri-Karma ───────────────────────────────────────────────────────

#: Nahida's seeded skill row at level 10 (C0, no boost).
TRI_KARMA_10 = ("Tri-Karma Purification DMG|{param3:F1P} ATK+{param4:F1P} Elemental Mastery",
                [1.7712, 2.3472, 1.8576, 3.7152])


def _baizhu_on_nahida(_: float) -> float:
    """**Baizhu's C4 on Nahida's Tri-Karma Purification**: 80 EM to the party after his burst,
    read by the hit's EM term.

    GO: `teamBuff.premod.eleMas.add(c4AfterBurst.ifOn(constellation4[0]))` (`pando Baizhu.ts:
    88-91,148-150,175`); Tri-Karma `splitScaleDmg(['atk', 'eleMas'])` (`pando Nahida.ts:
    246-255`)."""
    stats = base._stats(b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS)
    params = TRI_KARMA_10[1]
    return _hit(stats, base_damage=params[2] * base._total(stats, "atk")
                + params[3] * (stats["elemental_mastery"] + 80.0), channel="dendro")


# ── Dehya: Flame-Mane's Fist, C1's HP and flat damage, C6 ───────────────────────────────────

#: Her seeded burst row at level 13 (stored 10, +3 from C3).
DEHYA_FIST = ("Flame-Mane's Fist DMG|{param1:F1P} ATK+{param2:F2P} Max HP",
              [2.097375, 0.035955])
DEHYA_BASE = base._base_stats(base_atk=775.0, base_hp=15675.0, hp_pct=0.288, base_def=627.0)
DEHYA_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "flat_hp": 4780.0,
                   "pyro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.7}


def _dehya(_: float) -> float:
    """**Dehya, C6, on her own Flame-Mane's Fist** (ATK and HP parts), four C6 stacks: C1's 20%
    Max HP and 6% of her Max HP added to the burst's base, per candidate; C6's 10% burst CRIT
    Rate and 15% CRIT DMG per stack.

    GO: `splitScaleDmg('burst_fist', ['atk', 'hp'], …)` (`pando Dehya.ts:154-160`); C1
    `premod.hp_` and `formula.base.burst.add(prod(percent(c1[2]), own.premod.hp))` (`:70-74,
    101-111,129-131`); C6 (`:84-90,115-120,132-133`)."""
    stats = base._stats(DEHYA_BASE, DEHYA_ARTIFACTS)
    hp = base._total(stats, "hp", extra_pct=0.2)
    atk = base._total(stats, "atk")
    return _hit(stats, base_damage=DEHYA_FIST[1][0] * atk + DEHYA_FIST[1][1] * hp,
                flat=0.06 * hp, channel="pyro", extra_cr=0.1, extra_cd=4 * 0.15)


# ── Layla's C4 on Xiangling's Normal Attack ─────────────────────────────────────────────────

LAYLA_GIVER_STATS = {"base_hp": 11092.0, "hp_pct": 1.1, "flat_hp": 4780.0}


def _layla_on_xiangling(_: float) -> float:
    """**Layla's C4 on Xiangling's 1-Hit DMG** (Physical): 5% of Layla's pass-1 Max HP, 28,073.2
    (11,092 × 2.1 + 4,780), added to the party's Normal Attack base.

    GO: `teamBuff.formula.base.normal.add(c4Active.ifOn(prod(percent(constellation4[0]),
    final.hp)))` (`pando Layla.ts:69-73,113-119,135`)."""
    stats = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)
    layla_hp = (LAYLA_GIVER_STATS["base_hp"] * (1 + LAYLA_GIVER_STATS["hp_pct"])
                + LAYLA_GIVER_STATS["flat_hp"])
    return _hit(stats, base_damage=base._multiplier(b4.XIANGLING_NA_1) * base._total(stats, "atk"),
                flat=0.05 * layla_hp, channel="physical")


# ── Kirara: her burst, A4 per 1,000 Max HP ──────────────────────────────────────────────────

KIRARA_BURST = ("Skill DMG|{param1:F1P}", [10.26432])
KIRARA_BASE = base._base_stats(base_atk=677.0, base_hp=12180.0, hp_pct=0.24, base_def=546.0)
KIRARA_ARTIFACTS = {"hp_pct": 0.932, "flat_hp": 4780.0, "flat_atk": 311.0,
                    "dendro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}


def _kirara(_: float) -> float:
    """**Kirara, C0, on her own burst**: A4's 0.3% burst DMG per 1,000 Max HP, per candidate.

    GO: `premod.dmg_.burst.add(prod(percent(passive2[1]), final.hp, 1 / 1000))` (`pando
    Kirara.ts:77-80,113-117,165`)."""
    stats = base._stats(KIRARA_BASE, KIRARA_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(KIRARA_BURST) * base._total(stats, "atk"),
                channel="dendro", extra_dmg=0.003 * base._total(stats, "hp") / 1000)


# ── Lynette's A1 on Xiangling ───────────────────────────────────────────────────────────────

LYNETTE_TEAM = ["anemo", "pyro", "hydro", "cryo"]


def _lynette_on_xiangling(_: float) -> float:
    """**Lynette's A1 on Xiangling's Pyronado** in a party of four different elements: 20% ATK
    (`passive1[4]`, the fourth entry of GO's table by element count).

    GO: `teamBuff.premod.atk_.add(a1AfterBurst.ifOn(subscript(own.common.eleCount, [0,
    …passive1[1..4]])))` (`pando Lynette.ts:62-71,89-95,119`)."""
    stats = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(base.PYRONADO)
                * base._total(stats, "atk", extra_pct=0.2), channel="pyro")


# ── Thoma: Fiery Collapse, A4 from his Max HP ───────────────────────────────────────────────

THOMA_COLLAPSE = ("Fiery Collapse DMG|{param2:P}", [1.584, 1.044])
THOMA_BASE = base._base_stats(base_atk=733.0, atk_pct=0.24, base_hp=10331.0, base_def=751.0)
THOMA_ARTIFACTS = {"hp_pct": 0.466, "flat_hp": 4780.0, "flat_atk": 311.0,
                   "pyro_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}


def _thoma(_: float) -> float:
    """**Thoma, C0, on his own Fiery Collapse**: A4's 2.2% of his Max HP added to that row's
    base, per candidate.

    GO: `dmg('collapseDmg', …, ownBuff.formula.base.add(prod(percent(passive2[0]),
    final.hp)))` (`pando Thoma.ts:67-69,102-106,165-173`)."""
    stats = base._stats(THOMA_BASE, THOMA_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(THOMA_COLLAPSE) * base._total(stats, "atk"),
                flat=0.022 * base._total(stats, "hp"), channel="pyro")


# ── Beidou's, Ororon's and Iansan's buffs on Raiden Shogun's initial slash ───────────────────


def _raiden(*, extra_atk_pct: float = 0.0, flat_atk: float = 0.0, extra_dmg: float = 0.0,
            res: float = 0.1) -> float:
    stats = base._stats(b4.RAIDEN_BASE, b4.RAIDEN_ARTIFACTS)
    atk = base._total(stats, "atk", extra_pct=extra_atk_pct) + flat_atk
    return _hit(stats, base_damage=base._multiplier(b4.RAIDEN_INITIAL) * atk, channel="electro",
                extra_dmg=extra_dmg, res=res)


def _beidou_on_raiden(_: float) -> float:
    """**Beidou's C6 on Raiden Shogun's initial slash**: Electro RES -15% during her burst.

    GO: `enemyDebuff.common.preRes.electro.add(burst.ifOn(constellation6.electroResShred_))`,
    `-1 × constellation6[0]` (`pando Beidou.ts:86-90,137-141`)."""
    return _raiden(res=0.1 - 0.15)


def _ororon_on_raiden(_: float) -> float:
    """**Ororon's C6 on Raiden Shogun's initial slash**, three stacks: 10% ATK each to the active
    character.

    GO: `teamBuff.premod.atk_.add(prod(cmpGE(constellation, 6, prod(percent(c6[0]), c6Stacks)),
    destIsActive))` (`pando Ororon.ts:73-78,105-108,120`)."""
    return _raiden(extra_atk_pct=3 * 0.1)


#: Iansan's seeded burst row at level 13 (stored 10, +3 from C5): the 27% conversion, and the
#: Max ATK Bonus, 810 (690 at level 10), which binds here.
IANSAN_BURST_LABELS = ["Skill DMG|{param1:F1P}",
                       "High Nightsoul Points ATK Conversion Rate|{param2:P} ATK",
                       ("Low Nightsoul Points ATK Conversion Rate|{param3:F1P} ATK / Nightsoul "
                        "Point"), "Max ATK Bonus|{param4:F1}"]
IANSAN_BURST_13 = [9.146, 0.27, 0.005, 810.0, 1.0, 12.0, 18.0, 70.0]
IANSAN_GIVER_STATS = {"base_atk": 917.0, "atk_pct": 2.0, "flat_atk": 311.0}


def _iansan_on_raiden(_: float) -> float:
    """**Iansan, C6, on Raiden Shogun's initial slash**: her burst at 42 Nightsoul points or more
    gives the active character 27% of her pass-1 ATK (3,062 → 826.74), capped at the level-13
    row's 810; C2's 30% ATK while she is off the field; C6's 25% DMG.

    GO: `teamBuff.final.atk.add(cmpNE(destIsActive, 0, min(cmpGE(burstNs, 42, prod(percent(
    highAtkConversion), own.premod.atk), …), talentSubscript(burst, maxAtk))))` (`pando
    Iansan.ts:48-57,97-115,135`); C2 `teamBuff.premod.atk_` (`:75-78,120-122,136`); C6
    `teamBuff.premod.dmg_` (`:83-87,123-125,137`)."""
    iansan_atk = (IANSAN_GIVER_STATS["base_atk"] * (1 + IANSAN_GIVER_STATS["atk_pct"])
                  + IANSAN_GIVER_STATS["flat_atk"])
    return _raiden(extra_atk_pct=0.3, flat_atk=min(0.27 * iansan_atk, 810.0), extra_dmg=0.25)


# ── Lan Yan: Feathermoon Ring, A4 from her EM ───────────────────────────────────────────────

LAN_YAN_RING = ("Feathermoon Ring DMG|{param1:F1P}", [1.732608])
LAN_YAN_BASE = base._base_stats(base_atk=705.0, atk_pct=0.24, base_hp=9243.0, base_def=576.0)
LAN_YAN_ARTIFACTS = {"atk_pct": 0.466, "flat_atk": 311.0, "elemental_mastery": 200.0,
                     "anemo_dmg_bonus": 0.466, "crit_rate": 0.3, "crit_dmg": 0.6}


def _lan_yan(_: float) -> float:
    """**Lan Yan, C0, on her own Feathermoon Ring**: A4's 309% of her EM added to the skill's
    base, per candidate.

    GO: `ownBuff.formula.base.skill.add(prod(percent(passive2[0]), final.eleMas))` (`pando
    LanYan.ts:56-59,78-82,99`)."""
    stats = base._stats(LAN_YAN_BASE, LAN_YAN_ARTIFACTS)
    return _hit(stats, base_damage=base._multiplier(LAN_YAN_RING) * base._total(stats, "atk"),
                flat=3.09 * stats["elemental_mastery"], channel="anemo")


def batch6_fixtures() -> list[dict[str, Any]]:
    """Task 11, sixth batch: one fixture per sheet on its main damage effect, plus Yae Miko's C4
    on a teammate."""
    fx = base._buffer
    out: list[dict[str, Any]] = []

    out.append(fx(
        "chasca_a1_c6_on_her_own_shining_shell",
        "a table read by the count of distinct elements of a kind, with a constellation counting "
        "one more (A1), and a CRIT DMG buff, both scoped to rows of her skill talent",
        [FORMULA, f"{PANDO}Chasca.ts:62-74,89-92,104-124,160-173"],
        _subject("Chasca", 6, {"elemental_skill": 10}),
        {"element": "anemo", "weapon_type": "WEAPON_BOW", "member_elements": CHASCA_TEAM},
        CHASCA_BASE, CHASCA_ARTIFACTS, "pyro",
        b4._with_hit(base._row("shining", "Shining Shadowhunt Shell DMG", "charged", 1,
                               CHASCA_SHINING, None),
                     "elemental_skill", "Shining Shadowhunt Shell DMG"),
        b4._kit("10000104", _giver("Chasca", "10000104", 6, CHASCA_BASE), subject=True,
                receiver_element="anemo", team_elements=CHASCA_TEAM),
        {"kit:chasca/multitarget": 1, "kit:chasca/fatal": 1}, _chasca))

    out.append(fx(
        "kinich_a4_c2_on_his_own_cannon",
        "self flat damage from his own ATK per stack, CRIT DMG and DMG, all scoped to one skill "
        "row; an enemy Dendro RES decrease",
        [FORMULA, f"{PANDO}Kinich.ts:59-72,93-118,132,142-150"],
        _subject("Kinich", 2),
        {"element": "dendro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["dendro", "pyro"]},
        KINICH_BASE, KINICH_ARTIFACTS, "dendro",
        b4._with_hit(base._row("cannon", "Scalespiker Cannon DMG", "skill", 1, KINICH_CANNON,
                               None),
                     "elemental_skill", "Scalespiker Cannon DMG"),
        b4._kit("10000101", _giver("Kinich", "10000101", 2, KINICH_BASE), subject=True),
        {"kit:kinich/a4_stacks": 2, "kit:kinich/c2_hit": 1, "kit:kinich/c2_first": 1},
        _kinich))

    out.append(fx(
        "wanderer_windfavored_on_his_own_normal",
        "a skill row read as a Normal Attack's whole multiplier (a base multiplier less 1); self "
        "ATK and CRIT Rate gated on the party holding the element absorbed (A1)",
        [FORMULA, f"{PANDO}Wanderer.ts:43-46,55-61,104-133,170-181"],
        _subject("Wanderer", 0, {"elemental_skill": 10}),
        {"element": "anemo", "weapon_type": "WEAPON_CATALYST",
         "member_elements": WANDERER_TEAM},
        WANDERER_BASE, WANDERER_ARTIFACTS, "anemo",
        base._row("na1", "1-Hit DMG", "normal", 1, WANDERER_NA_1, None),
        b4._kit("10000075", _giver("Wanderer", "10000075", 0, WANDERER_BASE,
                                   levels={"elemental_skill": 10},
                                   rows={("elemental_skill", 10): (WANDERER_SKILL_LABELS,
                                                                   WANDERER_SKILL_10)}),
                subject=True, receiver_element="anemo", team_elements=WANDERER_TEAM),
        {"kit:wanderer/windfavored": 1, "kit:wanderer/pyro_contact": 1,
         "kit:wanderer/cryo_contact": 1}, _wanderer))

    out.append(fx(
        "keqing_a4_c4_c6_on_her_own_burst",
        "self CRIT Rate and ATK on toggles, Electro DMG per stack; a level-13 burst row (C3)",
        [FORMULA, f"{PANDO}Keqing.ts:61-76,84-109,118-121,152"],
        _subject("Keqing", 6, {"elemental_burst": 10}),
        {"element": "electro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["electro", "dendro"]},
        KEQING_BASE, KEQING_ARTIFACTS, "electro",
        base._row("last", "Last Attack DMG", "burst", 1, KEQING_LAST, None),
        b4._kit("10000042", _giver("Keqing", "10000042", 6, KEQING_BASE), subject=True),
        {"kit:keqing/after_burst": 1, "kit:keqing/reacted": 1, "kit:keqing/c6_stacks": 4},
        _keqing))

    out.append(fx(
        "kokomi_burst_a4_on_her_own_normal",
        "self flat damage from her own Max HP (a burst row, and A4 times a cited constant), per "
        "candidate; a CRIT Rate of -100%, a cited constant",
        [FORMULA, f"{PANDO}SangonomiyaKokomi.ts:59-65,93-108,141-146,152"],
        _subject("Sangonomiya Kokomi", 0, {"elemental_burst": 10}),
        {"element": "hydro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["hydro", "pyro"]},
        KOKOMI_BASE, KOKOMI_ARTIFACTS, "hydro",
        base._row("na1", "1-Hit DMG", "normal", 1, KOKOMI_NA_1, None),
        b4._kit("10000054", _giver("Sangonomiya Kokomi", "10000054", 0, KOKOMI_BASE,
                                   levels={"elemental_burst": 10},
                                   rows={("elemental_burst", 10): (KOKOMI_BURST_LABELS,
                                                                   KOKOMI_BURST_10)}),
                subject=True),
        {"kit:sangonomiya_kokomi/ascension": 1}, _kokomi))

    out.append(fx(
        "yae_miko_a4_c6_on_her_own_sakura",
        "self DMG from her own EM per candidate (A4), a party Electro DMG (C4), DEF ignore scoped "
        "to her Level 2-4 Sakura rows (C6)",
        [FORMULA_DEF, f"{PANDO}YaeMiko.ts:64-66,89-99,130-146,171-174,206-214"],
        _subject("Yae Miko", 6, {"elemental_skill": 10}),
        {"element": "electro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["electro", "electro"]},
        YAE_BASE, YAE_ARTIFACTS, "electro",
        b4._with_hit(base._row("sakura4", "Sesshou Sakura DMG: Level 4", "skill", 1,
                               YAE_SAKURA_4, None),
                     "elemental_skill", "Sesshou Sakura DMG: Level 4"),
        b4._kit("10000058", _giver("Yae Miko", "10000058", 6, YAE_BASE), subject=True),
        {"kit:yae_miko/c4_hit": 1}, _yae))

    out.append(fx(
        "yae_miko_c4_on_raiden",
        "a party Electro DMG from a teammate's constellation (C4)",
        [FORMULA, f"{PANDO}YaeMiko.ts:89-95,130-134,174"],
        _teammate("Yae Miko", 4, {}),
        {"element": "electro", "weapon_type": "WEAPON_POLE",
         "member_elements": ["electro", "electro"]},
        b4.RAIDEN_BASE, b4.RAIDEN_ARTIFACTS, "electro",
        base._row("initial", "Musou no Hitotachi Base DMG", "burst", 1, b4.RAIDEN_INITIAL, None),
        b4._kit("10000058", _giver("Yae Miko", "10000058", 4, {}), subject=False),
        {"kit:yae_miko/c4_hit": 1}, _yae_on_raiden))

    out.append(fx(
        "ayato_namisen_c2_on_his_own_shunsuiken",
        "self flat damage from his own Max HP per stack, scoped to his Shunsuiken rows (skill-"
        "talent rows dealt as Normal Attacks), the stack maximum raised by C2; a Max HP buff at "
        "three stacks or more; his burst's Normal Attack DMG to the active character, him",
        [FORMULA, f"{PANDO}KamisatoAyato.ts:43-60,75-79,95-125,129-141,150-152"],
        _subject("Kamisato Ayato", 2, {"elemental_skill": 10, "elemental_burst": 10}),
        {"element": "hydro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["hydro", "pyro"]},
        AYATO_BASE, AYATO_ARTIFACTS, "hydro",
        b4._with_hit(base._row("shun1", "Shunsuiken 1-Hit DMG", "normal", 1, AYATO_SHUN_1,
                               None),
                     "elemental_skill", "Shunsuiken 1-Hit DMG"),
        b4._kit("10000066", _giver("Kamisato Ayato", "10000066", 2, AYATO_BASE,
                                   levels={"elemental_skill": 10, "elemental_burst": 10},
                                   rows={("elemental_skill", 10): (AYATO_SKILL_LABELS,
                                                                   AYATO_SKILL_10),
                                         ("elemental_burst", 10): (AYATO_BURST_LABELS,
                                                                   AYATO_BURST_10)}),
                subject=True),
        {"kit:kamisato_ayato/namisen": 5, "kit:kamisato_ayato/in_area": 1,
         "kit:kamisato_ayato/low_hp": 0}, _ayato))

    out.append(fx(
        "baizhu_c4_on_nahida",
        "a party EM buff from a teammate's constellation, read by a mixed ATK and EM row",
        [FORMULA, f"{PANDO}Baizhu.ts:88-91,148-150,175", f"{PANDO}Nahida.ts:246-255"],
        _teammate("Baizhu", 4, {}),
        {"element": "dendro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["dendro", "dendro"]},
        b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS, "dendro",
        base._row("karma", "Tri-Karma Purification DMG", "skill", 1, TRI_KARMA_10, None),
        b4._kit("10000082", _giver("Baizhu", "10000082", 4, {}), subject=False),
        {"kit:baizhu/c4_after": 1}, _baizhu_on_nahida))

    out.append(fx(
        "dehya_c1_c6_on_her_own_fist",
        "self Max HP and flat damage from her own Max HP on her burst (C1), per candidate, over a "
        "mixed ATK and HP row; burst CRIT Rate and CRIT DMG per stack (C6); a level-13 row (C3)",
        [FORMULA, f"{PANDO}Dehya.ts:70-74,84-90,99-120,129-133,154-160"],
        _subject("Dehya", 6, {"elemental_burst": 10}),
        {"element": "pyro", "weapon_type": "WEAPON_CLAYMORE",
         "member_elements": ["pyro", "hydro"]},
        DEHYA_BASE, DEHYA_ARTIFACTS, "pyro",
        base._row("fist", "Flame-Mane's Fist DMG", "burst", 1, DEHYA_FIST, None),
        b4._kit("10000079", _giver("Dehya", "10000079", 6, DEHYA_BASE), subject=True),
        {"kit:dehya/c2_field": 0, "kit:dehya/c6_stacks": 4}, _dehya))

    out.append(fx(
        "layla_c4_on_xiangling",
        "a party Normal Attack flat damage from a teammate's Max HP (C4)",
        [FORMULA, f"{PANDO}Layla.ts:69-73,113-119,135"],
        _teammate("Layla", 4, LAYLA_GIVER_STATS),
        {"element": "pyro", "weapon_type": "WEAPON_POLE", "member_elements": ["pyro", "cryo"]},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "physical",
        base._row("na1", "1-Hit DMG", "normal", 1, b4.XIANGLING_NA_1, None),
        b4._kit("10000074", _giver("Layla", "10000074", 4, LAYLA_GIVER_STATS), subject=False),
        {"kit:layla/c4_active": 1}, _layla_on_xiangling))

    out.append(fx(
        "kirara_a4_on_her_own_burst",
        "self DMG per 1,000 of her own Max HP, a cited unit, per candidate (A4)",
        [FORMULA, f"{PANDO}Kirara.ts:77-80,106-117,164-165,210"],
        _subject("Kirara", 0),
        {"element": "dendro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["dendro", "hydro"]},
        KIRARA_BASE, KIRARA_ARTIFACTS, "dendro",
        base._row("burst", "Skill DMG", "burst", 1, KIRARA_BURST, None),
        b4._kit("10000061", _giver("Kirara", "10000061", 0, KIRARA_BASE), subject=True),
        {}, _kirara))

    out.append(fx(
        "lynette_a1_on_xiangling",
        "a party ATK% read from a table by the number of distinct elements (A1)",
        [FORMULA, f"{PANDO}Lynette.ts:62-71,89-95,119"],
        _teammate("Lynette", 0, {}),
        {"element": "pyro", "weapon_type": "WEAPON_POLE", "member_elements": LYNETTE_TEAM},
        base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS, "pyro",
        base._row("nado", "Pyronado DMG", "burst", 1, base.PYRONADO, None),
        b4._kit("10000083", _giver("Lynette", "10000083", 0, {}), subject=False,
                receiver_element="pyro", team_elements=LYNETTE_TEAM),
        {"kit:lynette/a1_after": 1}, _lynette_on_xiangling))

    out.append(fx(
        "thoma_a4_on_his_own_collapse",
        "self flat damage from his own Max HP scoped to one burst row (A4), per candidate",
        [FORMULA, f"{PANDO}Thoma.ts:67-69,102-106,165-173"],
        _subject("Thoma", 0),
        {"element": "pyro", "weapon_type": "WEAPON_POLE", "member_elements": ["pyro", "dendro"]},
        THOMA_BASE, THOMA_ARTIFACTS, "pyro",
        b4._with_hit(base._row("collapse", "Fiery Collapse DMG", "burst", 1, THOMA_COLLAPSE,
                               None),
                     "elemental_burst", "Fiery Collapse DMG"),
        b4._kit("10000050", _giver("Thoma", "10000050", 0, THOMA_BASE), subject=True),
        {}, _thoma))

    raiden_team = {"element": "electro", "weapon_type": "WEAPON_POLE",
                   "member_elements": ["electro", "electro"]}
    musou = base._row("initial", "Musou no Hitotachi Base DMG", "burst", 1, b4.RAIDEN_INITIAL,
                      None)
    out.append(fx(
        "beidou_c6_on_raiden",
        "an enemy Electro RES decrease from a teammate's constellation during her burst (C6)",
        [FORMULA, f"{PANDO}Beidou.ts:86-90,113-115,137-141"],
        _teammate("Beidou", 6, {}), raiden_team, b4.RAIDEN_BASE, b4.RAIDEN_ARTIFACTS,
        "electro", musou,
        b4._kit("10000024", _giver("Beidou", "10000024", 6, {}), subject=False),
        {"kit:beidou/storm": 1}, _beidou_on_raiden))

    out.append(fx(
        "ororon_c6_on_raiden",
        "an ATK% per stack to the active character from a teammate's constellation (C6)",
        [FORMULA, f"{PANDO}Ororon.ts:73-78,105-108,120"],
        _teammate("Ororon", 6, {}), raiden_team, b4.RAIDEN_BASE, b4.RAIDEN_ARTIFACTS,
        "electro", musou,
        b4._kit("10000105", _giver("Ororon", "10000105", 6, {}), subject=False),
        {"kit:ororon/c6_stacks": 3}, _ororon_on_raiden))

    out.append(fx(
        "iansan_burst_c2_c6_on_raiden",
        "flat ATK to the active character from a share of the giver's ATK, capped by a talent row "
        "at her boosted level (the burst); ATK% to the others (C2); DMG to the active character "
        "(C6)",
        [FORMULA, f"{PANDO}Iansan.ts:48-57,75-87,95-125,135-137"],
        _teammate("Iansan", 6, IANSAN_GIVER_STATS, {"elemental_burst": 10}),
        raiden_team, b4.RAIDEN_BASE, b4.RAIDEN_ARTIFACTS, "electro", musou,
        b4._kit("10000110", _giver("Iansan", "10000110", 6, IANSAN_GIVER_STATS,
                                   levels={"elemental_burst": 10},
                                   rows={("elemental_burst", 13): (IANSAN_BURST_LABELS,
                                                                   IANSAN_BURST_13)}),
                subject=False),
        {"kit:iansan/high_points": 1, "kit:iansan/precise": 1, "kit:iansan/c6_extreme": 1},
        _iansan_on_raiden))

    out.append(fx(
        "lan_yan_a4_on_her_own_ring",
        "self flat damage from her own EM on her skill (A4), per candidate",
        [FORMULA, f"{PANDO}LanYan.ts:56-59,78-82,99,111"],
        _subject("Lan Yan", 0),
        {"element": "anemo", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["anemo", "pyro"]},
        LAN_YAN_BASE, LAN_YAN_ARTIFACTS, "anemo",
        base._row("ring", "Feathermoon Ring DMG", "skill", 1, LAN_YAN_RING, None),
        b4._kit("10000108", _giver("Lan Yan", "10000108", 0, LAN_YAN_BASE), subject=True),
        {}, _lan_yan))
    return out
