"""Weapon passives for the formula estimate, as data a shared evaluator reads.

Math-fallback P3, task 12 (`docs/DESIGN_team_math_fallback.md` §2.8; owner go-ahead
2026-11-14, `docs/DECISIONS.md` §44). A **weapon passive file** says, for one weapon, which
buffs its refinement passive grants: to whom (the wielder, the active character, the whole team,
the others, the enemy), to which stat, under which conditions, and **where each number comes
from**. It is the kit sheet (`sheets.py`) carried over to a weapon, with one difference in what
a number is: a weapon has no talents, constellations or ascension passives, so a value is an
index into **the wielder's refinement's** `param_list` (`weapon_refinements`, seeded) —

- `{"param": i}` — `weapon_refinements[r].param_list[i]` at the wielder's refinement `r`;
- `{"constant": x, "cite": "…"}` — only for something no seeded list carries;

optionally `"times_stat"`: multiplied by one of the **wielder's** pass-1 stats (Key of
Khaj-Nisut's party EM is 0.2% of the wielder's Max HP).

## Why its own file format, and what it shares

A sheet's `ValueRef` names a talent row, a constellation or a passive, its pins are those lists
and its sources gate on ascension and constellation: none of that exists for a weapon, and a
refinement index exists in none of it. Bending `ValueRef` to carry a fifth kind would put a
weapon branch into every sheet validator. So the file is its own small schema — and **everything
else is the sheet's**: conditions are `sheets.SheetCondition` (so the default rule of
`DECISIONS.md` §41 is the one already written, `usual` included), team gates are
`sheets.TeamGate`, the giver stats and the per-candidate conversions a subject's own buff
becomes are `sheets.GIVER_STATS` / `sheets.SELF_CONVERSIONS`, values are evaluated on the Pando
DAG in the wielder's pass-1 registry exactly as a sheet's are, and the result is a
`sheets.ResolvedKit` in the P1 `Bonus` vocabulary the browser already applies.

## Pinned per refinement

Each file pins all five refinements' lists as seeded when it was curated. A wielder whose live
list differs from its refinement's pin withholds every effect that reads it, by name — never a
stale index read as if it meant the same thing.

## Receivers

As a sheet's (`sheets._reaches`): the receiver is always the optimized character. `self` reaches
them only when they wield the weapon, `others` only when a teammate does, `team`, `active` and
`enemy` always. A teammate's weapon's self buffs are the teammate's own stats, which enter no
number the estimate reads (pass 1 carries no weapon passive, DESIGN §2.6 rule 1), so they are
simply not this receiver's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from app.formula.builder import const, max_, min_, prod_, read_, sum_, tag_
from app.formula.genshin import sheets, tags
from app.formula.genshin.formula_effects import (
    MOVES,
    NO_DAMAGE,
    REACTIONS,
    Bonus,
    Effect,
    EffectStat,
    Proc,
    Unmodelled,
    When,
    status_of,
)
from app.pando.calculator import Calculator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.formula.nodes import AnyNode
    from app.pando.calculator import NodeRegistry

_DATA = Path(__file__).resolve().parents[2] / "data" / "formula" / "weapons"
#: GO's non-stacking buff names per weapon sheet (`scripts/build_go_nonstack.py`).
_NONSTACK = Path(__file__).resolve().parents[2] / "data" / "formula" / "weapon_nonstack_go.json"

REFINEMENTS: tuple[int, ...] = (1, 2, 3, 4, 5)

#: Every element a weapon's "all Elemental DMG" reaches: every channel but Physical (GO
#: `Object.fromEntries(allElements.map(e => [`${e}_dmg_`, …]))`).
ELEMENTAL: tuple[str, ...] = sheets.VISIONS


class WeaponParam(sheets._Strict):  # noqa: SLF001 - the sheet module's own strict base
    """A second number a value reads: its cap, or the threshold its stat counts above — a
    refinement parameter, or a cited constant no seeded list carries."""

    param: int | None = None
    constant: float | None = None
    cite: str | None = None

    @model_validator(mode="after")
    def _one(self) -> WeaponParam:
        if (self.param is None) == (self.constant is None):
            raise ValueError("a weapon parameter is a refinement param or a cited constant")
        if self.constant is not None and not self.cite:
            raise ValueError("a constant carries its citation")
        return self


class WeaponValue(sheets._Strict):  # noqa: SLF001
    """Where one number comes from: the wielder's refinement list, or a cited constant."""

    param: int | None = None
    constant: float | None = None
    cite: str | None = None
    #: Multiplied by one of the wielder's pass-1 stats (`sheets.GIVER_STATS`).
    times_stat: str | None = None
    #: With `times_stat`, the stat counted per this many points (GO `prod(x, hp, 1 / 1000)`); a
    #: number no list carries, so cited.
    stat_unit: sheets.Cited | None = None
    #: With `times_stat`, the stat counts only above this (Engulfing Lightning's ER above 100%).
    threshold: WeaponParam | None = None
    #: The most the value can be (GO `min(…, max)`).
    cap: WeaponParam | None = None
    #: A reduction the list publishes as a positive number, negated into `enemy_res`.
    negate: bool = False
    #: Multiplied by another refinement parameter (a per-stack value times a stack count GO
    #: reads from the list).
    times_param: int | None = None
    #: With `times_stat`, the stat capped at this before it multiplies (GO `min(total.def,
    #: 3200)`, Peak Patrol Song's party bonus).
    stat_cap: WeaponParam | None = None

    @model_validator(mode="after")
    def _well_formed(self) -> WeaponValue:
        if (self.param is None) == (self.constant is None):
            raise ValueError("a value names a refinement param or a cited constant")
        if self.constant is not None and not self.cite:
            raise ValueError("a constant carries its citation")
        if self.times_stat is not None and self.times_stat not in sheets.GIVER_STATS:
            raise ValueError(f"times_stat must be one of {sorted(sheets.GIVER_STATS)}")
        if (self.stat_unit is not None or self.threshold is not None
                or self.stat_cap is not None) and self.times_stat is None:
            raise ValueError("a unit, a threshold or a stat cap belongs to a value that reads "
                             "a stat")
        return self

    def params_read(self) -> list[int]:
        """Every refinement index this value reads."""
        out = [p for p in (self.param, self.times_param) if p is not None]
        out += [p.param for p in (self.threshold, self.cap, self.stat_cap)
                if p is not None and p.param is not None]
        return out


