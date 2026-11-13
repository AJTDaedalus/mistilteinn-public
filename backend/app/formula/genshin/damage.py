"""The Genshin damage chain: an ordered, named, explainable sequence of multipliers.

Every constant here cites gcsim at the commit pinned in `docs/CROSSVAL_gcsim.md`, and the
whole chain is a port of `pkg/enemy/damage.go:11-130` (`func (e *Enemy) calc`):

    dmgBonus = elemental_bonus[channel] + generic_bonus         # damage.go:47
    a        = TotalATK | MaxHP | TotalDEF | EM                 # damage.go:52-62
    base     = mult * a * (1 + base_dmg_bonus) + flat           # damage.go:65
               (+ sum of extra `mult_i * stat_i` terms, which gcsim writes as FlatDmg)
    damage   = base * (1 + dmgBonus)                            # damage.go:66
    damage  *= def_multiplier                                   # damage.go:86
    damage  *= res_multiplier                                   # damage.go:95
    damage  *= (1 + crit_dmg)              when it crits        # damage.go:102
    damage  *= amp_mult * (1 + em_bonus + reaction_bonus)       # damage.go:116

## Why this is a pipeline of floats and not a DAG

The stat layer is a DAG because aggregation needs tags: a scope-gated buff has to be
invisible outside its scope, and that is what `read`-over-tags does well. The damage chain
has no aggregation — it is one ordered multiplication after another — and DESIGN §1 A6 asks
that a damage number be able to say *which multipliers applied, in what order, from where*.
A list of named steps answers that by construction. Expressing it as a DAG would answer it
only by traversal, and would cost the optimizer's inner loop a tree walk per candidate.

## Where this deliberately differs from the oracle

1. **Crit is not rolled.** gcsim simulates and rolls (`damage.go:101`); a calculator reports
   all three of non-crit, crit, and expected. Expected is what an optimizer must score on —
   `1 + crit_rate * crit_dmg` — and reporting only a rolled value would make a build's score
   depend on a random number.
2. **The RES curve is continuous at exactly 0.75.** See `res_multiplier`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# ---- Constants, each with its line ----------------------------------------

#: DEF reduction is capped before it enters the DEF term. gcsim `damage.go:76-78`.
MAX_DEF_REDUCTION = 0.9
#: DEF ignore likewise. gcsim `damage.go:80` (`min(atk.Info.IgnoreDefPercent, 1.0)`).
MAX_DEF_IGNORE = 1.0

#: The RES value at and above which the curve switches to its diminishing branch.
RES_DIMINISHING_THRESHOLD = 0.75

#: Amplifying-reaction EM bonus: `2.78 * em / (1400 + em)`. gcsim `damage.go:113`.
#: **Not from memory** — this constant and its denominator are the two numbers a wrong
#: reaction figure usually traces back to.
AMPLIFYING_EM_NUMERATOR = 2.78
AMPLIFYING_EM_DENOMINATOR = 1400.0


class Amplifying(enum.StrEnum):
    """The four amplifying reactions, by *which element triggers*.

    The multiplier depends on the triggering element, not on the pair. Sources, both at the
    pin: `pkg/reactable/melt.go` (Pyro onto Cryo → 2.0; Cryo onto Pyro → 1.5) and
    `pkg/reactable/vaporize.go` (Hydro onto Pyro → 2.0; Pyro onto Hydro → 1.5).

    Transformative and additive reactions are **not** here: the BRIEF's ship order puts them
    after the gauge engine, and gcsim computes them on a different path entirely
    (`calcDirectReaction`, with its own `6*em/(2000+em)` bonus). Adding them to this enum
    would invite them into a chain that cannot express them.
    """

    #: Pyro applied onto a Cryo aura.
    MELT = "melt"
    #: Cryo applied onto a Pyro aura — the "reverse" direction, worth less.
    REVERSE_MELT = "reverse_melt"
    #: Hydro applied onto a Pyro aura.
    VAPORIZE = "vaporize"
    #: Pyro applied onto a Hydro aura — the "reverse" direction, worth less.
    REVERSE_VAPORIZE = "reverse_vaporize"

    @property
    def multiplier(self) -> float:
        """The `AmpMult` gcsim sets for this reaction."""
        return _AMP_MULTIPLIERS[self]


#: gcsim `melt.go:23` (`a.Info.AmpMult = 2.0`), `melt.go:30` (`1.5`),
#: `vaporize.go:33` (`2`), `vaporize.go:26` (`1.5`).
_AMP_MULTIPLIERS: dict[Amplifying, float] = {
    Amplifying.MELT: 2.0,
    Amplifying.REVERSE_MELT: 1.5,
    Amplifying.VAPORIZE: 2.0,
    Amplifying.REVERSE_VAPORIZE: 1.5,
}


class ScalingStat(enum.StrEnum):
    """What a talent's multiplier scales off.

    gcsim's `UseHP` / `UseDef` / `UseEM` flags (`damage.go:52-62`), as data on the hit
    rather than flags on a branch: a talent that scales off HP is a *described* talent, not
    a special case in the chain (DESIGN §1 A6).
    """

    ATK = "atk"
    HP = "hp"
    DEF = "def"
    ELEMENTAL_MASTERY = "elemental_mastery"


@dataclass(frozen=True, slots=True)
class ScalingTerm:
    """One `multiplier x stat` part of a hit that scales off more than one stat.

    Nahida's Tri-Karma Purification is `ATK x a + EM x b` in **one** instance of damage. gcsim
    writes the second part as `FlatDmg = em * triKarmaEM`
    (`internal/characters/nahida/skill.go:219-220`), so an extra term sits where flat damage
    sits: added after `base_damage_bonus`, before the DMG-bonus multiplier.

    GO (the formula comparator) sums every term into one base — `splitScaleDmgNode`,
    `libs/gi/sheets/src/Characters/dataUtil.tsx:193-218` — and has no `base_damage_bonus`
    to place them against, so the two agree whenever that bonus is zero, which it is for
    every hit the app builds today. `tests/unit/test_go_single_hit_fixtures.py` checks it.
    """

    stat: ScalingStat
    #: Already a fraction, like `Hit.multiplier`.
    multiplier: float


class DamageInputError(ValueError):
    """A hit or an enemy is described in a way the chain cannot evaluate."""


# ---- The individual terms -------------------------------------------------

def def_multiplier(
    character_level: int,
    enemy_level: int,
    def_reduction: float = 0.0,
    def_ignore: float = 0.0,
) -> float:
    """The DEF term. gcsim `damage.go:81-84`.

        (charLvl + 100) / ((charLvl + 100) + (enemyLvl + 100) * (1 - reduction) * (1 - ignore))

    Note the two are **different mechanics multiplied separately**, not one pool: DEF
    reduction (Zhongli's shred) and DEF ignore (Raiden's C2) stack multiplicatively, and
    modelling them as one number would overstate a build that has both.
    """
    if character_level < 1 or enemy_level < 1:
        msg = f"levels must be positive; got character {character_level}, enemy {enemy_level}"
        raise DamageInputError(msg)
    reduction = min(def_reduction, MAX_DEF_REDUCTION)
    ignore = min(def_ignore, MAX_DEF_IGNORE)
    attacker = character_level + 100
    defender = (enemy_level + 100) * (1 - reduction) * (1 - ignore)
    return attacker / (attacker + defender)


def res_multiplier(resistance: float) -> float:
    """The RES term. Three branches, gcsim `damage.go:89-93`.

        res < 0      ->  1 - res/2
        0 <= res < .75 -> 1 - res
        res >= .75   ->  1 / (4*res + 1)

    **The last branch differs from the oracle by one character, deliberately.** gcsim writes
    `else if res > 0.75`, so a resistance of *exactly* 0.75 falls through to the negative-RES
    branch and returns `1 - 0.75/2 = 0.625` — where both neighbouring branches return `0.25`.
    That is a 2.5x discontinuity at a single point, and both surrounding formulas agree there,
    so it reads as a `>` that should be `>=`.

    This chain uses `>=`, which is continuous. The divergence is recorded in
    `docs/CROSSVAL_gcsim.md` because F.8's tolerance argument has to know about it: a
    crossval case against an enemy at exactly 75% RES would disagree with gcsim by 2.5x, and
    that would not be a formula error on this side.
    """
    if resistance < 0:
        return 1 - resistance / 2
    if resistance < RES_DIMINISHING_THRESHOLD:
        return 1 - resistance
    return 1 / (4 * resistance + 1)


def amplifying_multiplier(
    reaction: Amplifying, elemental_mastery: float, reaction_bonus: float = 0.0,
) -> float:
    """The amplifying term. gcsim `damage.go:113-116`.

        amp_mult * (1 + 2.78*em/(1400 + em) + reaction_bonus)

    `reaction_bonus` is the kit/artifact bonus to this reaction specifically (Crimson Witch's
    4-piece, for instance) — additive with the EM bonus inside the bracket, not a separate
    multiplier.
    """
    if elemental_mastery < 0:
        msg = f"elemental mastery cannot be negative; got {elemental_mastery}"
        raise DamageInputError(msg)
    em_bonus = (AMPLIFYING_EM_NUMERATOR * elemental_mastery) / (
        AMPLIFYING_EM_DENOMINATOR + elemental_mastery
    )
    return reaction.multiplier * (1 + em_bonus + reaction_bonus)


def crit_multiplier(crit_rate: float, crit_dmg: float) -> float:
    """The **expected** crit multiplier: `1 + clamp(rate) * dmg`.

    gcsim rolls (`damage.go:101`); an optimizer cannot score on a coin flip. Crit rate is
    clamped to [0, 1] first, as gcsim does at `damage.go:66-71` — a build stacking crit rate
    past 100% gains nothing, and letting it read as 130% would make the optimizer chase it.
    """
    return 1 + min(max(crit_rate, 0.0), 1.0) * crit_dmg


# ---- The chain ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Hit:
    """One instance of damage, described as data.

    There is no per-character anything here: a talent is a multiplier, a scaling stat, a
    damage channel and a scope. That is what makes a kit describable (DESIGN §1 A6), and it
    is why `ScalingStat` is a field rather than the chain having an `if character ==` in it.
    """

    #: Talent multiplier as a fraction: `1.2` is 120% of the scaling stat.
    multiplier: float
    #: Which damage channel — one of `tags.DAMAGE_CHANNELS`.
    channel: str
    #: Which attack scope — one of `tags.SCOPES`. Decides which gated buffs apply.
    scope: str
    scaling_stat: ScalingStat = ScalingStat.ATK
    #: Flat damage added *inside* the base, before the DMG-bonus multiplier. gcsim's
    #: `atk.Info.FlatDmg` (`damage.go:65`).
    flat_damage: float = 0.0
    #: gcsim's `BaseDmgBonus` — multiplies the scaled stat before flat damage is added.
    base_damage_bonus: float = 0.0
    #: The amplifying reaction this hit triggers, if any.
    amplifying: Amplifying | None = None
    #: Bonus to that reaction specifically (Crimson Witch 4pc and friends).
    reaction_bonus: float = 0.0
    #: Further `multiplier x stat` parts of the **same** instance of damage, for a talent
    #: row such as `# ATK+# Elemental Mastery`. Empty for every single-stat hit. See
    #: `ScalingTerm` for where they enter the chain.
    extra_terms: tuple[ScalingTerm, ...] = ()


@dataclass(frozen=True, slots=True)
class Step:
    """One named factor in the chain, and what produced it."""

    name: str
    factor: float
    detail: str = ""

    def __str__(self) -> str:
        suffix = f"  ({self.detail})" if self.detail else ""
        return f"{self.name:<22} x{self.factor:.4f}{suffix}"


@dataclass(frozen=True, slots=True)
class DamageResult:
    """A damage figure that can account for itself.

    `non_crit`, `crit` and `expected` are all reported because they answer different
    questions: a user comparing to an in-game number wants the first two, an optimizer wants
    the third, and a build whose score depended on which one got returned would be
    unreproducible.
    """

    non_crit: float
    crit: float
    expected: float
    steps: tuple[Step, ...] = field(default_factory=tuple)

    def explain(self) -> str:
        """The chain, in order, with the running total after each step."""
        lines = []
        running = 1.0
        for step in self.steps:
            running *= step.factor
            lines.append(f"  {step}  -> {running:,.2f}")
        return "\n".join([
            "damage:",
            *lines,
            (
                f"  = {self.non_crit:,.2f} non-crit / {self.crit:,.2f} crit "
                f"/ {self.expected:,.2f} expected"
            ),
        ])


def compute_damage(
    hit: Hit,
    *,
    scaling_value: float,
    dmg_bonus: float,
    crit_rate: float,
    crit_dmg: float,
    elemental_mastery: float,
    character_level: int,
    enemy_level: int,
    resistance: float,
    def_reduction: float = 0.0,
    def_ignore: float = 0.0,
    extra_scaling_values: Sequence[float] = (),
) -> DamageResult:
    """Run the chain for one hit and return the figure with its account.

    Takes resolved numbers, not a build: the DAG has already aggregated them, and keeping
    this function free of registry lookups is what lets an optimizer call it millions of
    times without rebuilding a graph per candidate.

    `extra_scaling_values` is the resolved stat for each of `hit.extra_terms`, in order —
    one per term, and refused when the counts differ rather than zipped short.
    """
    if hit.multiplier < 0 or any(term.multiplier < 0 for term in hit.extra_terms):
        msg = f"talent multiplier cannot be negative; got {hit.multiplier}"
        raise DamageInputError(msg)
    if len(extra_scaling_values) != len(hit.extra_terms):
        msg = (
            f"the hit has {len(hit.extra_terms)} extra scaling term(s) and "
            f"{len(extra_scaling_values)} value(s) were resolved for them. Pairing them "
            f"short would drop a term's damage without saying so."
        )
        raise DamageInputError(msg)

    extra = sum(
        term.multiplier * value
        for term, value in zip(hit.extra_terms, extra_scaling_values, strict=True)
    )
    base = (
        hit.multiplier * scaling_value * (1 + hit.base_damage_bonus) + extra + hit.flat_damage
    )
    steps = [
        Step(
            "base",
            base,
            f"{hit.multiplier:.4g} x {scaling_value:,.1f} {hit.scaling_stat}"
            + "".join(
                f" + {term.multiplier:.4g} x {value:,.1f} {term.stat}"
                for term, value in zip(hit.extra_terms, extra_scaling_values, strict=True)
            )
            + (f" + {hit.flat_damage:,.1f} flat" if hit.flat_damage else ""),
        ),
        Step("dmg bonus", 1 + dmg_bonus, f"{dmg_bonus:.1%} on {hit.channel}"),
        Step(
            "def",
            def_multiplier(character_level, enemy_level, def_reduction, def_ignore),
            f"lv{character_level} vs lv{enemy_level}",
        ),
        Step("res", res_multiplier(resistance), f"{resistance:.1%} {hit.channel} RES"),
    ]
    if hit.amplifying is not None:
        steps.append(
            Step(
                "amplifying",
                amplifying_multiplier(hit.amplifying, elemental_mastery, hit.reaction_bonus),
                f"{hit.amplifying} at {elemental_mastery:.0f} EM",
            ),
        )

    non_crit = 1.0
    for step in steps:
        non_crit *= step.factor

    return DamageResult(
        non_crit=non_crit,
        crit=non_crit * (1 + crit_dmg),
        expected=non_crit * crit_multiplier(crit_rate, crit_dmg),
        steps=tuple(steps),
    )
