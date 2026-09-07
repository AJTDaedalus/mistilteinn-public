"""The cost and resin engines, and the crafting-bonus classifier.

These are pure functions over the committed snapshot, so they need no database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.planner import costs, resin
from app.services.planner.costs import PlanError, Progress
from app.services.planner.crafting import (
    Effect,
    MaterialClass,
    classify,
    craft_multiplier,
)
from app.services.planner.economy import economy

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"


@pytest.fixture(scope="module")
def eco():
    return economy()


@pytest.fixture(scope="module")
def level_exp() -> list[int]:
    return json.loads((FIXTURES / "character_10000002.json").read_text())["level_exp"]


# -- levels and EXP ------------------------------------------------------------------


def test_character_exp_to_ninety_is_the_published_total(level_exp: list[int]) -> None:
    """8,362,650. `level_exp` is per level, and this sum is what settled the indexing."""
    assert costs.character_exp_between(level_exp, 1, 90) == 8_362_650
    assert costs.character_exp_between(level_exp, 90, 90) == 0
    assert costs.character_exp_between(level_exp, 90, 1) == 0


def test_weapon_exp_reads_the_level_being_left() -> None:
    curve = json.loads((FIXTURES / "weapon_11501.json").read_text())["xp_requirements"]
    assert costs.weapon_exp_between(curve, 1, 90) == 9_064_450
    assert costs.weapon_exp_between(curve, 89, 90) == curve["89"]


def test_books_round_the_smallest_denomination_up(eco) -> None:
    """A partial book does not exist, and rounding down leaves the plan a level short."""
    books = dict(costs.books_for(20_001, eco.character_exp_items))
    assert books[104003] == 1
    assert sum(count * next(i.exp for i in eco.character_exp_items if i.id == mat)
               for mat, count in books.items()) >= 20_001


def test_exp_stock_is_a_pool_across_denominations(eco) -> None:
    """The three books feed one bar, so stock is credited as total EXP.

    They are **not** interchangeable by crafting — no recipe converts one into another and
    each is its own craft root — but they are interchangeable as fuel, and only the second
    thing matters for counting what a user already holds.
    """
    bill = costs.exp_bill(eco, 25_000, {104003: 1, 104002: 1}, "character")
    assert bill.exp_owned == 25_000
    assert bill.exp_short == 0
    assert bill.books == []


def test_exp_denominations_do_not_craft_into_one_another(eco) -> None:
    for material_id in eco.exp_material_ids():
        assert eco.craft_step(material_id) is None
        assert eco.craft_root(material_id) == material_id


def test_uncurated_mora_divisor_reports_none_not_zero(eco) -> None:
    """`None` is "we do not know", and a UI must not render it as free."""
    bill = costs.exp_bill(eco, 1_000_000, {}, "character")
    assert bill.mora is None


# -- ascension, including ascending without levelling --------------------------------


def test_ascending_without_levelling_is_legal(eco) -> None:
    """80/5 -> 80/6: the owner's "stay at 80/90" case. Costs the phase, no EXP."""
    costs.validate_move(Progress(80, 5), Progress(80, 6), eco.character_level_caps, "character")


def test_a_level_above_its_phase_cap_is_refused(eco) -> None:
    with pytest.raises(PlanError, match="which is what ascension phase 0 unlocks"):
        costs.validate_move(Progress(1, 0), Progress(50, 0), eco.character_level_caps, "character")


def test_the_planner_does_not_un_level_things(eco) -> None:
    with pytest.raises(PlanError, match="does not un-level"):
        costs.validate_move(
            Progress(80, 5), Progress(70, 5), eco.character_level_caps, "character",
        )


def test_ascension_charges_only_the_phases_crossed() -> None:
    bill = {n: (n * 1000, [{"id": 100 + n, "count": n}]) for n in range(1, 7)}
    items, mora = costs.ascension_bill(bill, 2, 4)
    assert items == {103: 3, 104: 4}
    assert mora == 7000


# -- talents --------------------------------------------------------------------------


def test_talent_levels_above_ten_charge_nothing() -> None:
    """11-15 come free from C3/C5 and have no material rows at all."""
    bill = {n: (n * 100, [{"id": 200, "count": 1}]) for n in range(1, 10)}
    to_ten = costs.talent_bill(bill, 1, 10)
    assert costs.talent_bill(bill, 1, 15) == to_ten
    assert to_ten[0] == {200: 9}


# -- resin -----------------------------------------------------------------------------


def test_expected_runs_are_at_least_the_continuous_ratio() -> None:
    """You cannot farm a fraction of a run, so the discrete answer sits above `need/mu`."""
    distribution = resin.runs_distribution(100, 2.2)
    expected = sum(index * p for index, p in enumerate(distribution))
    assert sum(distribution) == pytest.approx(1.0, abs=1e-6)
    assert expected >= 100 / 2.2


def test_a_crafted_tier_is_priced_as_the_tier_actually_farmed(eco) -> None:
    """Nine Philosophies are 81 Teachings, and the estimate says which root it counted."""
    estimate = resin.estimate(eco, 104303, 9)
    assert estimate is not None
    assert estimate.root_id == 104301
    assert estimate.expected_runs == pytest.approx(81 / 2.2)