class WeaponEffect(sheets._Strict):  # noqa: SLF001
    """One buff a weapon passive grants. Scope fields are `formula_effects.Effect`'s."""

    key: str
    label: str
    receivers: sheets.Receivers
    stat: EffectStat
    value: WeaponValue
    elements: tuple[str, ...] | None = None
    moves: tuple[str, ...] | None = None
    reactions: tuple[str, ...] | None = None
    when: tuple[When, ...] = ()
    per: str | None = None
    #: Holds only for these team compositions (`sheets.TeamGate`).
    team_gate: sheets.TeamGate | None = None
    #: Reaches the receiver only when their element is one of these.
    receiver_elements: tuple[str, ...] | None = None
    #: A DMG bonus for the wielder's own element (GO `equal(input.charEle, ele, …)`,
    #: Mistsplitter's Emblem): resolved to the receiver's element, which on a `self` effect is
    #: the wielder's.
    own_element: bool = False
    #: Times a teammate count, as a set's Gilded Dreams: members of the wielder's element
    #: (themselves excluded), or of another element (GO `tally`, A Thousand Floating Dreams).
    #: A `self` effect only: the browser counts against the optimized character's element.
    per_team: Literal["same_element_others", "different_element"] | None = None
    per_team_max: int | None = None
    #: GO's `nonStackBuff` name for this buff (`SheetUtil.tsx:102-117`), when GO lets only one
    #: of its kind apply: checked against the generated `weapon_nonstack_go.json`, never typed
    #: from memory. Two sources holding the same name and both holding: the one whose wielder's
    #: GO key sorts first applies (GO `uiData.ts:_small`; owner approval 2026-11-14, §45).
    non_stack: str | None = None
    #: GO sheet lines (relative to the file's `go`).
    go: str
    #: gcsim file:lines at the pin, where gcsim implements the same buff.
    gcsim: str | None = None

    @model_validator(mode="after")
    def _scoped(self) -> WeaponEffect:
        for move in self.moves or ():
            if move not in MOVES:
                raise ValueError(f"{self.key}: {move!r} is not one of {MOVES}")
        for reaction in self.reactions or ():
            if reaction not in REACTIONS:
                raise ValueError(f"{self.key}: {reaction!r} is not a reaction the estimate prices")
        for element in (*(self.elements or ()), *(self.receiver_elements or ())):
            if element not in (*sheets.VISIONS, "physical"):
                raise ValueError(f"{self.key}: {element!r} is not an element")
        if self.receivers == "enemy" and self.stat not in sheets.ENEMY_STATS:
            raise ValueError(f"{self.key}: an enemy debuff writes one of {sheets.ENEMY_STATS}")
        if self.stat in sheets.ENEMY_STATS and self.receivers != "enemy":
            raise ValueError(f"{self.key}: {self.stat} is an enemy debuff")
        if self.stat in ("talent_level", "def_ignore") and self.receivers != "self":
            raise ValueError(f"{self.key}: {self.stat} belongs to the wielder's own hits")
        if self.own_element and (self.elements is not None or self.receivers != "self"):
            raise ValueError(f"{self.key}: the wielder's own element is a self effect's channel")
        if self.per_team is not None and self.receivers != "self":
            raise ValueError(f"{self.key}: a teammate count is read for the wielder's own buff")
        return self


