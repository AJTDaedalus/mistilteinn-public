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
from app.services.planner.economy import Economy, economy

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


def test_feeding_exp_material_charges_no_mora(eco) -> None:
    """Zero, and it is a fact rather than a gap.

    Owner, 2026-09-07: *"there is no more per exp point conversion"*. The distinction still
    matters — `None` would mean "we do not know" and a UI must not render that as free — but
    this particular number is genuinely zero now.
    """
    bill = costs.exp_bill(eco, 1_000_000, {}, "character")
    assert bill.mora == 0


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


def test_an_unseeded_table_says_so_rather_than_blaming_the_character() -> None:
    """**Reported as a bug about Albedo, who publishes all six phases.**

    The user saw *"Albedo has no ascension phase 1 — it publishes none"*. Both faults produced
    that shape, and the empty-table one is the common one: these tables are created by a
    migration and filled by `seed_db`, so between the two every character answers this and the
    sentence names whichever one the user happened to pick.

    Naming the real cause is the difference between a five-minute fix and hunting a character's
    data. The message is asserted, not just the exception, because the message *was* the bug.
    """
    with pytest.raises(PlanError, match="No ascension costs are seeded at all") as raised:
        costs.ascension_bill({}, 0, 6, what="Albedo")

    assert "seed_db" in str(raised.value)
    # And it must not go on to accuse the character of publishing a short ladder.
    assert "has no ascension phase" not in str(raised.value)


def test_a_genuinely_short_ladder_still_names_what_it_does_publish() -> None:
    """The other fault is real and keeps its own sentence — a 1-star weapon publishes four
    phases, so planning one to 90/6 has to refuse rather than charge zero for 5 and 6."""
    four = {n: (n * 1000, [{"id": 100 + n, "count": n}]) for n in range(1, 5)}

    with pytest.raises(PlanError, match=r"has no ascension phase 5") as raised:
        costs.ascension_bill(four, 0, 6, what="a 1-star weapon")

    assert "[1, 2, 3, 4]" in str(raised.value)


# -- talents --------------------------------------------------------------------------


def test_talent_levels_above_ten_charge_nothing() -> None:
    """11-15 come free from C3/C5 and have no material rows at all."""
    bill = {n: (n * 100, [{"id": 200, "count": 1}]) for n in range(1, 10)}
    to_ten = costs.talent_bill(bill, 1, 10)
    assert costs.talent_bill(bill, 1, 15) == to_ten
    assert to_ten[0] == {200: 9}


# -- resin -----------------------------------------------------------------------------


def test_expected_runs_are_at_least_the_continuous_ratio(eco) -> None:
    """You cannot farm a fraction of a run, so the discrete answer sits above `need/mu`."""
    rate = eco.rate(104301)
    distribution = resin.runs_distribution(100, rate)
    expected = sum(index * p for index, p in enumerate(distribution))
    assert sum(distribution) == pytest.approx(1.0, abs=1e-5)
    assert expected >= 100 / rate.expected_per_run


def test_a_domain_run_is_priced_on_both_of_its_rolls(eco) -> None:
    """The bug the wiki's own tables exposed, and the biggest error this feature had.

    `RewardPreviewExcelConfigData` publishes a fractional count for the **guaranteed 2-star
    roll** and nothing for the drop packs, so a rate built from the preview alone counted a
    fraction of what a run really gives: 2.2 base-tier equivalents against 10.12 for a talent
    domain and 16.708 for a weapon one — 4.6x and 7.6x too pessimistic.

    The guaranteed roll's own mean is still 2.2, and that agreement is what says the curated
    table and the game's data are describing the same domain.
    """
    talent = eco.rate(104301)
    assert talent.expected_per_run == pytest.approx(10.12)
    assert eco.rate(114001).expected_per_run == pytest.approx(16.708)

    # A single 4-star book is worth nine 2-star ones, so the spread is wide and lumpy: the
    # best run is 3 guaranteed plus three 4-star packs, and the worst is 2 plus two 3-star.
    values = [value for value, _ in talent.distribution]
    assert (min(values), max(values)) == (8.0, 30.0)
    # And that lumpiness is the thing a mean cannot express — nearly a 4x spread.
    assert max(values) / min(values) > 3


def test_family_multipliers_come_from_the_crafting_tree(eco) -> None:
    """Read, not assumed to be 3:1 — a few recipes are not."""
    assert eco.family_multipliers(104301) == {0: 1, 1: 3, 2: 9}
    assert eco.family_multipliers(114001) == {0: 1, 1: 3, 2: 9, 3: 27}


def test_a_declared_shape_is_used_rather_than_the_mean(eco) -> None:
    """The bug this whole mechanism exists for.

    A ley-line run gives 6-7 blue books and 4-5 purple, which is four outcomes between
    110,000 and 135,000 EXP. Collapsed to its mean of 122,500 the fallback two-point model
    has `floor == ceil`, so it became a **point mass** and the run count came out certain —
    nine runs, probability 1.0, a histogram with one bar and no information in it.
    """
    rate = eco.rate(104003)
    assert rate.distribution is not None
    assert [value for value, _ in rate.distribution] == [110_000, 115_000, 130_000, 135_000]

    distribution = resin.runs_distribution(1_000_000, rate)
    assert sum(1 for p in distribution if p > 1e-6) > 1