def test_shared_families_are_summed_before_runs_are_counted(eco) -> None:
    """One domain run drops several tiers, so pricing them apart bills it twice."""
    combined = resin.total(eco, {104301: 100, 104303: 9})
    apart = (
        resin.estimate(eco, 104301, 100).expected_resin
        + resin.estimate(eco, 104303, 9).expected_resin
    )
    assert combined.expected == pytest.approx(apart)
    assert len(combined._roots) == 1


def test_no_resin_cost_and_no_known_rate_are_different_answers(eco) -> None:
    """One field for both would be wrong in opposite directions.

    A Sakura Bloom is picked off the ground and a Shivada Jade Sliver rides along with a boss
    run already paid for -- both genuinely cost no resin. A Bloodjade Branch costs resin at a
    trounce domain whose yield nobody publishes. Folding them together would tell the user
    their specialties are an unknown farming cost and their weekly bosses are free.
    """
    total = resin.total(eco, {104161: 20, 101202: 5, 112053: 5, 113018: 9})
    assert total.not_farmable == [101202, 104161, 112053]
    assert total.unpriced == [113018]
    assert total.expected == 0.0
    assert total.has_unpriced


def test_mora_and_exp_are_resin_too(eco) -> None:
    """Both are ley-line farmed at 20 resin a run, so a plan's mora bill has a resin price.

    Reported as unpriced sources while the blossom yields are uncurated -- never as zero.
    """
    total = resin.total(eco, {}, mora=500_000, character_exp=100_000)
    assert total.unpriced_sources == ["character EXP", "mora"]
    assert total.expected == 0.0


def test_the_histogram_is_a_distribution(eco) -> None:
    total = resin.total(eco, {104301: 100})
    assert total.histogram
    assert sum(b.probability for b in total.histogram) == pytest.approx(1.0, abs=1e-3)
    assert all(b.low < b.high for b in total.histogram)


def test_nothing_to_farm_draws_no_histogram(eco) -> None:
    assert resin.total(eco, {}).histogram == []


# -- crafting bonuses -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "description", "effect", "classes", "applied"),
    [
        (
            "Astable Invention",
            (
                "When Sucrose crafts Character and Weapon Enhancement Materials, she has a "
                "10% chance to obtain double the product."
            ),
            Effect.DOUBLE,
            {MaterialClass.TALENT, MaterialClass.WEAPON_ASCENSION},
            True,
        ),
        (
            "Unexpected Order",
            (
                "Has a 25% chance to recover some of the materials used when crafting "
                "Character and Weapon Materials."
            ),
            Effect.REFUND,
            {MaterialClass.TALENT, MaterialClass.WEAPON_ASCENSION},
            False,
        ),
        (
            "Flash of Genius",
            (
                "When Xingqiu crafts Character Talent Materials, he has a 25% chance to "
                "refund a portion of the crafting materials used."
            ),
            Effect.REFUND,
            {MaterialClass.TALENT},
            False,
        ),
    ],
)
def test_the_three_effect_shapes_classify(name, description, effect, classes, applied) -> None:
    bonus = classify("id", "Someone", name, description)
    assert bonus is not None
    assert bonus.effect is effect
    assert set(bonus.classes) == classes
    assert bonus.applicable is applied


@pytest.mark.parametrize(
    "description",
    [
        (
            "When a Perfect Cooking is achieved on a dish with restorative effects, there "
            "is a 12% chance to obtain double the product."
        ),
        "Refunds 15% of the ore used when crafting Claymore-type weapons.",
        (
            "When Yoimiya crafts Decoration, Ornament, and Landscape-type Furnishings, she "
            "has a 100% chance to refund a portion of the materials used."
        ),
    ],
)
def test_cooking_forging_and_furnishing_passives_are_not_planner_bonuses(description) -> None:
    """They match the same verbs. Filter by effect, never by "has a crafting passive"."""
    assert classify("id", "Someone", "Whatever", description) is None


def test_only_the_best_double_applies_because_one_character_crafts_a_batch() -> None:
    sucrose = classify(
        "a", "Sucrose", "Astable Invention",
        "When Sucrose crafts Character and Weapon Enhancement Materials, she has a 10% "
        "chance to obtain double the product.",
    )
    eula = classify(
        "b", "Eula", "Aristocratic Introspection",
        "When Eula crafts Character Talent Materials, she has a 10% chance to receive double "
        "the product.",
    )
    assert craft_multiplier([sucrose, eula], MaterialClass.TALENT) == pytest.approx(1.10)
    assert craft_multiplier([], MaterialClass.TALENT) == 1.0


def test_a_refund_bonus_never_moves_a_number() -> None:
    """The chance is published; "a portion" is not. Reported, never applied."""
    mona = classify(
        "c", "Mona", "Principium of Astrology",
        "When Mona crafts Weapon Ascension Materials, she has a 25% chance to refund a "
        "portion of the crafting materials used.",
    )
    assert craft_multiplier([mona], MaterialClass.WEAPON_ASCENSION) == 1.0