class WeaponProc(sheets._Strict):  # noqa: SLF001
    """A damage instance of the weapon's own (owner approval 2026-11-14, `DECISIONS.md` §45).

    Priced as a proc row the user counts (`formula_effects.Proc`), only when the wielder is the
    optimized character: a teammate's proc is their damage, a constant to every candidate, as a
    teammate's hits are not rows.
    """

    key: str
    label: str
    #: The ATK multiplier: the wielder's refinement entry, or a cited constant (Skyward Harp's
    #: 125%, GO `percent(1.25)`).
    multiplier: WeaponValue
    element: Literal["physical"]
    #: GO's ATK read: `premod` or `total` (`formula_effects.Proc.stat_layer`).
    stat_layer: Literal["premod", "total"]
    go: str
    gcsim: str

    @model_validator(mode="after")
    def _plain(self) -> WeaponProc:
        ref = self.multiplier
        if (ref.times_stat is not None or ref.cap is not None or ref.negate
                or ref.times_param is not None):
            raise ValueError(f"{self.key}: a proc's multiplier is one number")
        return self


class WeaponUnmodelled(sheets._Strict):  # noqa: SLF001
    """A part of the passive the estimate does not apply, and why — said, never silent."""

    what: str
    reason: str
    #: `teammate` when the note is about the passive reaching someone else, `subject` when it
    #: is about the wielder's own hits (`sheets.SheetUnmodelled.receiver`).
    receiver: Literal["any", "subject", "teammate"] = "any"


