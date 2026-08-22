"""D.4 — the explanation, and the ways it could be confidently wrong.

An explanation is the one place a fabricated number would be least likely to be checked: it
*reads* like prose, so a reader's guard is down, and it is exactly where a fluent sentence
with nothing behind it does the most damage. So most of what follows tests that the module
**refuses** rather than that it renders.
"""

from __future__ import annotations

import math

import pytest

from app.formula.genshin.explain import Contribution
from app.formula.genshin.tags import (
    SRC_ARTIFACT,
    SRC_ARTIFACT_SET,
    SRC_CHARACTER,
    SRC_WEAPON,
)
from app.models.sim_run import SimRun
from app.services.build_explanation import compare, explain
from app.services.sim_retrieval import retrieve


def _c(quantity: str, value: float, source: str = SRC_ARTIFACT, note: str = "") -> Contribution:
    return Contribution(quantity=quantity, value=value, source=source, note=note)


def _run(bucket: int, dps: float | None, *, sd: float = 0.0, iterations: int = 50) -> SimRun:
    return SimRun(
        context_key="a" * 64, er_bucket=bucket, gcsim_pin="b" * 40,
        result={"statistics": {"iterations": iterations, "dps": {"mean": dps, "sd": sd}}},
        dps_mean=dps,
    )


# ── Grouping, and the sum that is not your ATK ────────────────────────────────


def test_contributions_are_grouped_by_quantity():
    account = explain([
        _c("atk_pct", 0.466, note="sands main stat"),
        _c("crit_dmg", 0.622, note="circlet main stat"),
        _c("atk_pct", 0.058, note="flower substat"),
    ]).account_for("atk_pct")

    assert len(account.parts) == 2
    assert account.sum_of_parts == pytest.approx(0.524)


def test_the_sum_is_named_for_what_it_is_not_a_total():
    """`base * (1 + pct) + flat` does not equal the sum of its parts.

    A field called `total` would invite a reader to believe otherwise, which is why there
    isn't one. This test exists so a future rename has to argue with it.
    """
    from app.services.build_explanation import StatAccount

    assert hasattr(StatAccount, "sum_of_parts")
    assert not hasattr(StatAccount, "total")


def test_headline_quantities_come_first_and_the_rest_are_ordered():
    """An account opening with `character_level` buries what the reader came for."""
    order = [s.quantity for s in explain([
        _c("character_level", 90, SRC_CHARACTER),
        _c("crit_dmg", 0.6),
        _c("zzz_unknown", 1.0),
        _c("atk_pct", 0.4),
    ]).stats]
    assert order[:2] == ["atk_pct", "crit_dmg"]
    assert order[2:] == ["character_level", "zzz_unknown"], "the tail is alphabetical, not luck"


def test_an_account_reports_which_kinds_of_thing_fed_it():
    account = explain([
        _c("atk_pct", 0.2, SRC_WEAPON, "Mistsplitter substat"),
        _c("atk_pct", 0.466, SRC_ARTIFACT, "sands main stat"),
    ]).account_for("atk_pct")
    assert account.sources == (SRC_WEAPON, SRC_ARTIFACT)


# ── Catalogue text: published, never composed ─────────────────────────────────


def test_a_set_effect_carries_the_catalogues_own_words():
    result = explain(
        [_c("crit_rate", 0.2, SRC_ARTIFACT_SET, "Blizzard Strayer 4pc")],
        set_descriptions={"Blizzard Strayer 4pc": "CRIT Rate against Cryo-affected is +20%."},
    )
    assert result.set_effects[0].description == "CRIT Rate against Cryo-affected is +20%."
    assert result.uncited == ()


def test_a_set_with_no_catalogue_text_is_reported_uncited_not_paraphrased():
    """Writing the effect from memory is what this repo forbids everywhere else.

    Here it would be least likely to be caught, because the output reads like prose.
    """
    result = explain([_c("crit_rate", 0.2, SRC_ARTIFACT_SET, "Blizzard Strayer 4pc")])

    assert result.set_effects[0].description is None, "silence, not an invented sentence"
    assert len(result.uncited) == 1
    assert "Blizzard Strayer 4pc" in result.uncited[0].what


def test_a_missing_description_is_none_rather_than_empty():
    """"The catalogue is silent" and "the catalogue says nothing applies" differ."""
    result = explain([_c("crit_rate", 0.2, SRC_ARTIFACT_SET, "Unknown 2pc")])
    assert result.set_effects[0].description is None
    assert result.set_effects[0].description != ""


def test_a_set_bonus_with_no_note_is_uncited_and_not_shown():
    """"artifact_set +0.15" names neither which set nor how many pieces, and there are five
    pieces a user might change."""
    result = explain([_c("dmg_bonus", 0.15, SRC_ARTIFACT_SET, "")])
    assert result.set_effects == ()
    assert len(result.uncited) == 1
    assert "no note" in result.uncited[0].why


def test_only_set_contributions_become_set_effects():
    result = explain([
        _c("atk_pct", 0.466, SRC_ARTIFACT, "sands main stat"),
        _c("base_atk", 674.0, SRC_WEAPON, "Mistsplitter Reforged"),
    ])
    assert result.set_effects == ()
    assert result.uncited == ()


# ── The simulation, and its caveat ────────────────────────────────────────────


