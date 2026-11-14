"""Math-fallback P3 (task 13): GO fixtures for transformative, additive and Lunar reactions.

Kept beside `test_go_formula_fixtures.py` as the batch modules are, and imported by its
`build()`. Each figure is worked by hand from Genshin Optimizer's reaction formulas at
`2c13fc40` with **our** numbers: the level base is the committed game table
(`reaction_level_multiplier(90)`), set and sheet values resolve our pinned lists, builds are
stated. `formula:verify` replays each through the browser's recipe, and its planted checks apply
(no sources must miss; a kit effect 1% off must miss).

## GO's reaction formulas, as these figures use them

    transformative = multi × lvl × (1 + 16·EM/(2000 + EM) + <r>_dmg_)       # trans.ts:36-108
                     × (1 + clamp(<r>_critRate_) × <r>_critDMG_)            # :53-102, canCrit
                     × enemy.transDef × resMulti                            # :103-104
    additive       = (base + lvl × {1.25 | 1.15} × (1 + 5·EM/(1200 + EM) + <r>_dmg_))
                     × (1 + dmgBonus) × avgHit × enemy.def × resMulti       # formula.ts:405-453
    lunar          = multi × lvl × (1 + 6·EM/(2000 + EM) + <r>_dmg_) × (1 + <r>_baseDmg_)
                     × (1 + clamp(critRate_ + <r>_critRate_) × critDMG_)
                     × enemy.transDef × resMulti                            # special.ts:26-122

`multi` is `StatConstants.ts:29-131` (overloaded 2.75, swirl 0.6, superconduct 1.5, burning
0.25, bloom 2, hyperbloom and burgeon 3, Lunar-Charged 3, Lunar-Crystallize 1.6).

## The one divergence, recorded per fixture

GO's `enemy.transDef` is `99999999 / (99999999 + (5·100 + 500))` against a level-100 enemy
(`formula.ts:502-509`, GO's `frac(x, y)` being `x / (x + y)`), about `1 - 1e-5`. gcsim ignores
DEF for every reaction (`IgnoreDefPercent: 1`) and the chain follows gcsim, so `expected` uses 1
and `go_value` GO's term; an additive fixture rides on the talent hit's ordinary DEF and agrees
exactly.
"""

from __future__ import annotations

from typing import Any

from app.data.snapshot import reaction_level_multiplier
from tests.unit import go_fixtures_batch4 as b4
from tests.unit import go_fixtures_batch6 as b6
from tests.unit import go_fixtures_batch8 as b8
from tests.unit import test_go_formula_fixtures as base

TRANS = "libs/gi/wr/src/reaction/trans.ts:36-108"
SPECIAL = "libs/gi/wr/src/reaction/special.ts:26-122"
ADDITIVE = "libs/gi/wr/src/formula.ts:405-453"
CONSTANTS = "libs/gi/keymap/src/StatConstants.ts:29-131,151-158"
ARTIFACTS = "libs/gi/sheets/src/Artifacts/"
PANDO = "libs/gi/formula/src/data/char/"

LV90 = reaction_level_multiplier(90)
#: GO `enemy.transDef` at enemy level 100 with no DEF shred (`formula.ts:502-509`).
GO_TRANS_DEF = 99999999 / (99999999 + (5 * 100 + 500))
TRANS_DIVERGENCE = ("transformative DEF: gcsim ignores DEF (1, ours) against GO's "
                    "enemy.transDef, about 1 - 1e-5")
#: Owner ruling 2026-11-14 (`DECISIONS.md` §44): a Lunar row's contribution is weighted as gcsim
#: weights a solo (top-ranked) contributor, 0.6 (`pkg/reactable/lunarcharged.go:22,171-184`,
#: `lunarcrystallize.go:27,220-230`), where GO prices the whole contribution (1).
LUNAR_SOLO_WEIGHT = 0.6
LUNAR_DIVERGENCE = ("Lunar contributor weight: gcsim's solo 0.6 (ours, owner 2026-11-14) "
                    "against GO's whole contribution; and " + TRANS_DIVERGENCE)


def _crit(rate: float, dmg: float) -> float:
    return 1 + max(min(rate, 1.0), 0.0) * dmg


