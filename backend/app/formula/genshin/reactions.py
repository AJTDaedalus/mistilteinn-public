"""Transformative, additive and Lunar reaction damage (math-fallback P3, task 13).

`damage.py` is the talent-hit chain, and amplifying reactions ride on it as one more factor.
The reactions here do not: gcsim computes them on their own path, and so does GO, and each
has a shape of its own:

* **Transformative** (overloaded, electro-charged, superconduct, swirl, shattered, burning,
  bloom, hyperbloom, burgeon) — a separate instance of damage. gcsim builds it as an attack
  whose whole base is `FlatDmg`, with no DMG% (`pkg/enemy/damage.go:22-43` skips it for a
  reaction tag) and DEF ignored (`IgnoreDefPercent: 1` on every one):

      damage = multiplier × level_base × (1 + 16·EM/(2000 + EM) + reaction_bonus) × res
      # gcsim combat.CalcReactionDmg, pkg/core/combat/reaction.go:33-39, and each reaction's
      # `FlatDmg = k * flatdmg`; GO trans.ts:36-108, multi.ts:26-31

  Crit only where GO allows it (`canCrit`, `StatConstants.ts:29-131`): burning, bloom,
  hyperbloom and burgeon, plus swirl's own `swirl_critRate_` (`trans.ts:128-147`), and only
  from **reaction-specific** crit stats — `<reaction>_critRate_`/`_critDMG_`, never the
  character's own CRIT. gcsim's reaction snapshot carries EM and level and nothing else
  (`reaction.go:34-38`), so its crit is 0 unless a kit adds one; the two agree.

* **Additive** (spread, aggravate) — flat damage added to the triggering hit's base, before
  its DMG bonus (gcsim `catalyze.go:24,43` adds to `FlatDmg`; GO `formula.ts:405-431` to
  `dmgInc`):

      flat = multiplier × level_base × (1 + 5·EM/(1200 + EM) + reaction_bonus)
      # gcsim combat.CalcCatalyzeDmg, reaction.go:41-43; GO formula.ts:263,408-431

  It enters `damage.compute_damage` through `Hit.additive`, so the rest of the hit's chain
  (DMG%, DEF, RES, crit) applies to it as both oracles apply it.

* **Lunar** (Lunar-Charged, Lunar-Crystallize) — reaction damage that crits with the
  character's own CRIT:

      contribution = multiplier × level_base × (1 + 6·EM/(2000 + EM) + reaction_bonus)
                     × (1 + base_dmg_bonus) × crit × res
      # gcsim combat.CalcSpecialReactionDmg, reaction.go:20-31, and lunarcharged.go:140-150;
      # GO special.ts:26-122, lunar.ts:27-40

  **Lunar-Bloom is refused by name**: neither oracle has a reaction-triggered Lunar-Bloom
  instance at its pin. gcsim's `LunarBloom()` only signals the party (`lunarbloom.go:3-5`),
  and GO's multiplier for it is 0 (`StatConstants.ts:103-108`) — every Lunar-Bloom hit is a
  kit's own direct damage, which belongs to that kit's sheet.

## The level base is the game's

`level_base` is `ElementCoeffExcelConfigData.playerElementLevelCo`, committed in the
YuanShenResources snapshot (`app.data.snapshot.reaction_level_multiplier`). gcsim's
`reactionLvlBase` and GO's `transformativeReactionLevelMultipliers` are both generated from that
column; `tests/unit/test_reactions.py` holds all three to agree.

## Recorded divergences

1. **GO's transformative DEF term is not exactly 1.** `enemy.transDef` is
   `99999999 / (99999999 + (5·enemy_level + 500)(1 - defRed)(1 - defIgn))`
   (`formula.ts:502-509`; GO's `frac(x, y)` is `x / (x + y)`), about `1 - 9.5e-6` against a
   level-90 enemy. gcsim ignores DEF outright (`IgnoreDefPercent: 1` → `defmod = 1`), and this
   chain follows gcsim, as for every constant. Each GO fixture with a reaction instance
   records the gap.
2. **Lunar-Charged and Lunar-Crystallize are one character's contribution.** gcsim sums every
   contributor's damage, ranked, at weights 0.6/0.3/0.05/0.05 (`lunarcharged.go:22,159-185`,
   `lunarcrystallize.go:27`); GO prices one character's whole contribution
   (`special.ts:92-121`, no ranking). The estimate scores the optimized character's own
   contribution as GO does, at a stated `weight` that defaults to 1 (GO); the panel says so.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from app.data.snapshot import reaction_level_multiplier
from app.formula.genshin.damage import (
    DamageInputError,
    DamageResult,
    Step,
    crit_multiplier,
    res_multiplier,
)

#: `16 * em / (2000 + em)`. gcsim `reaction.go:38`; GO `multi.ts:31` (`prod(16, frac(EM, 2000))`).
TRANSFORMATIVE_EM_NUMERATOR = 16.0
TRANSFORMATIVE_EM_DENOMINATOR = 2000.0
#: `5 * em / (1200 + em)`. gcsim `reaction.go:42`; GO `formula.ts:263`.
ADDITIVE_EM_NUMERATOR = 5.0
ADDITIVE_EM_DENOMINATOR = 1200.0
#: `6 * em / (2000 + em)`. gcsim `reaction.go:30`; GO `special.ts:37`.
LUNAR_EM_NUMERATOR = 6.0
LUNAR_EM_DENOMINATOR = 2000.0


class Transformative(enum.StrEnum):
    """The transformative reactions, each a separate instance of damage."""

    OVERLOADED = "overloaded"
    ELECTRO_CHARGED = "electro_charged"
    SUPERCONDUCT = "superconduct"
    SWIRL = "swirl"
    SHATTERED = "shattered"
    BURNING = "burning"
    BLOOM = "bloom"
    HYPERBLOOM = "hyperbloom"
    BURGEON = "burgeon"


class Additive(enum.StrEnum):
    """The additive reactions, flat damage on the hit that triggers them."""

    SPREAD = "spread"
    AGGRAVATE = "aggravate"


class Lunar(enum.StrEnum):
    """The Lunar reactions with a reaction-triggered instance at both pins."""

    LUNAR_CHARGED = "lunar_charged"
    LUNAR_CRYSTALLIZE = "lunar_crystallize"


#: Reactions the formula estimate names and refuses, with the reason it gives.
REFUSED: dict[str, str] = {
    "lunar_bloom": (
        "Lunar-Bloom has no reaction-triggered instance in gcsim (lunarbloom.go:3-5 only "
        "signals the party) or GO (multiplier 0, StatConstants.ts:103-108) at the pins: its "
        "damage is each kit's own direct hit, which belongs to that kit's sheet"
    ),
    "stellar_conduct": (
        "Stellar-Conduct's damage is a kit's own direct hit in both oracles (GO multiplier 0, "
        "StatConstants.ts:117-122; gcsim AttackTagDirectStellarConduct) and depends on a kit's "
        "Polestar stacks: it belongs to the Stellar kits' sheets, not to a reaction row"
    ),
    "stellar_swirl": (
        "Stellar Swirl is outside P3's reaction list (owner, 2026-11-14: transformative, "
        "additive and Lunar); its vortex hits and kit multipliers are a follow-up"
    ),
}


@dataclass(frozen=True, slots=True)
class TransformativeSpec:
    """One transformative reaction's constants, each cited where it is defined."""

    multiplier: float
    #: The element of its damage, so of the RES it meets. `None` for swirl: the swirled one.
    element: str | None
    #: Whether a reaction-specific CRIT can reach it (GO `canCrit`, swirl's own crit).
    crittable: bool
    gcsim: str
    go: str


