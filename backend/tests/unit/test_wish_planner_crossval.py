"""Cross-validation of the exact wish planner against a simulation of the same rules.

**Why this exists.** The planner is a closed-form convolution and convolutions fail quietly:
an indexing slip shifts a distribution by one and every number stays plausible. That is not
hypothetical here — the prototype for this feature was wrong by exactly one wish per 5-star
drawn, invisible on a single milestone and 10.5 wishes adrift across a C0→C6 ladder.

So this file re-derives the same answers by **simulating the banner rules directly**, from the
pity curve rather than from anything the planner computes. The simulation is deliberately
naive and written to read like the game's rules, so that agreeing with it is evidence.

`docs/RESEARCH_wish_planner.md` §4 records the original pass, where these figures were also
matched against `/root/gachasim`'s independent Monte Carlo at 300,000 runs per cell (all
|z| < 2) and against Fribbels' own published table. gachasim is not a git repository and is
not vendored, so the check that runs *here* is self-contained.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from app.services.wishes import BannerKind, PlanInput, plan_wishes, rates_for
from app.services.wishes.rates import radiance_win_rates

#: Enough to separate a one-wish error (which is what the failure mode looks like) from noise,
#: while keeping the file inside a couple of seconds.
RUNS = 40_000
SEED = 20260922


def _simulate(banner: BannerKind, copies: int, lost: int, rng: random.Random) -> int:
    """Wishes spent obtaining `copies` copies, by playing the banner's rules out.

    Written to mirror the game rather than the planner: pull until a 5-star, decide whether it
    is the wanted one, and carry the two pieces of state that outlive a 5-star — the guarantee
    and, on the character banner, the Capturing Radiance counter.
    """
    rates = rates_for(banner)
    curve = rates.drop_curve()
    radiance_table = radiance_win_rates()

    spent = 0
    radiance = lost
    guaranteed = False
    for _ in range(copies):
        while True:
            for pity, rate in enumerate(curve, start=1):
                if rng.random() < rate:
                    spent += pity
                    break
            if guaranteed:
                guaranteed = False
                break
            if rates.capturing_radiance:
                win = radiance_table[min(radiance, len(radiance_table) - 1)]
            else:
                win = rates.featured_rate
            if rng.random() < win:
                radiance = 0
                break
            radiance += 1
            guaranteed = True
    return spent


@pytest.mark.parametrize(
    ("banner", "copies", "lost"),
    [
        (BannerKind.CHARACTER, 1, 0),
        (BannerKind.CHARACTER, 2, 0),
        (BannerKind.CHARACTER, 7, 0),
        (BannerKind.CHARACTER, 2, 2),
        (BannerKind.WEAPON, 1, 0),
        (BannerKind.WEAPON, 5, 0),
    ],
)
def test_the_exact_mean_matches_a_simulation(
    banner: BannerKind, copies: int, lost: int
) -> None:
    rng = random.Random(SEED)  # noqa: S311 — a Monte Carlo oracle, not a secret
    runs = [_simulate(banner, copies, lost, rng) for _ in range(RUNS)]
    observed = float(np.mean(runs))
    standard_error = float(np.std(runs, ddof=1)) / RUNS**0.5

    exact = plan_wishes(
        PlanInput(banner, lost_fifty_fifties=lost), budget=0
    ).milestones[copies - 1].average_wishes

    # Four standard errors: tight enough that a one-wish-per-5-star slip (>= 1.0 wishes, and
    # 7 wishes at copies=7) fails on every row, loose enough not to be flaky.
    assert abs(exact - observed) < 4 * standard_error, (
        f"{banner} x{copies}: exact {exact:.3f} vs simulated {observed:.3f} "
        f"(se {standard_error:.3f})"
    )


@pytest.mark.parametrize(
    ("banner", "copies", "budget"),
    [
        (BannerKind.CHARACTER, 1, 90),
        (BannerKind.CHARACTER, 2, 180),
        (BannerKind.WEAPON, 1, 80),
        (BannerKind.WEAPON, 2, 160),
    ],
)
def test_the_exact_cdf_matches_a_simulation(
    banner: BannerKind, copies: int, budget: int
) -> None:
    """The mean can be right while the shape is wrong, so check the budget question directly."""
    rng = random.Random(SEED + 1)  # noqa: S311 — a Monte Carlo oracle, not a secret
    runs = [_simulate(banner, copies, 0, rng) for _ in range(RUNS)]
    observed = sum(1 for value in runs if value <= budget) / RUNS
    standard_error = (observed * (1 - observed) / RUNS) ** 0.5 or 1e-9

    exact = plan_wishes(PlanInput(banner), budget=budget).milestones[copies - 1].success_chance
    assert abs(exact - observed) < 4 * standard_error


#: Means measured in the research pass and reproduced here. A **regression pin**, not an
#: oracle -- the oracle is the simulation above. Re-deriving these means re-running that.
PINNED_MEANS = {
    (BannerKind.CHARACTER, 1): 93.45,
    (BannerKind.CHARACTER, 2): 186.11,
    (BannerKind.CHARACTER, 7): 634.85,
    (BannerKind.WEAPON, 1): 86.53,
    (BannerKind.WEAPON, 5): 432.66,
}


@pytest.mark.parametrize(("key", "expected"), list(PINNED_MEANS.items()))
def test_pinned_means_have_not_moved(key: tuple[BannerKind, int], expected: float) -> None:
    banner, copies = key
    actual = plan_wishes(PlanInput(banner), budget=0).milestones[copies - 1].average_wishes
    assert actual == pytest.approx(expected, abs=0.01)