def _trans(multi: float, em: float, bonus: float, *, trans_def: float, res: float = 0.1,
           crit_rate: float = 0.0, crit_dmg: float = 0.0) -> float:
    return (multi * LV90 * (1 + 16 * em / (2000 + em) + bonus) * _crit(crit_rate, crit_dmg)
            * trans_def * base._res_multiplier(res))


def _lunar(multi: float, em: float, bonus: float, *, crit_rate: float, crit_dmg: float,
           trans_def: float, res: float = 0.1, base_bonus: float = 0.0) -> float:
    return (multi * LV90 * (1 + 6 * em / (2000 + em) + bonus) * (1 + base_bonus)
            * _crit(crit_rate, crit_dmg) * trans_def * base._res_multiplier(res))


def _additive(multi: float, em: float, bonus: float) -> float:
    return multi * LV90 * (1 + 5 * em / (1200 + em) + bonus)


def _go_def(figure: Any) -> Any:
    """`figure(trans_def)` as the fixture builder's `figure(coefficient)`: ours at 1, GO's at
    its own term. The amplifying coefficient a reaction fixture does not use is ignored."""
    return lambda coefficient: figure(
        1.0 if coefficient == base.OUR_EM_COEFFICIENT else GO_TRANS_DEF)


def _lunar_weight(figure: Any) -> Any:
    """`figure` with ours at gcsim's solo weight and GO's whole: the Lunar rows' own figure."""
    return lambda coefficient: figure(coefficient) * (
        LUNAR_SOLO_WEIGHT if coefficient == base.OUR_EM_COEFFICIENT else 1.0)


def _reaction_row(row_id: str, reaction: str, count: float, *, swirled: str | None = None,
                  label: str | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"reaction": reaction}
    if swirled:
        spec["swirled"] = swirled
    return {"id": row_id, "label": label or reaction.replace("_", " "), "move": None,
            "count": count, "reaction": spec, "conditionals": {}}


def _fixture(name: str, covers: str, go: list[str], givers: list[dict[str, Any]],
             team: dict[str, Any], stats: tuple[dict[str, float], dict[str, float]],
             set_pools: list[dict[str, float]], channel: str, rows: list[dict[str, Any]],
             sources: list[dict[str, Any]], conditionals: dict[str, Any], figure: Any,
             divergence: str) -> dict[str, Any]:
    return {
        "name": name, "covers": covers, "go": go, "givers": givers, "team": team,
        "base": stats[0], "artifacts": stats[1], "set_pools": set_pools, "channel": channel,
        "rows": rows, "sources": sources, "conditionals": conditionals,
        "expected": figure(base.OUR_EM_COEFFICIENT), "go_value": figure(base.GO_EM_COEFFICIENT),
        "divergence": divergence,
    }


# ── Hyperbloom: Thundering Fury, and a C2 Nahida's A1 EM and reaction CRIT ──────────────────

FISCHL_ARTIFACTS = {"elemental_mastery": 600.0, "flat_atk": 311.0, "crit_rate": 0.6,
                    "crit_dmg": 1.2}
HYPERBLOOM_TEAM = ["electro", "dendro", "hydro", "hydro"]


def _hyperbloom(trans_def: float) -> float:
    """**Three hyperblooms triggered by an Electro character in Thundering Fury**, with a C2
    Nahida in the party: TF's 40% (`ThunderingFury/index.tsx:12-15,22-27`), Nahida's A1 EM to
    the active character (25% of her 880, `pando Nahida.ts:168-182,212`) and her C2's 20% / 100%
    reaction CRIT (`:90-91,214-228`). The trigger's own 60% CRIT Rate must not reach it."""
    em = base._stats(b8.FISCHL_BASE, FISCHL_ARTIFACTS)["elemental_mastery"] + min(
        0.25 * b4.NAHIDA_TEAM_MAX["elemental_mastery"], 250.0)
    return 3 * _trans(3.0, em, 0.4, trans_def=trans_def, crit_rate=0.2, crit_dmg=1.0)


# ── Swirl: Viridescent Venerer on Kazuha's own swirls ───────────────────────────────────────


