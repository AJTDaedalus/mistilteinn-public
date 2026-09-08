"""The twelve crafting passives still classify, with the descriptions the game ships.

`app/services/planner/crafting.py` matches English description text, which is fragile — and
its docstring says the fragility is acceptable *because this file exists*. It did not, until
the review pointed out that the docstring cited a guard that had never been written.

The descriptions below are captured verbatim from the seeded catalogue at nanoka 7.0.54, so a
patch that rewords a passive fails here rather than silently dropping a bonus from every plan.
Re-capture by querying `ascension_passives` rather than editing by hand.
"""

# ruff: noqa: E501 — the descriptions below are verbatim game strings. Reflowing them to fit
# the line limit would make them no longer byte-exact, which is the one property that makes
# this file a guard rather than a paraphrase.
from __future__ import annotations

import pytest

from app.services.planner.crafting import (
    INPUTS_PER_CRAFT,
    CraftingBonus,
    Effect,
    MaterialClass,
    classify,
    craft_multiplier,
)
from app.services.planner.economy import MaterialSource, economy

#: `(character, passive, description)` for every passive the planner acts on, verbatim.
SEEDED: tuple[tuple[str, str, str], ...] = (
    (
        "Albedo",
        "Flash of Genius",
        "When Albedo crafts Weapon Ascension Materials, he has a 10% chance to receive double the product.",
    ),
    (
        "Alhaitham",
        "Law of Reductive Overdetermination",
        "When Alhaitham crafts Weapon Ascension Materials, he has a 10% chance to receive double the product.",
    ),
    (
        "Dori",
        "Unexpected Order",
        "Has a 25% chance to recover some of the materials used when crafting Character and Weapon Materials.",
    ),
    (
        "Eula",
        "Aristocratic Introspection",
        "When Eula crafts Character Talent Materials, she has a 10% chance to receive double the product.",
    ),
    (
        "Kamisato Ayaka",
        "Fruits of Shinsa",
        "When Ayaka crafts Weapon Ascension Materials, she has a 10% chance to receive double the product.",
    ),
    (
        "Layla",
        "Shadowy Dream-Signs",
        "When Layla crafts Character Talent Materials, she has a 10% chance to receive double the product.",
    ),
    (
        "Mona",
        "Principium of Astrology",
        "When Mona crafts Weapon Ascension Materials, she has a 25% chance to refund a portion of the crafting materials used.",
    ),
    (
        "Prune",
        "Tinker-Tink, Clank, and Bang!",
        "Has a 10% chance to get 1 regional Character Talent Material (base material excluded) when crafting. The rarity is the same as the resulting material.",
    ),
    (
        "Sucrose",
        "Astable Invention",
        "When Sucrose crafts Character and Weapon Enhancement Materials, she has a 10% chance to obtain double the product.",
    ),
    (
        "Wriothesley",
        "The Duke's Grace",
        "When Wriothesley crafts Weapon Ascension Materials, he has a 10% chance to receive double the product.",
    ),
    (
        "Xingqiu",
        "Flash of Genius",
        "When Xingqiu crafts Character Talent Materials, he has a 25% chance to refund a portion of the crafting materials used.",
    ),
    (
        "Yae Miko",
        "Meditations of a Yako",
        "Has a 25% chance to get 1 regional Character Talent Material (base material excluded) when crafting. The rarity is that of the base material.",
    ),
)

#: What each one must resolve to, or `None` for a passive that is not planner-relevant.
#: Ten apply, and two classify to nothing at all: a bonus *regional* material would need the
#: regional family modelled, which the owner ruled out, so they are refused the same way a
#: cooking passive is.
EXPECTED: dict[str, tuple[Effect, set[MaterialClass], bool] | None] = {
    "Albedo": (Effect.DOUBLE, {MaterialClass.WEAPON_ASCENSION}, True),
    "Alhaitham": (Effect.DOUBLE, {MaterialClass.WEAPON_ASCENSION}, True),
    "Dori": (Effect.REFUND, {MaterialClass.TALENT, MaterialClass.WEAPON_ASCENSION}, True),
    "Eula": (Effect.DOUBLE, {MaterialClass.TALENT}, True),
    "Kamisato Ayaka": (Effect.DOUBLE, {MaterialClass.WEAPON_ASCENSION}, True),
    "Layla": (Effect.DOUBLE, {MaterialClass.TALENT}, True),
    "Mona": (Effect.REFUND, {MaterialClass.WEAPON_ASCENSION}, True),
    "Prune": None,
    "Sucrose": (Effect.DOUBLE, {MaterialClass.TALENT, MaterialClass.WEAPON_ASCENSION}, True),
    "Wriothesley": (Effect.DOUBLE, {MaterialClass.WEAPON_ASCENSION}, True),
    "Xingqiu": (Effect.REFUND, {MaterialClass.TALENT}, True),
    "Yae Miko": None,
}