class WeaponPassive(sheets._Strict):  # noqa: SLF001
    """One weapon's passive, as committed."""

    about: str = Field(alias="_about")
    weapon: str
    nanoka_id: str
    slug: str
    go_commit: str
    #: GO's WR weapon sheet at the commit (`libs/gi/sheets/src/Weapons/<Type>/<Key>/index.tsx`).
    go: str
    gcsim_commit: str | None = None
    gcsim: str | None = None
    #: GO fixtures in `go_fixtures.json` that check this file; empty is **unverified**.
    verified_by: tuple[str, ...] = ()
    #: The seeded `param_list` of each refinement (1–5) the file was curated against.
    pins: dict[int, tuple[float, ...]]
    conditions: tuple[sheets.SheetCondition, ...] = ()
    effects: tuple[WeaponEffect, ...] = ()
    procs: tuple[WeaponProc, ...] = ()
    unmodelled: tuple[WeaponUnmodelled, ...] = ()

    @model_validator(mode="after")
    def _references_resolve(self) -> WeaponPassive:
        if sorted(self.pins) != list(REFINEMENTS):
            raise ValueError(f"{self.slug}: pins name refinements 1-5")
        lengths = {len(p) for p in self.pins.values()}
        keys = [c.key for c in self.conditions]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{self.slug}: condition keys repeat")
        effect_keys = [e.key for e in self.effects]
        if len(set(effect_keys)) != len(effect_keys):
            raise ValueError(f"{self.slug}: effect keys repeat")
        for effect in self.effects:
            for when in effect.when:
                if when.condition not in keys:
                    raise ValueError(f"{self.slug}/{effect.key}: unknown condition "
                                     f"{when.condition!r}")
            if effect.per is not None and not any(
                c.key == effect.per and c.kind in ("stacks", "number") for c in self.conditions
            ):
                raise ValueError(f"{self.slug}/{effect.key}: per names a stacks/number condition")
            for index in effect.value.params_read():
                if any(index >= n for n in lengths):
                    raise ValueError(f"{self.slug}/{effect.key}: param {index} is not pinned")
        self._check_procs(lengths)
        self._check_conditions()
        self._check_non_stack()
        if not self.effects and not self.unmodelled and not self.procs:
            raise ValueError(f"{self.slug}: a passive with no effect says why in `unmodelled`")
        return self

    def _check_procs(self, lengths: set[int]) -> None:
        for proc in self.procs:
            for index in proc.multiplier.params_read():
                if any(index >= n for n in lengths):
                    raise ValueError(f"{self.slug}/{proc.key}: param {index} is not pinned")
        if len({p.key for p in self.procs}) != len(self.procs):
            raise ValueError(f"{self.slug}: proc keys repeat")

    def _check_non_stack(self) -> None:
        """Every `non_stack` name is one GO's sheet for this weapon declares, and a sheet that
        declares one has it on some effect (or says why not) — so the family is GO's."""
        go_key = go_sheet_key(self.go)
        declared = go_non_stack().get(go_key, {})
        named = {e.non_stack for e in self.effects if e.non_stack is not None}
        for name in named:
            if not any(_matches(template, name) for template in declared):
                raise ValueError(f"{self.slug}: GO's {go_key} declares no non-stacking buff "
                                 f"{name!r} (it declares {sorted(declared)})")
        if declared and not named and not any("non-stacking" in u.what for u in self.unmodelled):
            raise ValueError(f"{self.slug}: GO's {go_key} declares non-stacking buffs "
                             f"{sorted(declared)}; name them on their effects")

    def _check_conditions(self) -> None:
        read = ({w.condition for e in self.effects for w in e.when}
                | {e.per for e in self.effects if e.per is not None})
        for condition in self.conditions:
            # A condition nothing reads is a toggle wired to nothing — and, found curating
            # Thrilling Tales, the sign of an effect that forgot its `when`.
            if condition.key not in read:
                raise ValueError(f"{self.slug}/{condition.key}: no effect reads this condition")
            if condition.max_raise is not None or condition.max_raise_cited is not None:
                raise ValueError(f"{self.slug}/{condition.key}: a weapon has no constellation "
                                 "to raise a maximum")


def go_sheet_key(go: str) -> str:
    """GO's weapon key: the sheet's directory (`…/Weapons/Bow/ElegyForTheEnd/index.tsx`)."""
    return Path(go).parent.name


@cache
def go_non_stack() -> dict[str, dict[str, list[str]]]:
    """`{GO weapon key: {nonStackBuff name: [file:line]}}`, generated from GO's sheets."""
    return json.loads(_NONSTACK.read_text(encoding="utf-8"))["weapons"]


def _matches(template: str, name: str) -> bool:
    """A GO name, or a GO template name (`hakushin${key}`) with its placeholder filled."""
    if "${" not in template:
        return template == name
    head, _, rest = template.partition("${")
    tail = rest.partition("}")[2]
    middle = name[len(head):len(name) - len(tail)] if tail else name[len(head):]
    return (name.startswith(head) and name.endswith(tail) and middle.isalpha()
            and len(name) > len(head) + len(tail))


@cache
def all_passives() -> dict[str, WeaponPassive]:
    """Every committed weapon passive by weapon `nanoka_id`. Cached: the files ship with the
    app."""
    out: dict[str, WeaponPassive] = {}
    for path in sorted(_DATA.glob("*.json")):
        passive = WeaponPassive.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if path.stem != passive.slug:
            msg = f"{path.name}: the file is named after its slug, {passive.slug}"
            raise ValueError(msg)
        if passive.nanoka_id in out:
            msg = f"weapon {passive.nanoka_id} has two passive files"
            raise ValueError(msg)
        out[passive.nanoka_id] = passive
    return out


def passive_for(nanoka_id: str | int) -> WeaponPassive | None:
    """This weapon's passive file, or None when nobody has written one yet."""
    return all_passives().get(str(nanoka_id))


