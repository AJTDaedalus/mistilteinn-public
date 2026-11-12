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
a fabricated one. **102 characters are captured**; the owner's *"manual, cited, small first"*
started at three and the shape held. Re-derive rather than trust this number:
`python -c "import json;print(len(json.load(open('app/data/kqm/weapons.json'))['characters']))"`.

## The ids here are the game's, never this database's

`weapon_nanoka_id` and `set_nanoka_id` are nanoka's, and the endpoint resolves them against the
live catalogue on the way out. They were row ids until 2026-09-04, which made the whole snapshot
meaningless outside the one database it was captured against —
`docs/RESEARCH_kqm_not_reaching_the_ui.md` has the measurement.
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
    #: The **game's** id for the weapon, not this database's row id.
    #:
    #: It was the row id until 2026-09-04, and that made the snapshot a set of pointers into
    #: whichever database happened to be seeded when the capture ran. `models/base.py` mints a
    #: `uuid7` per insert, so a fresh seed mints different ones — **zero of the 205 captured
    #: ids existed in production**, and every recommendation was silently dropped by a client
    #: joining on them. `docs/RESEARCH_kqm_not_reaching_the_ui.md`.
    #:
    #: `nanoka_id` is the game's own key and means the same thing in every environment, which
    #: is what a committed snapshot has to do. It is also what this module's *character* keys
    #: always were; the asymmetry was the bug.
    weapon_nanoka_id: int
    weapon_name: str
    #: KQM's own words. Verbatim.
    note: str
    #: Which build this is for, on a guide that recommends per build. `""` on a quick guide,
    #: which has one list and no playstyles.
    #:
    #: **Not optional decoration.** Zhongli's guide yields 46 recommendations across five
    #: playstyles, and without this they are 46 rows with no way to say that a ranking written
    #: for *Burst Support Zhongli* is not a ranking for Zhongli.
    playstyle: str = ""
    #: KQM's own comparison, as they published it — `"114.2%"` of a baseline their note names.
    #: `""` on a quick guide, which states an order and no number; deriving one would be
    #: putting a figure in their mouth.
    relative_dps: str = ""


@dataclass(frozen=True, slots=True)
class SetRecommendation:
    """One artifact set, or one *kind* of two-piece, KQM lists for a character.

    **`kind` is the whole point.** `2pc HP% / Skill% / ER / Hydro%` is not a set and must not
    become one: it names every set whose two-piece grants HP%, which this catalogue already
    knows. Published as KQM's text with `kind="stat"`, so the client can colour the two-piece
    selector from it rather than this repo resolving it to a name KQM never wrote.
    """

    position: int
    kind: str
    as_written: str
    note: str
    #: The game's id for the set. `None` on a `stat` row, which names no set.
    #: Portable for the reason `Recommendation.weapon_nanoka_id` documents at length.
    set_nanoka_id: int | None = None
    set_name: str | None = None
    pieces: str = ""
    playstyle: str = ""
    relative_dps: str = ""


@dataclass(frozen=True, slots=True)
class CharacterGuide:
    """One character's captured recommendations, with where they came from."""

    character: str
    #: The page. Published so a reader can check the claim rather than take it.
    url: str
    retrieved_at: str
    weapons: tuple[Recommendation, ...]
    #: The artifact-set half of the same guide; empty where KQM's page has no set table.
    sets: tuple[SetRecommendation, ...] = ()


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
                    weapon_nanoka_id=int(w["weapon_nanoka_id"]),
                    weapon_name=str(w["weapon_name"]),
                    note=str(w["note"]),
                    playstyle=str(w.get("playstyle", "")),
                    relative_dps=str(w.get("relative_dps", "")),
                )
                for w in entry["weapons"]
            ),
            sets=tuple(
                SetRecommendation(
                    position=int(e["position"]),
                    kind=str(e.get("kind", "stat")),
                    as_written=str(e.get("as_written", "")),
                    note=str(e.get("note", "")),
                    set_nanoka_id=(
                        int(e["set_nanoka_id"]) if e.get("set_nanoka_id") is not None else None
                    ),
                    set_name=e.get("set_name"),
                    pieces=str(e.get("pieces", "")),
                    playstyle=str(e.get("playstyle", "")),
                    relative_dps=str(e.get("relative_dps", "")),
                )
                for e in entry.get("sets", [])
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


@cache
def notes_withheld() -> bool:
    """Whether this copy of the data carries KQM's `note` text, or withholds it.

    The public copy of the repository blanks every `note` (`DECISIONS.md` §35) and marks the
    file `"withheld": ["note"]`, so a test can assert whichever state the file declares rather
    than one that is only true in one of the two trees.
    """
    if not _DATA.exists():
        return False
    return "note" in json.loads(_DATA.read_text()).get("withheld", [])
