"""Turn a talent's published rows into hits. M.1.

`DESIGN_multipliers.md` §2. A talent's `promote[level]` carries `desc` — a padded list of
`"Label|{paramN:FMT}"` — beside a flat `param` list that `paramN` indexes **1-based**:

    desc:  ["Cutting DMG|{param1:P}", "CD|{param4:F1}s", "Energy Cost|{param5:I}", "", …]
    param: [1.123, 1.6845, 5, 20, 80, 0, …]

Across the 498 non-empty rows in the committed fixtures there are four format codes — `F1P`,
`P`, `F1`, `I` — and five tails. **The params are already fractions**: `1.123` is 112.3%,
matching this repo's convention, so nothing here converts them. `P` and `F1P` differ only in
display precision; treating `F1P` as needing a divide would quietly make every normal attack a
hundredth of its real value.

## The separator carries meaning

- `{p}×3` — one hit landing three times. The count stays **separate** (OQ-M2): the damage
  chain applies crit and DEF per hit, so a pre-multiplied `param × 3` would apply them once to
  a tripled number, which is a different and smaller answer.
- `{a}+{b}` — two parts of one attack. Summed.
- `{a}/{b}` — two **alternatives**, `Low/High Plunge DMG`. Returned as two hits (OQ-M1).
  Summing them gives a multiplier for a hit nobody can perform, and collapsing to one loses
  the other.

## What counts as damage

The **label** contains `DMG`. Not the format: `Blazing Threshold` and `Nightsoul Point Limit`
are `P`-formatted percentages that are not damage.

**This is a heuristic over English text and that is a real limitation** — the fixtures are the
`en` locale. `TASKS_multipliers.md` M.4 is what stops it being taken on trust: gcsim's
generated tables carry the same numbers, so the parse is checked against an independent
implementation rather than reviewed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: `{param12:F1P}` — the index is 1-based against the `param` list.
_PARAM = re.compile(r"\{param(\d+):([A-Za-z0-9]+)\}")

#: What marks a row as damage. See the module docstring on why this is the label, not `FMT`.
_DAMAGE = "DMG"

#: The row whose value is a burst's energy cost. `Character.burst_energy_cost` has been
#: nullable since Chunk D precisely because this had never been parsed out.
_ENERGY_COST = "Energy Cost"


class TalentScalingError(ValueError):
    """A row this parser cannot read.

    Raised rather than skipped. A `DMG` row that does not resolve is a gap in the parser, and
    returning nothing for it would present an incomplete kit as a complete one.
    """


@dataclass(frozen=True)
class TalentHit:
    """One hit a talent can land."""

    #: The published label, e.g. `Cutting DMG`. Kept so a caller can offer the user the
    #: game's own wording rather than an invented name.
    label: str
    #: Already a fraction: `1.123` is 112.3%.
    multiplier: float
    #: How many times this hit lands per use. Separate from the multiplier — see the module
    #: docstring.
    hits: int = 1


def parse_talent_row(
    desc: list[str] | None, param: list[float] | None,
) -> list[TalentHit]:
    """The damage hits in one level's row of a talent's table.

    `desc` and `param` are not required to be the same length: `param` is padded with real
    zeroes well past the end of `desc`, and requiring them to match would refuse most rows.
    """
    hits: list[TalentHit] = []
    for entry in desc or []:
        if not entry:
            continue
        label, _, spec = entry.partition("|")
        if _DAMAGE not in label:
            continue
        hits.extend(_hits_from(label, spec, param or []))
    return hits


def energy_cost(desc: list[str] | None, param: list[float] | None) -> int | None:
    """A burst's energy cost, or `None` for a talent that has none.

    `None` rather than zero: a normal attack has no burst cost, and zero would claim it is
    free to cast.
    """
    for entry in desc or []:
        if not entry:
            continue
        label, _, spec = entry.partition("|")
        if label != _ENERGY_COST:
            continue
        found = _PARAM.search(spec)
        if found is None:
            msg = f"{_ENERGY_COST!r} row has no param: {entry!r}"
            raise TalentScalingError(msg)
        return int(_value(found.group(1), param or [], entry))
    return None


def _hits_from(label: str, spec: str, param: list[float]) -> list[TalentHit]:
    """One `Label|spec` pair, as one hit or two alternatives."""
    found = _PARAM.findall(spec)
    if not found:
        msg = (
            f"{label!r} is a damage row with no param reference: {spec!r}. A hit the parser "
            f"cannot resolve is a gap in the parser, not a hit that does no damage."
        )
        raise TalentScalingError(msg)

    values = [_value(index, param, f"{label}|{spec}") for index, _ in found]
    repeats = _repeats(spec)
    separators = _PARAM.sub("", spec)

    if len(values) == 1:
        return [TalentHit(label=label, multiplier=values[0], hits=repeats)]

    # `/` means alternatives — two different actions, and never a sum.
    if "/" in separators:
        if repeats > 1:
            # Unreachable in the committed payloads and refused rather than guessed: `×N`
            # could plausibly apply to each alternative or to only one, and picking is
            # inventing a rule the data does not state.
            msg = (
                f"{label!r} lists alternatives *and* a repeat count: {spec!r}. Which "
                f"alternative repeats is not something the payload says."
            )
            raise TalentScalingError(msg)
        return [TalentHit(label=label, multiplier=value) for value in values]

    if "+" in separators:
        return [TalentHit(label=label, multiplier=sum(values), hits=repeats)]

    # **Not defaulted to a sum.** Two params joined by something this does not recognise is a
    # shape the parser has not been taught, and summing them would produce a confident
    # multiplier for a hit whose composition nobody checked. Refusing says which row to look
    # at; a silent sum says nothing and is wrong somewhere downstream.
    msg = (
        f"{label!r} references {len(values)} params joined by {separators!r}, which this "
        f"parser does not recognise: {spec!r}. Summing them would invent a composition."
    )
    raise TalentScalingError(msg)


#: The repeat marker, spelled by codepoint.
#:
#: U+00D7 MULTIPLICATION SIGN is the character the payload uses, and ruff's ambiguity check
#: rightly flags it inline — an ASCII `x` beside it would be indistinguishable to a reader and
#: would silently match nothing. Named here so there is one place it is written and no
#: blanket `noqa` over a module that also handles user-facing labels.
_REPEAT = re.compile("\u00d7(\\d+)")


def _repeats(spec: str) -> int:
    """The repeat count after a param, or 1."""
    found = _REPEAT.search(spec)
    return int(found.group(1)) if found else 1


def _value(index: str, param: list[float], entry: str) -> float:
    """`param[index - 1]`, refusing an index the list does not reach.

    **Not defaulted to zero.** `param` is padded with real zeroes, so a default is
    indistinguishable from a published value — and a zero multiplier is a real answer meaning
    "this hit does no damage", which is the plausible-wrong-number this repo refuses.
    """
    position = int(index) - 1
    if position < 0 or position >= len(param):
        msg = (
            f"param{index} is past the end of a {len(param)}-long param list, in {entry!r}. "
            f"Defaulting to zero would be a real multiplier for a hit that does no damage."
        )
        raise TalentScalingError(msg)
    return float(param[position])
