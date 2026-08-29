"""The display forms the catalogue publishes, and why they are the API's job.

The catalogue pages were printing the source's internal spellings on screen — `WEAPON_POLE`,
`four_star`, `FIGHT_PROP_CHARGE_EFFICIENCY` — not by choice, but because nothing readable was
published and a page had nothing else to render.

**Each of these is a rule that already exists** (`WeaponType.display`, `Rarity.stars`,
`StatType.display`). Publishing them keeps the client from carrying a second copy: the
characters page had already grown `rarity === 'five_star' ? 5 : 4`, which calls a three-star
— or a null — a four-star, silently.
"""

from __future__ import annotations

import pytest

from app.schemas.catalogue import CharacterSummary, WeaponSummary


def _weapon(**over: object) -> WeaponSummary:
    return WeaponSummary.model_validate({
        "id": "w", "nanoka_id": 1, "name": "Favonius Sword",
        "weapon_type": "WEAPON_SWORD_ONE_HAND", "rarity": "four_star", **over,
    })


def _character(**over: object) -> CharacterSummary:
    return CharacterSummary.model_validate({
        "id": "c", "nanoka_id": "10000002", "name": "Kamisato Ayaka",
        "weapon_type": "WEAPON_SWORD_ONE_HAND", "rarity": "five_star", **over,
    })


@pytest.mark.parametrize(
    ("stat", "expected"),
    [
        ("FIGHT_PROP_CRITICAL_HURT", "CRIT DMG"),
        ("FIGHT_PROP_ATTACK_PERCENT", "ATK%"),
        ("FIGHT_PROP_ELEMENT_MASTERY", "Elemental Mastery"),
        ("FIGHT_PROP_CHARGE_EFFICIENCY", "Energy Recharge"),
    ],
)
def test_a_weapon_publishes_its_substat_in_words(stat: str, expected: str) -> None:
    assert _weapon(sub_stat_type=stat).sub_stat_display == expected


def test_a_weapon_with_no_substat_says_nothing_rather_than_guessing() -> None:
    """18 weapons have a null `sub_stat_type` — no substat, not an unknown one."""
    assert _weapon(sub_stat_type=None).sub_stat_display is None


def test_an_unrecognised_substat_is_shown_verbatim() -> None:
    """A visible oddity is findable; a blank is a weapon that looks substat-less."""
    assert _weapon(sub_stat_type="FIGHT_PROP_FUTURE").sub_stat_display == "FIGHT_PROP_FUTURE"


@pytest.mark.parametrize(
    ("rarity", "stars"),
    [("five_star", 5), ("four_star", 4), ("three_star", 3), ("one_star", 1)],
)
def test_rarity_is_published_as_a_number_for_both_catalogues(rarity: str, stars: int) -> None:
    """The page drew `four_star` because there was no number to draw.

    Both summaries, because the characters page had already written its own version — and
    that version answered `4` for every rarity that was not five, including `three_star`.
    """
    assert _weapon(rarity=rarity).stars == stars
    assert _character(rarity=rarity).stars == stars


def test_the_weapon_class_is_published_in_words() -> None:
    assert _weapon(weapon_type="WEAPON_POLE").weapon_type_display == "Polearm"
    assert _character(weapon_type="WEAPON_CATALYST").weapon_type_display == "Catalyst"
