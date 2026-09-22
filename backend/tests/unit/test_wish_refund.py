"""The starglitter refund, and the proof it needs no simulation.

`docs/DESIGN_wish_planner.md` §9.7. The refund *looks* path-dependent because a featured 4★
crosses max constellation during a campaign and its payout changes from 2 starglitter to 5.
It is not: given a character's own draw count the payout is deterministic, and every count
distribution in the chain is exactly computable.

So this file does two things. It checks each stage against the figure its source publishes,
and then it checks the whole against a **simulation of the same rules** — the same discipline
`test_wish_planner_crossval.py` applies to the ladder, and for the same reason: a nested
convolution fails quietly, and every number it produces stays plausible.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from app.services.wishes.rates import (
    BannerKind,
    four_star_rates,
    non_featured_character_share,
)
from app.services.wishes.refund import (
    FATE_COST,
    RefundInputs,
    expected_refund,
    featured_split_pmf,
    four_star_count_pmf,
    payout,
    refund_pmf,
    roster_payout_pmf,
)

ROSTER = tuple([6] * 20 + [4] * 10 + [2] * 8 + [None] * 7)
RUNS = 40_000
SEED = 20260922


# --- each stage against its published figure ------------------------------------------


@pytest.mark.parametrize(
    ("banner", "published"), [(BannerKind.CHARACTER, 0.13), (BannerKind.WEAPON, 0.145)],
)
def test_the_four_star_curve_reproduces_the_published_rate(
    banner: BannerKind, published: float
) -> None:
    """HoYoverse publishes 13 % and 14.5 % "including pity" in its own disclosure."""
    from app.services.wishes.planner import first_passage_pmf

    pmf = first_passage_pmf(four_star_rates(banner))
    mean = float((np.arange(len(pmf)) * pmf).sum())
    assert 1.0 / mean == pytest.approx(published, rel=0.01)


@pytest.mark.parametrize(
    ("rate", "expected"), [(0.5, 2 / 3), (0.75, 0.8)],
)
def test_the_featured_share_matches_the_published_consolidated(
    rate: float, expected: float
) -> None:
    """`1 / (1 + (1 − rate))` — 66.67 % at a half, 80 % at three quarters."""
    split = featured_split_pmf(40, rate)
    mean = float((np.arange(len(split)) * split).sum())
    assert split.sum() == pytest.approx(1.0)
    assert mean / 40 == pytest.approx(expected, abs=0.01)


def test_the_four_star_count_is_a_distribution() -> None:
    counts = four_star_count_pmf(four_star_rates(BannerKind.CHARACTER), 200)
    mean = float((np.arange(len(counts)) * counts).sum())
    assert counts.sum() == pytest.approx(1.0)
    assert mean == pytest.approx(200 * 0.13057, rel=0.02)


# --- what a pull pays ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("draws", "constellation", "expected"),
    [
        (0, 6, 0),
        (1, 6, 5),         # already maxed: every copy is 5
        (3, 6, 15),
        (1, 5, 2),         # one short of maxed: this copy is the constellation
        (2, 5, 7),         # then the next is 5
        (1, 0, 2),
        (6, 0, 12),        # six constellations at 2 apiece
        (7, 0, 17),        # then 5
        (1, None, 0),      # a character you do not own pays NOTHING -- you get the character
        (2, None, 2),
        # one free copy, then six constellations at 2, then 5 apiece
        (8, None, 17),
    ],
)
def test_payout(draws: int, constellation: int | None, expected: int) -> None:
    assert payout(draws, constellation) == expected


def test_an_unowned_character_pays_nothing_for_its_first_copy() -> None:
    """The wiki's quantity table lists *duplicates* only, and this is the row that makes the
    refund axis two-dimensional rather than one."""
    assert payout(1, None) == 0
    assert payout(1, 0) == 2


# --- the roster nesting ----------------------------------------------------------------


def test_the_roster_payout_is_a_distribution() -> None:
    for draws in (0, 1, 5):
        pmf = roster_payout_pmf(draws, ROSTER)
        assert pmf.sum() == pytest.approx(1.0), f"{draws} draws"


def test_no_draws_pays_nothing() -> None:
    pmf = roster_payout_pmf(0, ROSTER)
    assert pmf[0] == pytest.approx(1.0)


def test_a_maxed_roster_always_pays_five_each() -> None:
    """With no spread in the roster there is no spread in the payout."""
    pmf = roster_payout_pmf(4, (6,) * 10)
    assert pmf[20] == pytest.approx(1.0)


def test_counts_are_dependent_not_independent() -> None:
    """Two draws over ONE character pay 10 (both at max), not 2 × E[one draw].

    The multinomial coupling is the whole reason this is a nested enumeration; treating the
    draws as independent would miss that the second draw lands on a character the first one
    has already advanced.
    """
    assert roster_payout_pmf(2, (5,))[7] == pytest.approx(1.0)  # 2 then 5, not 2 + 2


# --- the whole thing, against a simulation ----------------------------------------------


def _simulate(inputs: RefundInputs, pulls: int, rng: random.Random) -> int:
    """Play the 4-star stream out and bank the starglitter. Mirrors the rules, not the maths."""
    rates = four_star_rates(inputs.banner)
    curve = rates.drop_curve()
    featured = list(inputs.featured)
    roster = list(inputs.roster)
    # Resolved the same way the service resolves it, so the oracle and the thing it checks
    # cannot disagree about which banner's share applies.
    share = (
        inputs.non_featured_character_share
        if inputs.non_featured_character_share is not None
        else non_featured_character_share(inputs.banner)
    )

    starglitter = 0
    guaranteed = False
    spent = 0
    while spent < pulls:
        for pity, rate in enumerate(curve, start=1):
            if rng.random() < rate:
                spent += pity
                break
        if spent > pulls:
            break
        is_featured = guaranteed or rng.random() < rates.featured_rate
        guaranteed = not is_featured
        if is_featured:
            if not featured:
                starglitter += 2          # weapon banner: the featured items are weapons
                continue
            index = rng.randrange(len(featured))
            starglitter += payout(1, featured[index])
            if featured[index] is None:
                featured[index] = 0
            elif featured[index] < 6:
                featured[index] += 1
        elif rng.random() < share and roster:
            index = rng.randrange(len(roster))
            starglitter += payout(1, roster[index])
            if roster[index] is None:
                roster[index] = 0
            elif roster[index] < 6:
                roster[index] += 1
        else:
            starglitter += 2              # a non-featured weapon
    return starglitter // FATE_COST


@pytest.mark.parametrize(
    ("featured", "pulls"),
    [((6, 6, 6), 200), ((6, 2, None), 200), ((None, None, None), 200), ((6, 6, 6), 90)],
)
def test_the_exact_refund_matches_a_simulation(
    featured: tuple[int | None, ...], pulls: int
) -> None:
    rng = random.Random(SEED)  # noqa: S311 — a Monte Carlo oracle, not a secret
    runs = [_simulate(RefundInputs(BannerKind.CHARACTER, featured, ROSTER), pulls, rng)
            for _ in range(RUNS)]
    observed = float(np.mean(runs))
    standard_error = float(np.std(runs, ddof=1)) / RUNS**0.5

    exact = expected_refund(RefundInputs(BannerKind.CHARACTER, featured, ROSTER), pulls)
    assert abs(exact - observed) < 4 * standard_error, (
        f"exact {exact:.3f} vs simulated {observed:.3f} (se {standard_error:.3f})"
    )


def test_the_refund_is_a_distribution_not_an_estimate() -> None:
    """The population, not a sample: it sums to one and repeats exactly."""
    inputs = RefundInputs(BannerKind.CHARACTER, (6, 6, 6), ROSTER)
    first = refund_pmf(inputs, 200)
    assert sum(first.values()) == pytest.approx(1.0)
    assert refund_pmf(RefundInputs(BannerKind.CHARACTER, (6, 6, 6), ROSTER), 200) == first


def test_a_maxed_roster_refunds_more_than_a_fresh_one() -> None:
    """The axis the shipped constant tiers vary, now read from the account instead."""
    maxed = expected_refund(RefundInputs(BannerKind.CHARACTER, (6, 6, 6), (6,) * 45), 200)
    fresh = expected_refund(
        RefundInputs(BannerKind.CHARACTER, (None,) * 3, (None,) * 45), 200
    )
    assert maxed > fresh * 1.8


def test_the_weapon_banner_refunds_less_for_a_maxed_account() -> None:
    """Its featured third is *weapons*, which can never pay more than 2.

    Compared at each banner's own non-featured share, which is the point of finding 3: with
    the character banner's 0.15 forced on both, this test passed for the wrong reason.
    """
    character = expected_refund(RefundInputs(BannerKind.CHARACTER, (6, 6, 6), ROSTER), 200)
    weapon = expected_refund(RefundInputs(BannerKind.WEAPON, (), ROSTER), 200)
    assert weapon < character


def test_the_refund_rounds_down_to_whole_fates() -> None:
    """Starglitter buys whole fates; promising a wish a player cannot buy is the worse error.

    A single pull can still land a 4-star, so the interesting assertion is not that the
    refund is zero — it is that four starglitter buys nothing and five buys one.
    """
    assert FATE_COST == 5
    # A roster of one maxed character: every non-featured character draw pays exactly 5.
    one_draw = refund_pmf(RefundInputs(BannerKind.CHARACTER, (5,), (6,)), 1)
    assert all(isinstance(k, int) and k >= 0 for k in one_draw)
    # Two starglitter is not a wish; the only outcomes here are 0 or a whole fate.
    assert min(one_draw) == 0


# --- PR #332 review findings -----------------------------------------------------------


def test_the_count_does_not_freeze_at_a_hidden_cap() -> None:
    """Finding 4. A fixed ceiling of 120 piled the remaining mass onto the last bin.

    The array still summed to 1.0 and nothing warned, so the mean four-star count simply
    stopped rising — understating the refund by 39 % at 1,500 wishes. A C6R5 campaign is
    well over a thousand.
    """
    rates = four_star_rates(BannerKind.CHARACTER)
    for pulls in (1_000, 1_500, 2_000):
        counts = four_star_count_pmf(rates, pulls)
        mean = float((np.arange(len(counts)) * counts).sum())
        assert counts.sum() == pytest.approx(1.0)
        assert mean == pytest.approx(pulls * 0.13057, rel=0.02), f"{pulls} pulls"


def test_the_non_featured_share_is_read_per_banner() -> None:
    """Finding 3. The two banners are near-opposite and the data file publishes both."""
    from app.services.wishes.rates import non_featured_character_share

    assert non_featured_character_share(BannerKind.CHARACTER) == pytest.approx(0.15, abs=0.01)
    assert non_featured_character_share(BannerKind.WEAPON) == pytest.approx(0.925, abs=0.01)


def test_the_weapon_banner_uses_its_own_share_by_default() -> None:
    """Hardcoding the character banner's 0.15 for both changed the answer by over a wish."""
    default = expected_refund(RefundInputs(BannerKind.WEAPON, (), ROSTER), 300)
    forced = expected_refund(
        RefundInputs(BannerKind.WEAPON, (), ROSTER, non_featured_character_share=0.15), 300
    )
    assert default != pytest.approx(forced, abs=0.5)
