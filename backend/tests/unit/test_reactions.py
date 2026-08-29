"""Which reactions a party can produce.

The data is **committed and cited** — `docs/RESEARCH_elemental_reactions.md` records the source
URL, the retrieval date and the wiki's own wording per reaction. These tests are about the
*reading* of it, and about the two things that would go wrong silently.
"""

from __future__ import annotations

import json

import pytest

from app.services.reactions import _DATA, offered, possible_for


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


def test_shattered_is_never_offered() -> None:
    """**Not an element pair at all.**

    The wiki says *"a Blunt or Geo attack"*, and Blunt is Physical — so `{Cryo, Hydro}`
    over-counts teams and adding Geo under-counts them. Mis-classifying a team quietly is worse
    than offering less, and the owner's ruling agrees: *"just the base reactions (minus
    shatter)"*.
    """
    assert "shattered" not in {r.id for r in offered()}


@pytest.mark.parametrize(
    "reaction", ["lunar_charged", "lunar_bloom", "lunar_crystallize", "stellar_conduct",
                 "stellar_swirl"],
)
def test_a_lunar_or_stellar_variant_is_never_offered(reaction: str) -> None:
    """Owner ruling: *"You can leave out lunar and stellar variants."*

    **Lunar-Bloom is the one that matters here**, because it is the only one the source settles
    — it would otherwise have been offered on certainty alone. The other four are uncertain as
    well, so the two rules overlap; this test is about the ruling, not the uncertainty.
    """
    assert reaction not in {r.id for r in offered()}


def test_an_excluded_reaction_is_still_in_the_committed_file() -> None:
    """**An exclusion that deletes its own evidence reads as an oversight.**

    All six excluded rows stay in the JSON with their citation and their `uncertain` /
    `party_gate` notes, so the next reader can see *why* they are out and reverse it without
    redoing the research. A tidy-up that deleted them would leave the filter looking merely
    incomplete, and the transcription in `docs/RESEARCH_elemental_reactions.md` is the only
    other copy.
    """
    ids = {row["id"] for row in json.loads(_DATA.read_text())["reactions"]}

    assert {
        "shattered", "lunar_charged", "lunar_bloom", "lunar_crystallize", "stellar_conduct",
        "stellar_swirl",
    } <= ids
    assert len(ids) == 21


def test_the_offered_set_is_the_fifteen_a_player_would_name() -> None:
    """A guard on the count. Growing it means someone resolved an uncertainty, reversed the
    Lunar/Stellar ruling, or the source added a reaction — each a decision rather than a side
    effect."""
    assert len(offered()) == 15


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
