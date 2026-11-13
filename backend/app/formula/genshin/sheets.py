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

from app.formula.builder import const, prod_, read_, tag_
from app.formula.genshin import stats, tags
from app.formula.genshin.formula_effects import (
    AMPLIFYING_REACTIONS,
    MOVES,
    Bonus,
    Condition,
    ConditionKind,
    Effect,
    EffectStat,
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
#: ascension passives (gated on ascension phase 1 and 4, GO `input.asc`); `c1`…`c6` the
#: constellations (gated on `constellation >= n`, GO `cmpGE(constellation, n, …)`).
Source = Literal["talent", "a1", "a4", "c1", "c2", "c3", "c4", "c5", "c6"]

#: The `tags.SRC_*` label each source is attributed to in an explanation.
SOURCE_LABEL: dict[str, str] = {
    "talent": tags.SRC_TALENT,
    "a1": tags.SRC_ASCENSION_PASSIVE, "a4": tags.SRC_ASCENSION_PASSIVE,
    **{f"c{n}": tags.SRC_CONSTELLATION for n in range(1, 7)},
}

MAX_CONSTELLATION = 6

Receivers = Literal["self", "active", "team", "others", "enemy"]

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
}

DefaultBy = Literal["self", "situational", "giver_is_subject"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ValueRef(_Strict):
    """Where one number comes from. Exactly one of `talent`, `constellation`, `passive` or
    `constant`."""

    talent: str | None = None
    row: str | None = None
    constellation: int | None = None
    passive: int | None = None
    param: int | None = None
    constant: float | None = None
    cite: str | None = None
    times_stat: str | None = None

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
        if self.passive is not None and self.passive not in (1, 4):
            raise ValueError("an ascension passive unlocks at phase 1 or 4")
        if self.times_stat is not None and self.times_stat not in GIVER_STATS:
            raise ValueError(f"times_stat must be one of {sorted(GIVER_STATS)}")
        return self


class SheetCondition(_Strict):
    """A condition as a sheet declares it. Its default follows the owner's rule
    (`DECISIONS.md` §39) and is derived, never written: `self` is on at its maximum,
    `situational` off, and `giver_is_subject` is `self` when the giver is the optimized
    character and `situational` when a teammate is (Bennett standing in his own field is his
    own doing; a teammate standing in it depends on the fight)."""

    key: str
    label: str
    kind: ConditionKind
    default_by: DefaultBy
    max: float | None = None
    step: float | None = None
    options: tuple[str, ...] | None = None
    go: str

    @model_validator(mode="after")
    def _derivable(self) -> SheetCondition:
        if self.kind == "choice" and self.default_by != "situational":
            raise ValueError(f"{self.key}: a choice has no maximum to default to; "
                             "only a situational one (none chosen) is derivable")
        if self.kind in ("stacks", "number") and self.max is None:
            raise ValueError(f"{self.key}: a {self.kind} names its max")
        return self

    def resolve(self, *, giver_is_subject: bool) -> Condition:
        """The P1 `Condition` for this receiver, its default derived."""
        reason: Literal["self", "situational"]
        if self.default_by == "giver_is_subject":
            reason = "self" if giver_is_subject else "situational"
        else:
            reason = self.default_by
        if self.kind == "choice":
            default: float | str = ""
        elif reason == "situational":
            default = 0
        else:
            default = 1 if self.kind == "toggle" else float(self.max or 0)
        return Condition(
            key=self.key, label=self.label, kind=self.kind, default=default,
            default_reason=reason, max=self.max, step=self.step, options=self.options,
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
        if self.receivers == "enemy" and self.stat != "enemy_res":
            raise ValueError(f"{self.key}: an enemy debuff writes enemy_res")
        return self


class SheetUnmodelled(_Strict):
    """A part of the kit the estimate does not apply, and why — said, never silent."""

    source: Source | Literal["kit"]
    what: str
    reason: str


class TalentBoost(_Strict):
    """A constellation that raises a talent's level by 3 (GO `ownBuff.char.<t>.add(…)`)."""

    constellation: int
    talent: str
    go: str
    gcsim: str | None = None


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

    @model_validator(mode="after")
    def _references_resolve(self) -> Sheet:
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
            ref = effect.value
            if ref.talent is not None and not any(
                label.split("|", 1)[0] == ref.row
                for label in self.pins.talent_rows.get(ref.talent, ())
            ):
                raise ValueError(f"{self.slug}/{effect.key}: row {ref.row!r} is not pinned")
            if ref.constellation is not None and ref.constellation not in self.pins.constellations:
                raise ValueError(f"{self.slug}/{effect.key}: C{ref.constellation} not pinned")
            if ref.passive is not None and ref.passive not in self.pins.passives:
                raise ValueError(f"{self.slug}/{effect.key}: A{ref.passive} not pinned")
        return self


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
    #: By unlock ascension phase (1 or 4).
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


def _number(sheet: Sheet, giver: Giver, ref: ValueRef) -> float:
    """The constant part of a value: one parameter, from our own seeded rows."""
    if ref.constant is not None:
        return ref.constant
    if ref.talent is not None:
        level = effective_level(sheet, giver, ref.talent)
        row = giver.talent_rows.get((ref.talent, level))
        if row is None:
            raise _Withheld(f"{ref.talent} has no published row at level {level}")
        pinned = {label.split("|", 1)[0]: label for label in sheet.pins.talent_rows[ref.talent]}
        label = next((lab for lab in row.labels if lab.split("|", 1)[0] == ref.row), None)
        if label is None or label != pinned[ref.row or ""]:
            raise _Withheld(
                f"{ref.talent} row {ref.row!r} changed since curation: pinned "
                f"{pinned[ref.row or '']!r}, seeded {label!r}",
            )
        found = _PARAM.search(label.split("|", 1)[1])
        if found is None:
            raise _Withheld(f"{ref.talent} row {label!r} names no parameter")
        return float(row.params[int(found.group(1)) - 1])
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
    return float(pin[ref.param or 0])


def _unlocked(source: str, giver: Giver) -> bool:
    if source == "talent":
        return True
    if source in ("a1", "a4"):
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


def _value_node(sheet: Sheet, giver: Giver, effect: SheetEffect) -> AnyNode:
    """The effect's value as a node: its parameter, times the giver's stat where it reads one."""
    factor = const(_number(sheet, giver, effect.value))
    stat = effect.value.times_stat
    return factor if stat is None else prod_(factor, GIVER_STATS[stat])


def _effect_node(
    sheet: Sheet, giver: Giver, effect: SheetEffect, *, giver_is_subject: bool,
) -> tuple[EffectStat, AnyNode]:
    """The stat an effect writes and the node of its value, for this receiver.

    When the giver is the optimized character and the value reads one of their stats that
    artifacts move, the number would be frozen at the equipped build — wrong for every other
    candidate. So it becomes the per-candidate conversion the recipe can carry, valued at the
    coefficient alone, or it is withheld by name.
    """
    reads = effect.value.times_stat
    if not (giver_is_subject and reads is not None and reads not in STATIC_STATS):
        return effect.stat, _value_node(sheet, giver, effect)
    converted = SELF_CONVERSIONS.get((effect.stat, reads))
    if converted is None:
        msg = (
            f"it reads {sheet.character}'s own {reads}, which moves with every candidate, and "
            f"the recipe cannot carry {effect.stat} from {reads} per candidate yet"
        )
        raise _Withheld(msg)
    return converted, const(_number(sheet, giver, effect.value))


def resolve(sheet: Sheet, giver: Giver, *, giver_is_subject: bool) -> ResolvedKit:
    """One giver's sheet as the optimized character receives it.

    An effect that is locked (constellation or ascension too low) is simply absent, as in GO.
    One that cannot be resolved honestly — a stale pin, a missing talent row, a self buff
    reading an artifact-moved stat the recipe cannot carry per candidate — is **listed** as
    unmodelled with the reason, never dropped.
    """
    calculator = Calculator(giver.registry)
    conditions = tuple(c.resolve(giver_is_subject=giver_is_subject) for c in sheet.conditions)
    effects: list[Effect] = []
    unmodelled: list[Unmodelled] = [
        Unmodelled(what=f"{u.source.upper()}: {u.what}", reason=u.reason)
        for u in sheet.unmodelled if u.source == "kit" or _unlocked(u.source, giver)
    ]
    used_conditions: set[str] = set()
    applied: list[str] = []
    for effect in sheet.effects:
        if not _unlocked(effect.source, giver):
            continue
        if not _reaches(effect.receivers, giver_is_subject=giver_is_subject):
            continue
        try:
            stat, node = _effect_node(sheet, giver, effect, giver_is_subject=giver_is_subject)
            # Registered under `{sheet, name}` and evaluated with both cleared, so the
            # formula's own stat reads gather the giver's stats — and not, through the subset
            # rule, the formula itself (a read under `{sheet, name, q}` would match it).
            giver.registry.register(
                tags.formula_tag(sheet.slug, effect.key), tag_(node, _CLEAR_FORMULA),
            )
            value = float(calculator.compute(
                read_(tags.formula_tag(sheet.slug, effect.key), "unique"),
            ))
        except _Withheld as why:
            unmodelled.append(Unmodelled(
                what=f"{effect.source.upper()}: {effect.label}", reason=f"withheld: {why}",
            ))
            continue
        effects.append(Effect(
            stat=stat, value=value, elements=effect.elements, moves=effect.moves,
            reactions=effect.reactions, when=effect.when,
        ))
        used_conditions.update(w.condition for w in effect.when)
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


def stats_read(sheet: Sheet, giver: Giver) -> dict[str, float]:
    """The giver's value of every stat this sheet's effects read — what a number came from.

    Reported beside the resolved kit so a reader can redo "Bennett's base ATK × 1.008" by
    hand; evaluated by the same graph, over the same pass-1 registry, as the effects were.
    """
    calculator = Calculator(giver.registry)
    read = sorted({e.value.times_stat for e in sheet.effects if e.value.times_stat})
    return {stat: float(calculator.compute(GIVER_STATS[stat])) for stat in read}
