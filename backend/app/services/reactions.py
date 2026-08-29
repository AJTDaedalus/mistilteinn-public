"""Which reactions a party of elements can produce.

**The data is committed and cited, never written from memory.**
`app/data/reactions/elemental_reactions.json` comes verbatim from
`docs/RESEARCH_elemental_reactions.md`, which records the source URL, the retrieval date and the
wiki's own wording for each reaction. This module only reads it.

## Uncertain rows are not offered

Five reactions carry `uncertain: true` in the research, and each for a reason the source could
not settle:

- **Shattered** is not an element pair at all — the source says *"a Blunt or Geo attack"*, and
  Blunt is Physical. Listing it as Cryo+Hydro over-counts teams; adding Geo under-counts them.
- **Lunar-Charged, Lunar-Crystallize, Stellar-Conduct, Stellar Swirl** may require a party
  talent, which the source gates the *effect* on rather than clearly the reaction.

A filter that quietly mis-classified a team would be worse than one that offers less, so these
are excluded from what is offered and kept in the file so the exclusion is visible.

## Two traps the wildcard makes easy to miss

**Lunar-Crystallize is Hydro only and Stellar Swirl is Cryo only** — they do *not* inherit the
four-element wildcard that ordinary Crystallize and Swirl carry. Both are uncertain and so
unoffered today, but the shape is the reason the wildcard is data on a row rather than a rule
about "reactions whose name contains Swirl".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "data" / "reactions" / "elemental_reactions.json"

#: The placeholder a wildcard row uses in `elements_required`.
_WILDCARD = "__WILDCARD__"


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
        if row.get("uncertain"):
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