TRANSFORMATIVE: dict[Transformative, TransformativeSpec] = {
    Transformative.OVERLOADED: TransformativeSpec(
        2.75, "pyro", False, "pkg/reactable/overload.go:55-61", "StatConstants.ts:33-39"),
    Transformative.ELECTRO_CHARGED: TransformativeSpec(
        2.0, "electro", False, "pkg/reactable/electrocharged.go:68-74",
        "StatConstants.ts:47-53"),
    Transformative.SUPERCONDUCT: TransformativeSpec(
        1.5, "cryo", False, "pkg/reactable/superconduct.go:100-106", "StatConstants.ts:61-67"),
    Transformative.SWIRL: TransformativeSpec(
        0.6, None, True, "pkg/reactable/swirl.go:20-37",
        "StatConstants.ts:68-74; trans.ts:110-167"),
    Transformative.SHATTERED: TransformativeSpec(
        3.0, "physical", False, "pkg/reactable/freeze.go:88-98", "StatConstants.ts:40-46"),
    Transformative.BURNING: TransformativeSpec(
        0.25, "pyro", True, "pkg/reactable/burning.go:81-92", "StatConstants.ts:75-81"),
    Transformative.BLOOM: TransformativeSpec(
        2.0, "dendro", True, "internal/template/dendrocore/dendrocore.go:16,164-176",
        "StatConstants.ts:82-88"),
    Transformative.HYPERBLOOM: TransformativeSpec(
        3.0, "dendro", True, "internal/template/dendrocore/dendrocore.go:18,203-212",
        "StatConstants.ts:96-102"),
    Transformative.BURGEON: TransformativeSpec(
        3.0, "dendro", True, "internal/template/dendrocore/dendrocore.go:17,185-194",
        "StatConstants.ts:89-95"),
}