def _swirl(trans_def: float) -> float:
    """**Kazuha's own swirls in Viridescent Venerer**, having swirled Pyro: two Pyro swirls take
    VV's 60% (`ViridescentVenerer/index.tsx:21,44-46`) and its Pyro RES -40% (`:37-40`), one Hydro
    swirl the 60% only. His A4 Pyro DMG% (`pando KaedeharaKazuha.ts:154-166`) must not reach a
    swirl: reaction damage takes no DMG% (`trans.ts`, no `dmg_` term)."""
    em = base._stats(base.KAZUHA_BASE, base.KAZUHA_ARTIFACTS)["elemental_mastery"]
    return (2 * _trans(0.6, em, 0.6, trans_def=trans_def, res=0.1 - 0.4)
            + _trans(0.6, em, 0.6, trans_def=trans_def))


def _mona_c1_swirl(coefficient: float) -> float:
    """**A Pyro and a Hydro swirl by Kazuha with a C1 Mona's Omen**: her C1's 15% Swirl DMG.

    Owner ruling 2026-11-14 (`DECISIONS.md` §44): **a Hydro swirl only**, as gcsim
    (`internal/characters/mona/cons.go:71-80`, `AttackTagSwirlHydro`) and her text have it:
    ours. GO adds it to every swirl (`pando Mona.ts:87,137-139,248-250`, `swirl_dmg_`): GO's
    figure, so the Pyro swirl is the recorded divergence."""
    em = base._stats(base.KAZUHA_BASE, base.KAZUHA_ARTIFACTS)["elemental_mastery"]
    ours = coefficient == base.OUR_EM_COEFFICIENT
    trans_def = 1.0 if ours else GO_TRANS_DEF
    pyro_bonus = 0.0 if ours else 0.15
    return (_trans(0.6, em, pyro_bonus, trans_def=trans_def)
            + _trans(0.6, em, 0.15, trans_def=trans_def))


MONA_DIVERGENCE = ("Mona's C1 on a Pyro swirl: a Hydro swirl only (gcsim and her text, ours, "
                   "owner 2026-11-14) against GO's every swirl; and " + TRANS_DIVERGENCE)


# ── Aggravate: Keqing's Last Attack in Thundering Fury ──────────────────────────────────────

KEQING_ARTIFACTS = {**b6.KEQING_ARTIFACTS, "elemental_mastery": 120.0}


def _aggravate(_: float) -> float:
    """**Keqing's Last Attack, aggravated, in Thundering Fury**: the flat term
    `lvl × 1.15 × (1 + 5·EM/(1200+EM) + 20%)` (`formula.ts:263,421-429`; TF `aggravate_dmg_`,
    `ThunderingFury/index.tsx:16`) inside the base, under TF's 2-piece Electro DMG and her CRIT."""
    stats = base._stats(b6.KEQING_BASE, KEQING_ARTIFACTS)
    stats["electro_dmg_bonus"] += 0.15
    flat = _additive(1.15, stats["elemental_mastery"], 0.2)
    return b6._hit(stats, base_damage=base._multiplier(b6.KEQING_LAST) * base._total(stats, "atk")
                   + flat, channel="electro")


# ── Spread: Nahida's Tri-Karma with a teammate Baizhu's A4 ──────────────────────────────────

BAIZHU_GIVER_STATS = {"base_hp": 13348.0, "hp_pct": 1.398, "flat_hp": 4780.0}


def _baizhu_hp() -> float:
    return base._total(BAIZHU_GIVER_STATS, "hp")


def _spread(_: float) -> float:
    """**Nahida's Tri-Karma Purification, spread** (an ATK + EM row: the flat term rides once on
    the hit, `formula.ts:405-419`), with Baizhu's A4: 0.8% Spread DMG per 1,000 of his Max HP,
    his HP counted to 50,000 (`pando Baizhu.ts:75-76,128-137,172-173`)."""
    stats = base._stats(b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS)
    em = stats["elemental_mastery"]
    bonus = 0.008 * min(_baizhu_hp(), 50000.0) / 1000
    params = b6.TRI_KARMA_10[1]
    return b6._hit(stats, base_damage=params[2] * base._total(stats, "atk") + params[3] * em
                   + _additive(1.25, em, bonus), channel="dendro")


# ── Burgeon, Burning and Overloaded: Crimson Witch ──────────────────────────────────────────