@pytest.mark.parametrize(("character", "passive", "description"), SEEDED)
def test_every_seeded_crafting_passive_still_classifies(
    character: str, passive: str, description: str,
) -> None:
    bonus = classify("id", character, passive, description)
    expected = EXPECTED[character]
    if expected is None:
        # **Refused, and the description is still pinned.** These two are held here rather than
        # deleted so a reworded passive that started matching `_DOUBLE` would fail loudly
        # instead of quietly reappearing in the planner.
        assert bonus is None, f"{character}'s {passive!r} is not planner-relevant"
        return
    assert bonus is not None, f"{character}'s {passive!r} no longer classifies"
    effect, classes, applicable = expected
    assert bonus.effect is effect
    assert set(bonus.classes) == classes
    assert bonus.applicable is applicable
    assert 0 < bonus.chance <= 1


def test_the_expected_set_is_exactly_the_seeded_set() -> None:
    """A passive added to one list and not the other is the drift this file exists to catch."""
    assert {character for character, _, _ in SEEDED} == set(EXPECTED)


def test_dori_needs_the_looser_wording() -> None:
    """She says "Character and Weapon Materials" with no middle word, and a stricter pattern
    missed her entirely — found by listing what classified, not by a test.
    """
    dori = next(row for row in SEEDED if row[0] == "Dori")
    assert "Enhancement" not in dori[2]
    assert "Ascension" not in dori[2]
    bonus = classify("id", *dori)
    assert set(bonus.classes) == {MaterialClass.TALENT, MaterialClass.WEAPON_ASCENSION}


# -- the refund arithmetic ------------------------------------------------------------


def _bonus(effect: Effect, chance: float) -> CraftingBonus:
    return CraftingBonus(
        character_id="i", character_name="n", passive_name="p", effect=effect,
        chance=chance, classes=frozenset({MaterialClass.TALENT}), applicable=True,
        description="",
    )


def test_a_refund_is_worth_less_than_it_reads() -> None:
    """**"25% refund" is not a quarter of the materials back**, and reading it that way is the
    whole reason this needs a test rather than a constant.

    The description says one count of one material, and a craft eats three, so the expected
    return is `p/3` per material — 8.3%, not 25%. Compounding those refunds gives
    `3 / (3 - p)` = 1.0909.

    Simulated to confirm the closed form, not merely transcribed:
    crafting 3->1 from 3000 materials with a 25% refund yields ~1090 products against the
    formula's 1090.91, the gap being materials left over too few to craft.

    https://genshin-impact.fandom.com/wiki/Crafting#Efficiency
    """
    assert craft_multiplier([_bonus(Effect.REFUND, 0.25)], MaterialClass.TALENT) == pytest.approx(
        3 / 2.75,
    )


def test_a_ten_percent_double_beats_a_twenty_five_percent_refund() -> None:
    """The source states it outright, and it reads backwards until the arithmetic is done —
    which is exactly why the best-bonus rule must compare the *values* and not the chances.

    Picking by `chance` would take the 25% and quietly cost the user materials.
    """
    double = craft_multiplier([_bonus(Effect.DOUBLE, 0.10)], MaterialClass.TALENT)
    refund = craft_multiplier([_bonus(Effect.REFUND, 0.25)], MaterialClass.TALENT)

    assert double > refund
    assert craft_multiplier(
        [_bonus(Effect.DOUBLE, 0.10), _bonus(Effect.REFUND, 0.25)], MaterialClass.TALENT,
    ) == double


def test_a_bonus_for_another_class_does_nothing() -> None:
    """Mona refunds weapon ascension materials and must not cheapen a talent book."""
    weapon_only = CraftingBonus(
        character_id="i", character_name="Mona", passive_name="p", effect=Effect.REFUND,
        chance=0.25, classes=frozenset({MaterialClass.WEAPON_ASCENSION}), applicable=True,
        description="",
    )

    assert craft_multiplier([weapon_only], MaterialClass.TALENT) == 1.0


def test_every_recipe_a_bonus_can_touch_is_three_to_one() -> None:
    """**The constant `INPUTS_PER_CRAFT` is only safe while this holds.**

    The refund arithmetic divides by three because a craft consumes three. Measured over
    `CombineExcelConfigData`: 245 of the 249 recipes the planner can walk are 3-in-1-out, and
    the four that are not are Fabric and the three Dyes — furnishing recipes that no crafting
    passive names and no plan bills.

    Asserted against the talent-book and weapon-material families specifically, so a patch that
    adds one on a different ratio fails here rather than silently mispricing every refund.
    """
    eco = economy()
    off_ratio = [
        (material_id, step)
        for material_id, step in eco._combine.items()
        if step.input_count != INPUTS_PER_CRAFT
        and eco.source_of(material_id) is MaterialSource.DOMAIN
    ]

    assert off_ratio == []
