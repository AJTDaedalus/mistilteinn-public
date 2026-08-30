"""KeqingMains' weapon recommendations, read from a committed snapshot.

**The data is captured and cited, never written from memory.**
`scripts/capture_kqm_weapons.py` fetches a guide, finds its weapons section by anchor, and
records the source URL and retrieval date alongside every row. This module only reads the
result — the same shape as `app/services/reactions.py` and for the same reason: fabricated
citations in curated data is the failure `CLAUDE.md` names as fairy's worst, and the defence
is that every claim here can be traced to a page someone can open.

## What is claimed, and what is not

KQM's table has **no rank numbers**. It has an order, and its top row is described as the
character's best-in-slot. So this publishes `position` and the API says *"KQM lists these in
this order"* — never "ranked first". Citing a source and putting words in its mouth are
different acts.

`note` is KQM's own sentence, verbatim. Summarising it here would be this repo asserting a
judgement it did not make.

## Absent means absent

A character with no guide captured has **no** entry, and callers get an empty list rather than
a fabricated one. Three characters are captured today, which is the owner's *"manual, cited,
small first"* — the shape proved before it is scaled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "data" / "kqm" / "weapons.json"


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One weapon KQM lists for a character, and what it said about it."""

    #: Where it appears in KQM's list. **Not a rank** — see the module docstring.
    position: int
    weapon_id: str
    weapon_name: str
    #: KQM's own words. Verbatim.
    note: str
    #: The refinement KQM specified, when it specified one. `R5 Festering Desire` and
    #: `Festering Desire` are different recommendations, so this is data rather than noise.
    refinement: int | None = None


@dataclass(frozen=True, slots=True)
class CharacterGuide:
    """One character's captured recommendations, with where they came from."""

    character: str
    #: The page. Published so a reader can check the claim rather than take it.
    url: str
    retrieved_at: str
    weapons: tuple[Recommendation, ...]


@cache
def _loaded() -> dict[str, CharacterGuide]:
    if not _DATA.exists():
        # An absent snapshot is an empty one, not an error. The capture is deliberate and
        # occasional; a deployment without it should serve no recommendations rather than fail
        # to start.
        return {}
    raw = json.loads(_DATA.read_text())
    retrieved = str(raw.get("retrieved_at", ""))
    return {
        nanoka_id: CharacterGuide(
            character=entry["character"],
            url=entry["url"],
            retrieved_at=retrieved,
            weapons=tuple(
                Recommendation(
                    position=int(w["position"]),
                    weapon_id=str(w["weapon_id"]),
                    weapon_name=str(w["weapon_name"]),
                    note=str(w["note"]),
                    refinement=w.get("refinement"),
                )
                for w in entry["weapons"]
            ),
        )
        for nanoka_id, entry in raw.get("characters", {}).items()
    }


def for_character(nanoka_id: str | None) -> CharacterGuide | None:
    """What KQM lists for this character, or None if no guide has been captured.

    `None` rather than an empty guide: "nobody has captured this character" and "KQM recommends
    nothing" are different statements, and a caller showing an empty recommendations panel for
    the second is right while showing one for the first is a claim about KQM that nobody made.
    """
    return _loaded().get(nanoka_id) if nanoka_id else None


def captured_characters() -> tuple[str, ...]:
    """Every nanoka id with a captured guide. For a caller deciding whether to offer the UI."""
    return tuple(_loaded())