def _crimson(trans_def: float) -> float:
    """**Two burgeons, four burning ticks and an overload** from a Pyro trigger in Crimson Witch:
    40% to all three (`CrimsonWitchOfFlames/index.tsx:28-34,52-56`); burning and burgeon can crit
    but nothing gives them a CRIT."""
    em = base._stats(base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS)["elemental_mastery"]
    return (2 * _trans(3.0, em, 0.4, trans_def=trans_def)
            + 4 * _trans(0.25, em, 0.4, trans_def=trans_def)
            + _trans(2.75, em, 0.4, trans_def=trans_def))


# ── Bloom: Flower of Paradise Lost at four stacks ───────────────────────────────────────────


def _bloom(trans_def: float) -> float:
    """**Two blooms from a Dendro trigger in Flower of Paradise Lost** at four stacks: 40% and
    4 × 10% (`FlowerOfParadiseLost/index.tsx:24-58`), and the 2-piece's 80 EM in the pool."""
    em = base._stats(b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS)["elemental_mastery"] + 80.0
    return 2 * _trans(2.0, em, 0.4 + 4 * 0.1, trans_def=trans_def)


# ── Superconduct: Disenchantment in Deep Shadow ─────────────────────────────────────────────

KAEYA_ARTIFACTS = {"elemental_mastery": 50.0, "atk_pct": 0.466, "flat_atk": 311.0,
                   "crit_rate": 0.3, "crit_dmg": 0.6}


def _superconduct(trans_def: float) -> float:
    """**A superconduct by a Cryo trigger in Disenchantment in Deep Shadow**: 80%
    (`DisenchantmentInDeepShadow/index.tsx:19-23,38`)."""
    em = base._stats(b8.KAEYA_BASE, KAEYA_ARTIFACTS)["elemental_mastery"]
    return _trans(1.5, em, 0.8, trans_def=trans_def)


# ── Lunar-Charged: a C2 Flins in Night of the Sky's Unveiling ───────────────────────────────

FLINS_ARTIFACTS = {**b8.FLINS_ARTIFACTS, "elemental_mastery": 200.0}


def _lunar_charged(trans_def: float) -> float:
    """**Two Lunar-Charged contributions from a C2 Flins in Night of the Sky's Unveiling**, at
    Ascendant Gleam with Gleaming Moon: Intent: the set's 30% CRIT Rate and 10% Lunar Reaction DMG
    (`NightOfTheSkysUnveiling/index.tsx:32-49`), his C2's Electro RES -25% (`pando
    Flins.ts:81-86,124-130,176`). His own CRIT applies (`special.ts:43-75`); his C4 ATK does
    not."""
    stats = base._stats(b8.FLINS_BASE, FLINS_ARTIFACTS)
    return 2 * _lunar(3.0, stats["elemental_mastery"], 0.1, crit_rate=stats["crit_rate"] + 0.3,
                      crit_dmg=stats["crit_dmg"], trans_def=trans_def, res=0.1 - 0.25)


# ── Lunar-Crystallize: Aubade, and a C4 Mona's C1 and C4 ────────────────────────────────────

GEO_BASE = base._base_stats(base_atk=850.0, base_hp=12000.0, base_def=800.0, crit_dmg=0.884)
GEO_ARTIFACTS = {"elemental_mastery": 300.0, "flat_atk": 311.0, "crit_rate": 0.4,
                 "crit_dmg": 0.8, "geo_dmg_bonus": 0.466}


def _lunar_crystallize(trans_def: float) -> float:
    """**Three Lunar-Crystallize contributions from a Geo trigger in Aubade**, off-field at
    Ascendant Gleam (20% + 40%, `AubadeOfMorningstarAndMoon/index.tsx:25-45`), with a C4 Mona's
    Omen: C1's 15% Lunar-Crystallize DMG (`pando Mona.ts:92,143-145,254-259`) and C4's 15% CRIT
    Rate (`:103,146-148,233`). Omen's DMG% (`:130,232`) and the trigger's Geo DMG% must not
    reach it."""
    stats = base._stats(GEO_BASE, GEO_ARTIFACTS)
    return 3 * _lunar(1.6, stats["elemental_mastery"], 0.2 + 0.4 + 0.15,
                      crit_rate=stats["crit_rate"] + 0.15, crit_dmg=stats["crit_dmg"],
                      trans_def=trans_def)


