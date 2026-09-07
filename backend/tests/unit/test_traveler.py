"""Telling sixteen characters called `Traveler` apart.

The bug this closes: the roster tab drew sixteen rows with one name and one element chip, so
Aether Pyro and Lumine Pyro were the same row twice and the two unreleased bodies — no element,
so no chip — were *identical*. Every checkbox announced "I have Traveler".
`docs/RESEARCH_traveler_identity.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.traveler import TRAVELER_BODIES, body_of, display_name

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "character.json"


def _catalogue() -> dict[str, dict]:
    return json.loads(FIXTURE.read_text())


# ── the naming ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("icon", "element", "expected"), [
    ("UI_AvatarIcon_PlayerGirl", "Dendro", "Traveler (Lumine · Dendro)"),
    ("UI_AvatarIcon_PlayerBoy", "Dendro", "Traveler (Aether · Dendro)"),
    # The two unreleased bodies have no element at all, and are the pair that rendered
    # *identically* before this existed.
    ("UI_AvatarIcon_PlayerBoy", None, "Traveler (Aether)"),
    ("UI_AvatarIcon_PlayerGirl", None, "Traveler (Lumine)"),
])
def test_a_traveler_is_named_by_body_and_element(
    icon: str, element: str | None, expected: str,
) -> None:
    assert display_name(name="Traveler", icon=icon, element=element) == expected


def test_every_variant_gets_a_name_no_other_variant_has() -> None:
    """**The property that matters**, rather than four spellings.

    Sixteen rows, sixteen distinct names — which is the whole point, and what a test asserting
    one row at a time would not establish.
    """
    variants = [
        (icon, element)
        for icon in TRAVELER_BODIES
        for element in [None, "Anemo", "Cryo", "Dendro", "Electro", "Geo", "Hydro", "Pyro"]
    ]
    names = {display_name(name="Traveler", icon=icon, element=element)
             for icon, element in variants}

    assert len(names) == len(variants) == 16


def test_every_other_character_keeps_the_name_they_have() -> None:
    """Nobody else is ambiguous, so nobody else is touched — a helper that decorated every card
    would be a rename, not a disambiguation."""
    assert display_name(name="Nahida", icon="UI_AvatarIcon_Nahida", element="Dendro") == "Nahida"
    assert display_name(name="Hu Tao", icon=None, element="Pyro") == "Hu Tao"


def test_a_character_reusing_the_art_is_not_renamed_behind_its_back() -> None:
    """Both halves must agree. A story double or an alternate carrying the Traveler's portrait
    is not a Traveler variant, and calling it `"Someone (Aether)"` would be this repo inventing
    a relationship the catalogue does not record."""
    assert display_name(
        name="Someone Else", icon="UI_AvatarIcon_PlayerBoy", element="Pyro",
    ) == "Someone Else"


def test_an_unknown_icon_is_not_a_body() -> None:
    assert body_of("UI_AvatarIcon_Nahida") is None
    assert body_of(None) is None


# ── the assumption the whole thing rests on ──────────────────────────────────


def test_the_two_body_icons_are_still_what_the_capture_calls_them() -> None:
    """**The icon is the only signal that exists**, so a rename upstream is the way this breaks.

    Read from the committed nanoka 7.0.51 capture rather than the database, for the reason
    `test_roster_excludes_only_the_mannequins.py` gives: the fixture is always present, so this
    can never pass by being skipped.

    The failure it exists to catch is quiet and one-directional — an icon that stopped matching
    would return every Traveler to the bare name `"Traveler"`, restoring exactly the tab this
    was written to fix, with nothing on screen to say so.
    """
    catalogue = _catalogue()
    travelers = {
        key: row for key, row in catalogue.items()
        if row.get("en") == "Traveler"
    }

    assert len(travelers) == 16, "seven elements for each of two bodies, plus two unreleased"
    assert {row["icon"] for row in travelers.values()} == set(TRAVELER_BODIES)


def test_no_other_character_in_the_capture_carries_a_traveler_icon() -> None:
    """Otherwise the naming rule would reach someone it should not, and the name check in
    `display_name` would be the only thing standing between them and a wrong label."""
    wearing = {
        row.get("en") for row in _catalogue().values() if row.get("icon") in TRAVELER_BODIES
    }

    assert wearing == {"Traveler"}


def test_the_dashed_keys_are_half_travelers_and_half_mannequins() -> None:
    """**28 was the right number with the wrong explanation, in six places at once.**

    Six docstrings said "28 of the 150 characters are Traveler variants". 28 *is* the number of
    keys spelled `10000005-2` and needing a string column — but they are **14 Travelers and 14
    practice mannequins**: `10000117` is Manekin and `10000118` Manekina, and somebody counted
    four Traveler bodies x seven elements.

    So the count was load-bearing and correct while the sentence around it was wrong, which is
    why every one of the six survived review — a reader checking the number would have found
    it right. This pins the composition rather than the total.
    """
    catalogue = _catalogue()
    dashed = [key for key in catalogue if "-" in key]
    travelers = [key for key, row in catalogue.items() if row.get("en") == "Traveler"]
    mannequins = [
        key for key, row in catalogue.items() if row.get("en") in {"Manekin", "Manekina"}
    ]

    assert len(dashed) == 28
    assert len([k for k in dashed if k in travelers]) == 14
    assert len([k for k in dashed if k in mannequins]) == 14
    # And the two the suffix rule misses, which is why 16 != 14.
    assert len(travelers) == 16
    assert len(catalogue) - len(travelers) - len(mannequins) == 120
