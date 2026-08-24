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
- `{a}+{b}` — **two hits that both land**, not one summed multiplier. Venti's `1-Hit DMG` is
  `{param1}+{param1}`: two arrows of 0.20382 each, and gcsim stores one per-hit value rather
  than 0.40764. Summing applies crit and DEF once to a doubled figure, which is the same
  mistake as folding `×3` into the multiplier — **M.4 caught it summing, and this is the fix.**
- `{a}/{b}` — two **alternatives**, `Low/High Plunge DMG`. Only one of them happens. A
  repeat binds to the alternative it follows: `{a}/{b}/{c}×3` repeats only `c`, which is how
  gcsim models Clorinde's three Bond-of-Life lunges.

Both shapes yield two hits; `exclusive` is what tells them apart, because a caller totalling a
talent's damage adds the first pair and picks one of the second.

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

#: The same, with the repeat marker that may follow it. The marker binds to **the param it
#: follows**, not to the row: `{a}/{b}/{c}×3` repeats only `c`.
#:
#: `\u00d7` is U+00D7 MULTIPLICATION SIGN, which is what the payload contains. Written as an
#: escape because ruff's ambiguity check is right that an inline `×` beside an ASCII `x` is
#: indistinguishable to a reader.
_PARAM_WITH_REPEAT = re.compile(
    r"\{param(\d+):([A-Za-z0-9]+)\}(?:\u00d7(\d+))?",
)

#: What marks a row as damage. See the module docstring on why this is the label, not `FMT`.
_DAMAGE = "DMG"

#: Words that make a `DMG` label something other than an instance of damage.
#:
#: **Derived from the data, not guessed.** Of the 430 distinct `DMG` labels across the seeded
#: catalogue, 50 carry one of these — `Shield DMG Absorption` is a shield's capacity,
#: `Anemo DMG Bonus` is an additive modifier, `DMG Reduction` is damage *taken*, and
#: `Elemental Mastery-Based Swirl DMG Increase` is a coefficient per point of EM. gcsim's own
#: comment for that last one ends `per Point`, which is what first identified it (M.4).
#:
#: Treating any of them as a hit produces a multiplier for something that never strikes.
_NOT_A_HIT = ("Bonus", "Increase", "Absorption", "Reduction", "Resistance", "per ")

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
    #: True when this hit is **one of several alternatives** and only one of them happens —
    #: a low plunge against a high plunge. False for the parts of a multi-hit attack, which
    #: all land. A caller totalling a talent's damage sums the latter and picks one of the
    #: former, and without this it cannot tell which it is looking at.
    exclusive: bool = False


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
        if _DAMAGE not in label or any(word in label for word in _NOT_A_HIT):
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
    """One `Label|spec` pair, as the hits it describes.

    The spec is read **positionally**, which is how the payload writes it:

        {param4:F1P}/{param5:F1P}/{param7:F1P}×3

    Split on `/` gives three alternatives; the `×3` belongs to the third because it follows
    it. gcsim models exactly that — Clorinde's `Impale the Night` is three tables, no / low /
    full Bond of Life, and only the third repeats (M.4). Within an alternative, `+` joins
    parts that all land.
    """
    alternatives = spec.split("/")
    exclusive = len(alternatives) > 1

    hits: list[TalentHit] = []
    for segment in alternatives:
        found = _PARAM_WITH_REPEAT.findall(segment)
        if not found:
            continue
        joins = _PARAM_WITH_REPEAT.sub("", segment).strip()
        if len(found) > 1 and "+" not in joins:
            # **Not defaulted to a sum.** Params joined by something this has not been taught
            # is a shape nobody has checked, and combining them would produce a confident
            # multiplier for a hit whose composition is a guess. Refusing names the row.
            msg = (
                f"{label!r} references {len(found)} params joined by {joins!r}, which this "
                f"parser does not recognise: {spec!r}. Combining them would invent a "
                f"composition."
            )
            raise TalentScalingError(msg)
        for index, _, repeat in found:
            hits.append(
                TalentHit(
                    label=label,
                    multiplier=_value(index, param, f"{label}|{spec}"),
                    hits=int(repeat) if repeat else 1,
                    exclusive=exclusive,
                ),
            )

    if not hits:
        msg = (
            f"{label!r} is a damage row with no param reference: {spec!r}. A hit the parser "
            f"cannot resolve is a gap in the parser, not a hit that does no damage."
        )
        raise TalentScalingError(msg)
    return hits


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
