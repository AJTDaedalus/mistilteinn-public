"""A.3 — how a stat reads, and whether its value is a fraction.

`StatType`'s values are the source's `FIGHT_PROP_*` keys, so nothing about them is a label.
Worse, the stored numbers are **units-dependent**: `artifact_main_stat_value(5, 20, …)` gives
`4780.0` for flat HP and `0.466` for HP%. A page that rendered both the same way would print
"0.466 HP%" or "478000% HP", and neither looks obviously wrong at a glance.

Both facts live on the enum and are published once (`/artifacts/options`) rather than being
restated per row or reimplemented per client.
"""

from __future__ import annotations

import pytest

from app.models.enums import StatType


def test_every_stat_has_a_label() -> None:
    """Derived, not a 26-entry table.

    A hand-written map is a second list to keep in step: adding a member later gets a
    `KeyError` at best and a blank label at worst. Deriving means a new member reads sensibly
    the day it arrives.
    """
    for stat in StatType:
        label = stat.display
        assert label, f"{stat.name} has no label"
        assert "_" not in label, f"{stat.name} reads as {label!r}"
        assert label == label.strip()


@pytest.mark.parametrize(("stat", "expected"), [
    (StatType.HP_FLAT, "HP"),
    (StatType.HP_PCT, "HP%"),
    (StatType.ATK_PCT, "ATK%"),
    (StatType.DEF_FLAT, "DEF"),
    (StatType.CRIT_RATE, "CRIT Rate"),
    (StatType.CRIT_DMG, "CRIT DMG"),
    (StatType.ELEMENTAL_MASTERY, "Elemental Mastery"),
    (StatType.ENERGY_RECHARGE, "Energy Recharge"),
    (StatType.CRYO_DMG_BONUS, "Cryo DMG Bonus"),
    (StatType.PHYSICAL_DMG_BONUS, "Physical DMG Bonus"),
    (StatType.BASE_ATK, "Base ATK"),
])
def test_the_labels_read_the_way_the_game_writes_them(stat: StatType, expected: str) -> None:
    """The acronyms are the point. `Hp_Pct` and `Crit Dmg` are what a naive title-case gives,
    and neither is what a player would recognise."""
    assert stat.display == expected


def test_percentage_stats_are_the_ones_stored_as_fractions() -> None:
    """`0.466` is 46.6% HP; `4780` is 4780 HP. The same float renders two different ways and
    only this flag says which."""
    assert StatType.HP_PCT.is_percentage
    assert StatType.CRIT_DMG.is_percentage
    assert StatType.ENERGY_RECHARGE.is_percentage
    assert StatType.CRYO_DMG_BONUS.is_percentage
    assert StatType.SHIELD_STRENGTH.is_percentage

    assert not StatType.HP_FLAT.is_percentage
    assert not StatType.ATK_FLAT.is_percentage
    assert not StatType.DEF_FLAT.is_percentage
    assert not StatType.ELEMENTAL_MASTERY.is_percentage
    assert not StatType.BASE_HP.is_percentage


def test_the_flag_matches_the_committed_value_table() -> None:
    """Checked against the data rather than asserted.

    A stat whose 5-star +20 main value is below 1 is a fraction; one in the thousands is not.
    That is a crude test and it is the right one: it fails if the flag and the numbers ever
    disagree, which is the only way this can actually hurt anyone.
    """
    from app.data.snapshot import SnapshotUnavailableError, artifact_main_stat_value

    checked = 0
    for stat in StatType:
        try:
            value = artifact_main_stat_value(5, 20, stat.value)
        except (SnapshotUnavailableError, KeyError):
            continue  # not a main stat any artifact can roll
        checked += 1
        if stat.is_percentage:
            assert 0 < value < 5, f"{stat.name} is flagged a fraction but is {value}"
        else:
            assert value >= 1, f"{stat.name} is flagged absolute but is {value}"

    assert checked >= 8, "the table resolved too few stats for this to prove anything"
