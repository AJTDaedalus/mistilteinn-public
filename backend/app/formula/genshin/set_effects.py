"""Conditional artifact set bonuses, resolved against the seeded catalogue.

Math-fallback P1, task 7. `docs/RESEARCH_math_fallback_inventory.md` §3.3 measured the gap:
of the 125 set tiers in the database, **every 4-piece (60) and nine 2-pieces** carry no
`add_props` the chain can apply, so the single-hit search has always scored every 4-piece in
the game at zero. Their *numbers* were stored all along, in `param_list`; what was missing
was their *meaning* — which number buffs what, for whom, under which condition.

That meaning lives in `app/data/formula/set_effects.json`, one entry per conditional tier,
**transcribed from Genshin Optimizer's artifact sheets** (the comparator, `DECISIONS.md` §38)
and cited to file and line. The numbers are **never** copied from GO and never parsed out of a
description: each value is `{"param": i}`, an index into our own seeded list. A constant
the list does not hold (a stack cap the game states only in text) carries its own GO citation.

## Pinned, so a patch cannot silently change what a number means

Each entry records the `params` it was curated against. If the live `param_list` differs, the
tier resolves to **stale** — its effects withheld and the reason named — rather than reading
index 3 of a list whose index 3 now means something else. A changed list is a new curation
question, and the answer must not be a guess.

## Value forms

- `{"param": i}` — `param_list[i]`.
- `{"param": i, "times_param": j}` — `param_list[i] × param_list[j]` (Vourukasha's Glow's
  stack, 10% × 80%; Nighttime Whispers' crystallize increase, 20% × 150%).
- `{"param": i, "times_tier_prop": {"pieces": n, "prop": P}}` — times the *static* value the
  same set's `n`-piece tier grants as `P` (Crimson Witch's stack is 50% of its 2-piece's
  Pyro DMG Bonus).
- `{"param": i, "negate": true}` — a resistance shred, which the list states as a positive.
- `{"constant": x, "cite": "…"}` — only for something the list does not carry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.formula.genshin.formula_effects import (
    Bonus,
    Condition,
    Effect,
    Unmodelled,
    When,
    status_of,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

_DATA = Path(__file__).resolve().parents[2] / "data" / "formula" / "set_effects.json"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TierProp(_Strict):
    """A sibling tier's static prop a value scales by."""

    pieces: int
    prop: str


class ValueSpec(_Strict):
    """Where a number comes from. Exactly one of `param` or `constant`."""

    param: int | None = None
    times_param: int | None = None
    times_tier_prop: TierProp | None = None
    negate: bool = False
    constant: float | None = None
    cite: str | None = None


class CuratedCondition(_Strict):
    """A condition as curated; `max` may still be a param index."""

    key: str
    label: str
    kind: Literal["toggle", "stacks", "choice", "number"]
    default: float | str
    default_reason: Literal["self", "situational"]
    max: ValueSpec | None = None
    step: float | None = None
    options: tuple[str, ...] | None = None


class CuratedEffect(_Strict):
    """An effect as curated, its numbers still `ValueSpec`s."""

    stat: str
    value: ValueSpec | None = None
    elements: tuple[str, ...] | None = None
    element_from: tuple[str, ...] | None = None
    moves: tuple[str, ...] | None = None
    reactions: tuple[str, ...] | None = None
    when: tuple[When, ...] = ()
    per: str | None = None
    by_stack: tuple[ValueSpec, ...] | None = None
    per_team: Literal["same_element_others", "different_element"] | None = None
    per_team_max: int | None = None
    cap: ValueSpec | None = None
    weapon_types: tuple[str, ...] | None = None


class CuratedTier(_Strict):
    """One conditional tier's curation."""

    set_id: int
    #: The set's name, for a reader of the JSON. The catalogue's is what a response carries.
    set: str
    pieces: int
    params: tuple[float, ...]
    #: GO file and lines under `go_root`, or why there is none.
    go: str
    conditions: tuple[CuratedCondition, ...] = Field(default=())
    effects: tuple[CuratedEffect, ...] = Field(default=())
    unmodelled: tuple[Unmodelled, ...] = Field(default=())


class Curated(_Strict):
    """The whole committed file."""

    about: str = Field(alias="_about")
    go_commit: str
    go_root: str
    tiers: tuple[CuratedTier, ...]


@cache
def curated() -> Curated:
    """The committed curation, validated. Cached: it is a file that ships with the app."""
    return Curated.model_validate(json.loads(_DATA.read_text(encoding="utf-8")))


@cache
def _by_tier() -> dict[tuple[int, int], CuratedTier]:
    out: dict[tuple[int, int], CuratedTier] = {}
    for tier in curated().tiers:
        key = (tier.set_id, tier.pieces)
        if key in out:
            raise ValueError(f"set {tier.set_id} {tier.pieces}pc is curated twice")
        out[key] = tier
    return out


