"""Substat decomposition: what can be established, and what is refused.

The approach is Genshin Optimizer's (MIT, `libs/gi/util/src/artifact/artifact.ts:getSubstatRolls`)
— **match on the value as the export displays it, not within a float tolerance** — reimplemented
here against this repo's own committed tables. The tests that matter are the refusals: a roll
count is the number people judge an artifact by, and a confident wrong one is worse than none.
"""

from __future__ import annotations

from itertools import combinations_with_replacement

import pytest

from app.services.substat_rolls import (
    _budget,
    _denoise,
    _displayed,
    _max_rolls,
    _tiers_for,
    analyse,
    resolve_artifact,
)

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
    """Several decompositions that agree on how many rolls: one reading, flagged as such.

    11.0% Energy Recharge at 5★ is two rolls whichever way it is split (4.53+6.48, 5.18+5.83,
    …), so the count is established even though no single pair is. **10.2% of a real
    inventory lands here.**

    This used to publish no tiers at all. Genshin Optimizer takes the first fitting pair and
    colours the bars, and that is the better answer: the readings differ by a tier on one
    roll, while a grey bar says "this line never rolled". `tiers_exact` keeps the caveat that
    GO drops — `roll_values` stays `None`, because a float claims more than a bar does.
    """
    found = analyse(stars=5, stat="FIGHT_PROP_CHARGE_EFFICIENCY", value=0.11)

    assert found.rolls == 2
    assert found.roll_values is None
    assert found.roll_tiers is not None
    assert len(found.roll_tiers) == 2
    assert found.tiers_exact is False


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
    ("stars", "level", "shown", "expected"),
    [
        (5, 20, 4, {8, 9}),   # 3 or 4 initial + 5 upgrades
        (5, 8, 4, {5, 6}),    # only two upgrades have happened
        (4, 16, 3, {6, 7}),   # 2 or 3 initial + 4 upgrades
        (3, 12, 2, {4, 5}),   # 1 or 2 initial + 3 upgrades
    ],
)
def test_the_bounds_come_from_the_rarity_not_from_the_line_count(
    stars: int, level: int, shown: int, expected: set[int],
) -> None:
    """**The bug this is named for, and it must stay fixed.** The first version inferred the
    initial substat count from how many the piece has *now, minus one* — right only at 5-star,
    where four-now equals the high bound by coincidence. A 4-star drops with two or three
    lines, so its `+16` budget came out `{7, 8}` against a truth of `{6, 7}`: the real answer
    excluded half the time, and a total the rarity cannot reach admitted.

    The line count is now an input again, but as a **constraint on the initial count**, never
    as a substitute for the rarity bounds — see the test below. Every case here is unchanged.

    The bounds are Genshin Optimizer's `artSubstatRollData` (MIT), used rather than derived —
    1-star and 2-star do not follow the pattern at all.
    """
    assert _budget(stars=stars, level=level, shown=shown) == expected


@pytest.mark.parametrize(
    ("stars", "shown", "expected"),
    [(4, 2, {2}), (4, 3, {3}), (5, 3, {3}), (5, 4, {4})],
)
def test_an_unupgraded_piece_knows_exactly_how_many_rolls_it_has(
    stars: int, shown: int, expected: set[int],
) -> None:
    """**Where the grey bars came from.**

    A piece that started with the low count gains its extra line on the *first* upgrade — so
    one still showing the low count has had none, and one showing the high count at `+0`
    started there. Either way the total is exactly the number of lines on the card.

    Without this, a `+0` five-star showing three substats got `{3, 4}`, and a four-roll
    assignment over three lines — impossible when every line holds exactly one roll — stayed a
    live solution. The piece was reported undetermined and the card drew grey bars with no
    denominator. **230 of 266 undetermined pieces in a real 2,370-piece inventory were exactly
    that shape.**
    """
    assert _budget(stars=stars, level=0, shown=shown) == expected


def test_a_line_count_the_rarity_cannot_produce_widens_rather_than_empties() -> None:
    """An empty budget refuses every assignment and reports the whole piece unknown, which is
    a worse answer than a wide one. A hand-written row should degrade, not vanish."""
    assert _budget(stars=5, level=20, shown=2) == {8, 9}


