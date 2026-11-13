"""Resolve a hit from a build's own character. M.2.

`HitSpec` has carried this note since Chunk F:

    Deriving a talent's multiplier, scaling stat and damage channel from a character's stored
    talent rows is the kit corpus's job (Chunk H), and this repo has no kit corpus. Rather
    than parse a multiplier out of a `desc` string and present the result as though it came
    from the game, the caller states the hit. […] a `talent` field that resolves this from
    the build's own character replaces it.

Quoted with its marker removed, so the repo-wide search for open work counts open work
and not this note about work that is done.

Chunk H is closed. `talent_scaling` parses the rows and M.4 checked that parse against gcsim
across 105 characters and 18,611 hits, so "the caller states the hit" no longer has to mean
"the user types 1.2091".

**The channel is still the caller's, deliberately.** The published table gives a multiplier
and says nothing about which element the hit lands as. A normal attack is physical for most
characters and not for a catalyst user, and infusions move it. Deriving it would be inventing
a rule the data does not state — the failure the parser was written to avoid, and it would be
perverse to commit it in the task that finally reads the parser's output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.formula.genshin.damage import ScalingStat, ScalingTerm
from app.models.enums import TalentType
from app.services.talent_scaling import (
    TalentHit,
    TalentScalingError,
    classify_talent_row,
    parse_talent_row,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


class TalentHitUnavailableError(LookupError):
    """The build cannot supply that hit, and the message says which part is missing."""


class _Scaling(Protocol):
    level: int
    labels: Sequence[str] | None
    params: Sequence[float] | None


class _Talent(Protocol):
    talent_type: TalentType
    scalings: Iterable[_Scaling]


class _Character(Protocol):
    name: str
    talents: Iterable[_Talent]


@dataclass(frozen=True)
class AvailableHit:
    """One hit a build could ask about, in the terms `resolve_talent_hit` takes."""

    talent: TalentType
    label: str
    #: Which hit under that label. `Low/High Plunge DMG` has two, and only an index tells
    #: them apart.
    index: int
    multiplier: float
    hits: int
    #: True when this is one of several alternatives and only one of them happens.
    exclusive: bool
    #: What `multiplier` scales off, from the row's own words (math-fallback P0).
    scaling_stat: ScalingStat = ScalingStat.ATK
    #: A mixed-stat hit's further terms; empty for every single-stat hit.
    extra_terms: tuple[ScalingTerm, ...] = ()


def resolve_talent_hit(
    character: _Character,
    talent_levels: Mapping[str, int],
    talent: TalentType,
    label: str,
    index: int = 0,
) -> TalentHit:
    """The multiplier for one hit of one talent, at the level this build has it.

    Refuses rather than defaults at every step. A missing level is not level 1: a talent-9
    burst reported at talent 1 is 59% of its real multiplier, and the result still looks
    like a damage figure.
    """
    hits = _hits_for(character, talent_levels, talent)
    matching = [hit for hit in hits if hit.label == label]
    if not matching:
        available = sorted({hit.label for hit in hits})
        msg = (
            f"{character.name} has no {label!r} on their {talent.value}. "
            f"It has {available}."
        )
        raise TalentHitUnavailableError(msg)
    if index >= len(matching):
        msg = (
            f"{label!r} has {len(matching)} hit(s) and index {index} is past the end. "
            f"Alternatives such as a low and a high plunge are told apart by index."
        )
        raise TalentHitUnavailableError(msg)
    return matching[index]


def available_hits(
    character: _Character, talent_levels: Mapping[str, int],
) -> list[AvailableHit]:
    """Every hit this build could ask about.

    **The same parse `resolve_talent_hit` uses**, so a page built from this cannot offer a
    label that is then refused — the picker-matches-validator guarantee this repo applies
    everywhere a user chooses from a list.

    A talent the build has no level for is absent rather than offered at level 1: offering it
    would produce a refusal the moment it was picked.
    """
    offered: list[AvailableHit] = []
    for talent in TalentType:
        try:
            hits = _hits_for(character, talent_levels, talent)
        except TalentHitUnavailableError:
            continue
        seen: dict[str, int] = {}
        for hit in hits:
            index = seen.get(hit.label, 0)
            seen[hit.label] = index + 1
            offered.append(
                AvailableHit(
                    talent=talent, label=hit.label, index=index,
                    multiplier=hit.multiplier, hits=hit.hits, exclusive=hit.exclusive,
                    scaling_stat=hit.scaling_stat, extra_terms=hit.extra_terms,
                ),
            )
    return offered


def _hits_for(
    character: _Character, talent_levels: Mapping[str, int], talent: TalentType,
) -> list[TalentHit]:
    """The hits of one talent at the level this build has it."""
    row = _row_for(character, talent_levels, talent)
    try:
        return parse_talent_row(list(row.labels or []), list(row.params or []))
    except TalentScalingError as exc:
        raise TalentHitUnavailableError(str(exc)) from exc


@dataclass(frozen=True)
class RefusedTalentHit:
    """A damage row the parser recognised and will not score, with its reason.

    Owner, 2026-11-13: these must not **vanish** from the hit pickers. Venti's Windsunder
    Arrow and Yoimiya's Blazing Arrow are real attacks the player knows by name; a picker that
    silently lacks them reads as a bug in the picker. Published beside the offered hits so a
    page can show them, greyed out, with the parser's reason — never as something to choose,
    because the chain cannot compute them (`talent_scaling._REFUSED_WORDS`).
    """

    talent: TalentType
    label: str
    #: The row's format string after the `|`, verbatim — what was refused.
    spec: str
    reason: str


def refused_hits(
    character: _Character, talent_levels: Mapping[str, int],
) -> list[RefusedTalentHit]:
    """Every damage row this build's talents carry that the parser refuses, by name.

    The same rows, at the same levels, that `available_hits` reads — so a refused entry sits
    beside the offered hits of the very table it came from. A talent with no level, or a row
    the parser cannot read at all, contributes nothing here: those are absences
    `available_hits` already explains, not refusals of a recognised hit.
    """
    refused: list[RefusedTalentHit] = []
    for talent in TalentType:
        try:
            row = _row_for(character, talent_levels, talent)
            classified = classify_talent_row(list(row.labels or []), list(row.params or []))
        except (TalentHitUnavailableError, TalentScalingError):
            continue
        refused.extend(
            RefusedTalentHit(
                talent=talent, label=r.label, spec=r.spec,
                # The parser prefixes the row it refused; the label and spec are already
                # fields here, so the reason a picker shows is the sentence alone.
                reason=r.reason.removeprefix(f"{f'{r.label}|{r.spec}'!r}: "),
            )
            for r in classified.refused
        )
    return refused


def _row_for(
    character: _Character, talent_levels: Mapping[str, int], talent: TalentType,
) -> _Scaling:
    """One talent's published row at the level this build has it."""
    found = next((t for t in character.talents if t.talent_type == talent), None)
    if found is None:
        msg = f"{character.name} has no {talent.value} talent."
        raise TalentHitUnavailableError(msg)

    level = talent_levels.get(talent.value)
    if level is None:
        msg = (
            f"this build has no level for {talent.value}, and a missing level is not level "
            f"1 — reporting one would be a weaker multiplier than the character has."
        )
        raise TalentHitUnavailableError(msg)

    row = next((s for s in found.scalings if s.level == level), None)
    if row is None:
        published = sorted(s.level for s in found.scalings)
        msg = (
            f"{talent.value} has no row for level {level}; the table publishes "
            f"{published}. Falling back to the nearest would be a multiplier for a "
            f"different talent level."
        )
        raise TalentHitUnavailableError(msg)
    return row
