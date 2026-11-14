"""Kit sheets: a character's talent, passive and constellation buffs, as data.

Math-fallback P2, task 9 (`docs/DESIGN_team_math_fallback.md` §2.6). A **sheet** says, for one
character, which buffs their kit grants: from which source (a talent, an ascension passive, a
constellation), to whom (themselves, the active character, the whole team, the others, the
enemy), to which stat, under which conditions, and **where each number comes from**. It is
the P1 set-effect pattern (`set_effects.py`) carried over to kits: the structure is transcribed
from Genshin Optimizer's character sheets and cited to file and line, and the numbers are
**never** written into it. Each value is a reference into this repo's own seeded rows:

- `{"talent": T, "row": "ATK Bonus Ratio"}` — the parameter a talent row's format string names
  (`"ATK Bonus Ratio|{param4:P}"` → `params[3]`), at the **giver's** effective talent level;
- `{"constellation": n, "param": i}` — `constellations[n].param_list[i]`;
- `{"passive": a, "param": i}` — the ascension-`a` passive's `param_list[i]`;
- `{"constant": x, "cite": "…"}` — only for something no seeded list carries;

optionally `"times_stat"`: multiplied by one of the **giver's** stats (Bennett's burst is its
ratio × Bennett's base ATK; Kazuha's A4 is 0.04% × Kazuha's EM).

## Pinned, so a patch cannot silently change what a number means

As in `set_effects.json`: each constellation and passive list a sheet reads is pinned to the
list it was curated against, and each talent row to its full label. A mismatch withholds the
effect — it is listed as unmodelled, with the reason — rather than reading index 3 of a list
whose index 3 now means something else.

## Evaluated in the giver's context, on the Pando DAG

Each effect value is a node (`builder.prod_` of a constant and, with `times_stat`, the stat
graph's own node for that stat) registered in the **giver's** registry under
`tags.formula_tag(sheet, effect)`, and read back there by a `Calculator` over that registry.
That registry is the one the stat calculator built from the giver's build
(`services/kit_buffs.py`, pass 1), so "Bennett's base ATK" is resolved by the same graph that
resolves every stat in this repo — one mechanic, one implementation (DESIGN §1 A6).

**Conditions are not evaluated here.** They travel with each effect as `when`, in the P1
vocabulary (`formula_effects.py`), and the browser decides them per row of the target (GO's
"frames"). So the DAG resolves a value *as if* its conditions held, and the browser gates it.

## Receivers

GO tags a buff `own` (self), `teamBuff` (everyone), `notOwnBuff` (the others) or
`enemyDeBuff`; Bennett's field is `teamBuff` gated on `destIsActive`. In the formula estimate
the receiver is always **the optimized character**, who is the one dealing every hit of the
target — so `active` is "the subject, standing where the buff is", `team` and `enemy` always
reach them, `self` only when they are the giver, and `others` only when they are not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.formula.builder import const, max_, min_, prod_, read_, sum_, tag_
from app.formula.genshin import stats, tags
from app.formula.genshin.formula_effects import (
    AMPLIFYING_REACTIONS,
    MOVES,
    Bonus,
    Condition,
    ConditionKind,
    Effect,
    EffectStat,
    TalentRowScope,
    Unmodelled,
    When,
    status_of,
)
from app.formula.tags import Tag
from app.pando.calculator import Calculator

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.formula.nodes import AnyNode
    from app.pando.calculator import NodeRegistry

_DATA = Path(__file__).resolve().parents[2] / "data" / "formula" / "sheets"

#: The talents a sheet can read a row from, in `TalentType`'s spelling.
TALENTS: tuple[str, ...] = ("normal_attack", "elemental_skill", "elemental_burst")

#: Where a buff comes from. `talent` is any of the three levelled talents; `a1`/`a4` the
#: ascension passives (gated on ascension phase 1 and 4, GO `input.asc`); `a0` the passive a
#: character has from the start (`ascension_passives.unlock_ascension` 0: Arlecchino's
#: Balemoon, GO `passive3`, ungated); `c1`…`c6` the constellations (gated on
#: `constellation >= n`, GO `cmpGE(constellation, n, …)`).
Source = Literal["talent", "a0", "a1", "a4", "c1", "c2", "c3", "c4", "c5", "c6"]

#: The ascension phases a passive's list is read at: 0 (from the start), 1 and 4.
PASSIVE_PHASES: tuple[int, ...] = (0, 1, 4)

#: The `tags.SRC_*` label each source is attributed to in an explanation.
SOURCE_LABEL: dict[str, str] = {
    "talent": tags.SRC_TALENT,
    "a0": tags.SRC_ASCENSION_PASSIVE, "a1": tags.SRC_ASCENSION_PASSIVE,
    "a4": tags.SRC_ASCENSION_PASSIVE,
    **{f"c{n}": tags.SRC_CONSTELLATION for n in range(1, 7)},
}

MAX_CONSTELLATION = 6

Receivers = Literal["self", "active", "team", "others", "enemy"]

#: Stats an `enemy` debuff writes: the target's resistance, or its DEF (Nahida's C2).
ENEMY_STATS: tuple[str, ...] = ("enemy_res", "def_reduction")

#: A character's element, lower case, as `receiver_elements`/`per_team_elements` name it.
VISIONS: tuple[str, ...] = ("pyro", "hydro", "electro", "cryo", "anemo", "geo", "dendro")

#: Giver stats a value may be multiplied by, and the stat graph's node for each.
GIVER_STATS: dict[str, AnyNode] = {
    tags.Q_BASE_ATK: read_(tags.stat_tag(tags.Q_BASE_ATK), "sum"),
    tags.Q_BASE_HP: read_(tags.stat_tag(tags.Q_BASE_HP), "sum"),
    tags.Q_BASE_DEF: read_(tags.stat_tag(tags.Q_BASE_DEF), "sum"),
    tags.Q_ATK: stats.ATK_NODE,
    tags.Q_HP: stats.HP_NODE,
    tags.Q_DEF: stats.DEF_NODE,
    tags.Q_ELEMENTAL_MASTERY: stats.ELEMENTAL_MASTERY_NODE,
    tags.Q_ENERGY_RECHARGE: stats.ENERGY_RECHARGE_NODE,
}

#: Giver stats artifacts do not move: character and weapon base only. A buff that reads one of
#: these is a constant even when its giver is the optimized character.
STATIC_STATS: frozenset[str] = frozenset({tags.Q_BASE_ATK, tags.Q_BASE_HP, tags.Q_BASE_DEF})

#: When the giver **is** the optimized character, a buff reading one of their artifact-moved
#: stats must move with each candidate. The pairs the browser's recipe can carry per
#: candidate, and the effect stat each becomes. Anything else is withheld, by name.
SELF_CONVERSIONS: dict[tuple[str, str], EffectStat] = {
    ("dmg_bonus", tags.Q_ELEMENTAL_MASTERY): "dmg_bonus_from_em",
    # Flat damage from the hit owner's own total ATK (Valeriy's Offensive Directive on
    # Valeriy) or DEF (Kachina's A4 on her own skill): GO `prod(percent(x), own.premod.<s>)`
    # into `formula.base` — the recipe's resolved flat-term conversion (`recipe-eval.ts`).
    ("flat_damage", tags.Q_ATK): "flat_damage_from_atk",
    ("flat_damage", tags.Q_DEF): "flat_damage_from_def",
    # Zhongli's A4 on his own hits (GO `prod(percent(x), own.premod.hp)` into `formula.base`),
    # and the same from EM: the recipe resolves a flat term from any of its four sources.
    ("flat_damage", tags.Q_HP): "flat_damage_from_hp",
    ("flat_damage", tags.Q_ELEMENTAL_MASTERY): "flat_damage_from_em",
    # Noelle's Sweeping Time on herself: ATK from her own DEF (GO `ownBuff.premod.atk.add(
    # prod(own.premod.def, …))`), carried per candidate into every ATK-scaling term.
    ("flat_atk", tags.Q_DEF): "flat_atk_from_def",
    # The capped self-conversions the owner ruled priced exactly per build (2026-11-14,
    # `DECISIONS.md` §40): Hu Tao's ATK from her Max HP, Furina's A4 DMG from her Max HP,
    # Nahida's A4 CRIT Rate from her EM. Each carries its cap and threshold to the recipe.
    ("flat_atk", tags.Q_HP): "flat_atk_from_hp",
    ("dmg_bonus", tags.Q_HP): "dmg_bonus_from_hp",
    ("crit_rate", tags.Q_ELEMENTAL_MASTERY): "crit_rate_from_em",
}

DefaultBy = Literal["self", "situational", "giver_is_subject"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ParamRef(_Strict):
    """Another seeded parameter a value reads: a factor (Vesna's C4 multiplying her A4), a cap
    (Chevreuse's A4 at 40%), or a raise to a condition's maximum (Furina's C1). A factor may
    also be a talent row of the giver's, at their effective level (Raiden's Eye on herself is
    the skill's per-Energy ratio times her burst's own "Energy Cost" row, GO `dm.burst.enerCost`).
    """

    constellation: int | None = None
    passive: int | None = None
    param: int | None = None
    talent: str | None = None
    row: str | None = None
    #: With `talent`: the row's published parameter at this **0-based index**, one that no
    #: label's format string names (Hu Tao's skill `params[6]`, the 400% base-ATK cap of her
    #: Guide to Afterlife: GO `skillParam_gen.skill[6][0]`, `maxAtkInc`). `row` still names the
    #: pinned label the talent was curated against, so a re-seed that changes the row withholds
    #: it; a seeded row whose labels come to name the index withholds it too.
    unnamed: int | None = None

    @model_validator(mode="after")
    def _one_list(self) -> ParamRef:
        named = [x for x in (self.constellation, self.passive, self.talent) if x is not None]
        if len(named) != 1:
            raise ValueError("a parameter reference names a constellation, a passive or a "
                             "talent row")
        if self.talent is not None:
            if self.talent not in TALENTS or not self.row or self.param is not None:
                raise ValueError("a talent parameter names a talent and a row, not a param")
            if self.unnamed is not None and self.unnamed < 0:
                raise ValueError("an unnamed talent parameter is a 0-based index")
        elif self.param is None:
            raise ValueError("a constellation or passive parameter names its index")
        elif self.unnamed is not None:
            raise ValueError("`unnamed` indexes a talent row's parameters")
        return self


class Cited(_Strict):
    """A number no seeded list carries, with where it was read (GO's `1 / 1000`)."""

    constant: float
    cite: str


class TeamIndex(_Strict):
    """A value read from a seeded **table** indexed by a team count (GO `subscript(count,
    table)`): Escoffier's A4 by Hydro/Cryo members, Yelan's A1 by distinct elements. The value
    at count `k` is the list's entry `param + k - 1`; a count of 0 is no buff, and a count above
    `size` (the table's length) is withheld rather than read past the table's end."""

    #: `elements`: members whose element is one of `elements` (the receiver included, GO
    #: `team.common.count`); `distinct`: how many different elements the team has (GO
    #: `own.common.eleCount`).
    count: Literal["elements", "distinct"]
    elements: tuple[str, ...] | None = None
    size: int
    #: A count past `size` reads the table's last entry instead of being withheld: GO writes
    #: the last entry again (Gorou's C6, `[c6[0], c6[1], c6[2], c6[2]]` by the Geo count).
    clamp: bool = False

    @model_validator(mode="after")
    def _named(self) -> TeamIndex:
        if (self.count == "elements") != (self.elements is not None):
            raise ValueError("an `elements` count names its elements, a `distinct` one none")
        for element in self.elements or ():
            if element not in VISIONS:
                raise ValueError(f"{element!r} is not one of {VISIONS}")
        return self


class TeamCount(_Strict):
    """How many members (the receiver included) have one of `elements`: at least `at_least`,
    at most `at_most`. GO `cmpGE(team.common.count.geo, 3, …)` (Gorou's banner at three Geo
    members), `cmpLT(sum(count.pyro, count.hydro, count.cryo, count.electro), 3, …)`
    (Xilonen's Geo sample, while fewer than three samplers are converted)."""

    elements: tuple[str, ...]
    at_least: int | None = None
    at_most: int | None = None

    @model_validator(mode="after")
    def _bounded(self) -> TeamCount:
        if self.at_least is None and self.at_most is None:
            raise ValueError("a team count names a bound")
        for element in self.elements:
            if element not in VISIONS:
                raise ValueError(f"{element!r} is not one of {VISIONS}")
        return self

    def holds(self, present: Sequence[str]) -> bool:
        """Whether these members' (lower-case) elements satisfy both bounds."""
        n = sum(1 for e in present if e in self.elements)
        return ((self.at_least is None or n >= self.at_least)
                and (self.at_most is None or n <= self.at_most))


class TeamGate(_Strict):
    """A buff that holds only for some team compositions: every member's element is one of
    `only`, each of `includes` is present, (when given) the team has `members` members, and
    every `counts` bound holds. GO `cmpEq(own.common.eleCount, 2, …)` with `count.electro >= 1`
    (Chevreuse's A1, a Pyro and Electro team), `cmpEq(count.hydro + count.cryo, 4, …)`
    (Escoffier's C1), `cmpGE(count.geo, 3, …)` (Gorou's banner)."""

    only: tuple[str, ...] = VISIONS
    includes: tuple[str, ...] = ()
    members: int | None = None
    counts: tuple[TeamCount, ...] = ()

    @model_validator(mode="after")
    def _visions(self) -> TeamGate:
        for element in (*self.only, *self.includes):
            if element not in VISIONS:
                raise ValueError(f"{element!r} is not one of {VISIONS}")
        return self

    def holds(self, team_elements: Sequence[str | None]) -> bool:
        """Whether this team (every member's element, the receiver's included) qualifies."""
        present = [e.lower() for e in team_elements if e is not None]
        if len(present) != len(team_elements):
            return False
        if self.members is not None and len(present) != self.members:
            return False
        return (all(e in self.only for e in present)
                and all(e in present for e in self.includes)
                and all(c.holds(present) for c in self.counts))


class CountBonus(_Strict):
    """A constellation that counts as one more member of the elements a row is chosen by:
    Nahida's C1 (GO `sum(count.pyro, cmpGE(constellation, 1, 1))`). The 1 is GO's literal (her
    C1 `param_list` is all zeros), so it is a cited constant."""

    constellation: int
    add: Cited


class TeamRows(_Strict):
    """A talent value whose **row** is chosen by a team count (GO `cmpGE(level, 1, cmpEq(level,
    1, row_1, row_2))`): Nahida's burst bonus reads its one-Pyro row or its two-Pyro row. Count
    0 is no buff; count `k` reads `labels[k - 1]`, and a count past the last label reads the
    last, as GO's `cmpEq(…, 1, a, b)` gives `b` for every count above 1. The labels are written
    in full, because the rows share the text before their `|`."""

    elements: tuple[str, ...]
    labels: tuple[str, ...]
    count_bonus: CountBonus | None = None

    @model_validator(mode="after")
    def _named(self) -> TeamRows:
        if not self.labels:
            raise ValueError("a team-chosen row names its rows")
        for element in self.elements:
            if element not in VISIONS:
                raise ValueError(f"{element!r} is not one of {VISIONS}")
        return self


class ValueRef(_Strict):
    """Where one number comes from. Exactly one of `talent`, `constellation`, `passive` or
    `constant`."""

    talent: str | None = None
    row: str | None = None
    #: With `talent`: which of the row's parameters, in the order its format string names them
    #: (Skirk's "0/1/2/3 Void Rift Absorption DMG Bonus|{param4}/{param5}/{param6}/{param7}",
    #: `nth: 2` → `params[5]`). Absent is the first.
    nth: int | None = None
    constellation: int | None = None
    passive: int | None = None
    param: int | None = None
    constant: float | None = None
    cite: str | None = None
    times_stat: str | None = None
    #: The seeded list publishes a reduction as a positive number (Vodyanitsa's "Hydro/Cryo
    #: RES Reduction" 0.3); GO writes it negated into `enemyRes_` (`.map((v) => -v)`).
    negate: bool = False
    #: A talent row with several parameters: which one, 0 for the first `{paramN}` its format
    #: string names. Raiden's "Resolve Bonus|{param2} Initial/{param3} ATK DMG Per Stack" is
    #: GO's `resolveBonus1` (part 0) and `resolveBonus2` (part 1).
    part: int = 0
    #: Multiplied by a second seeded parameter: GO `prod(percent(a4), c4)`.
    times_param: ParamRef | None = None
    #: With `times_stat`: the stat is counted per this many points (GO `prod(percent(x), hp,
    #: 1 / 1000)`, "per 1,000 Max HP"). Without one, on an effect with `per`: the condition is
    #: counted per this many (GO `hydro_dmg_: passive2[2][0] / 100`, Neuvillette's A4 per
    #: percentage point of HP). A number, so it carries its citation.
    stat_unit: Cited | None = None
    #: The most the value can be: GO `min(…, percent(max))`, the maximum a seeded parameter.
    cap: ParamRef | None = None
    #: Read from a table indexed by a team count, decided in `resolve`.
    index_by_team: TeamIndex | None = None
    #: A talent row chosen by a team count (Nahida's burst bonus by the Pyro count).
    rows_by_team: TeamRows | None = None
    #: Multiplied by the **highest** value of this stat among the optimized character's
    #: teammates, the giver included (GO `team.premod.eleMas.max`, Nahida's A1). Each member's
    #: pass-1 value (DESIGN §2.6 rule 1); the subject's own never enters it, since it moves
    #: with every candidate, and a giver who is the subject is withheld by name.
    times_team_max: str | None = None
    #: With `times_stat`: the stat is capped at this parameter before it is multiplied (GO
    #: `prod(ratio, min(total.atk, maxAtk))`, Xianyun's A4).
    stat_cap: ParamRef | None = None
    #: A number added to the parameter, cited: a talent row published as a hit's whole
    #: multiplier ("Blazing Arrow DMG|{param4} Normal Attack DMG", GO `baseMulti: skillMult`)
    #: written as a `base_dmg_bonus`, which adds to the default multiplier of 1 — so the value
    #: is the row less 1 (GO `dmg()`'s `baseMulti` default, `formula/src/data/char/util.ts`).
    offset: Cited | None = None
    #: With `times_stat`: the stat counts only above this parameter (GO `max(sum(final.eleMas,
    #: -eleMas_min), 0)`, Nahida's A4 above 200 EM). Applied before `stat_cap`, so a stat cap
    #: then bounds the **counted** stat (her 800).
    threshold: ParamRef | None = None
    #: With `cap`: the cap is multiplied by this giver stat (GO `prod(percent(maxAtkInc),
    #: own.base.atk)`, Hu Tao's 400% of her base ATK). On a giver who is the subject it must be
    #: one artifacts do not move, or the cap itself would move and is withheld.
    cap_times_stat: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> ValueRef:
        named = [x for x in (self.talent, self.constellation, self.passive, self.constant)
                 if x is not None]
        if len(named) != 1:
            raise ValueError("a value names exactly one of talent, constellation, passive, "
                             "constant")
        if self.talent is not None:
            if self.talent not in TALENTS or not self.row or self.param is not None:
                raise ValueError("a talent value names a talent and a row label, not a param")
        elif self.constant is not None:
            if not self.cite or self.param is not None:
                raise ValueError("a constant carries its citation and no param")
        elif self.param is None:
            raise ValueError("a constellation or passive value names its param index")
        if self.constellation is not None and not 1 <= self.constellation <= MAX_CONSTELLATION:
            raise ValueError("constellations are 1-6")
        if self.passive is not None and self.passive not in PASSIVE_PHASES:
            raise ValueError("an ascension passive unlocks at phase 0, 1 or 4")
        if self.times_stat is not None and self.times_stat not in GIVER_STATS:
            raise ValueError(f"times_stat must be one of {sorted(GIVER_STATS)}")
        if self.nth is not None and (self.talent is None or self.nth < 0):
            raise ValueError("`nth` picks a parameter of a talent row")
        if self.index_by_team is not None and self.param is None:
            raise ValueError("a team-indexed value reads a constellation or passive list")
        return self

    @model_validator(mode="after")
    def _team_reads(self) -> ValueRef:
        if self.rows_by_team is not None and self.talent is None:
            raise ValueError("a team-chosen row belongs to a talent value")
        if self.times_team_max is not None:
            if self.times_team_max not in GIVER_STATS:
                raise ValueError(f"times_team_max must be one of {sorted(GIVER_STATS)}")
            if self.times_stat is not None:
                raise ValueError("a value reads the giver's stat or the team's highest, not both")
        if self.stat_cap is not None and self.times_stat is None:
            raise ValueError("a stat cap belongs to a value that reads a stat")
        if self.threshold is not None and self.times_stat is None:
            raise ValueError("a threshold belongs to a value that reads a stat")
        if self.cap_times_stat is not None:
            if self.cap is None:
                raise ValueError("`cap_times_stat` multiplies a cap")
            if self.cap_times_stat not in GIVER_STATS:
                raise ValueError(f"cap_times_stat must be one of {sorted(GIVER_STATS)}")
        if self.offset is not None and (self.times_stat is not None or self.cap is not None
                                        or self.times_team_max is not None):
            raise ValueError("an offset belongs to a plain parameter, not one read with a stat "
                             "or a cap")
        return self

    def params_read(self) -> list[ParamRef]:
        """The extra parameters this value reads besides its own: pinned like it."""
        return [p for p in (self.times_param, self.cap, self.stat_cap, self.threshold)
                if p is not None]


class Usual(_Strict):
    """The value a condition's character holds it at in ordinary play, and why: the default
    rule of owner ruling 2026-11-14 (`DECISIONS.md` §40 (ii)). `reason` is the one line the
    panel shows beside the control; `cite` names where the value comes from (a GO default, a
    seeded parameter, a KQM guide's sentence) where one exists. **Never invented**: where no
    usual value can be justified, `value` is `"max"` and the reason says so.

    A `value` of 0 (or `""` for a choice) keeps the condition off, and `reason` then says why:
    the circumstance it needs is not the character's normal play."""

    value: float | str
    reason: str
    cite: str | None = None
    #: The usual value holds only when the optimized character's element is one of these
    #: (Kazuha swirls the element of the carry he buffs): for any other receiver the condition
    #: is off, and the note says why. A choice may instead name `"receiver_element"` as its
    #: value: the option equal to the receiver's element (Sucrose's C6 absorbs it).
    receiver_elements: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _elements(self) -> Usual:
        for element in self.receiver_elements or ():
            if element not in VISIONS:
                raise ValueError(f"{element!r} is not one of {VISIONS}")
        return self


class SheetCondition(_Strict):
    """A condition as a sheet declares it, and its default.

    **The default rule, in this one place** (owner rulings `DECISIONS.md` §39 (i), amended by
    §40 (ii) on 2026-11-14):

    1. A condition with a curated `usual` defaults to it — the value its character's ordinary
       play holds it at, with the reason shown (`default_reason` `usual`; `situational` where
       the usual value is off).
    2. Otherwise `default_by` decides: `self` (triggered by the character's own kit) is on at
       its maximum; `giver_is_subject` is the same when the giver is the optimized character,
       and when a teammate is, the teammate's buff is assumed up as they play it — on at its
       maximum (`teammate`), said in the note.
    3. A `situational` condition (the enemy, the fight, rare circumstances) must carry a
       `usual`: either its normal-play value, or 0 with the reason it stays off. So no
       condition is off without a reason, and every one stays a visible toggle.
    """

    key: str
    label: str
    kind: ConditionKind
    default_by: DefaultBy
    max: float | None = None
    step: float | None = None
    options: tuple[str, ...] | None = None
    #: A constellation (or passive) that raises `max` by one of its parameters once unlocked:
    #: Furina's C1 raises the Fanfare limit by its 100 (GO `sum(maxFanfare, cmpGE(constellation,
    #: 1, fanfareLimitInc))`). Pinned like any value.
    max_raise: ParamRef | None = None
    #: The same raise by a number no seeded list carries, cited: Valeriy's C4 adds 30 to the
    #: Impact Momentum limit (GO `momentumLimitInc: 30`, a literal; his C4 list holds only its
    #: charging efficiency).
    max_raise_cited: CountBonus | None = None
    #: The curated usual value (§40 (ii)); required on a `situational` condition.
    usual: Usual | None = None
    go: str

    @model_validator(mode="after")
    def _derivable(self) -> SheetCondition:
        if self.kind == "choice" and self.usual is None:
            raise ValueError(f"{self.key}: a choice has no maximum to default to; it names "
                             "its usual option (or none, with the reason)")
        if self.default_by == "situational" and self.usual is None:
            raise ValueError(f"{self.key}: a situational condition names its usual value, or "
                             "0 with the reason it stays off")
        if self.kind in ("stacks", "number") and self.max is None:
            raise ValueError(f"{self.key}: a {self.kind} names its max")
        if ((self.max_raise is not None or self.max_raise_cited is not None)
                and self.kind not in ("stacks", "number")):
            raise ValueError(f"{self.key}: only a stacks or number condition has a max to raise")
        if self.max_raise is not None and self.max_raise_cited is not None:
            raise ValueError(f"{self.key}: a maximum is raised by a parameter or a constant")
        if self.usual is not None:
            self._check_usual(self.usual.value)
        return self

    def _check_usual(self, value: float | str) -> None:
        if value == "max":
            if self.kind == "choice":
                raise ValueError(f"{self.key}: a choice has no maximum")
            return
        if value == "receiver_element":
            if self.kind != "choice" or not set(self.options or ()) <= set(VISIONS):
                raise ValueError(f"{self.key}: only a choice of elements can follow the "
                                 "receiver's")
            return
        if self.kind == "choice":
            if not isinstance(value, str) or (value and value not in (self.options or ())):
                raise ValueError(f"{self.key}: usual {value!r} is not an option")
        elif isinstance(value, str):
            raise ValueError(f"{self.key}: a {self.kind} usual is a number or \"max\"")
        elif self.kind == "toggle" and value not in (0, 1):
            raise ValueError(f"{self.key}: a toggle's usual is 0 or 1")
        elif self.kind != "toggle" and not 0 <= value <= (self.max or 0):
            raise ValueError(f"{self.key}: usual {value} is outside [0, {self.max}]")

    def resolve(self, *, giver_is_subject: bool, raised: float = 0.0,
                receiver_element: str | None = None) -> Condition:
        """The P1 `Condition` for this receiver, its default by the rule above; `raised` is
        what an unlocked `max_raise` adds to the maximum, `receiver_element` the optimized
        character's element (read only by a usual value that follows it)."""
        top = None if self.max is None else self.max + raised
        at_max: float = 1 if self.kind == "toggle" else float(top or 0)
        note: str | None = None
        reason: Literal["self", "situational", "usual", "teammate"]
        default: float | str
        if self.usual is not None:
            usual = self.usual
            element = None if receiver_element is None else receiver_element.lower()
            value = usual.value
            note = usual.reason
            if value == "receiver_element":
                value = element if element in (self.options or ()) else ""
                if not value:
                    note = f"Off: the optimized character's element is not an option. {note}"
            if usual.receiver_elements is not None and element not in usual.receiver_elements:
                value = "" if self.kind == "choice" else 0
                note = (f"Off: the optimized character is not "
                        f"{'/'.join(e.capitalize() for e in usual.receiver_elements)}. {note}")
            default = at_max if value == "max" else value
            reason = "situational" if default in (0, "") else "usual"
        elif self.default_by == "self" or (self.default_by == "giver_is_subject"
                                           and giver_is_subject):
            reason, default = "self", at_max
        else:
            # A teammate's buff with no curated usual value: up, at its maximum, and said so.
            reason, default = "teammate", at_max
            note = ("a teammate's buff, assumed up as they play it; at its maximum, since no "
                    "usual value is curated")
        return Condition(
            key=self.key, label=self.label, kind=self.kind, default=default,
            default_reason=reason, default_note=note, max=top, step=self.step,
            options=self.options,
        )


class SheetEffect(_Strict):
    """One buff a kit grants. Scope fields are `formula_effects.Effect`'s, unchanged."""

    key: str
    label: str
    source: Source
    receivers: Receivers
    stat: EffectStat
    value: ValueRef
    elements: tuple[str, ...] | None = None
    moves: tuple[str, ...] | None = None
    reactions: tuple[str, ...] | None = None
    when: tuple[When, ...] = ()
    #: Multiply by this stacks/number condition's value (GO's `prod(stacks, x)`), as in P1.
    per: str | None = None
    #: Reaches the receiver only when **their** element is one of these (GO `target.char.ele`,
    #: Linnea's C2) — not the hit's channel, which `elements` scopes. Decided in `resolve`
    #: from the receiver's element, which the caller names.
    receiver_elements: tuple[str, ...] | None = None
    #: Multiply by how many team members (the receiver included) have one of these elements
    #: (GO `sum(team.common.count.<ele>, …)`, Vesna's A4). Decided in `resolve` from the
    #: team's elements, which the caller names.
    per_team_elements: tuple[str, ...] | None = None
    #: Holds only for these team compositions (Chevreuse's A1), decided in `resolve`.
    team_gate: TeamGate | None = None
    #: Also needs this ascension phase (GO `cmpGE(ascension, 4, …)` inside a constellation's
    #: buff: Escoffier's C1 reads her A4's count).
    min_ascension: int | None = None
    #: Holds only **below** this constellation, i.e. up to it: GO `cmpGE(constellation, 2,
    #: <C2 value>, <C0 value>)` replaces Nefer's A1 EM at 3 Veils by her C2's at 5.
    max_constellation: int | None = None
    #: The giver's own talent rows it reaches (Nahida's burst bonus, Tri-Karma Purification
    #: only: GO adds it inside that one formula). Only a `self` effect names rows.
    rows: tuple[TalentRowScope, ...] | None = None
    #: The value at 1, 2, … stacks of `per` is the list's entry `param`, `param + 1`, … up to
    #: the condition's maximum (GO `subscript(stacks - 1, [p0, p1, …])`: Nahida's C4 by the
    #: opponent count, Xianyun's A1 by the plunge-stack count). The value names the first entry.
    by_stack: bool = False
    #: GO sheet file:lines (relative to the sheet's `go` roots).
    go: str
    #: gcsim file:lines at the pin, where gcsim implements the same buff.
    gcsim: str | None = None

    @model_validator(mode="after")
    def _scoped(self) -> SheetEffect:
        for move in self.moves or ():
            if move not in MOVES:
                raise ValueError(f"{self.key}: {move!r} is not one of {MOVES}")
        for reaction in self.reactions or ():
            if reaction not in AMPLIFYING_REACTIONS:
                raise ValueError(f"{self.key}: {reaction!r} is not an amplifying reaction")
        if self.receivers == "enemy" and self.stat not in ENEMY_STATS:
            raise ValueError(f"{self.key}: an enemy debuff writes one of {ENEMY_STATS}")
        if self.stat in ENEMY_STATS and self.receivers != "enemy":
            raise ValueError(f"{self.key}: {self.stat} is an enemy debuff")
        return self

    @model_validator(mode="after")
    def _own_hits(self) -> SheetEffect:
        if self.stat == "def_ignore" and self.receivers != "self":
            raise ValueError(f"{self.key}: DEF ignore belongs to the giver's own hits")
        if self.rows is not None and self.receivers != "self":
            raise ValueError(f"{self.key}: only a self effect names its giver's own rows")
        for row in self.rows or ():
            if row.talent not in TALENTS:
                raise ValueError(f"{self.key}: {row.talent!r} is not one of {TALENTS}")
        if self.by_stack:
            if self.per is None:
                raise ValueError(f"{self.key}: a stack table needs the condition it reads (per)")
            if self.value.param is None or self.value.times_stat is not None:
                raise ValueError(f"{self.key}: a stack table reads a constellation or passive "
                                 "list, with no stat")
        for element in (*(self.receiver_elements or ()), *(self.per_team_elements or ())):
            if element not in VISIONS:
                raise ValueError(f"{self.key}: {element!r} is not one of {VISIONS}")
        if (self.value.stat_unit is not None and self.value.times_stat is None
                and self.per is None):
            raise ValueError(f"{self.key}: a unit counts a stat (`times_stat`) or a condition "
                             "(`per`)")
        return self


class SheetUnmodelled(_Strict):
    """A part of the kit the estimate does not apply, and why — said, never silent."""

    source: Source | Literal["kit"]
    what: str
    reason: str
    #: Whom the note concerns: `teammate` when it is about the kit reaching someone else, so a
    #: giver who is the subject — for whom the effect itself is withheld, with its own reason —
    #: is not told the same thing twice (Nahida's A1, found driving it); `subject` the reverse.
    receiver: Literal["any", "subject", "teammate"] = "any"


class TalentBoost(_Strict):
    """A constellation that raises a talent's level by 3 (GO `ownBuff.char.<t>.add(…)`)."""

    constellation: int
    talent: str
    go: str
    gcsim: str | None = None


class RowMove(_Strict):
    """The move (attack type) GO gives some of a character's talent rows, where it is not the
    talent's own: Skirk's Seven-Phase Flash attacks are rows of her **skill** talent that GO
    deals as Normal, Charged and Plunging Attacks (`customDmg(name, 'cryo', 'normal', …)`).

    Owner ruling 2026-11-14 (`DECISIONS.md` §40 (iv)) asked for each row's attack type from the
    imported per-hit data (`character_attacks`). That data cannot give it: its `attack_type` is
    the strike geometry (`Melee`, `Range`, `Default`), not the move, and nothing links an entry
    to a talent row (its `damage_param` is an internal name, `SkirkNew_NormalAttack_
    ElementalArt_01_Damage`, which no row label carries). So the move is transcribed, cited,
    from the comparator's own per-row declaration, and `/hits` reports it; a row a sheet does
    not name keeps the label-based guess (`suggestMove` in the browser)."""

    talent: str
    #: Row labels before their `|`, as `/hits` names them.
    labels: tuple[str, ...]
    move: str
    go: str

    @model_validator(mode="after")
    def _known(self) -> RowMove:
        if self.talent not in TALENTS:
            raise ValueError(f"{self.talent!r} is not one of {TALENTS}")
        if self.move not in MOVES:
            raise ValueError(f"{self.move!r} is not one of {MOVES}")
        if not self.labels:
            raise ValueError("a row move names its rows")
        return self


class Pins(_Strict):
    """The seeded rows a sheet was curated against."""

    talent_rows: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    constellations: dict[int, tuple[float, ...]] = Field(default_factory=dict)
    passives: dict[int, tuple[float, ...]] = Field(default_factory=dict)


class Sheet(_Strict):
    """One character's kit sheet, as committed."""

    about: str = Field(alias="_about")
    character: str
    nanoka_id: str
    slug: str
    go_commit: str
    #: GO roots the `go` fields are relative to: `pando` and/or `wr`.
    go: dict[str, str]
    gcsim_commit: str | None = None
    gcsim: str | None = None
    #: Names of the GO fixtures (`tests/fixtures/formula/go_fixtures.json`) that check this
    #: sheet. Empty means **unverified**, and the API says so.
    verified_by: tuple[str, ...] = ()
    talent_boosts: tuple[TalentBoost, ...] = ()
    pins: Pins = Field(default_factory=Pins)
    conditions: tuple[SheetCondition, ...] = ()
    effects: tuple[SheetEffect, ...] = ()
    unmodelled: tuple[SheetUnmodelled, ...] = ()
    #: The rows whose move is not their talent's (`RowMove`), from GO's per-row declarations.
    row_moves: tuple[RowMove, ...] = ()

    @model_validator(mode="after")
    def _references_resolve(self) -> Sheet:
        keys = [c.key for c in self.conditions]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{self.slug}: condition keys repeat")
        effect_keys = [e.key for e in self.effects]
        if len(set(effect_keys)) != len(effect_keys):
            raise ValueError(f"{self.slug}: effect keys repeat")
        for effect in self.effects:
            self._check_effect(effect, keys)
        for condition in self.conditions:
            if condition.max_raise is not None and not self._pinned(condition.max_raise):
                raise ValueError(f"{self.slug}/{condition.key}: max_raise is not pinned")
        named = [(m.talent, label) for m in self.row_moves for label in m.labels]
        if len(set(named)) != len(named):
            raise ValueError(f"{self.slug}: a row is given two moves")
        return self

    def move_of(self, talent: str, label: str) -> str | None:
        """The move GO gives this talent row, where the sheet names one."""
        return next((m.move for m in self.row_moves
                     if m.talent == talent and label in m.labels), None)

    def _check_effect(self, effect: SheetEffect, keys: list[str]) -> None:
        for when in effect.when:
            if when.condition not in keys:
                raise ValueError(f"{self.slug}/{effect.key}: unknown condition "
                                 f"{when.condition!r}")
        if effect.per is not None and not any(
            c.key == effect.per and c.kind in ("stacks", "number") for c in self.conditions
        ):
            raise ValueError(f"{self.slug}/{effect.key}: `per` names a stacks or number "
                             f"condition, not {effect.per!r}")
        ref = effect.value
        if ref.talent is not None and not any(
            label.split("|", 1)[0] == ref.row
            for label in self.pins.talent_rows.get(ref.talent, ())
        ):
            raise ValueError(f"{self.slug}/{effect.key}: row {ref.row!r} is not pinned")
        if ref.rows_by_team is not None:
            for label in ref.rows_by_team.labels:
                if (label not in self.pins.talent_rows.get(ref.talent or "", ())
                        or label.split("|", 1)[0] != ref.row):
                    raise ValueError(f"{self.slug}/{effect.key}: {label!r} is not a pinned "
                                     f"{ref.row!r} row")
        if effect.by_stack and not any(
            c.key == effect.per and c.max is not None and c.max_raise is None
            and c.max_raise_cited is None
            for c in self.conditions
        ):
            raise ValueError(f"{self.slug}/{effect.key}: a stack table reads a condition with "
                             "a fixed maximum")
        if ref.constellation is not None and ref.constellation not in self.pins.constellations:
            raise ValueError(f"{self.slug}/{effect.key}: C{ref.constellation} not pinned")
        if ref.passive is not None and ref.passive not in self.pins.passives:
            raise ValueError(f"{self.slug}/{effect.key}: A{ref.passive} not pinned")
        for extra in ref.params_read():
            if not self._pinned(extra):
                raise ValueError(f"{self.slug}/{effect.key}: {extra} is not pinned")

    def _pinned(self, ref: ParamRef) -> bool:
        if ref.constellation is not None:
            return ref.constellation in self.pins.constellations
        if ref.talent is not None:
            return any(label.split("|", 1)[0] == ref.row
                       for label in self.pins.talent_rows.get(ref.talent, ()))
        return ref.passive in self.pins.passives


@cache
def all_sheets() -> dict[str, Sheet]:
    """Every committed sheet by character `nanoka_id`. Cached: the files ship with the app."""
    out: dict[str, Sheet] = {}
    for path in sorted(_DATA.glob("*.json")):
        sheet = Sheet.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if path.stem != sheet.slug:
            raise ValueError(f"{path.name}: the file is named after its slug, {sheet.slug}")
        if sheet.nanoka_id in out:
            raise ValueError(f"character {sheet.nanoka_id} has two sheets")
        out[sheet.nanoka_id] = sheet
    return out


def sheet_for(nanoka_id: str) -> Sheet | None:
    """This character's sheet, or None when nobody has written one yet."""
    return all_sheets().get(str(nanoka_id))


def row_move(nanoka_id: str, talent: str, label: str) -> str | None:
    """The move of one of this character's talent rows, from their sheet's `row_moves` (GO's
    per-row declaration), or None where no sheet names it — the caller then guesses from the
    label, as before."""
    sheet = sheet_for(nanoka_id)
    return None if sheet is None else sheet.move_of(talent, label.split("|", 1)[0])


# ---- The giver ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TalentRow:
    """One talent's published row at one level, as `talent_scalings` stores it."""

    labels: Sequence[str]
    params: Sequence[float]


@dataclass(frozen=True, slots=True)
class Giver:
    """What resolving a sheet needs to know about the character whose kit it is.

    `registry` is the giver's **pass-1** stat registry (`services/kit_buffs.py`): their
    character, weapon, equipped artifacts and the static bonuses of the sets they wear. The
    resolver registers each sheet formula into it and evaluates there.
    """

    name: str
    nanoka_id: str
    constellation: int
    ascension_phase: int
    #: The build's stored levels — GOOD's, which exclude constellation boosts.
    talent_levels: Mapping[str, int]
    #: `(talent, level) -> row`, for whichever levels the catalogue publishes.
    talent_rows: Mapping[tuple[str, int], TalentRow]
    constellation_params: Mapping[int, Sequence[float]]
    #: By unlock ascension phase (0, 1 or 4).
    passive_params: Mapping[int, Sequence[float]]
    registry: NodeRegistry


@dataclass(frozen=True, slots=True)
class ResolvedKit:
    """One giver's kit, resolved for one receiver: P1 `Bonus` vocabulary, numbers in."""

    source_id: str
    label: str
    giver: str
    bonus: Bonus
    citation: str
    verified: bool
    #: `modelled` / `partial` / `unmodelled` / `no_damage_effect`, from `status_of`.
    status: str


#: Merged into a sheet formula's context before it is evaluated: `None` removes the axis.
_CLEAR_FORMULA = Tag.of(**{tags.SHEET: None, tags.NAME: None})


class _Withheld(Exception):  # noqa: N818 - control flow, not an error a caller sees
    """An effect that cannot be resolved, with the sentence the reader is told."""


_PARAM = re.compile(r"\{param(\d+)")


def effective_level(sheet: Sheet, giver: Giver, talent: str) -> int:
    """The giver's level in a talent, with their constellation boosts.

    GOOD stores levels **without** constellation boosts (the importer copies its `talent`
    block verbatim, `good_build_service.py`), and both comparators add them: GO
    `ownBuff.char.burst.add(cmpGE(constellation, 5, 3))` and gcsim `c.BurstCon = 5`.
    """
    level = giver.talent_levels.get(talent)
    if level is None:
        raise _Withheld(f"the build has no {talent} level")
    for boost in sheet.talent_boosts:
        if boost.talent == talent and giver.constellation >= boost.constellation:
            level += 3
    return level


def _number(sheet: Sheet, giver: Giver, ref: ValueRef, *, shift: int = 0) -> float:
    """The constant part of a value: one parameter (or two multiplied), from our own seeded
    rows, negated where the list publishes a reduction as a positive number. `shift` moves
    along a team-indexed table (`TeamIndex`)."""
    number = _parameter(sheet, giver, ref, shift=shift)
    if ref.times_param is not None:
        number *= _extra(sheet, giver, ref.times_param)
    number = -number if ref.negate else number
    return number if ref.offset is None else number + ref.offset.constant


def _extra(sheet: Sheet, giver: Giver, extra: ParamRef) -> float:
    if extra.unnamed is not None:
        return _unnamed_parameter(sheet, giver, extra)
    return _parameter(sheet, giver, ValueRef(
        constellation=extra.constellation, passive=extra.passive, param=extra.param,
        talent=extra.talent, row=extra.row,
    ))


def _unnamed_parameter(sheet: Sheet, giver: Giver, ref: ParamRef) -> float:
    """A talent row's parameter that no label names, by index, at the giver's effective level:
    only while the row's pinned label is unchanged and no seeded label has come to name it."""
    talent = ref.talent or ""
    level = effective_level(sheet, giver, talent)
    row = giver.talent_rows.get((talent, level))
    if row is None:
        raise _Withheld(f"{talent} has no published row at level {level}")
    pinned = {lab.split("|", 1)[0]: lab for lab in sheet.pins.talent_rows[talent]}
    found = next((lab for lab in row.labels if lab.split("|", 1)[0] == ref.row), None)
    if found is None or found != pinned[ref.row or ""]:
        raise _Withheld(f"{talent} row {ref.row!r} changed since curation: pinned "
                        f"{pinned[ref.row or '']!r}, seeded {found!r}")
    index = ref.unnamed or 0
    named = {int(n) - 1 for lab in row.labels if "|" in lab
             for n in _PARAM.findall(lab.split("|", 1)[1])}
    if index in named:
        raise _Withheld(f"{talent} param{index + 1} is named by a seeded label now; read it by "
                        "that label instead")
    if index >= len(row.params):
        raise _Withheld(f"{talent} has no param{index + 1} at level {level}")
    return float(row.params[index])


def _talent_parameter(sheet: Sheet, giver: Giver, ref: ValueRef, *, shift: int) -> float:
    """A talent row's parameter at the giver's effective level: the row by its pinned label
    (or the team-chosen one), the parameter its format string names (`part`)."""
    talent = ref.talent or ""
    level = effective_level(sheet, giver, talent)
    row = giver.talent_rows.get((talent, level))
    if row is None:
        raise _Withheld(f"{talent} has no published row at level {level}")
    if ref.rows_by_team is not None:
        # The rows share their text before `|`, so the full label is the key; the pins hold
        # each one, and a seeded row without that exact label is withheld.
        want = ref.rows_by_team.labels[shift]
        if want not in row.labels:
            raise _Withheld(f"{talent} row {want!r} is not in the seeded row any more")
        label = want
    else:
        pinned = {lab.split("|", 1)[0]: lab for lab in sheet.pins.talent_rows[talent]}
        found_label = next((lab for lab in row.labels if lab.split("|", 1)[0] == ref.row),
                           None)
        if found_label is None or found_label != pinned[ref.row or ""]:
            raise _Withheld(
                f"{talent} row {ref.row!r} changed since curation: pinned "
                f"{pinned[ref.row or '']!r}, seeded {found_label!r}",
            )
        label = found_label
    found = _PARAM.findall(label.split("|", 1)[1])
    # `nth` (the DPS batch) and `part` (the fourth batch) name the same thing, which parameter
    # of the row; a sheet sets at most one.
    which = ref.nth if ref.nth is not None else ref.part
    if len(found) <= which:
        raise _Withheld(f"{talent} row {label!r} names no parameter {which}")
    index = int(found[which]) - 1
    if index >= len(row.params):
        raise _Withheld(f"{talent} row {label!r} has no param{index + 1} at this level")
    return float(row.params[index])


def _parameter(sheet: Sheet, giver: Giver, ref: ValueRef, *, shift: int = 0) -> float:
    if ref.constant is not None:
        return ref.constant
    if ref.talent is not None:
        return _talent_parameter(sheet, giver, ref, shift=shift)
    if ref.constellation is not None:
        live, pin, name = (giver.constellation_params.get(ref.constellation),
                           sheet.pins.constellations[ref.constellation], f"C{ref.constellation}")
    else:
        live, pin, name = (giver.passive_params.get(ref.passive or 0),
                           sheet.pins.passives[ref.passive or 0], f"A{ref.passive}")
    if live is None or tuple(float(p) for p in live) != pin:
        raise _Withheld(
            f"{name} param_list changed since curation: curated {list(pin)}, seeded "
            f"{None if live is None else list(live)}; withheld rather than read by a stale index",
        )
    index = (ref.param or 0) + shift
    if index >= len(pin):
        raise _Withheld(f"{name} has no entry {index} to read")
    return float(pin[index])


def _unlocked(source: str, giver: Giver) -> bool:
    if source == "talent":
        return True
    if source in ("a0", "a1", "a4"):
        return giver.ascension_phase >= int(source[1])
    return giver.constellation >= int(source[1])


def _reaches(receivers: str, *, giver_is_subject: bool) -> bool:
    return {
        "self": giver_is_subject,
        "others": not giver_is_subject,
        "active": True,
        "team": True,
        "enemy": True,
    }[receivers]


def _value_node(
    sheet: Sheet, giver: Giver, effect: SheetEffect, *, shift: int = 0,
    team_max: Mapping[str, float] | None = None,
) -> AnyNode:
    """The effect's value as a node: its parameter, times the giver's stat where it reads one
    (per `stat_unit` points, the stat capped at `stat_cap`), or times the team's highest value
    of a stat, capped where it has a cap."""
    ref = effect.value
    factor = const(_number(sheet, giver, ref, shift=shift))
    if ref.times_team_max is not None:
        highest = (team_max or {}).get(ref.times_team_max)
        if highest is None:
            raise _Withheld(f"it reads the team's highest {ref.times_team_max}, which was not "
                            "given")
        node = prod_(factor, const(highest))
    elif ref.times_stat is not None:
        unit = 1.0 if ref.stat_unit is None else 1.0 / ref.stat_unit.constant
        stat = GIVER_STATS[ref.times_stat]
        if ref.threshold is not None:
            stat = max_(sum_(stat, const(-_extra(sheet, giver, ref.threshold))), const(0.0))
        if ref.stat_cap is not None:
            stat = min_(stat, const(_extra(sheet, giver, ref.stat_cap)))
        node = prod_(factor, const(unit), stat)
    else:
        if ref.stat_unit is not None:  # per `stat_unit` of the `per` condition
            return prod_(factor, const(1.0 / ref.stat_unit.constant))
        return factor
    if ref.cap is not None:
        node = min_(node, _cap_node(sheet, giver, ref))
    return node


def _cap_node(sheet: Sheet, giver: Giver, ref: ValueRef) -> AnyNode:
    """A value's cap: its parameter, times a giver stat where it names one (Hu Tao's 400% of
    her base ATK, GO `prod(percent(maxAtkInc), own.base.atk)`)."""
    assert ref.cap is not None
    cap = const(_extra(sheet, giver, ref.cap))
    if ref.cap_times_stat is None:
        return cap
    return prod_(cap, GIVER_STATS[ref.cap_times_stat])


@dataclass(frozen=True, slots=True)
class _Resolving:
    """What `_effect_node` hands `resolve`: the stat, its value's node and, for a capped
    self-conversion, the cap's node (in the term's own units) and the threshold."""

    stat: EffectStat
    node: AnyNode
    cap: AnyNode | None = None
    threshold: float | None = None


def _effect_node(
    sheet: Sheet, giver: Giver, effect: SheetEffect, *, giver_is_subject: bool, shift: int = 0,
    team_max: Mapping[str, float] | None = None,
) -> _Resolving:
    """The stat an effect writes and the node of its value, for this receiver.

    When the giver is the optimized character and the value reads one of their stats that
    artifacts move, the number would be frozen at the equipped build — wrong for every other
    candidate. So it becomes the per-candidate conversion the recipe can carry, valued at the
    coefficient alone, or it is withheld by name. The team's highest stat is withheld outright
    for a giver who is the subject: their own value, which moves, may be the highest.

    **A capped or thresholded conversion is priced per candidate** (owner ruling 2026-11-14,
    `DECISIONS.md` §40): the recipe evaluates `min(coefficient × max(stat − threshold, 0),
    cap)` for each build. The cap travels in the term's own units — a `cap` parameter (times a
    static giver stat, Hu Tao's base ATK), or a `stat_cap` on the counted stat turned into one
    (Nahida's 800 EM × 0.1% = 80%), the smaller where both are given. A cap that would itself
    move with the candidate is still withheld.
    """
    if giver_is_subject and effect.value.times_team_max is not None:
        msg = (
            f"it reads the team's highest {effect.value.times_team_max}, which includes "
            f"{sheet.character}'s own, and that moves with every candidate through a cap the "
            "recipe cannot carry per candidate"
        )
        raise _Withheld(msg)
    reads = effect.value.times_stat
    if not (giver_is_subject and reads is not None and reads not in STATIC_STATS):
        return _Resolving(effect.stat, _value_node(sheet, giver, effect, shift=shift,
                                                   team_max=team_max))
    ref = effect.value
    converted = SELF_CONVERSIONS.get((effect.stat, reads))
    if converted is None:
        msg = (
            f"it reads {sheet.character}'s own {reads}, which moves with every candidate, and "
            f"the recipe cannot carry {effect.stat} from {reads} per candidate yet"
        )
        raise _Withheld(msg)
    if ref.cap_times_stat is not None and ref.cap_times_stat not in STATIC_STATS:
        msg = (
            f"its cap reads {sheet.character}'s own {ref.cap_times_stat}, which moves with every "
            "candidate, so the cap itself would move"
        )
        raise _Withheld(msg)
    # A unit is a constant divisor (GO `prod(percent(x), stat, 1 / 100)`), so the per-candidate
    # coefficient carries it: Arlecchino's Masque per Bond of Life percentage point.
    unit = 1.0 if ref.stat_unit is None else ref.stat_unit.constant
    coefficient = _number(sheet, giver, ref, shift=shift) / unit
    caps: list[AnyNode] = []
    if ref.cap is not None:
        caps.append(_cap_node(sheet, giver, ref))
    if ref.stat_cap is not None:
        caps.append(const(coefficient * _extra(sheet, giver, ref.stat_cap)))
    cap = None if not caps else caps[0] if len(caps) == 1 else min_(*caps)
    threshold = None if ref.threshold is None else _extra(sheet, giver, ref.threshold)
    return _Resolving(converted, const(coefficient), cap, threshold)


def _team_shift(
    effect: SheetEffect, team_elements: Sequence[str | None] | None, giver: Giver,
) -> int | None:
    """For a team-indexed value or a team-chosen row: how far along its table (or its rows)
    this team reads (count − 1), or None when the count is 0 and there is no buff."""
    index = effect.value.index_by_team
    rows = effect.value.rows_by_team
    if index is None and rows is None:
        return 0
    if team_elements is None:
        raise _Withheld("it is read by the team's elements, which were not given")
    present = [e.lower() for e in team_elements if e is not None]
    if rows is not None:
        count = sum(1 for e in present if e in rows.elements)
        bonus = rows.count_bonus
        if bonus is not None and giver.constellation >= bonus.constellation:
            count += int(bonus.add.constant)
        return None if count == 0 else min(count, len(rows.labels)) - 1
    assert index is not None
    if index.count == "distinct":
        count = len(set(present))
    else:
        count = sum(1 for e in present if e in (index.elements or ()))
    if count > index.size:
        if not index.clamp:
            raise _Withheld(f"its table has {index.size} entries and the team counts {count}")
        count = index.size
    return None if count == 0 else count - 1


def _team_factor(
    effect: SheetEffect, *, receiver_element: str | None,
    team_elements: Sequence[str | None] | None,
) -> float:
    """The receiver- and team-dependent part of an effect: 1, 0, or a member count."""
    if effect.team_gate is not None:
        if team_elements is None:
            raise _Withheld("it depends on the team's elements, which were not given")
        if not effect.team_gate.holds(team_elements):
            return 0.0
    if effect.receiver_elements is not None:
        if receiver_element is None:
            raise _Withheld("it depends on the receiver's element, which was not given")
        if receiver_element.lower() not in effect.receiver_elements:
            return 0.0
    if effect.per_team_elements is not None:
        if team_elements is None:
            raise _Withheld("it counts the team's elements, which were not given")
        return float(sum(1 for e in team_elements
                         if e is not None and e.lower() in effect.per_team_elements))
    return 1.0


def _raised(sheet: Sheet, giver: Giver, condition: SheetCondition,
            unmodelled: list[Unmodelled]) -> float:
    """What an unlocked `max_raise` adds to a condition's maximum; a stale pin keeps the
    maximum unraised and says so."""
    cited = condition.max_raise_cited
    if cited is not None:
        return cited.add.constant if giver.constellation >= cited.constellation else 0.0
    ref = condition.max_raise
    if ref is None:
        return 0.0
    if ref.constellation is not None and giver.constellation < ref.constellation:
        return 0.0
    if ref.passive is not None and giver.ascension_phase < ref.passive:
        return 0.0
    try:
        return _extra(sheet, giver, ref)
    except _Withheld as why:
        unmodelled.append(Unmodelled(what=f"{condition.label}: the raised maximum",
                                     reason=f"withheld: {why}"))
        return 0.0


def resolve(
    sheet: Sheet, giver: Giver, *, giver_is_subject: bool,
    receiver_element: str | None = None, team_elements: Sequence[str | None] | None = None,
    team_max: Mapping[str, float] | None = None,
) -> ResolvedKit:
    """One giver's sheet as the optimized character receives it.

    `receiver_element` (the optimized character's element) and `team_elements` (every
    member's, the receiver's included) are read only by effects that depend on them
    (`receiver_elements`, `per_team_elements`, `index_by_team`, `rows_by_team`, `team_gate`);
    `team_max` (the highest pass-1 value of each stat among the subject's teammates) only by
    `times_team_max`. One that needs them, without them, is withheld.

    An effect that is locked (constellation or ascension too low) is simply absent, as in GO.
    One that cannot be resolved honestly — a stale pin, a missing talent row, a self buff
    reading an artifact-moved stat the recipe cannot carry per candidate — is **listed** as
    unmodelled with the reason, never dropped.
    """
    calculator = Calculator(giver.registry)
    unmodelled: list[Unmodelled] = [
        Unmodelled(what=f"{u.source.upper()}: {u.what}", reason=u.reason)
        for u in sheet.unmodelled
        if (u.source == "kit" or _unlocked(u.source, giver))
        and u.receiver in ("any", "subject" if giver_is_subject else "teammate")
    ]
    conditions = tuple(
        c.resolve(giver_is_subject=giver_is_subject,
                  raised=_raised(sheet, giver, c, unmodelled),
                  receiver_element=receiver_element)
        for c in sheet.conditions
    )
    effects: list[Effect] = []
    used_conditions: set[str] = set()
    applied: list[str] = []
    for effect in sheet.effects:
        if not _unlocked(effect.source, giver):
            continue
        if effect.min_ascension is not None and giver.ascension_phase < effect.min_ascension:
            continue
        if (effect.max_constellation is not None
                and giver.constellation > effect.max_constellation):
            continue
        if not _reaches(effect.receivers, giver_is_subject=giver_is_subject):
            continue
        try:
            factor = _team_factor(effect, receiver_element=receiver_element,
                                  team_elements=team_elements)
            shift = _team_shift(effect, team_elements, giver)
            if factor == 0 or shift is None:
                # Like a locked constellation: this receiver is not one the effect reaches.
                continue
            by_stack = _stack_table(sheet, giver, effect) if effect.by_stack else None
            made = _effect_node(sheet, giver, effect, giver_is_subject=giver_is_subject,
                                shift=shift, team_max=team_max)
            value = factor * _evaluate(calculator, giver, sheet, effect.key, made.node)
            cap = (None if made.cap is None
                   else _evaluate(calculator, giver, sheet, f"{effect.key}.cap", made.cap))
        except _Withheld as why:
            unmodelled.append(Unmodelled(
                what=f"{effect.source.upper()}: {effect.label}", reason=f"withheld: {why}",
            ))
            continue
        effects.append(Effect(
            stat=made.stat, value=by_stack[-1] if by_stack else value,
            elements=effect.elements, moves=effect.moves, rows=effect.rows,
            reactions=effect.reactions, when=effect.when, per=effect.per, by_stack=by_stack,
            cap=cap, threshold=made.threshold,
        ))
        used_conditions.update(w.condition for w in effect.when)
        if effect.per is not None:
            used_conditions.add(effect.per)
        applied.append(effect.key)
    bonus = Bonus(
        # Only the conditions something applied still reads: a toggle for a locked
        # constellation would be a switch wired to nothing.
        conditions=tuple(c for c in conditions if c.key in used_conditions),
        effects=tuple(effects),
        unmodelled=tuple(unmodelled),
    )
    roots = ", ".join(f"{root} ({kind})" for kind, root in sheet.go.items())
    citation = f"GO {roots} @ {sheet.go_commit[:8]}"
    lines = [f"{e.key} {e.go}" for e in sheet.effects
             if any(e.key == k for k in applied)]
    if lines:
        citation += " — " + "; ".join(lines)
    if sheet.gcsim and sheet.gcsim_commit:
        citation += f"; gcsim {sheet.gcsim} @ {sheet.gcsim_commit[:8]}"
    return ResolvedKit(
        source_id=f"kit:{sheet.slug}",
        label=f"{sheet.character} (kit)",
        giver=sheet.character,
        bonus=bonus,
        citation=citation,
        verified=bool(sheet.verified_by),
        status=status_of(bonus),
    )


def _evaluate(calculator: Calculator, giver: Giver, sheet: Sheet, name: str,
              node: AnyNode) -> float:
    """One sheet formula's value in the giver's context.

    Registered under `{sheet, name}` and evaluated with both cleared, so the formula's own stat
    reads gather the giver's stats — and not, through the subset rule, the formula itself (a
    read under `{sheet, name, q}` would match it).
    """
    giver.registry.register(tags.formula_tag(sheet.slug, name), tag_(node, _CLEAR_FORMULA))
    return float(calculator.compute(read_(tags.formula_tag(sheet.slug, name), "unique")))


def _stack_table(sheet: Sheet, giver: Giver, effect: SheetEffect) -> tuple[float, ...]:
    """A `by_stack` effect's values at 1, 2, … stacks up to its condition's maximum: the
    list's consecutive entries from the value's own (`SheetEffect.by_stack`)."""
    top = next(c.max for c in sheet.conditions if c.key == effect.per)
    return tuple(_number(sheet, giver, effect.value, shift=i) for i in range(int(top or 0)))


def team_stats_read(sheet: Sheet) -> tuple[str, ...]:
    """The stats whose team-wide highest this sheet reads (`times_team_max`)."""
    return tuple(sorted({e.value.times_team_max for e in sheet.effects
                         if e.value.times_team_max}))


def stats_read(
    sheet: Sheet, giver: Giver, team_max: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """The giver's value of every stat this sheet's effects read — what a number came from.

    Reported beside the resolved kit so a reader can redo "Bennett's base ATK × 1.008" by
    hand; evaluated by the same graph, over the same pass-1 registry, as the effects were. A
    team-wide highest a value read is reported as `team_max_<stat>`.
    """
    calculator = Calculator(giver.registry)
    read = sorted({s for e in sheet.effects
                   for s in (e.value.times_stat, e.value.cap_times_stat) if s})
    out = {stat: float(calculator.compute(GIVER_STATS[stat])) for stat in read}
    for stat in team_stats_read(sheet):
        if team_max is not None and stat in team_max:
            out[f"team_max_{stat}"] = float(team_max[stat])
    return out
