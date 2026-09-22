"""The wish planner's exact math, and the invariants that keep it exact.

The cross-validation against gachasim's Monte Carlo lives in
`test_wish_planner_crossval.py`. This file is about the properties that must hold for the
convolution to mean anything at all.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.wishes import (
    BannerKind,
    PlanInput,
    UnreachableStateError,
    plan_wishes,
    rates_for,
)
from app.services.wishes.planner import (
    MAX_CONSTELLATION,
    MAX_REFINEMENT,
    _conditioned_on_pity,
    first_passage_pmf,
    wishes_from,
)


@pytest.mark.parametrize("banner", list(BannerKind))
def test_the_first_passage_pmf_is_a_distribution(banner: BannerKind) -> None:
    pmf = first_passage_pmf(rates_for(banner))
    assert pmf.sum() == pytest.approx(1.0)
    assert (pmf >= 0).all()


@pytest.mark.parametrize("banner", list(BannerKind))
def test_index_zero_is_impossible(banner: BannerKind) -> None:
    """Index *k* means exactly *k* wishes, so index 0 must be empty.

    This is the invariant the whole module is shaped around: a PMF whose index 0 means "one
    wish" makes `sum(k * p)` low by one **per 5-star drawn**, which is invisible on a single
    milestone and grows linearly down the ladder.
    """
    assert first_passage_pmf(rates_for(banner))[0] == 0.0


def test_the_mean_cycle_matches_the_published_consolidated_rate() -> None:
    """HoYoverse publishes 1.6% / 1.85% "including pity"; the fitted curves must reproduce it.

    This is the constraint the soft-pity ramp was fitted to, so it is the one thing about
    these curves that is pinned rather than estimated.
    """
    for banner, published in ((BannerKind.CHARACTER, 0.016), (BannerKind.WEAPON, 0.0185)):
        pmf = first_passage_pmf(rates_for(banner))
        mean_cycle = float((np.arange(len(pmf)) * pmf).sum())
        assert 1.0 / mean_cycle == pytest.approx(published, rel=0.02)


def test_conditioning_on_pity_shortens_the_wait() -> None:
    pmf = first_passage_pmf(rates_for(BannerKind.CHARACTER))
    fresh_mean = float((np.arange(len(pmf)) * pmf).sum())
    deep = _conditioned_on_pity(pmf, 80)
    deep_mean = float((np.arange(len(deep)) * deep).sum())
    assert deep.sum() == pytest.approx(1.0)
    assert deep[0] == 0.0
    assert deep_mean < fresh_mean


def test_a_5_star_always_arrives_by_hard_pity() -> None:
    rates = rates_for(BannerKind.CHARACTER)
    pmf = first_passage_pmf(rates)
    assert len(pmf) == rates.hard_pity + 1
    assert pmf[rates.hard_pity :].sum() > 0.0


@pytest.mark.parametrize(
    ("banner", "expected"),
    [(BannerKind.CHARACTER, MAX_CONSTELLATION + 1), (BannerKind.WEAPON, MAX_REFINEMENT)],
)
def test_the_ladder_runs_to_the_cap(banner: BannerKind, expected: int) -> None:
    plan = plan_wishes(PlanInput(banner), budget=1_000)
    assert len(plan.milestones) == expected
    assert [m.copies for m in plan.milestones] == list(range(1, expected + 1))


def test_labels_read_the_way_a_player_says_them() -> None:
    character = [m.label for m in plan_wishes(PlanInput(BannerKind.CHARACTER), 0).milestones]
    weapon = [m.label for m in plan_wishes(PlanInput(BannerKind.WEAPON), 0).milestones]
    assert character == ["C0", "C1", "C2", "C3", "C4", "C5", "C6"]
    assert weapon == ["R1", "R2", "R3", "R4", "R5"]


def test_owning_copies_shortens_the_ladder() -> None:
    plan = plan_wishes(PlanInput(BannerKind.CHARACTER, owned_copies=4), budget=500)
    assert [m.label for m in plan.milestones] == ["C4", "C5", "C6"]


def test_success_chance_is_monotonic_down_the_ladder() -> None:
    plan = plan_wishes(PlanInput(BannerKind.CHARACTER), budget=400)
    chances = [m.success_chance for m in plan.milestones]
    averages = [m.average_wishes for m in plan.milestones]
    assert chances == sorted(chances, reverse=True)
    assert averages == sorted(averages)


def test_a_bigger_budget_never_lowers_the_odds() -> None:
    small = plan_wishes(PlanInput(BannerKind.CHARACTER), budget=100).milestones
    large = plan_wishes(PlanInput(BannerKind.CHARACTER), budget=300).milestones
    assert all(b.success_chance >= a.success_chance for a, b in zip(small, large, strict=True))


# --- Capturing Radiance ---------------------------------------------------------------


def test_banked_losses_improve_the_odds() -> None:
    """The input exists because it moves the answer — by 22 points at the extremes.

    `docs/RESEARCH_wish_planner.md` §5: without it Capturing Radiance is *inert* for the most
    common question, because a single fresh copy ends on the ordinary guarantee before the
    counter can ever fire.
    """
    chances = [
        plan_wishes(
            PlanInput(BannerKind.CHARACTER, lost_fifty_fifties=lost), budget=180
        ).milestones[1].success_chance
        for lost in range(4)
    ]
    assert chances == sorted(chances)
    assert chances[0] == pytest.approx(0.4908, abs=5e-4)
    assert chances[3] == pytest.approx(0.7127, abs=5e-4)
    assert chances[3] - chances[0] > 0.2


def test_three_losses_is_already_a_guarantee() -> None:
    """`w(3) == 1.0`, so the fourth 50/50 cannot be lost.

    Two states that look different therefore agree, and the page has to say so rather than
    let it read as a bug.
    """
    unguaranteed = plan_wishes(
        PlanInput(BannerKind.CHARACTER, lost_fifty_fifties=3), budget=180
    ).milestones[0]
    guaranteed = plan_wishes(
        PlanInput(BannerKind.CHARACTER, guaranteed=True, lost_fifty_fifties=1), budget=180
    ).milestones[0]
    assert unguaranteed.average_wishes == pytest.approx(guaranteed.average_wishes)


def test_guaranteed_with_no_losses_is_refused() -> None:
    """Arming the guarantee *requires* losing a 50/50, which increments the counter."""
    with pytest.raises(UnreachableStateError):
        plan_wishes(PlanInput(BannerKind.CHARACTER, guaranteed=True), budget=180)


def test_every_other_combination_is_reachable() -> None:
    for guaranteed in (False, True):
        for lost in range(4):
            if guaranteed and lost == 0:
                continue
            plan_wishes(
                PlanInput(BannerKind.CHARACTER, guaranteed=guaranteed, lost_fifty_fifties=lost),
                budget=180,
            )


def test_the_weapon_banner_has_no_radiance() -> None:
    """Capturing Radiance is scoped to the Character Event Wish, so asking is an error."""
    with pytest.raises(ValueError, match="character banner only"):
        plan_wishes(PlanInput(BannerKind.WEAPON, lost_fifty_fifties=2), budget=180)


def test_a_guaranteed_weapon_banner_is_fine() -> None:
    """Epitomized Path arms without any radiance counter, so this state is ordinary."""
    guaranteed = plan_wishes(PlanInput(BannerKind.WEAPON, guaranteed=True), 180).milestones[0]
    fresh = plan_wishes(PlanInput(BannerKind.WEAPON), 180).milestones[0]
    assert guaranteed.average_wishes < fresh.average_wishes


# --- the wallet -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("primogems", "fate", "expected"),
    [(0, 0, 0), (160, 0, 1), (159, 0, 0), (24_000, 60, 210), (0, 7, 7), (161, 1, 2)],
)
def test_wishes_from_a_wallet(primogems: int, fate: int, expected: int) -> None:
    """160 primogems a wish, and remainders do not buy a partial wish."""
    assert wishes_from(primogems, fate) == expected


def test_a_negative_wallet_is_refused() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        wishes_from(-1, 0)


# --- input validation -----------------------------------------------------------------


@pytest.mark.parametrize("pity", [-1, 90, 500])
def test_pity_outside_the_curve_is_refused(pity: int) -> None:
    with pytest.raises(ValueError, match="pity must be within"):
        plan_wishes(PlanInput(BannerKind.CHARACTER, pity=pity), budget=180)


def test_a_negative_budget_is_refused() -> None:
    with pytest.raises(ValueError, match="budget must not be negative"):
        plan_wishes(PlanInput(BannerKind.CHARACTER), budget=-1)


def test_owning_the_cap_already_is_refused() -> None:
    with pytest.raises(ValueError, match="owned_copies"):
        plan_wishes(PlanInput(BannerKind.CHARACTER, owned_copies=7), budget=180)


def test_a_zero_budget_still_reports_averages() -> None:
    """Someone with nothing saved still wants to know what the goal costs."""
    plan = plan_wishes(PlanInput(BannerKind.CHARACTER), budget=0)
    assert plan.milestones[0].success_chance == 0.0
    assert plan.milestones[0].average_wishes > 0.0