@dataclass(frozen=True, slots=True)
class AffixRow:
    """What the resolver needs of one `artifact_set_affixes` row."""

    pieces: int
    param_list: Sequence[float]
    add_props: Sequence[Mapping[str, Any]]


Status = Literal["modelled", "partial", "unmodelled", "no_damage_effect", "stale", "uncurated"]


@dataclass(frozen=True, slots=True)
class ResolvedTier:
    """One conditional tier, ready for the browser: numbers in, references checked."""

    set_id: int
    pieces: int
    status: Status
    bonus: Bonus
    citation: str
    #: Why `stale` or `uncurated`; None otherwise.
    problem: str | None = None


def is_conditional(add_props: Iterable[Mapping[str, Any]]) -> bool:
    """True when a tier grants no static prop. `artifact_optimizer.SetBonus.is_conditional`'s
    rule, restated over plain rows so this module needs no service import."""
    absent = {"", "FIGHT_PROP_NONE", "NONE"}
    return all(str(p.get("prop_type") or "").upper() in absent for p in add_props)


def _value(spec: ValueSpec, params: Sequence[float], tiers: Mapping[int, AffixRow]) -> float:
    if spec.constant is not None:
        if spec.param is not None or not spec.cite:
            raise ValueError("a constant stands alone and carries a citation")
        return spec.constant
    if spec.param is None:
        raise ValueError("a value is a param or a constant")
    value = float(params[spec.param])
    if spec.times_param is not None:
        value *= float(params[spec.times_param])
    if spec.times_tier_prop is not None:
        other = tiers.get(spec.times_tier_prop.pieces)
        props = {str(p.get("prop_type")): float(p.get("value", 0.0))
                 for p in (other.add_props if other else ())}
        if spec.times_tier_prop.prop not in props:
            raise ValueError(
                f"the {spec.times_tier_prop.pieces}-piece tier carries no "
                f"{spec.times_tier_prop.prop} to scale",
            )
        value *= props[spec.times_tier_prop.prop]
    return -value if spec.negate else value


def _resolve(tier: CuratedTier, tiers: Mapping[int, AffixRow]) -> Bonus:
    params = tier.params
    conditions = tuple(
        Condition(
            key=c.key, label=c.label, kind=c.kind, default=c.default,
            default_reason=c.default_reason, step=c.step, options=c.options,
            max=_value(c.max, params, tiers) if c.max is not None else None,
        )
        for c in tier.conditions
    )
    effects = []
    for e in tier.effects:
        by_stack = (tuple(_value(v, params, tiers) for v in e.by_stack)
                    if e.by_stack is not None else None)
        if e.value is None and by_stack is None:
            raise ValueError(f"set {tier.set_id}: an effect needs a value or a by_stack row")
        value = _value(e.value, params, tiers) if e.value is not None else by_stack[-1]  # type: ignore[index]
        effects.append(Effect(
            stat=e.stat,  # type: ignore[arg-type]
            value=value, elements=e.elements, element_from=e.element_from, moves=e.moves,
            reactions=e.reactions, when=e.when, per=e.per, by_stack=by_stack,
            per_team=e.per_team, per_team_max=e.per_team_max,
            cap=_value(e.cap, params, tiers) if e.cap is not None else None,
            weapon_types=e.weapon_types,
        ))
    return Bonus(conditions=conditions, effects=tuple(effects), unmodelled=tier.unmodelled)


def resolve_set(set_id: int, affixes: Sequence[AffixRow]) -> list[ResolvedTier]:
    """Every **conditional** tier of one set, resolved against its own rows.

    A static tier is not here: it is a stat pool the kernel already applies
    (`build_assembler.bonus_stats`), and repeating it would count it twice.
    """
    by_pieces = {row.pieces: row for row in affixes}
    go_root = f"GO {curated().go_root}"
    out: list[ResolvedTier] = []
    for row in sorted(affixes, key=lambda r: r.pieces):
        if not is_conditional(row.add_props):
            continue
        tier = _by_tier().get((set_id, row.pieces))
        if tier is None:
            out.append(ResolvedTier(
                set_id=set_id, pieces=row.pieces, status="uncurated", bonus=Bonus(),
                citation="", problem=(
                    "this conditional tier has no entry in set_effects.json; the estimate "
                    "applies nothing for it until one is curated"
                ),
            ))
            continue
        citation = f"{go_root}/{tier.go} @ {curated().go_commit[:8]}"
        live = tuple(float(p) for p in row.param_list)
        if live != tier.params:
            out.append(ResolvedTier(
                set_id=set_id, pieces=row.pieces, status="stale", bonus=Bonus(),
                citation=citation, problem=(
                    f"param_list changed since curation: curated {list(tier.params)}, "
                    f"seeded {list(live)}; withheld rather than read by a stale index"
                ),
            ))
            continue
        bonus = _resolve(tier, by_pieces)
        out.append(ResolvedTier(
            set_id=set_id, pieces=row.pieces, status=status_of(bonus), bonus=bonus,
            citation=citation,
        ))
    return out

