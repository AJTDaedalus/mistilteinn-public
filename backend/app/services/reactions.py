"""Which reactions a party of elements can produce.

**The data is committed and cited, never written from memory.**
`app/data/reactions/elemental_reactions.json` comes verbatim from
`docs/RESEARCH_elemental_reactions.md`, which records the source URL, the retrieval date and the
wiki's own wording for each reaction. This module only reads it.

## Only the base reactions are offered

Owner ruling (2026-08-29): *"You can leave out lunar and stellar variants, just the base
reactions (minus shatter) is fine."*

So the five Lunar/Stellar rows are excluded whatever their certainty, and Shattered stays out
for the reason below. That leaves the **fifteen** reactions a Genshin player would name.

## Uncertain rows are not offered either

Five carry `uncertain: true` in the research, and the exclusions overlap: four of them are the
Lunar/Stellar rows the owner has ruled out anyway. The fifth stands on its own —

- **Shattered** is not an element pair at all. The source says *"a Blunt or Geo attack"*, and
  Blunt is Physical: listing it as Cryo+Hydro over-counts teams, adding Geo under-counts them.

Everything excluded stays **in the file**, so an exclusion is visible rather than looking like
an oversight. A filter that quietly mis-classified a team is worse than one that offers less.

## Two traps the wildcard makes easy to miss

**Lunar-Crystallize is Hydro only and Stellar Swirl is Cryo only** — they do *not* inherit the
four-element wildcard their namesakes carry. Neither is offered now, but the shape is why the
wildcard is data on a row rather than a rule about "reactions whose name contains Swirl", and it
is exactly what a later pass would get wrong from the names alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "data" / "reactions" / "elemental_reactions.json"

#: The placeholder a wildcard row uses in `elements_required`.
_WILDCARD = "__WILDCARD__"

#: Id prefixes for the reactions the owner has ruled out of the filter. Matched on the id
#: rather than a `category`, because the research's categories describe how a reaction *works*
#: — amplifying, transformative — and this is a decision about which ones a player names.
_NOT_BASE = ("lunar_", "stellar_")


@dataclass(frozen=True, slots=True)
class Reaction:
    """One reaction, and what a party needs to field to produce it."""

    id: str
    name: str
    #: Elements every party must have. Excludes the wildcard slot.
    required: tuple[str, ...]
    #: For Swirl and Crystallize: one of these, in addition to `required`.
    one_of: tuple[str, ...]

    def possible_for(self, elements: frozenset[str]) -> bool:
        """Whether a party fielding `elements` can produce this reaction.

        **Possible, not guaranteed.** Two characters can produce Vaporize; whether a given
        rotation actually does is a question for the simulator. A filter that claimed otherwise
        would be answering something it cannot see.
        """
        if not all(element in elements for element in self.required):
            return False
        return not self.one_of or bool(elements & set(self.one_of))


@cache
def _loaded() -> dict[str, object]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


@cache
def offered() -> tuple[Reaction, ...]:
    """Every reaction certain enough to filter by, in the source's order."""
    rows = _loaded()["reactions"]
    out: list[Reaction] = []
    for row in rows:  # type: ignore[union-attr]
        if row.get("uncertain") or str(row["id"]).startswith(_NOT_BASE):
            continue
        wildcard = row.get("wildcard") or {}
        out.append(
            Reaction(
                id=str(row["id"]),
                name=str(row["name"]),
                required=tuple(e for e in row["elements_required"] if e != _WILDCARD),
                one_of=tuple(wildcard.get("one_of", ())),
            ),
        )
    return tuple(out)


def possible_for(elements: frozenset[str]) -> tuple[str, ...]:
    """The ids of every offered reaction this party could produce."""
    return tuple(r.id for r in offered() if r.possible_for(elements))
