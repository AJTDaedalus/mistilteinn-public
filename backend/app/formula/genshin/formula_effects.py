"""The vocabulary of the formula fallback's buffs: conditions, and the effects they gate.

Math-fallback P1 (`docs/DESIGN_team_math_fallback.md` §2, tasks 6 and 7). A buff the formula
estimate applies is an **effect** — a stat, a value, and where it reaches — optionally gated by
one or more **conditions** the user can see and change. Resonance (`resonance.py`) and
conditional set bonuses (`set_effects.py`) both speak it, and the browser's synthetic recipe
(`frontend/src/app/sim/formula-recipe.ts`) applies it. One vocabulary, so the two sources
cannot drift apart in what "a +15% CRIT Rate against a Cryo-affected enemy" means.

## Why it is not the Pando tag DAG

`DESIGN` §2.2 names the Pando evaluator as P2's home for *kit* buffs, which need the giver's
and the receiver's stats at once. Set bonuses and resonance need neither: every value here is
a constant, or a constant times something the user states (a stack count, a healing total),
or a per-candidate conversion the recipe already knows how to carry (flat damage from ATK,
burst bonus from Energy Recharge). A tag DAG would be machinery for nothing P1 asks.

## The shape mirrors GO's, deliberately

Genshin Optimizer is the comparator for this estimate (`docs/DECISIONS.md` §38). Its sheets
gate each buff with `greaterEq(input.artSet.X, n, …)` and a conditional read
(`cond(key, name)` → `equal`/`lookup`), and scope it by the key it writes —
`normal_dmg_`, `pyro_dmg_`, `critRate_`, `<ele>_enemyRes_`. Each field below is one of those
choices: `moves` is the `normal_`/`charged_` prefix, `elements` the `<ele>_` one, `when` the
`equal`, `per` the `lookup` over stacks, `by_stack` a `lookup` whose rows are not linear.

## Conditions are static for the whole calculation

As in GO (`docs/RESEARCH_go_team_math.md` §2): a stack count is a number the user states, not
something derived from a timeline. A row of the target can override any of them — GO's newer
"frames" — which is what lets one row be "after the skill" and the next not.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.formula.genshin import tags

#: What a row's hit can be, for a buff that gates on it. `tags.SCOPES` minus the two that are
#: not a talent's own move: `skill_hold` is a skill for every set and resonance that reads it
#: (GO writes only `skill_dmg_`), and `weapon_skill` is a weapon's own damage instance.
MOVES: tuple[str, ...] = ("normal", "charged", "plunge", "skill", "burst")

#: Amplifying reactions, in `damage.Amplifying`'s spelling — a reaction bonus reaches both
#: directions of its reaction (GO `vaporize_dmg_` reads into forward and reverse alike).
AMPLIFYING_REACTIONS: tuple[str, ...] = ("vaporize", "reverse_vaporize", "melt", "reverse_melt")

#: Stats an effect can write. The first block are kernel quantities, added to the hit's own
#: pool exactly as an artifact stat would be. The rest are scoped or derived terms with no
#: pool of their own:
#:
#: - `dmg_bonus` — DMG%, reaching `elements` (None = every channel, GO's `all_dmg_`).
#: - `reaction_bonus` — added to an amplifying reaction's multiplier (GO `vaporize_dmg_`).
#: - `enemy_res` — the target's resistance to `elements`, negative for a shred
#:   (GO `<ele>_enemyRes_`).
#: - `flat_damage` — flat damage added to the base, times the `per` condition's value
#:   (GO `<move>_dmgInc`).
#: - `flat_damage_from_atk` — flat damage of `value` × the candidate's **total** ATK
#:   (GO `prod(..., input.total.atk)`), so it moves with every candidate.
#: - `flat_damage_from_def` — the same, from the candidate's total DEF: a kit whose giver is
#:   the optimized character adding flat damage from their own DEF (Kachina's A4, P2). GO
#:   `prod(percent(x), own.premod.def)` into `formula.base`.
#: - `flat_damage_from_hp`, `flat_damage_from_em` — the same, from the candidate's total HP
#:   (Zhongli's A4 on his own hits, GO `prod(percent(x), own.premod.hp)` into `formula.base`)
#:   or Elemental Mastery (task 11).
#: - `dmg_bonus_from_energy_recharge` — DMG% of `value` × total Energy Recharge, capped at
#:   `cap` (GO `min(cap, prod(rate, input.premod.enerRech_))`), likewise per candidate.
#: - `flat_atk` — flat ATK added after the percentage (GO `total.atk`/`final.atk`), the shape
#:   a kit buff derived from its giver's stats takes once the giver's stat is a number
#:   (Bennett's burst, P2 — `sheets.py`).
#: - `dmg_bonus_from_em` — DMG% of `value` × the **hit owner's own** total Elemental Mastery,
#:   per candidate. Only a kit buff whose giver is also the optimized character emits it
#:   (Kazuha's A4 on Kazuha): a teammate's EM is a number, the subject's moves with every
#:   candidate. GO `prod(percent(x), own.premod.eleMas)`.
#: - `flat_atk_from_def` — flat ATK of `value` × the **hit owner's own** total DEF, per
#:   candidate (Noelle's Sweeping Time, P2 task 11: GO `ownBuff.premod.atk.add(prod(
#:   own.premod.def, …))`). Only a giver who is the optimized character emits it; it reaches
#:   every ATK-scaling term of a hit and moves with the candidate's DEF.
#: - `base_atk` — base ATK added before the percentage (GO `ownBuff.base.atk`, Mavuika's C2),
#:   so every ATK% multiplies it.
#: - `base_dmg_bonus` — added to the hit's base-damage multiplier on its talent term (GO
#:   `baseMulti`: `talent × stat × (1 + x)`), the `baseDamageBonus` the single-hit kernel
#:   already carries (Neuvillette's A1, Skirk's A4).
EffectStat = Literal[
    "atk_pct", "hp_pct", "def_pct", "elemental_mastery", "energy_recharge",
    "crit_rate", "crit_dmg",
    "dmg_bonus", "reaction_bonus", "enemy_res",
    "flat_damage", "flat_damage_from_atk", "flat_damage_from_hp", "flat_damage_from_def",
    "flat_damage_from_em",
    "dmg_bonus_from_energy_recharge",
    "flat_atk", "dmg_bonus_from_em",
    "flat_atk_from_def", "base_atk", "base_dmg_bonus",
]

#: Stats that are kernel quantities and so can also travel in a set-bonus pool.
POOL_STATS: frozenset[str] = frozenset({
    tags.Q_ATK_PCT, tags.Q_HP_PCT, tags.Q_DEF_PCT, tags.Q_ELEMENTAL_MASTERY,
    tags.Q_ENERGY_RECHARGE, tags.Q_CRIT_RATE, tags.Q_CRIT_DMG,
})

#: Where an effect's element list can come from when it is not written out: the wearer's own
#: element (Scroll of the Hero of Cinder City, Celestial Gift), or the option a `choice`
#: condition holds (Viridescent Venerer's swirled element, Archaic Petra's shard).
ElementSource = Literal["wearer"] | str

ConditionKind = Literal["toggle", "stacks", "choice", "number"]

#: Why a default is what it is. The rule (owner decision pending — `TASKS` task 7):
#:
#: - `self` — the wearer triggers it in ordinary play on their own (*after using an Elemental
#:   Skill*, stacks from their own hits): **on, at its maximum**.
#: - `situational` — it depends on the enemy, the team, HP changes, shields, reactions or being
#:   off-field: **off**, which is also GO's default for every conditional.
DefaultReason = Literal["self", "situational"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Condition(_Model):
    """One assumption the user owns. Keys are unique within their tier or resonance."""

    key: str
    label: str
    kind: ConditionKind
    #: toggle: 0 or 1. stacks/number: a count. choice: the option's name, or "" for none.
    default: float | str
    default_reason: DefaultReason
    #: stacks/number: the largest value it can hold.
    max: float | None = None
    #: number: the step a picker offers (GO's `range(1000, 15000, 1000)`).
    step: float | None = None
    #: choice: the options, none of which is "" (that is "no option chosen").
    options: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _well_formed(self) -> Condition:
        if self.kind == "choice":
            if not self.options or not isinstance(self.default, str):
                raise ValueError(f"{self.key}: a choice needs options and a string default")
            if self.default and self.default not in self.options:
                raise ValueError(f"{self.key}: default {self.default!r} is not an option")
        else:
            if isinstance(self.default, str):
                raise ValueError(f"{self.key}: a {self.kind} default is a number")
            if self.kind == "toggle" and self.default not in (0, 1):
                raise ValueError(f"{self.key}: a toggle defaults to 0 or 1")
            if self.kind in ("stacks", "number") and (
                self.max is None or not 0 <= self.default <= self.max
            ):
                raise ValueError(f"{self.key}: default must lie in [0, max]")
        expected = {"self": "on", "situational": "off"}[self.default_reason]
        is_on = bool(self.default)
        if (expected == "on") != is_on:
            raise ValueError(
                f"{self.key}: a `{self.default_reason}` condition defaults "
                f"{expected}, and this one does not",
            )
        if (self.default_reason == "self" and self.kind in ("stacks", "number")
                and self.default != self.max):
            raise ValueError(f"{self.key}: a `self` stack count defaults to its maximum")
        return self


class When(_Model):
    """`condition` holds one of `values` (a toggle is on when it holds 1)."""

    condition: str
    values: tuple[float | str, ...]


class Effect(_Model):
    """One buff, resolved to a number."""

    stat: EffectStat
    value: float
    #: Channels it reaches; None means every channel. Mutually exclusive with `element_from`.
    elements: tuple[str, ...] | None = None
    #: `wearer`, or keys of `choice` conditions whose option is an element. Several sources
    #: are a **union**, each element once (GO's non-stacking per element: Scroll of the Hero
    #: of Cinder City buffs the wearer's element and the other one in the reaction, and the
    #: same element chosen twice is still one buff).
    element_from: tuple[ElementSource, ...] | None = None
    #: Moves it reaches; None means every move.
    moves: tuple[str, ...] | None = None
    #: `reaction_bonus` only: which amplifying reactions it reaches.
    reactions: tuple[str, ...] | None = None
    #: Every one must hold for the effect to apply.
    when: tuple[When, ...] = ()
    #: Multiply by this stacks/number condition's value (GO's `lookup` over a linear range).
    per: str | None = None
    #: The value at 1, 2, 3 … stacks of `per`, when the steps are not linear (Nymph's Dream).
    by_stack: tuple[float, ...] | None = None
    #: Multiply by a count of teammates (Gilded Dreams), capped at `per_team_max`.
    per_team: Literal["same_element_others", "different_element"] | None = None
    per_team_max: int | None = None
    #: `dmg_bonus_from_energy_recharge`: the most it can grant.
    cap: float | None = None
    #: Applies only to a wearer of one of these weapon classes (`WeaponType` values).
    weapon_types: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _well_formed(self) -> Effect:
        if self.elements is not None and self.element_from is not None:
            raise ValueError("an effect names its elements or derives them, not both")
        for element in self.elements or ():
            if element not in tags.DAMAGE_CHANNELS:
                raise ValueError(f"{element!r} is not one of {tags.DAMAGE_CHANNELS}")
        for move in self.moves or ():
            if move not in MOVES:
                raise ValueError(f"{move!r} is not one of {MOVES}")
        if self.stat == "reaction_bonus":
            if not self.reactions or set(self.reactions) - set(AMPLIFYING_REACTIONS):
                raise ValueError("a reaction bonus names amplifying reactions")
        elif self.reactions is not None:
            raise ValueError(f"only a reaction bonus names reactions, not {self.stat}")
        if self.stat == "enemy_res" and self.elements is None and self.element_from is None:
            raise ValueError("a resistance shred names its element")
        if (self.stat == "dmg_bonus_from_energy_recharge") != (self.cap is not None):
            raise ValueError("a cap belongs to, and only to, an Energy Recharge conversion")
        if self.by_stack is not None and self.per is None:
            raise ValueError("`by_stack` needs the stacks condition it reads (`per`)")
        if (self.per_team is None) != (self.per_team_max is None):
            raise ValueError("`per_team` and `per_team_max` come together")
        return self


class Unmodelled(_Model):
    """A part of a bonus the estimate does **not** apply, said out loud."""

    what: str
    reason: str


class Bonus(_Model):
    """What a set tier or a resonance contributes, ready to apply."""

    conditions: tuple[Condition, ...] = Field(default=())
    effects: tuple[Effect, ...] = Field(default=())
    unmodelled: tuple[Unmodelled, ...] = Field(default=())

    @model_validator(mode="after")
    def _references_resolve(self) -> Bonus:
        by_key = {c.key: c for c in self.conditions}
        if len(by_key) != len(self.conditions):
            raise ValueError("condition keys repeat")
        for effect in self.effects:
            for when in effect.when:
                if when.condition not in by_key:
                    raise ValueError(f"`when` names unknown condition {when.condition!r}")
            if effect.per is not None:
                if effect.per not in by_key or by_key[effect.per].kind not in ("stacks", "number"):
                    raise ValueError(f"`per` must name a stacks or number condition: {effect.per}")
                if effect.by_stack is not None:
                    top = by_key[effect.per].max or 0
                    if len(effect.by_stack) != int(top):
                        raise ValueError(f"`by_stack` needs one value per stack up to {top}")
            for source in effect.element_from or ():
                if source == "wearer":
                    continue
                condition = by_key.get(source)
                if condition is None or condition.kind != "choice":
                    raise ValueError(f"`element_from` must name a choice condition: {source}")
                if set(condition.options or ()) - set(tags.DAMAGE_CHANNELS):
                    raise ValueError(f"{source}: every option must be an element")
        return self


def status_of(bonus: Bonus) -> Literal["modelled", "partial", "unmodelled", "no_damage_effect"]:
    """What a reader is told about this bonus — computed, never curated, so it cannot lie.

    `no_damage_effect` is a bonus whose whole effect is outside damage (healing, shields,
    energy, the wearer's own RES): applying nothing for it is **correct**, not a gap. It is
    recognised by every unmodelled part carrying the `NO_DAMAGE` reason.
    """
    if bonus.effects:
        return "partial" if bonus.unmodelled else "modelled"
    if bonus.unmodelled and all(u.reason.startswith(NO_DAMAGE) for u in bonus.unmodelled):
        return "no_damage_effect"
    return "unmodelled"


#: The prefix of every reason that says "this is not damage, so nothing is missing".
NO_DAMAGE = "no damage effect"
