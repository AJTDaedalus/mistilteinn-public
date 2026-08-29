"""Substat decomposition: what can be established, and what is refused.

The approach is Genshin Optimizer's (MIT, `libs/gi/util/src/artifact/artifact.ts:getSubstatRolls`)
— **match on the value as the export displays it, not within a float tolerance** — reimplemented
here against this repo's own committed tables. The tests that matter are the refusals: a roll
count is the number people judge an artifact by, and a confident wrong one is worse than none.
"""

from __future__ import annotations

import pytest

from app.services.substat_rolls import _budget, analyse, resolve_artifact

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


# ── the artifact-level solve ─────────────────────────────────────────────────
#
# **These were missing when `resolve_artifact` shipped**, and the review found three bugs in
# it that a single table-driven budget test would have caught. That is the second time in two
# PRs that new logic arrived with tests pointed somewhere else.


@pytest.mark.parametrize(
    ("stars", "level", "expected"),
    [
        (5, 20, {8, 9}),   # 3 or 4 initial + 5 upgrades
        (5, 8, {5, 6}),    # only two upgrades have happened
        (4, 16, {6, 7}),   # 2 or 3 initial + 4 upgrades
        (3, 12, {4, 5}),   # 1 or 2 initial + 3 upgrades
        (4, 0, {2, 3}),    # unupgraded
    ],
)
def test_the_budget_is_rarity_derived_not_substat_derived(
    stars: int, level: int, expected: set[int],
) -> None:
    """**The bug this is named for.** The first version inferred the initial substat count
    from how many the piece has *now*, minus one — right only at 5-star, where four-now
    equals the high bound by coincidence. A 4-star drops with two or three lines, so its
    `+16` budget was computed as `{7, 8}` against a truth of `{6, 7}`: the real answer
    excluded half the time, and a total the rarity cannot reach admitted.

    The bounds are Genshin Optimizer's `artSubstatRollData` (MIT), used rather than derived —
    1-star and 2-star do not follow the pattern at all.
    """
    assert _budget(stars=stars, level=level) == expected


def test_an_unknown_rarity_has_no_budget_rather_than_a_guessed_one() -> None:
    assert _budget(stars=99, level=20) == set()


def test_the_budget_resolves_lines_the_value_alone_cannot() -> None:
    """The reported case: a +20 5-star flower whose CRIT lines had no bars.

    Alone, 27.2% CRIT DMG is four rolls or five and 10.9% CRIT rate is three or four. Only
    one combination of the four lines sums to a legal total, which settles both.
    """
    found = resolve_artifact(stars=5, level=20, substats=[
        ("FIGHT_PROP_DEFENSE", 16.0),
        ("FIGHT_PROP_CHARGE_EFFICIENCY", 0.065),
        ("FIGHT_PROP_CRITICAL_HURT", 0.272),
        ("FIGHT_PROP_CRITICAL", 0.109),
    ])

    assert [f.rolls for f in found] == [1, 1, 4, 3]
    assert sum(f.rolls for f in found) in _budget(stars=5, level=20)


def test_a_line_settled_on_its_own_is_never_marked_estimated() -> None:
    """The solve may guess elsewhere on the piece; that cannot unsettle a line that was sure."""
    found = resolve_artifact(stars=5, level=20, substats=[
        ("FIGHT_PROP_DEFENSE", 16.0),
        ("FIGHT_PROP_CHARGE_EFFICIENCY", 0.065),
        ("FIGHT_PROP_CRITICAL_HURT", 0.272),
        ("FIGHT_PROP_CRITICAL", 0.109),
    ])

    assert found[0].estimated is False
    assert found[0].roll_tiers is not None


def test_an_estimated_count_never_carries_per_roll_tiers() -> None:
    """A guessed count can still have exactly one decomposition. Publishing its tiers painted
    bars *as fact* on a number nothing established — `roll_tiers` promises otherwise.
    """
    for f in resolve_artifact(stars=5, level=20, substats=[
        ("FIGHT_PROP_ATTACK_PERCENT", 0.169),
        ("FIGHT_PROP_CRITICAL", 0.109),
        ("FIGHT_PROP_CRITICAL_HURT", 0.272),
        ("FIGHT_PROP_HP_PERCENT", 0.099),
    ]):
        if f.estimated:
            assert f.roll_tiers is None, "coloured a guess"


def test_a_piece_whose_lines_do_not_decompose_is_left_alone() -> None:
    """No budget arithmetic can rescue a line the table cannot read; it must not invent one."""
    found = resolve_artifact(stars=5, level=20, substats=[
        ("FIGHT_PROP_NOT_A_STAT", 1.0),
        ("FIGHT_PROP_CRITICAL", 0.109),
    ])

    assert found[0].rolls is None


def test_roll_value_survives_a_line_with_no_count() -> None:
    """`roll_value` is value over the best single roll and needs no decomposition, so it is
    the number that stays available when the count is not."""
    found = resolve_artifact(stars=5, level=20, substats=[("FIGHT_PROP_CRITICAL_HURT", 5.0)])

    assert found[0].rolls is None
    assert found[0].roll_value is not None
