"""Constellation talent-level boosts: which talent a character's C3 and C5 raise by three.

Math-fallback 9b. **A build stores talent levels without these boosts**, because that is what
a GOOD export carries — the importer copies its `talent` block verbatim
(`good_build_service`, `talent_levels=dict(entry.talents)`) — and it is what gcsim takes:
`character.go:163-174` refuses a level outside 1-10 and `TalentLvlSkill`/`TalentLvlBurst`/
`TalentLvlAttack` (`:221-264`) add 3 once the constellation reaches the
character's `SkillCon`/`BurstCon`/`NormalCon`. GO adds them the
same way (`skillBoost: greaterEq(input.constellation, N, 3)`).

So the **damage chain reads the effective level** — `/explain`, `/search-context`, `/hits`
and the formula estimate built on them — while three things deliberately keep the stored one:

- **the gcsim config** (`gcsim_config._talents`): gcsim adds the boost itself, so adding it
  here as well would count it twice, and gcsim refuses a level above 10 anyway;
- **the planner**: it prices the books and crowns a talent really costs, and a constellation
  costs none of them;
- **storage and import**: a build's `talent_levels` stays GOOD's number, so a re-import or a
  round trip never compounds the +3.

**The table is derived, never written by hand and never parsed from constellation text.**
Two committed snapshots, each generated from source at a pin:

1. gcsim's `NewChar` assignments, `app/data/gcsim/keys.json:character_talent_boosts`
   (`scripts/gcsim/build_key_snapshot.py`, at the pin in `docs/CROSSVAL_gcsim.md`);
2. GO's sheets, `app/data/formula/talent_boosts_go.json`
   (`scripts/build_go_talent_boosts.py`, at the commit the kit sheets cite) — for the
   characters gcsim has not implemented.

gcsim is read first because the damage chain is crossvalidated against it. The two agree on
every character both know except Aloy, whose six constellations are placeholders in the game
data and who therefore can never reach C3 — `tests/unit/test_talent_boosts.py` pins that.
A character in neither is **refused by name** once their constellation could matter (C3+),
never given a guessed table.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from app.services import gcsim_keys
from app.services.gcsim_keys import GcsimKeyError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from app.models.enums import Element

_GO_SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "formula" / "talent_boosts_go.json"

#: The levels a constellation adds: `character.go:228`, `:243` and `:255` (`add += 3`), and GO's
#: `greaterEq(input.constellation, N, 3)`.
BOOST = 3

#: The lowest constellation that boosts anything. Below it no table is consulted, so a
#: character missing from both sources is still scored at C0-C2.
FIRST_BOOSTING_CONSTELLATION = 3

#: A base talent level's ceiling: gcsim's `character.go:163-174` refuses anything above it.
BASE_TALENT_CAP = 10


class TalentBoostError(LookupError):
    """No derived boost table covers this character, or a stored level cannot be a base one."""


class _Character(Protocol):
    name: str
    nanoka_id: str
    element: Element | str | None


@cache
def _go_snapshot() -> dict[str, object]:
    return json.loads(_GO_SNAPSHOT.read_text())


def gcsim_table() -> dict[str, dict[str, int]]:
    """The table derived from gcsim, by gcsim key."""
    return gcsim_keys.character_talent_boosts()


def go_table() -> dict[str, dict[str, int]]:
    """GO's table, by GO sheet key, without the citations."""
    characters = _go_snapshot()["characters"]
    return {
        key: {talent: int(boost["constellation"]) for talent, boost in boosts.items()}
        for key, boosts in characters.items()  # type: ignore[union-attr]
    }


def go_key(name: str, element: Element | str | None) -> str:
    """GO's sheet key for a character: the name without spaces or punctuation.

    Every Traveler is named "Traveler"; GO keys the element's sheet off the F body (the M
    bodies reuse its file), so the element decides.
    """
    if name == "Traveler":
        return f"traveler{gcsim_keys.normalise(str(element))}f" if element else ""
    return gcsim_keys.normalise(name)


def boosts_for(character: _Character) -> dict[str, int]:
    """`{talent: constellation}` for one character, from the first source that knows them."""
    try:
        key = gcsim_keys.character_key(
            str(character.nanoka_id), character.name, character.element,
        )
    except GcsimKeyError:
        key = None
    if key is not None and key in gcsim_table():
        return dict(gcsim_table()[key])
    by_go = {k.lower(): v for k, v in go_table().items()}
    found = by_go.get(go_key(character.name, character.element))
    if found is not None:
        return dict(found)
    msg = (
        f"no derived constellation talent-boost table covers {character.name} — neither "
        f"gcsim at {gcsim_keys.pinned_commit()[:12]} nor GO at "
        f"{str(_go_snapshot()['go_commit'])[:12]} implements them — so which talent their C3 "
        f"and C5 raise is unknown, and a guess would score the boosted talent three levels "
        f"wrong."
    )
    raise TalentBoostError(msg)


def effective_talent_levels(
    character: _Character, constellation: int, stored: Mapping[str, int],
) -> dict[str, int]:
    """The levels a character's hits are read at: the stored ones, plus constellation boosts.

    Below C3 nothing is looked up. A stored level above 10 on a boosted talent is refused:
    stored levels are base levels, and adding three to one that already looks boosted would
    count the constellation twice.
    """
    levels = dict(stored)
    if constellation < FIRST_BOOSTING_CONSTELLATION:
        return levels
    for talent, needs in boosts_for(character).items():
        if constellation < needs or talent not in levels:
            continue
        if levels[talent] > BASE_TALENT_CAP:
            msg = (
                f"{character.name}'s {talent} is stored at {levels[talent]}, above the base "
                f"cap of {BASE_TALENT_CAP}. Levels are stored without constellation boosts — "
                f"as GOOD exports them and gcsim reads them — and C{needs} adds {BOOST} to "
                f"this talent, so store the level shown before the boost."
            )
            raise TalentBoostError(msg)
        levels[talent] += BOOST
    return levels
