"""Every vision has an emblem; nothing else gets one invented for it."""

from __future__ import annotations

import pytest

from app.models.enums import Element
from app.services.element_symbols import all_symbols, symbol_for


@pytest.mark.parametrize("element", list(Element))
def test_every_vision_has_an_emblem(element: Element) -> None:
    """All seven, with no gaps. A missing one shows as a hole in a row of coloured marks —
    which reads as a loading failure rather than as missing data."""
    assert symbol_for(element) is not None


def test_the_traveler_without_a_vision_gets_nothing_rather_than_a_guess() -> None:
    """Two catalogue rows carry the literal `"None"`. `Element.parse` handles it rather than
    mapping it, and a basename built by string interpolation would have requested
    `None.webp`."""
    assert symbol_for("None") is None
    assert symbol_for(None) is None


def test_physical_is_not_a_vision_and_has_no_emblem() -> None:
    """A damage type, not an element — the ZZZ-shaped trap DESIGN §2.6 names. It has no
    emblem in this family either, so asking for one must not produce a broken image."""
    assert symbol_for("Physical") is None


def test_a_vision_from_a_future_patch_is_absent_rather_than_broken() -> None:
    """The reason this is an allowlist and not `f"{element}.webp"`. A constructed basename
    would request art nobody has vendored and render a broken mark; an allowlist renders
    nothing, which every consumer already handles."""
    assert symbol_for("Pneuma") is None


def test_the_downloader_is_offered_each_emblem_once() -> None:
    symbols = all_symbols()

    assert len(symbols) == len(set(symbols)) == len(list(Element))


def test_the_names_are_case_sensitive_as_the_cdn_serves_them() -> None:
    """`pyro.webp` is a 404 upstream. Lowercasing on the way out would vendor nothing and
    show no emblem anywhere — a whole-feature failure that no test of the mapping's *shape*
    would catch."""
    assert symbol_for(Element.PYRO) == "Pyro"