def test_a_run_that_drops_none_of_your_material_still_costs_resin(eco) -> None:
    """39% of trounce runs yield none of the one material you came for.

    Filtering those outcomes out leaked their probability from the walk, and an 18-material
    plan came back needing **0.01 runs**.
    """
    rate = eco.rate(113018)
    zero = next(p for value, p in rate.distribution if value == 0)
    assert zero == pytest.approx(0.3852, abs=1e-3)

    distribution = resin.runs_distribution(18, rate)
    assert sum(distribution) == pytest.approx(1.0, abs=1e-5)
    expected_runs = sum(index * p for index, p in enumerate(distribution))
    assert expected_runs == pytest.approx(18 / rate.expected_per_run, rel=0.05)


def test_a_genuinely_flat_source_stays_deterministic(eco) -> None:
    """Mora is 60,000 a run, full stop. One outcome is the right answer, not a missing shape."""
    distribution = resin.runs_distribution(600_000, eco.rate(202))
    assert distribution.count(1.0) == 1
    assert len(distribution) == 11  # index 10 == exactly ten runs


def test_a_declared_shape_must_average_to_its_stated_mean() -> None:
    """Two ways to say the same thing, and the file must not let them disagree."""
    derived = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "app" / "data" / "yuanshen" / "snapshot" / "planner_economy.json"
        ).read_text(encoding="utf-8"),
    )
    curated = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "app" / "data" / "planner" / "curated_rates.json"
        ).read_text(encoding="utf-8"),
    )
    curated["source_defaults"]["ley_line_exp"]["expected_per_run"] = 99_999
    with pytest.raises(ValueError, match="declared shape averages"):
        Economy(derived, curated).rate(104003)


def test_a_crafted_tier_is_priced_as_the_tier_actually_farmed(eco) -> None:
    """Nine Philosophies are 81 Teachings, and the estimate says which root it counted."""
    estimate = resin.estimate(eco, 104303, 9)
    assert estimate is not None
    assert estimate.root_id == 104301
    assert estimate.expected_runs == pytest.approx(81 / eco.rate(104301).expected_per_run)


def test_shared_families_are_summed_before_runs_are_counted(eco) -> None:
    """One domain run drops several tiers, so pricing them apart bills it twice."""
    combined = resin.total(eco, {104301: 100, 104303: 9})
    apart = (
        resin.estimate(eco, 104301, 100).expected_resin
        + resin.estimate(eco, 104303, 9).expected_resin
    )
    assert combined.expected == pytest.approx(apart)
    assert len(combined._roots) == 1


def test_materials_with_no_resin_cost_are_named_and_charged_nothing(eco) -> None:
    """A Sakura Bloom is picked up, and a gem rides along with a boss run already paid for."""
    total = resin.total(eco, {104161: 20, 101202: 5, 112053: 5})
    assert total.not_farmable == [101202, 104161, 112053]
    assert total.unpriced == []
    assert total.expected == 0.0


def test_a_source_nobody_has_costed_is_named_rather_than_treated_as_free() -> None:
    """The branch that fires when a *new* patch adds a resin source with no rate.

    Every source is curated today, so nothing reaches this path through the real files — and
    that is exactly why it is exercised against a stripped economy instead. Without it the
    only test of "we do not know" would be one that can no longer fail, which is the
    can-only-return-one-answer shape this repo keeps finding.
    """
    derived = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "app" / "data" / "yuanshen" / "snapshot" / "planner_economy.json"
        ).read_text(encoding="utf-8"),
    )
    curated = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "app" / "data" / "planner" / "curated_rates.json"
        ).read_text(encoding="utf-8"),
    )
    curated["source_defaults"]["weekly_boss"]["expected_per_run"] = None
    stripped = Economy(derived, curated)

    total = resin.total(stripped, {113018: 9})

    assert total.unpriced == [113018]
    assert total.not_farmable == []
    assert total.expected == 0.0
    assert total.has_unpriced


def test_mora_and_exp_are_resin_too(eco) -> None:
    """Both are ley-line farmed at 20 resin a run, so a plan's mora bill has a resin price.

    60,000 mora and 122,500 character EXP per 20-resin blossom at World Level 9.
    """
    mora_only = resin.total(eco, {}, mora=600_000)
    assert mora_only.expected == pytest.approx(600_000 / 60_000 * 20)
    assert mora_only.unpriced_sources == []

    exp_only = resin.total(eco, {}, character_exp=1_225_000)
    assert exp_only.expected == pytest.approx(1_225_000 / 122_500 * 20)


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
            True,
        ),
        (
            "Flash of Genius",
            (
                "When Xingqiu crafts Character Talent Materials, he has a 25% chance to "
                "refund a portion of the crafting materials used."
            ),
            Effect.REFUND,
            {MaterialClass.TALENT},
            True,
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


def test_a_refund_bonus_moves_the_number_by_the_derived_amount() -> None:
    """**This asserted the opposite until 2026-09-07**, on the grounds that "a portion" left
    the size unstated. The description states it — one count of one material — and the owner
    supplied the derivation that turns it into a figure:
    https://genshin-impact.fandom.com/wiki/Crafting#Efficiency

    A craft eats three, so a 25% chance of one back is `3 / (3 - 0.25)`, not 1.25 and not 1.0.
    Both of those wrong answers are round numbers a reader could believe, which is why the
    value is asserted rather than just "greater than one".
    """
    mona = classify(
        "c", "Mona", "Principium of Astrology",
        "When Mona crafts Weapon Ascension Materials, she has a 25% chance to refund a "
        "portion of the crafting materials used.",
    )

    assert craft_multiplier([mona], MaterialClass.WEAPON_ASCENSION) == pytest.approx(3 / 2.75)
    # And still nothing for the class she does not name.
    assert craft_multiplier([mona], MaterialClass.TALENT) == 1.0
