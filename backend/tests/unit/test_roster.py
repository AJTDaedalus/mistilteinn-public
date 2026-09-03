"""The character roster — `TASKS_character_roster.md` 3 and 4.

Replaces `test_build_ownership.py`, which tested `builds.owned`. Owner's ruling 2026-09-03
moved that fact off builds entirely, for the reason `DESIGN_character_roster.md` §1.2 measures:
a build is made only for a character *holding gear*, so twelve characters the owner has could
not carry the flag at all — 22 furnishing sets, 440 Primogems the teapot tracker never saw.
"""
from __future__ import annotations

from app.services.roster import (
    MANNEQUIN_ID_PREFIXES,
    RosterRow,
    is_mannequin,
    roster_rows,
)


def _catalogue(*entries: tuple[str, str]) -> list[dict[str, str]]:
    return [{"id": row_id, "nanoka_id": nanoka} for row_id, nanoka in entries]


def test_a_mannequin_is_not_a_character() -> None:
    """Both dummies, across every elemental variant the catalogue carries."""
    assert is_mannequin("10000117-2")
    assert is_mannequin("10000118-8")


def test_a_real_character_is_not_a_mannequin() -> None:
    """Including the ids that share a prefix *length* with them but not the prefix.

    `10000117` and `10000118` are the mannequins; `10000011` is Ningguang, one of the twelve
    this whole design exists for. A substring match rather than a prefix match would catch her.
    """
    assert not is_mannequin("10000011")
    assert not is_mannequin("10000064")
    assert not is_mannequin("10000115")


def test_a_character_with_no_id_is_not_a_mannequin() -> None:
    """An unseeded row is unknown, not a dummy — and `None.startswith` would raise."""
    assert not is_mannequin(None)
    assert not is_mannequin("")


def test_the_prefixes_are_not_a_bare_number() -> None:
    """The trailing hyphen is load-bearing and easy to drop.

    Without it `10000117` would prefix-match a hypothetical `100001170`, and more to the point
    the constant would stop describing what it matches. Pinned so a well-meaning tidy fails.
    """
    assert all(prefix.endswith("-") for prefix in MANNEQUIN_ID_PREFIXES)


def test_the_roster_offers_every_catalogue_character() -> None:
    """The tab has to draw a toggle for a character nobody has said anything about, so the
    join is the catalogue *left*-joined to the answers, not the answers alone."""
    rows = roster_rows(_catalogue(("c1", "10000011"), ("c2", "10000064")), {})

    assert [row.character_id for row in rows] == ["c1", "c2"]


def test_no_answer_is_not_the_same_as_not_owned() -> None:
    """DESIGN §2.1. Collapsing these would make a fresh account read as *"you own none of the
    150 characters"*, and would let an import quietly resurrect a character somebody
    deliberately un-owned."""
    rows = roster_rows(_catalogue(("c1", "10000011")), {})

    assert rows[0].owned is None
    assert rows[0].source is None
    assert rows[0].is_owned is False


def test_an_explicit_no_is_recorded_as_such() -> None:
    rows = roster_rows(_catalogue(("c1", "10000011")), {"c1": (False, "manual")})

    assert rows[0].owned is False
    assert rows[0].source == "manual"
    assert rows[0].is_owned is False


def test_an_answer_is_carried_through_with_who_gave_it() -> None:
    rows = roster_rows(_catalogue(("c1", "10000011")), {"c1": (True, "import")})

    assert rows[0] == RosterRow(character_id="c1", owned=True, source="import")


def test_mannequins_are_dropped_from_the_roster() -> None:
    """They are real catalogue rows — `/characters` should still show what the game has — but
    they can never be owned, so offering a toggle would be offering a lie."""
    rows = roster_rows(
        _catalogue(("c1", "10000011"), ("dummy", "10000117-2"), ("c2", "10000118-5")),
        {},
    )

    assert [row.character_id for row in rows] == ["c1"]