# ---- The wielder ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Wielder:
    """What resolving a weapon passive needs to know about the build that wields it.

    `registry` is the wielder's **pass-1** registry (`services/kit_buffs.py`), the same one
    their own kit sheet resolves in.
    """

    name: str
    refinement: int
    #: The seeded `param_list` of the wielder's refinement.
    params: Sequence[float]
    registry: NodeRegistry
    #: The wielder's GO character key, GO's tie-break for a non-stacking buff (§45).
    stack_rank: str | None = None


class _Withheld(Exception):  # noqa: N818 - control flow, not an error a caller sees
    """An effect that cannot be resolved, with the sentence the reader is told."""


def _pinned_params(passive: WeaponPassive, wielder: Wielder) -> tuple[float, ...]:
    if wielder.refinement not in passive.pins:
        raise _Withheld(f"refinement {wielder.refinement} is not 1-5")
    pin = passive.pins[wielder.refinement]
    live = tuple(float(p) for p in wielder.params)
    if live != pin:
        raise _Withheld(
            f"R{wielder.refinement} param_list changed since curation: curated {list(pin)}, "
            f"seeded {list(live)}; withheld rather than read by a stale index",
        )
    return pin


def _number(params: Sequence[float], ref: WeaponValue | WeaponParam) -> float:
    if ref.constant is not None:
        return ref.constant
    assert ref.param is not None
    if ref.param >= len(params):
        raise _Withheld(f"the refinement list has no entry {ref.param}")
    return float(params[ref.param])


def _constant(params: Sequence[float], ref: WeaponValue) -> float:
    number = _number(params, ref)
    if ref.times_param is not None:
        number *= float(params[ref.times_param])
    return -number if ref.negate else number


@dataclass(frozen=True, slots=True)
class _Resolving:
    stat: EffectStat
    node: AnyNode
    cap: float | None = None
    threshold: float | None = None


def _effect_node(params: Sequence[float], effect: WeaponEffect, *,
                 wielder_is_subject: bool) -> _Resolving:
    """The stat an effect writes and the node of its value, for this receiver — a sheet's
    rule (`sheets._effect_node`): a value the subject's own artifacts move becomes the
    per-candidate conversion the recipe carries, or is withheld by name."""
    ref = effect.value
    factor = _constant(params, ref)
    reads = ref.times_stat
    if reads is None:
        node: AnyNode = const(factor)
        if ref.cap is not None:
            node = min_(node, const(_number(params, ref.cap)))
        return _Resolving(effect.stat, node)
    unit = 1.0 if ref.stat_unit is None else ref.stat_unit.constant
    threshold = None if ref.threshold is None else _number(params, ref.threshold)
    if wielder_is_subject and reads not in sheets.STATIC_STATS:
        converted = sheets.SELF_CONVERSIONS.get((effect.stat, reads))
        if converted is None:
            msg = (f"it reads the wielder's own {reads}, which moves with every candidate, and "
                   f"the recipe cannot carry {effect.stat} from {reads} per candidate yet")
            raise _Withheld(msg)
        caps = [] if ref.cap is None else [_number(params, ref.cap)]
        if ref.stat_cap is not None:
            # A cap on the counted stat is a cap on the value: `k × min(s, c)` is
            # `min(k × s, k × c)` for k > 0, and above a threshold `k × (c − t)` (Peak Patrol
            # Song's party DMG from DEF up to 3,200, owner approval 2026-11-14, §45). The sheet's
            # own rule (`sheets._effect_node`).
            caps.append(factor / unit * (_number(params, ref.stat_cap) - (threshold or 0.0)))
        cap = min(caps) if caps else None
        return _Resolving(converted, const(factor / unit), cap, threshold)
    stat: AnyNode = sheets.GIVER_STATS[reads]
    if threshold is not None:
        stat = max_(sum_(stat, const(-threshold)), const(0.0))
    if ref.stat_cap is not None:
        stat = min_(stat, const(_number(params, ref.stat_cap)))
    node = prod_(const(factor), const(1.0 / unit), stat)
    if ref.cap is not None:
        node = min_(node, const(_number(params, ref.cap)))
    return _Resolving(effect.stat, node)