#: The elements a swirl can carry. gcsim `swirl.go` (`TrySwirl{Electro,Hydro,Pyro,Cryo}`); GO
#: `StatConstants.ts:71` (`variants`).
SWIRL_ELEMENTS: tuple[str, ...] = ("pyro", "hydro", "electro", "cryo")


@dataclass(frozen=True, slots=True)
class AdditiveSpec:
    """One additive reaction's constants."""

    multiplier: float
    #: The element of the hit that triggers it: Dendro onto Quicken spreads, Electro aggravates.
    element: str
    gcsim: str
    go: str


ADDITIVE: dict[Additive, AdditiveSpec] = {
    Additive.SPREAD: AdditiveSpec(
        1.25, "dendro", "pkg/reactable/catalyze.go:43",
        "formula.ts:411-419; StatConstants.ts:152"),
    Additive.AGGRAVATE: AdditiveSpec(
        1.15, "electro", "pkg/reactable/catalyze.go:24",
        "formula.ts:421-429; StatConstants.ts:153"),
}


@dataclass(frozen=True, slots=True)
class LunarSpec:
    """One Lunar reaction's constants."""

    multiplier: float
    element: str
    gcsim: str
    go: str


LUNAR: dict[Lunar, LunarSpec] = {
    Lunar.LUNAR_CHARGED: LunarSpec(
        3.0, "electro", "pkg/core/combat/reaction.go:25-26; pkg/reactable/lunarcharged.go:118",
        "StatConstants.ts:54-60; lunar.ts:31"),
    Lunar.LUNAR_CRYSTALLIZE: LunarSpec(
        1.6, "geo", "pkg/core/combat/reaction.go:27-28; pkg/reactable/lunarcrystallize.go:161",
        "StatConstants.ts:110-116; lunar.ts:31"),
}


def _check_em(elemental_mastery: float) -> None:
    if elemental_mastery < 0:
        msg = f"elemental mastery cannot be negative; got {elemental_mastery}"
        raise DamageInputError(msg)


def em_bonus(numerator: float, denominator: float, elemental_mastery: float) -> float:
    """`numerator · EM / (denominator + EM)`: each reaction family's EM term."""
    _check_em(elemental_mastery)
    return numerator * elemental_mastery / (denominator + elemental_mastery)


def transformative_element(reaction: Transformative, swirled: str | None = None) -> str:
    """The element a transformative reaction's damage carries, so whose RES it meets."""
    spec = TRANSFORMATIVE[reaction]
    if spec.element is not None:
        if swirled is not None:
            msg = f"{reaction} carries {spec.element}; only a swirl takes a swirled element"
            raise DamageInputError(msg)
        return spec.element
    if swirled not in SWIRL_ELEMENTS:
        msg = f"a swirl carries one of {SWIRL_ELEMENTS}; got {swirled!r}"
        raise DamageInputError(msg)
    return swirled


