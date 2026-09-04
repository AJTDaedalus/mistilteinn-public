"""Which characters can be owned, and what the roster tab shows.

`DESIGN_character_roster.md` §2.2 and §5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

#: Genshin Optimizer's practice mannequins, which a GOOD export lists among the characters.
#:
#: **Excluded by id prefix, not by name.** `good_build_service` avoided naming them at all — it
#: gave a build only to a character holding gear, which excluded them for free — and that was a
#: reasonable instinct, because a name match on `"Manekin"` is fragile across localisations. But
#: it also excluded twelve real characters the owner owns, which is why this module exists.
#:
#: An id prefix is not fragile: it is the game's own key, the same one `characters.nanoka_id`
#: holds. Read off the seeded catalogue at nanoka **7.0.51**, where these two expand to seven
#: elemental variants each:
#:
#:     10000117-2 … 10000117-8   Manekin    UI_AvatarIcon_MannequinBoy
#:     10000118-2 … 10000118-8   Manekina   UI_AvatarIcon_MannequinGirl
#:
#: `tests/unit/test_roster_excludes_only_the_mannequins.py` asserts against the seeded database
#: that this matches exactly `MANNEQUIN_ROW_COUNT` rows and that every one of them is named
#: `Manekin` or `Manekina` — so a prefix that stops meaning what it means fails loudly rather
#: than silently hiding a real character from the roster.
MANNEQUIN_ID_PREFIXES = ("10000117-", "10000118-")

#: Fourteen: two mannequins, seven elemental variants each. Named so a seed bump that changes it
#: is a test failure rather than a silent change in who can be owned.
MANNEQUIN_ROW_COUNT = 14


def is_mannequin(nanoka_id: str | None) -> bool:
    """Is this catalogue row one of GO's practice dummies rather than a character?"""
    return bool(nanoka_id) and nanoka_id.startswith(MANNEQUIN_ID_PREFIXES)  # type: ignore[union-attr]


def is_unreleased(element: object | None, talent_count: int | None) -> bool:
    """Is this catalogue row a character the game has not shipped yet?

    **A separate predicate from `is_mannequin`, deliberately.** Both mean "cannot be owned",
    for different reasons — a mannequin will never be a character, and one of these will be.
    Folding them together would make the mannequin test, which asserts *these fourteen rows are
    the mannequins*, quietly stop saying that.

    **Not a release date.** Every Traveler row carries `release_date` `1970-01-01`, the epoch
    sentinel nanoka gives a character with no date, so a date comparison excludes all sixteen.

    **Both halves, and the conjunction is the safety.** "No talents" is the property that
    actually matters — a character with none cannot be built, damaged-calculated or compiled to
    gcsim — but on its own it is the quiet, one-directional failure this repo keeps warning
    about: a seed whose *detail* pass failed leaves real characters talentless, and a roster
    that silently dropped them is the exact defect `DESIGN_character_roster.md` was written to
    fix. A missing **element** cannot happen that way. Element is read from the index row and
    talents from the detail fetch, so a half-imported real character has an element and no
    talents, and is kept.

    Exactly two rows are missing both at nanoka 7.0.51 — `10000134` and `10000135`, the two
    crossbow Traveler bodies, which rendered as two identical blank rows on the roster tab.
    When they ship, an element and talents arrive with them and they become ownable with no
    code change, which is why this is a property and not a list of ids that would go stale.

    A `talent_count` of `None` means the caller did not count, and is not an answer: it reads
    as *released*, so a query that forgot to join cannot empty the roster.
    """
    return element is None and talent_count == 0


@dataclass(frozen=True, slots=True)
class RosterRow:
    """One catalogue character, and what this user has said about them.

    `owned` is **tri-state on purpose**, and the reason is DESIGN §2.1: `None` means nobody has
    said, which is not the same as `False` meaning the user said no. Collapsing them would make
    a fresh account read as *"you own none of the 150 characters"* and would let an import
    quietly resurrect a character somebody deliberately un-owned.
    """

    character_id: str
    owned: bool | None
    source: str | None

    @property
    def is_owned(self) -> bool:
        """For the one question that genuinely has two answers: does this count as owned."""
        return self.owned is True


def roster_rows(
    characters: Iterable[Mapping[str, object]],
    entries: Mapping[str, tuple[bool, str]],
) -> list[RosterRow]:
    """Join the catalogue to this user's answers, dropping the mannequins.

    `entries` is `{character_id: (owned, source)}`. Pure, so the join rule is testable without
    a database — which is the half of this that has a wrong answer worth catching.
    """
    rows = []
    for character in characters:
        if is_mannequin(character.get("nanoka_id")):  # type: ignore[arg-type]
            continue
        character_id = str(character["id"])
        entry = entries.get(character_id)
        rows.append(
            RosterRow(
                character_id=character_id,
                owned=entry[0] if entry else None,
                source=entry[1] if entry else None,
            ),
        )
    return rows