def _elements(effect: WeaponEffect, receiver_element: str | None) -> tuple[str, ...] | None:
    """The channels an effect reaches: its own list, or the wielder's element for
    `own_element` (on a self effect the receiver is the wielder)."""
    if not effect.own_element:
        return effect.elements
    if receiver_element is None:
        raise _Withheld("it reaches the wielder's own element, which was not given")
    return (receiver_element.lower(),)


def _team_factor(effect: WeaponEffect, *, receiver_element: str | None,
                 team_elements: Sequence[str | None] | None) -> float:
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
    return 1.0


def _evaluate(passive: WeaponPassive, wielder: Wielder, name: str, node: AnyNode) -> float:
    """One formula's value in the wielder's context, registered under `{sheet: weapon:<slug>,
    name}` so it cannot collide with the wielder's own kit sheet in the same registry."""
    tag = tags.formula_tag(f"weapon:{passive.slug}", name)
    wielder.registry.register(tag, tag_(node, sheets._CLEAR_FORMULA))  # noqa: SLF001
    return float(Calculator(wielder.registry).compute(read_(tag, "unique")))


#: Wielder stats a weapon's own unconditional bonus raises before its other values read them.
_POOL = frozenset({tags.Q_ATK_PCT, tags.Q_HP_PCT, tags.Q_DEF_PCT, tags.Q_ELEMENTAL_MASTERY,
                   tags.Q_ENERGY_RECHARGE, tags.Q_CRIT_RATE, tags.Q_CRIT_DMG})


def _own_statics(passive: WeaponPassive, params: Sequence[float], wielder: Wielder) -> None:
    """The weapon's own unconditional stat bonuses, into the wielder's registry, before any of
    its values reads a wielder stat: Key of Khaj-Nisut's party EM is 0.2% of the wielder's Max
    HP **including** its own +20% HP (GO `input.total.hp`, which carries the weapon's `premod.
    hp_`). Pass 1 carries no weapon passive (DESIGN §2.6 rule 1), and that rule is about other
    sources' buffs; a weapon reading a stat it raises itself is GO's arithmetic, not a cycle.
    The registry is the one this resolution was given, built for it alone (`kit_buffs`)."""
    for effect in passive.effects:
        ref = effect.value
        if (effect.receivers != "self" or effect.when or effect.per is not None
                or effect.stat not in _POOL or ref.times_stat is not None
                or effect.team_gate is not None or effect.elements or effect.moves):
            continue
        wielder.registry.register(tags.stat_tag(effect.stat), const(_constant(params, ref)))


def _procs(passive: WeaponPassive, params: Sequence[float] | None, wielder: Wielder, *,
           wielder_is_subject: bool, unmodelled: list[Unmodelled]) -> list[Proc]:
    """The weapon's damage instances at the wielder's refinement, when the wielder is the
    optimized character (§45). A teammate's proc is their own damage, a constant to every
    candidate as a teammate's hits are, so it is said rather than silently absent."""
    if params is None or not passive.procs:
        return []
    if not wielder_is_subject:
        unmodelled += [Unmodelled(
            what=proc.label,
            reason=f"no damage effect on the optimized character: {wielder.name}'s own hit",
        ) for proc in passive.procs]
        return []
    out: list[Proc] = []
    for proc in passive.procs:
        try:
            multiplier = _number(params, proc.multiplier)
        except _Withheld as why:
            unmodelled.append(Unmodelled(what=proc.label, reason=f"withheld: {why}"))
            continue
        out.append(Proc(key=proc.key, label=proc.label, multiplier=multiplier,
                        element=proc.element, stat_layer=proc.stat_layer))
    return out


def source_id(passive: WeaponPassive) -> str:
    """`weapon:<slug>`; condition keys are `<id>/<condition>`, as a kit's."""
    return f"weapon:{passive.slug}"