def test_the_simulation_note_carries_the_measured_divergence():
    found = retrieve([_run(180, 100.0), _run(185, 113.0)], 1.82)
    note = explain([_c("atk_pct", 0.4)], retrieval=found).simulation
    assert note.is_exact_bucket
    assert note.divergence_pct == pytest.approx(13.0)


def test_an_exact_bucket_still_states_a_caveat():
    """RESEARCH_er_bucketing: an exact *key* is not an exact *answer*.

    A reader must not be able to come away thinking a distance-zero match means no
    approximation was made.
    """
    found = retrieve([_run(180, 100.0), _run(185, 113.0)], 1.82)
    note = explain([_c("atk_pct", 0.4)], retrieval=found).simulation
    assert "lower bound" in note.caveat
    assert "inside its bucket" in note.caveat


def test_a_neighbour_says_how_far_it_was():
    found = retrieve([_run(175, 100.0), _run(170, 96.0)], 1.80)
    note = explain([_c("atk_pct", 0.4)], retrieval=found).simulation
    assert not note.is_exact_bucket
    assert "1 away from 180" in note.caveat


def test_an_unmeasurable_neighbourhood_says_so_rather_than_claiming_zero():
    found = retrieve([_run(180, 100.0)], 1.80)
    note = explain([_c("atk_pct", 0.4)], retrieval=found).simulation
    assert note.divergence_pct is None
    assert "has not been measured" in note.caveat


def test_a_build_scored_without_a_run_has_no_simulation_note():
    assert explain([_c("atk_pct", 0.4)]).simulation is None


# ── The comparison: why is this better ────────────────────────────────────────


def test_a_comparison_reports_what_was_gained_and_lost():
    before = [_c("crit_dmg", 0.622, note="circlet main stat")]
    after = [
        _c("crit_dmg", 0.662, note="circlet main stat"),
        _c("crit_dmg", 0.2, SRC_ARTIFACT_SET, "Blizzard Strayer 4pc"),
    ]

    difference = compare(before, after).differences[0]
    assert difference.quantity == "crit_dmg"
    assert difference.delta == pytest.approx(0.24)
    assert {p.note for p in difference.gained} == {"circlet main stat", "Blizzard Strayer 4pc"}
    assert {p.note for p in difference.lost} == {"circlet main stat"}


def test_differences_are_ranked_by_relative_size_not_absolute():
    """`flat_atk +311` above `crit_dmg +0.20` would rank builds by which stats are big numbers.

    A quantity is only comparable with itself, so the ordering has to be scale-free.
    """
    before = [_c("flat_atk", 3110.0), _c("crit_dmg", 0.5)]
    after = [_c("flat_atk", 3421.0), _c("crit_dmg", 0.7)]

    order = [d.quantity for d in compare(before, after).differences]
    assert order == ["crit_dmg", "flat_atk"], "crit_dmg moved 40%, flat_atk 10%"


def test_a_quantity_appearing_from_nothing_ranks_first():
    before = [_c("crit_dmg", 0.5)]
    after = [_c("crit_dmg", 0.6), _c("elemental_mastery", 80.0)]

    ranked = compare(before, after).differences
    assert ranked[0].quantity == "elemental_mastery"
    assert math.isinf(
        abs(ranked[0].delta) / abs(ranked[0].left) if ranked[0].left else float("inf")
    )


def test_identical_builds_have_no_differences():
    same = [_c("crit_dmg", 0.5), _c("atk_pct", 0.4)]
    result = compare(same, list(same))
    assert result.differences == ()
    assert set(result.unchanged) == {"crit_dmg", "atk_pct"}


def test_the_same_total_from_different_pieces_is_a_difference_not_a_match():
    """Two goblets summing to the same ATK% are not the same build.

    A comparison that reported "nothing changed" would be telling a user their swap did
    nothing, when what actually happened is that the *stat* did nothing and the piece changed.
    """
    before = [_c("atk_pct", 0.466, note="goblet A")]
    after = [_c("atk_pct", 0.466, note="goblet B")]

    result = compare(before, after)
    assert result.unchanged == ()
    assert result.differences[0].delta == 0.0
    assert result.differences[0].gained[0].note == "goblet B"
    assert result.differences[0].lost[0].note == "goblet A"


def test_unchanged_quantities_are_reported_as_the_denominator():
    """One stat out of twenty differing is a different claim from one out of two."""
    before = [_c("crit_dmg", 0.5), _c("atk_pct", 0.4), _c("elemental_mastery", 40.0)]
    after = [_c("crit_dmg", 0.7), _c("atk_pct", 0.4), _c("elemental_mastery", 40.0)]

    result = compare(before, after)
    assert len(result.differences) == 1
    assert set(result.unchanged) == {"atk_pct", "elemental_mastery"}


# ── The standing constraint ───────────────────────────────────────────────────


def test_the_explanation_computes_nothing_of_its_own():
    """DESIGN §1 A6 — a second implementation of the chain would be free to disagree.

    Every value reaching the output is a value that arrived, so the set of numbers out is a
    subset of the numbers in.
    """
    contributions = [
        _c("atk_pct", 0.466, note="sands"),
        _c("crit_dmg", 0.622, note="circlet"),
        _c("crit_rate", 0.2, SRC_ARTIFACT_SET, "Blizzard Strayer 4pc"),
    ]
    given = {c.value for c in contributions}
    produced = {part.value for account in explain(contributions).stats for part in account.parts}
    assert produced <= given
