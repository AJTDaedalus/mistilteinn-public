"""What `weapon_symbols` can be checked without a catalogue.

**The mapping itself is not verified here, and that is deliberate.** It is a claim about game
data — that every sword character's normal-attack talent carries `Skill_A_01` — and the
committed fixtures hold four characters covering three of the five classes. A test that
verified three and said nothing about the other two would report green on a question it had
only two-fifths answered, which is the green-by-absence shape this repo refuses everywhere.

So the data claim lives in `scripts/verify_seed.py`, which runs against a **full** catalogue
and is a deploy gate. It fires in both directions: a symbol that disagrees with the talents
table, and a symbol no character carries. Breaking the catalyst entry produces both.

What is left here is what holds regardless of which patch is seeded.
"""

from __future__ import annotations

import pytest

from app.models.enums import WeaponType
from app.services.weapon_symbols import all_classes, all_symbols, symbol_for


def test_the_class_with_no_symbol_gets_none_rather_than_a_substitute() -> None:
    """`WEAPON_CROSSBOW` is two unreleased Traveler variants with no talents seeded at 7.0.51,
    so there is nothing to derive.

    Returning the sword mark because it is the commonest would put a **wrong weapon class** on
    a card — silently, and forever. `CatalogueIcon` already renders nothing for a null
    basename, so absent is a shape every consumer handles.
    """
    assert symbol_for(WeaponType.CROSSBOW) is None


def test_both_spellings_of_the_crossbow_class_reach_the_same_answer() -> None:
    """Characters spell it `WEAPON_CROSSBOW` and weapons spell it `ITEM_TPS_WEAPON` — the two
    indexes disagree, and `WeaponType.parse` is the one place that reconciles them. Reading a
    raw string past it would give a weapon card and a character card different answers about
    the same class."""
    assert symbol_for("WEAPON_CROSSBOW") is symbol_for("ITEM_TPS_WEAPON") is None


@pytest.mark.parametrize("weapon_type", list(WeaponType))
def test_every_class_gets_an_answer_rather_than_an_error(weapon_type: WeaponType) -> None:
    """A card asks for a symbol for whatever class it holds. A `KeyError` on the sixth would
    take out the page rather than omit a mark."""
    assert symbol_for(weapon_type) is None or isinstance(symbol_for(weapon_type), str)


def test_a_raw_spelling_nothing_recognises_is_none_not_a_crash() -> None:
    """A re-pin that introduces a seventh class must not break the page it appears on."""
    assert symbol_for("WEAPON_TRIDENT_OF_THE_FUTURE") is None
    assert symbol_for(None) is None


def test_the_downloader_is_offered_every_symbol_exactly_once() -> None:
    """`all_symbols()` is what `download_icons` vendors. A duplicate would fetch twice and a
    gap would leave a card with a broken mark that only shows up in a browser."""
    symbols = all_symbols()

    assert len(symbols) == len(set(symbols))
    assert set(symbols) == {
        symbol_for(w) for w in WeaponType if symbol_for(w) is not None
    }


def test_the_filter_bar_is_offered_only_the_classes_that_have_a_mark() -> None:
    """**The crossbow class is deliberately not here.**

    It has no mark, so a chip for it would render as a wide word among five glyphs — and the
    only two characters carrying it are unreleased Traveler variants with no talents seeded.
    A control that finds nothing anyone is looking for, wearing the odd one out's shape.
    """
    classes = all_classes()

    assert len(classes) == len(all_symbols())
    assert WeaponType.CROSSBOW.value not in {value for value, _, _ in classes}


def test_each_offered_class_carries_the_name_and_the_mark_the_rest_of_the_api_uses() -> None:
    """A second copy of either would be a second thing to drift. `weapon_type_display` and
    `weapon_type_icon` on a summary must agree with what the filter bar was handed."""
    for value, display, icon in all_classes():
        weapon_type = WeaponType(value)
        assert display == weapon_type.display
        assert icon == symbol_for(weapon_type)