def test_an_unknown_rarity_has_no_budget_rather_than_a_guessed_one() -> None:
    assert _budget(stars=99, level=20, shown=4) == set()


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
    assert sum(f.rolls for f in found) in _budget(stars=5, level=20, shown=len(found))


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


def test_an_estimated_count_carries_a_reading_but_never_calls_it_exact() -> None:
    """The reverse of this module's earlier rule, and the reason the bars were mostly grey.

    Withholding tiers from an estimated count stripped them from lines that decomposed
    perfectly well, because some *other* line on the piece had needed the budget solve. On
    screen that is indistinguishable from "no rolls here". The count is still a guess, so the
    reading is published with `tiers_exact` False rather than presented as fact.
    """
    # A real +20 piece from a 2,370-artifact export. **The values are load-bearing**: the
    # four this test used to carry produced no estimate at all, so its `if f.estimated:` body
    # never ran and it passed while checking nothing.
    found = resolve_artifact(stars=5, level=20, substats=[
        ("FIGHT_PROP_CRITICAL", 0.039),
        ("FIGHT_PROP_ATTACK_PERCENT", 0.169),
        ("FIGHT_PROP_CHARGE_EFFICIENCY", 0.11),
        ("FIGHT_PROP_ELEMENT_MASTERY", 42.0),
    ])
    estimated = [f for f in found if f.estimated]

    assert estimated, "this piece is the estimated case"
    for f in estimated:
        assert f.roll_tiers is not None, "a guessed count still shows what it read"
        assert len(f.roll_tiers) == f.rolls
        assert f.tiers_exact is False, "published a guess as fact"

    # And the point of the change: a line that decomposes on its own keeps its exact reading
    # even though the *piece* needed the budget solve elsewhere.
    assert found[0].roll_tiers == (3,)
    assert found[0].tiers_exact is True


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


# ── the displayed value, and the two roundings that hid it ───────────────────


def test_a_roll_on_a_rounding_boundary_still_matches() -> None:
    """**The grey bars.**

    A true 5-star ATK% roll of 5.25% is stored in the float32 tier table as `0.05249999836`.
    The game displays `5.3%` and an export writes `0.053`. Ours rounded the tier with Python's
    banker's `round`, got `5.2`, and reported a line that matched *no combination at all* —
    so the card drew a grey bar with no denominator.

    Both halves were needed: de-noising without half-up still gives 5.2, and half-up without
    de-noising rounds 5.2499998 down.
    """
    found = analyse(stars=5, stat="FIGHT_PROP_ATTACK_PERCENT", value=0.053)

    assert found.rolls == 1


@pytest.mark.parametrize("value", [0.041, 0.047, 0.053, 0.058])
def test_every_single_roll_an_export_can_write_is_recognised(value: float) -> None:
    """The four 5-star ATK% tiers, as an export writes them.

    Measured on a real 2,370-piece inventory: these are the four commonest values in it, and
    **two of the four never matched** before the rounding was fixed.
    """
    assert analyse(stars=5, stat="FIGHT_PROP_ATTACK_PERCENT", value=value).rolls == 1


def test_the_display_rounds_the_way_the_game_does() -> None:
    """Half-up, not banker's. `round(5.25, 1)` is `5.2` in Python and `5.3` in the game."""
    assert _displayed(0.0525, fraction=True) == 5.3
    assert _displayed(0.05249999836087227, fraction=True) == 5.3


def test_a_flat_stat_still_displays_whole() -> None:
    """Flat ATK and HP are shown as integers, and the same rounding has to apply to them."""
    assert _displayed(16.0, fraction=False) == 16
    assert _displayed(16.5, fraction=False) == 17