def transformative_damage(
    reaction: Transformative,
    *,
    character_level: int,
    elemental_mastery: float,
    resistance: float,
    reaction_bonus: float = 0.0,
    crit_rate: float = 0.0,
    crit_dmg: float = 0.0,
) -> DamageResult:
    """One transformative reaction instance, with its account.

    `crit_rate`/`crit_dmg` are the **reaction's own** (Nahida's C2 on bloom), refused on a
    reaction that cannot crit rather than silently ignored.
    """
    spec = TRANSFORMATIVE[reaction]
    if not spec.crittable and (crit_rate or crit_dmg):
        msg = f"{reaction} cannot crit (GO `canCrit` false); a CRIT for it is a caller bug"
        raise DamageInputError(msg)
    level_base = reaction_level_multiplier(character_level)
    bonus = em_bonus(TRANSFORMATIVE_EM_NUMERATOR, TRANSFORMATIVE_EM_DENOMINATOR,
                     elemental_mastery)
    steps = (
        Step("level base", level_base, f"lv{character_level} playerElementLevelCo"),
        Step("reaction", spec.multiplier, f"{reaction} ({spec.gcsim})"),
        Step("em + bonus", 1 + bonus + reaction_bonus,
             f"16·{elemental_mastery:.0f}/(2000+EM) + {reaction_bonus:.1%}"),
        Step("def", 1.0, "ignored (gcsim IgnoreDefPercent 1)"),
        Step("res", res_multiplier(resistance), f"{resistance:.1%} RES"),
    )
    non_crit = 1.0
    for step in steps:
        non_crit *= step.factor
    return DamageResult(
        non_crit=non_crit,
        crit=non_crit * (1 + crit_dmg),
        expected=non_crit * crit_multiplier(crit_rate, crit_dmg),
        steps=steps,
    )


def additive_flat(
    reaction: Additive,
    *,
    character_level: int,
    elemental_mastery: float,
    reaction_bonus: float = 0.0,
) -> float:
    """The flat damage an additive reaction adds to the hit that triggers it."""
    spec = ADDITIVE[reaction]
    bonus = em_bonus(ADDITIVE_EM_NUMERATOR, ADDITIVE_EM_DENOMINATOR, elemental_mastery)
    return spec.multiplier * reaction_level_multiplier(character_level) * (
        1 + bonus + reaction_bonus
    )


def lunar_damage(
    reaction: Lunar,
    *,
    character_level: int,
    elemental_mastery: float,
    resistance: float,
    crit_rate: float,
    crit_dmg: float,
    reaction_bonus: float = 0.0,
    base_dmg_bonus: float = 0.0,
) -> DamageResult:
    """One character's Lunar contribution, crit with their own CRIT (see the module notes)."""
    spec = LUNAR[reaction]
    level_base = reaction_level_multiplier(character_level)
    bonus = em_bonus(LUNAR_EM_NUMERATOR, LUNAR_EM_DENOMINATOR, elemental_mastery)
    steps = (
        Step("level base", level_base, f"lv{character_level} playerElementLevelCo"),
        Step("reaction", spec.multiplier, f"{reaction} ({spec.gcsim})"),
        Step("em + bonus", 1 + bonus + reaction_bonus,
             f"6·{elemental_mastery:.0f}/(2000+EM) + {reaction_bonus:.1%}"),
        Step("base bonus", 1 + base_dmg_bonus, f"{base_dmg_bonus:.1%}"),
        Step("def", 1.0, "ignored (gcsim IgnoreDefPercent 1)"),
        Step("res", res_multiplier(resistance), f"{resistance:.1%} RES"),
    )
    non_crit = 1.0
    for step in steps:
        non_crit *= step.factor
    return DamageResult(
        non_crit=non_crit,
        crit=non_crit * (1 + crit_dmg),
        expected=non_crit * crit_multiplier(crit_rate, crit_dmg),
        steps=steps,
    )