def resolve(
    passive: WeaponPassive, wielder: Wielder, *, wielder_is_subject: bool,
    receiver_element: str | None = None, team_elements: Sequence[str | None] | None = None,
) -> sheets.ResolvedKit:
    """One wielder's weapon passive as the optimized character receives it.

    An effect this receiver does not get (a teammate's self buff, a gate the team fails) is
    absent; one that cannot be resolved honestly — a stale pin, a subject's own buff the recipe
    cannot carry per candidate — is listed as unmodelled with the reason, never dropped.
    """
    unmodelled: list[Unmodelled] = [
        Unmodelled(what=u.what, reason=u.reason) for u in passive.unmodelled
        if u.receiver in ("any", "subject" if wielder_is_subject else "teammate")
    ]
    conditions = tuple(
        c.resolve(giver_is_subject=wielder_is_subject, receiver_element=receiver_element)
        for c in passive.conditions
    )
    effects: list[Effect] = []
    used: set[str] = set()
    applied: list[str] = []
    try:
        params: Sequence[float] | None = _pinned_params(passive, wielder)
    except _Withheld as why:
        params = None
        unmodelled.append(Unmodelled(what="the whole passive", reason=f"withheld: {why}"))
    if params is not None:
        _own_statics(passive, params, wielder)
    for effect in passive.effects if params is not None else ():
        if not sheets._reaches(effect.receivers, giver_is_subject=wielder_is_subject):  # noqa: SLF001
            continue
        try:
            factor = _team_factor(effect, receiver_element=receiver_element,
                                  team_elements=team_elements)
            if factor == 0:
                continue
            elements = _elements(effect, receiver_element)
            made = _effect_node(params, effect, wielder_is_subject=wielder_is_subject)
            value = factor * _evaluate(passive, wielder, effect.key, made.node)
        except _Withheld as why:
            unmodelled.append(Unmodelled(what=effect.label, reason=f"withheld: {why}"))
            continue
        effects.append(Effect(
            stat=made.stat, value=value, elements=elements, moves=effect.moves,
            reactions=effect.reactions, when=effect.when, per=effect.per, cap=made.cap,
            per_team=effect.per_team, per_team_max=effect.per_team_max,
            threshold=made.threshold, non_stack=effect.non_stack,
        ))
        used.update(w.condition for w in effect.when)
        if effect.per is not None:
            used.add(effect.per)
        applied.append(effect.key)
    if (params is not None and not wielder_is_subject and not effects and passive.effects
            and all(e.receivers == "self" for e in passive.effects)):
        # A teammate's Homa or Aquila: every part is the wielder's own (their stats, their
        # procs), so nothing here concerns this receiver — said once, as no damage effect on
        # them, rather than as "applied" beside the wielder's own unmodelled parts. Found
        # driving it: Bennett's Aquila Favonia read "Applied whenever it is active".
        unmodelled = [Unmodelled(
            what="every part of this passive",
            reason=f"no damage effect on the optimized character: it is {wielder.name}'s own",
        )]
    procs = _procs(passive, params, wielder, wielder_is_subject=wielder_is_subject,
                   unmodelled=unmodelled)
    applied += [p.key for p in procs]
    bonus = Bonus(
        conditions=tuple(c for c in conditions if c.key in used),
        effects=tuple(effects),
        unmodelled=tuple(unmodelled),
    )
    status = status_of(bonus)
    if procs and not effects:
        # A passive whose damage is its proc (Crescent Pike): the proc row is the effect.
        status = "partial" if any(not u.reason.startswith(NO_DAMAGE) for u in unmodelled) \
            else "modelled"
    citation = f"GO {passive.go} @ {passive.go_commit[:8]}"
    lines = [f"{e.key} :{e.go}" for e in passive.effects if e.key in applied]
    lines += [f"{p.key} :{p.go} (gcsim {p.gcsim})" for p in passive.procs if p.key in applied]
    if lines:
        citation += " — " + "; ".join(lines)
    if passive.gcsim and passive.gcsim_commit:
        citation += f"; gcsim {passive.gcsim} @ {passive.gcsim_commit[:8]}"
    return sheets.ResolvedKit(
        source_id=source_id(passive),
        label=f"{passive.weapon} R{wielder.refinement} ({wielder.name})",
        giver=wielder.name,
        bonus=bonus,
        citation=citation,
        verified=bool(passive.verified_by),
        status=status,
        procs=tuple(procs),
        stack_rank=wielder.stack_rank,
    )


def stats_read(passive: WeaponPassive, wielder: Wielder) -> dict[str, float]:
    """The wielder's pass-1 value of every stat this passive's effects read."""
    calculator = Calculator(wielder.registry)
    read = sorted({e.value.times_stat for e in passive.effects if e.value.times_stat})
    return {stat: float(calculator.compute(sheets.GIVER_STATS[stat])) for stat in read}
