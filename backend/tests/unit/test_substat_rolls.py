"""Substat decomposition: what can be established, and what is refused.

The approach is Genshin Optimizer's (MIT, `libs/gi/util/src/artifact/artifact.ts:getSubstatRolls`)
— **match on the value as the export displays it, not within a float tolerance** — reimplemented
here against this repo's own committed tables. The tests that matter are the refusals: a roll
count is the number people judge an artifact by, and a confident wrong one is worse than none.
"""

from __future__ import annotations

import pytest

from app.services.substat_rolls import analyse

#: 5★ CRIT DMG: 5.44 / 6.22 / 6.99 / 7.77 percent.
CRIT_DMG_MAX = 0.0777


def test_a_unique_decomposition_yields_every_roll_value() -> None:
    # 7.4% CRIT rate is 3.50 + 3.89 and nothing else, so both rolls are known exactly.
    found = analyse(stars=5, stat="FIGHT_PROP_CRITICAL", value=0.074)

    assert found.rolls == 2
    assert found.roll_tiers == (2, 3)
    assert found.roll_values is not None
    assert sum(found.roll_values) == pytest.approx(0.0739, abs=1e-4)


def test_roll_value_is_the_total_against_one_best_roll() -> None:
    """The number GO's card shows as `320%`, and the reason it is computed separately.

    It needs no decomposition, so it survives every ambiguity below and is available on
    substats where the roll count is not.
    """
    found = analyse(stars=5, stat="FIGHT_PROP_CRITICAL_HURT", value=0.249)

    assert found.roll_value == pytest.approx(0.249 / CRIT_DMG_MAX, rel=1e-6)
    assert round(found.roll_value * 100) == 320


def test_a_count_beyond_the_reachable_maximum_is_excluded() -> None:
    """24.9% CRIT DMG cannot be three rolls: three of the best tier is 23.31%.

    Worth pinning because it is the case where eyeballing a reference screenshot and the
    arithmetic disagree, and the arithmetic is right.
    """
    assert analyse(stars=5, stat="FIGHT_PROP_CRITICAL_HURT", value=0.249).rolls == 4


def test_the_count_survives_when_only_the_individual_values_are_ambiguous() -> None:
    """Several decompositions that agree on how many rolls: report the count, not the values.

    11.0% Energy Recharge at 5★ is two rolls whichever way it is split (4.53+6.48, 5.18+5.83,
    …), so the count is established even though no single pair is. **10.2% of a real
    inventory lands here**, and refusing the count too would throw away a well-founded number
    to avoid publishing an unfounded one.
    """
    found = analyse(stars=5, stat="FIGHT_PROP_CHARGE_EFFICIENCY", value=0.11)

    assert found.rolls == 2
    assert found.roll_values is None
    assert found.roll_tiers is None


def test_a_count_ambiguous_total_reports_nothing_but_the_ratio() -> None:
    """16.9% ATK% is three rolls or four, and the count itself is not established.

    Distinct from the case above, and the reason `rolls` is nullable at all.
    """
    found = analyse(stars=5, stat="FIGHT_PROP_ATTACK_PERCENT", value=0.169)

    assert found.rolls is None
    assert found.roll_tiers is None
    assert found.roll_value is not None


def test_unupgradable_depots_are_kept_out_of_the_ladder() -> None:
    """`depot_ranks` maps depots 961-965 to rarities 4 *and* 5, and they hold one fixed value
    per prop — the unupgradable artifacts, not rolls.

    Merging them in put `0.1943` beside 5★ CRIT DMG's real `0.0544-0.0777` ladder, which made
    `roll_value` divide by the wrong maximum (24.9% scored 1.28 instead of 3.20) and invented
    decompositions that made sound substats look ambiguous. Asserting the maximum is the
    cheapest way to catch that coming back.
    """
    found = analyse(stars=5, stat="FIGHT_PROP_CRITICAL_HURT", value=CRIT_DMG_MAX)

    assert found.rolls == 1
    assert found.roll_value == pytest.approx(1.0)


def test_a_value_no_combination_reaches_reports_no_rolls_but_keeps_roll_value() -> None:
    # Far beyond six best-tier rolls. Nothing to decompose, but the ratio is still a fact.
    found = analyse(stars=5, stat="FIGHT_PROP_CRITICAL_HURT", value=5.0)

    assert found.rolls is None
    assert found.roll_values is None
    assert found.roll_value is not None


def test_an_unknown_stat_is_refused_rather_than_defaulted() -> None:
    found = analyse(stars=5, stat="FIGHT_PROP_NOT_A_STAT", value=1.0)

    assert found.rolls is None
    assert found.roll_value is None


def test_an_unknown_rarity_is_refused() -> None:
    assert analyse(stars=99, stat="FIGHT_PROP_CRITICAL", value=0.039).rolls is None


@pytest.mark.parametrize("value", [0.0, -0.05])
def test_a_non_positive_value_is_refused(value: float) -> None:
    assert analyse(stars=5, stat="FIGHT_PROP_CRITICAL", value=value).rolls is None


def test_a_flat_stat_rounds_whole_and_a_percentage_to_one_decimal() -> None:
    """One display rule cannot serve both, and the rounding *is* the match.

    EM is written whole (`42`) and CRIT rate as a percentage to one decimal (`3.9`). Rounding
    EM to one decimal-percent, or CRIT rate to a whole number, makes every comparison fail.
    """
    assert analyse(stars=5, stat="FIGHT_PROP_ELEMENT_MASTERY", value=42.0).rolls is not None
    assert analyse(stars=5, stat="FIGHT_PROP_CRITICAL", value=0.039).rolls == 1


def test_roll_tiers_index_the_ladder_lowest_first() -> None:
    """`0` is the worst roll and `3` the best — the card colours by this, so the order is API."""
    found = analyse(stars=5, stat="FIGHT_PROP_CRITICAL_HURT", value=CRIT_DMG_MAX)

    assert found.roll_tiers == (3,)