def test_a_four_roll_sum_on_the_boundary_matches() -> None:
    """**The one two users hit, and the reason the tier de-noise moved.**

    `6.22 + 6.22 + 6.22 + 6.99 = 25.65`, which the game displays as `25.7%` and an export
    writes as `0.257`. An ordinary four-roll CRIT DMG line.

    De-noising the *sum* to six decimal places is enough for one roll and not for four: the
    stored total is `25.6499994…`, which rounds to `25.649999` and half-ups to `25.6`. So the
    line matched nothing, and `good_import_service` refused the whole piece as a scanner
    error. Two separate users reported it — twice on one export, which is the tell that it was
    arithmetic rather than a scanner slip.
    """
    found = analyse(stars=5, stat="FIGHT_PROP_CRITICAL_HURT", value=0.257, level=20)

    assert found.rolls == 4


def test_the_neighbour_below_it_still_matches_too() -> None:
    """25.6% is `5.44 + 5.44 + 6.99 + 7.77` and was reachable before the fix.

    Pinned beside its neighbour because a de-noise that moved *every* sum up by a tenth would
    satisfy the test above and be just as wrong. The two values are adjacent and both real.
    """
    assert analyse(stars=5, stat="FIGHT_PROP_CRITICAL_HURT", value=0.256, level=20).rolls == 4


def _reachable(stars: int, stat: str, tiers: tuple[float, ...]) -> set[tuple[int, float]]:
    """Every `(count, displayed total)` these tier values can produce at this rarity."""
    fraction = tiers[-1] < 1.0
    return {
        (n, _displayed(sum(combo), fraction=fraction))
        for n in range(1, _max_rolls(stars, None) + 1)
        for combo in combinations_with_replacement(tiers, n)
    }


def test_every_sum_the_stored_tiers_reach_is_one_the_published_tiers_reach() -> None:
    """**The invariant, rather than the instance.**

    The 25.7% case was found by a user rather than by a test, and a test pinning 25.7 would
    not have found the other twenty-six values in the same state. This is the general claim:
    for every rarity, stat and legal roll count, a sum of the tiers *as stored* must display
    like a sum of the tiers *as published*.

    Published values are recovered by rounding to the number of decimals the game shows them
    to — four for a fraction, two for a flat stat — which is deliberately **not** how
    `_denoise` does it. A check that reproduces the implementation cannot disagree with it.
    """
    for stars in (1, 2, 3, 4, 5):
        for stat, tiers in _tiers_for(stars).items():
            fraction = tiers[-1] < 1.0
            published = tuple(round(v, 4 if fraction else 2) for v in tiers)

            assert _reachable(stars, stat, tiers) == _reachable(stars, stat, published), (
                f"{stars}star {stat}"
            )


def test_the_invariant_notices_a_tier_that_is_off() -> None:
    """**The planted failure.** A check that can only return one answer is not a check.

    Nudging one 5-star CRIT DMG tier by a millionth is smaller than the float32 noise the real
    table carries, and the test above must still see it — otherwise it would have passed
    against the noisy tiers that caused the bug.
    """
    tiers = _tiers_for(5)["FIGHT_PROP_CRITICAL_HURT"]
    nudged = (tiers[0], tiers[1] - 1e-6, *tiers[2:])

    assert _reachable(5, "FIGHT_PROP_CRITICAL_HURT", nudged) != _reachable(
        5, "FIGHT_PROP_CRITICAL_HURT", tiers,
    )


def test_a_tier_is_denoised_to_the_value_the_game_publishes() -> None:
    """Six significant figures, not six decimal places — the distinction is the whole fix."""
    assert _denoise(0.062199998646974564) == 0.0622
    assert _denoise(298.7500000001) == 298.75
    # Wide enough not to touch a real value: a flat HP roll has five significant figures.
    assert _denoise(0.05249999836) == 0.0525


def test_a_value_no_combination_reaches_is_still_unknown() -> None:
    """**The fix must not turn "cannot determine" into a guess.**

    One piece in the owner's 2,370 has a CRIT DMG value no combination of tiers produces at any
    legal roll count. It stays unknown, which is the honest answer — a rounding fix that
    swallowed it would be reporting a decomposition nothing supports.
    """
    found = analyse(stars=5, stat="FIGHT_PROP_CRITICAL_HURT", value=0.999)

    assert found.rolls is None