def reaction_fixtures() -> list[dict[str, Any]]:
    """P3, task 13: one fixture per reaction family and set/kit part, by hand from GO."""
    out: list[dict[str, Any]] = []
    tf = base._set_source(15005, 4, [0.4, 0.8, 0.2, 0.2, 0, 0, 0, 0], [])

    out.append(_fixture(
        "hyperbloom_thundering_fury_nahida_c2",
        "transformative reaction rows: a set's reaction bonus, a teammate's EM, and a teammate's "
        "reaction CRIT; the trigger's own CRIT does not reach a transformative reaction",
        [TRANS, CONSTANTS, f"{ARTIFACTS}ThunderingFury/index.tsx:11-31",
         f"{PANDO}Nahida.ts:79-94,112-116,168-182,212-228"],
        [b6._subject("Fischl", 0),
         {"name": "Nahida", "constellation": 2, "ascension_phase": 6,
          "stats": b4.NAHIDA_TEAM_MAX}],
        {"element": "electro", "weapon_type": "WEAPON_BOW", "member_elements": HYPERBLOOM_TEAM},
        (b8.FISCHL_BASE, FISCHL_ARTIFACTS), [], "electro",
        [_reaction_row("hyperbloom", "hyperbloom", 3)],
        [tf, b4._kit("10000073", b4._nahida_giver(2), subject=False,
                     receiver_element="electro", team_elements=HYPERBLOOM_TEAM,
                     team_max=b4.NAHIDA_TEAM_MAX)],
        {"kit:nahida/a1_field": 1, "kit:nahida/shrine": 1, "kit:nahida/c2_quicken": 0,
         "kit:nahida/c4_count": 0, "kit:nahida/c2_bloom": 1},
        _go_def(_hyperbloom), TRANS_DIVERGENCE))

    out.append(_fixture(
        "swirl_viridescent_venerer_on_kazuha",
        "swirl rows of two elements: the set's RES shred reaches only the swirled element's, its "
        "swirl bonus both; the subject's own DMG% conversion reaches neither",
        [TRANS, CONSTANTS, f"{ARTIFACTS}ViridescentVenerer/index.tsx:21-50",
         f"{PANDO}KaedeharaKazuha.ts:65-67,94-107,154-166"],
        [b6._subject("Kaedehara Kazuha", 0)],
        {"element": "anemo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["anemo", "pyro", "hydro"]},
        (base.KAZUHA_BASE, base.KAZUHA_ARTIFACTS), [], "anemo",
        [_reaction_row("swirl_pyro", "swirl", 2, swirled="pyro", label="swirl (pyro)"),
         _reaction_row("swirl_hydro", "swirl", 1, swirled="hydro", label="swirl (hydro)")],
        [base._set_source(15002, 4, [0.6, 0.4, 10, 0.2, 0, 0, 0, 0], []),
         base._kit_source("10000047", base._kazuha_giver({**base.KAZUHA_BASE}), subject=True)],
        {"set:15002:4/swirled": "pyro", "kit:kaedehara_kazuha/swirl_pyro": 1,
         "kit:kaedehara_kazuha/swirl_hydro": 1, "kit:kaedehara_kazuha/swirl_electro": 0,
         "kit:kaedehara_kazuha/swirl_cryo": 0},
        _go_def(_swirl), TRANS_DIVERGENCE))
    # Kazuha's kit is there to prove a DMG% does **not** reach a swirl: `formula:verify` moves
    # every one of its values and requires the figure to stay put.
    out[-1]["kit_must_not_reach"] = True

    keqing_row = {**base._row("last", "Last Attack DMG", "burst", 1, b6.KEQING_LAST, None),
                  "additive": "aggravate"}
    out.append(_fixture(
        "aggravate_keqing_thundering_fury",
        "an additive reaction on a talent row: flat damage inside the base, under the hit's DMG "
        "bonus, DEF, RES and CRIT, with a set's aggravate bonus",
        [ADDITIVE, CONSTANTS, f"{ARTIFACTS}ThunderingFury/index.tsx:11-31"],
        [b6._subject("Keqing", 0)],
        {"element": "electro", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["electro", "dendro"]},
        (b6.KEQING_BASE, KEQING_ARTIFACTS), [{"electro_dmg_bonus": 0.15}], "electro",
        [keqing_row], [tf], {}, _aggravate, "none: an additive reaction takes the hit's own DEF"))

    karma = {**base._row("karma", "Tri-Karma Purification DMG", "skill", 1, b6.TRI_KARMA_10,
                         None), "additive": "spread"}
    out.append(_fixture(
        "spread_nahida_baizhu_a4",
        "an additive reaction on a mixed ATK + EM row (the flat term once), with a teammate's "
        "reaction bonus from his Max HP, capped at 50,000",
        [ADDITIVE, CONSTANTS, f"{PANDO}Baizhu.ts:72-77,118-137,168-173"],
        [b6._subject("Nahida", 0),
         {"name": "Baizhu", "constellation": 0, "ascension_phase": 6,
          "stats": BAIZHU_GIVER_STATS}],
        {"element": "dendro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["dendro", "dendro", "electro"]},
        (b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS), [], "dendro", [karma],
        [b4._kit("10000082", b6._giver("Baizhu", "10000082", 0, BAIZHU_GIVER_STATS),
                 subject=False, receiver_element="dendro",
                 team_elements=["dendro", "dendro", "electro"])],
        {"kit:baizhu/active_hp": "above", "kit:baizhu/c4_after": 0,
         "kit:baizhu/a4_after_heal": 1},
        _spread, "none: an additive reaction takes the hit's own DEF"))

    witch = base._set_source(15006, 4, base.WITCH_PARAMS, [base.WITCH_TWO_PIECE_ROW])
    out.append(_fixture(
        "burgeon_burning_overloaded_crimson_witch",
        "three transformative rows of different multipliers under one set bonus",
        [TRANS, CONSTANTS, f"{ARTIFACTS}CrimsonWitchOfFlames/index.tsx:20-58"],
        [b6._subject("Xiangling", 0)],
        {"element": "pyro", "weapon_type": "WEAPON_POLE",
         "member_elements": ["pyro", "dendro", "hydro", "electro"]},
        (base.XIANGLING_BASE, base.XIANGLING_ARTIFACTS), [base.CRIMSON_WITCH_TWO_PIECE], "pyro",
        [_reaction_row("burgeon", "burgeon", 2), _reaction_row("burning", "burning", 4),
         _reaction_row("overloaded", "overloaded", 1)],
        [witch], {"set:15006:4/stacks": 3}, _go_def(_crimson), TRANS_DIVERGENCE))

    out.append(_fixture(
        "bloom_flower_of_paradise_lost",
        "a reaction bonus per stack (a set condition), and a 2-piece's EM in the pool reaching a "
        "reaction row",
        [TRANS, CONSTANTS, f"{ARTIFACTS}FlowerOfParadiseLost/index.tsx:22-104"],
        [b6._subject("Nahida", 0)],
        {"element": "dendro", "weapon_type": "WEAPON_CATALYST",
         "member_elements": ["dendro", "hydro"]},
        (b4.NAHIDA_BASE, b4.NAHIDA_ARTIFACTS), [{"elemental_mastery": 80.0}], "dendro",
        [_reaction_row("bloom", "bloom", 2)],
        [base._set_source(15028, 4, [0.4, 0.4, 0.4, 10, 4, 0.25, 1, 0.1], [])],
        {"set:15028:4/stacks": 4}, _go_def(_bloom), TRANS_DIVERGENCE))

    out.append(_fixture(
        "superconduct_disenchantment",
        "a superconduct row under a set's superconduct bonus",
        [TRANS, CONSTANTS, f"{ARTIFACTS}DisenchantmentInDeepShadow/index.tsx:14-45"],
        [b6._subject("Kaeya", 0)],
        {"element": "cryo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": ["cryo", "electro"]},
        (b8.KAEYA_BASE, KAEYA_ARTIFACTS), [], "cryo",
        [_reaction_row("superconduct", "superconduct", 1)],
        [base._set_source(15046, 4, [0.8, 0.16, 0.4, 0, 0, 0, 0, 0], [])],
        {"set:15046:4/enemy_superconduct": 1}, _go_def(_superconduct), TRANS_DIVERGENCE))

    out.append(_fixture(
        "lunar_charged_flins_night_of_the_skys_unveiling",
        "a Lunar row: the trigger's own CRIT and a set's CRIT Rate reach it, a set's Lunar bonus "
        "and the kit's Electro RES shred too; the kit's ATK does not",
        [SPECIAL, CONSTANTS, "libs/gi/wr/src/reaction/lunar.ts:10-40",
         f"{ARTIFACTS}NightOfTheSkysUnveiling/index.tsx:26-62",
         f"{PANDO}Flins.ts:81-91,124-131,176-177"],
        [b6._subject("Flins", 2)],
        {"element": "electro", "weapon_type": "WEAPON_POLE",
         "member_elements": ["electro", "hydro"]},
        (b8.FLINS_BASE, FLINS_ARTIFACTS), [], "electro",
        [_reaction_row("lc", "lunar_charged", 2, label="lunar-charged")],
        [base._set_source(15041, 4, [4, 0.15, 0.3, 0.1, 0, 0, 0, 0], []),
         b4._kit("10000120", b6._giver("Flins", "10000120", 2, b8.FLINS_BASE), subject=True)],
        {"set:15041:4/gleaming_moon": "ascendant_gleam", "kit:flins/c2_hit": 1,
         "kit:flins/moonsign": 1},
        _lunar_weight(_go_def(_lunar_charged)), LUNAR_DIVERGENCE))

    swirl_team = ["anemo", "hydro", "pyro"]
    out.append(_fixture(
        "mona_c1_hydro_swirl_on_kazuha",
        "a teammate's swirl bonus scoped to one swirled element (Mona's C1, Hydro swirls only, "
        "owner ruling 2026-11-14): it reaches the Hydro swirl row and not the Pyro one",
        [TRANS, CONSTANTS, f"{PANDO}Mona.ts:84-92,128-139,248-250",
         "gcsim: internal/characters/mona/cons.go:71-80"],
        [b6._subject("Kaedehara Kazuha", 0),
         {"name": "Mona", "constellation": 1, "ascension_phase": 6,
          "talent_levels": {"elemental_burst": 10}, "stats": {}}],
        {"element": "anemo", "weapon_type": "WEAPON_SWORD_ONE_HAND",
         "member_elements": swirl_team},
        (base.KAZUHA_BASE, base.KAZUHA_ARTIFACTS), [], "anemo",
        [_reaction_row("swirl_pyro", "swirl", 1, swirled="pyro", label="swirl (pyro)"),
         _reaction_row("swirl_hydro", "swirl", 1, swirled="hydro", label="swirl (hydro)")],
        [b4._kit("10000041", b4._giver("Mona", "10000041", constellation=1,
                                       rows={("elemental_burst", 13): b4.MONA_BURST_13}),
                 subject=False, receiver_element="anemo", team_elements=swirl_team)],
        {"kit:mona/omen": 1, "kit:mona/c1_omen": 1},
        _mona_c1_swirl, MONA_DIVERGENCE))

    mona_team = ["geo", "hydro"]
    out.append(_fixture(
        "lunar_crystallize_aubade_mona_c4",
        "a Lunar-Crystallize row: a set's two conditional Lunar bonuses, a teammate's reaction "
        "bonus and CRIT Rate; the teammate's DMG% does not reach it",
        [SPECIAL, CONSTANTS, f"{ARTIFACTS}AubadeOfMorningstarAndMoon/index.tsx:25-46",
         f"{PANDO}Mona.ts:84-92,103,128-148,232-259"],
        [b6._subject("a Geo trigger", 0),
         {"name": "Mona", "constellation": 4, "ascension_phase": 6,
          "talent_levels": {"elemental_burst": 10}, "stats": {}}],
        {"element": "geo", "weapon_type": "WEAPON_CLAYMORE", "member_elements": mona_team},
        (GEO_BASE, GEO_ARTIFACTS), [], "geo",
        [_reaction_row("lcr", "lunar_crystallize", 3, label="lunar-crystallize")],
        [base._set_source(15043, 4, [0.2, 0.4, 3, 0, 0, 0, 0, 0], []),
         b4._kit("10000041", b4._giver("Mona", "10000041", constellation=4,
                                       rows={("elemental_burst", 13): b4.MONA_BURST_13}),
                 subject=False, receiver_element="geo", team_elements=mona_team)],
        {"set:15043:4/off_field": 1, "set:15043:4/moonsign": "ascendant_gleam",
         "kit:mona/omen": 1, "kit:mona/c1_omen": 1, "kit:mona/c6_stacks": 0},
        _lunar_weight(_go_def(_lunar_crystallize)), LUNAR_DIVERGENCE))
    return out
