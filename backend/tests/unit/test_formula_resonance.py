"""Math-fallback P1, task 6 — elemental resonance from a team's elements.

The rules are GO's `Resonance.tsx` and gcsim's `SetupResonance` (cited in
`app/formula/genshin/resonance.py`): four members or nothing, two of an element is enough and
more is no better, each member counted once, and a member with no element counted not at all.
"""

from __future__ import annotations

import pytest

from app.formula.genshin import resonance
from app.formula.genshin.formula_effects import status_of


def _keys(elements: list[str | None]) -> list[str]:
    return [r.key for r in resonance.active(elements)]


def test_three_members_have_no_resonance_however_alike():
    # GO `greaterEq(teamSize, 4, …)`, gcsim `len(chars) < 4` returns early.
    assert _keys(["Pyro", "Pyro", "Pyro"]) == []
    assert resonance.tally(["Pyro", "Pyro", "Pyro"]).size == 3


def test_two_of_an_element_in_four_is_enough():
    assert _keys(["Pyro", "Pyro", "Hydro", "Cryo"]) == ["fervent_flames"]


def test_four_of_an_element_is_one_resonance_not_two():
    # Duplicates: a resonance applies once however many members share the element.
    assert _keys(["Pyro", "Pyro", "Pyro", "Pyro"]) == ["fervent_flames"]


def test_two_pairs_give_two_resonances():
    assert _keys(["Pyro", "Pyro", "Hydro", "Hydro"]) == ["fervent_flames", "soothing_waters"]


def test_four_different_elements_give_protective_canopy_only():
    assert _keys(["Pyro", "Hydro", "Cryo", "Electro"]) == ["protective_canopy"]


def test_a_traveler_counts_as_the_variant_on_the_team():
    # Each Traveler variant is its own catalogue character carrying its element, so a Geo
    # Traveler beside a Geo character is two Geo members.
    assert _keys(["Geo", "Geo", "Pyro", "Hydro"]) == ["enduring_rock"]


def test_a_member_with_no_element_counts_toward_nothing():
    # The two unreleased Traveler bodies have a null element. GO's teamSize is the sum of the
    # element tallies, so three elemental members and one without are a team of three.
    tallied = resonance.tally(["Pyro", "Pyro", "Hydro", None])
    assert tallied.size == 3
    assert _keys(["Pyro", "Pyro", "Hydro", None]) == []


def test_tally_lowercases_and_refuses_a_non_element():
    assert resonance.tally(["Dendro", "dendro"]).elements == {"dendro": 2}
    with pytest.raises(ValueError, match="seven elements"):
        resonance.tally(["Physical"])


def test_the_static_effects_are_gos_and_gcsims_numbers():
    by_key = {r.key: r for r in resonance.RESONANCES}
    assert [(e.stat, e.value) for e in by_key["fervent_flames"].bonus.effects] == [
        ("atk_pct", 0.25),
    ]
    assert [(e.stat, e.value) for e in by_key["soothing_waters"].bonus.effects] == [
        ("hp_pct", 0.25),
    ]
    greenery = by_key["sprawling_greenery"].bonus.effects
    # 50 static, then +30 and +20 each behind its own condition.
    assert [(e.value, bool(e.when)) for e in greenery] == [
        (50.0, False), (30.0, True), (20.0, True),
    ]


def test_conditional_resonances_default_off():
    ice = {r.key: r for r in resonance.RESONANCES}["shattering_ice"].bonus
    assert [c.default for c in ice.conditions] == [0]
    assert ice.effects[0].when[0].condition == "enemy_cryo"


def test_every_resonance_is_cited_to_go_and_has_an_honest_status():
    for r in resonance.RESONANCES:
        assert "Resonance.tsx:" in r.citation, r.key
    statuses = {r.key: status_of(r.bonus) for r in resonance.RESONANCES}
    assert statuses == {
        "fervent_flames": "modelled",
        "soothing_waters": "modelled",
        "shattering_ice": "modelled",
        "enduring_rock": "partial",
        "sprawling_greenery": "modelled",
        "high_voltage": "no_damage_effect",
        "impetuous_winds": "no_damage_effect",
        "protective_canopy": "no_damage_effect",
    }
