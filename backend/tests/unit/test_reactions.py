"""Which reactions a party can produce.

The data is **committed and cited** — `docs/RESEARCH_elemental_reactions.md` records the source
URL, the retrieval date and the wiki's own wording per reaction. These tests are about the
*reading* of it, and about the two things that would go wrong silently.
"""

from __future__ import annotations

import pytest

from app.services.reactions import offered, possible_for


def party(*elements: str) -> frozenset[str]:
    return frozenset(elements)


def test_hyperbloom_needs_all_three_of_its_elements() -> None:
    """**The owner called this one out**, because it is three elements where most are two.

    A pair-shaped model would offer it to a Dendro/Hydro team that cannot produce it.
    """
    assert "hyperbloom" in possible_for(party("Dendro", "Hydro", "Electro"))
    assert "hyperbloom" not in possible_for(party("Dendro", "Hydro"))
    assert "hyperbloom" not in possible_for(party("Dendro", "Electro"))


def test_a_two_element_reaction_needs_exactly_its_pair() -> None:
    assert possible_for(party("Pyro", "Cryo")) == ("melt",)


def test_swirl_takes_anemo_plus_any_one_of_four() -> None:
    """The wildcard. Anemo alone swirls nothing, and Anemo with Dendro or Geo still does not —
    the source excludes both from what Swirl carries."""
    assert "swirl" in possible_for(party("Anemo", "Pyro"))
    assert "swirl" in possible_for(party("Anemo", "Cryo"))
    assert "swirl" not in possible_for(party("Anemo"))
    assert "swirl" not in possible_for(party("Anemo", "Dendro"))
    assert "swirl" not in possible_for(party("Anemo", "Geo"))


def test_crystallize_takes_geo_plus_any_one_of_four() -> None:
    assert "crystallize" in possible_for(party("Geo", "Hydro"))
    assert "crystallize" not in possible_for(party("Geo", "Anemo"))


@pytest.mark.parametrize(
    "reaction",
    ["shattered", "lunar_charged", "lunar_crystallize", "stellar_conduct", "stellar_swirl"],
)
def test_an_uncertain_reaction_is_never_offered(reaction: str) -> None:
    """**Five rows the source could not settle, and a filter must not guess for them.**

    Shattered is not an element pair at all — the wiki says *"a Blunt or Geo attack"*, and Blunt
    is Physical, so `{Cryo, Hydro}` over-counts teams and adding Geo under-counts them. The four
    Lunar/Stellar ones may require a party talent, which the source gates the *effect* on rather
    than clearly the reaction.

    Mis-classifying a team quietly is worse than offering less.
    """
    assert reaction not in {r.id for r in offered()}


def test_the_offered_set_is_the_certain_one() -> None:
    """A guard on the count. Growing it means someone resolved an uncertainty or the source
    added a reaction, and either is a decision rather than a side effect."""
    assert len(offered()) == 16


def test_a_party_with_one_element_reacts_with_nothing() -> None:
    """Every reaction needs at least two, so a mono-element team produces none of them —
    which is the correct answer and not an empty-data bug."""
    assert possible_for(party("Pyro")) == ()


def test_possible_is_not_guaranteed() -> None:
    """A four-element party is offered a great many reactions, because it *could* produce them.

    Whether a rotation actually does is the simulator's question. This is a filter over what a
    party can field, and claiming more would be answering something it cannot see.
    """
    found = possible_for(party("Dendro", "Hydro", "Electro", "Anemo"))

    assert "hyperbloom" in found
    assert "swirl" in found
    assert len(found) > 2
