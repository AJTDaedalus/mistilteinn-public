"""Exact odds of reaching a constellation or refinement on a given wish budget.

**Nothing here is simulated.** The whole question is a discrete convolution, which is both
exact and cheaper than sampling it would be — about 14 ms for a full C0→C6 ladder. Fribbels'
Warp Planner computes the HSR equivalent the same way; `docs/RESEARCH_wish_planner.md` §2 has
the reading of their implementation and §4 the cross-validation of this one against gachasim's
Monte Carlo.

The algorithm, in four steps:

1. **First-passage PMF** — the distribution of "wishes until the next 5-star", from the
   banner's pity curve.
2. **Pity conditioning** — slice it at the current pity and renormalise, which is exactly
   "given no 5-star in the last *pity* wishes".
3. **Per-copy cost** — a 5-star is the wanted one with probability *w*, else the next one is
   guaranteed. Two branches, and exact because a loss really does guarantee the next.
4. **Convolve down the ladder** and read the CDF at the budget.

**Capturing Radiance is why this is not just Fribbels' code in Python.** The counter survives
obtaining a copy — winning *through the guarantee* does not reset it — so *w* is not a
constant and cannot be folded into a single PMF. The carried state is therefore a **vector of
PMFs indexed by the counter**, and each milestone mixes between them. Still exact, still four
convolutions wide.

## The off-by-one this module is shaped to prevent

A PMF whose index 0 means "one wish" makes `sum(k * p)` too low by exactly **one per 5-star
drawn** — 1.6 wishes on a single copy, 10.5 across seven. It is invisible on one milestone and
grows linearly down the ladder, and it is how the prototype for this feature was first wrong.
So: **index k means exactly k wishes, and index 0 is always 0.0.** Every function here holds
that invariant and `tests/unit/test_wish_planner_math.py` asserts it directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.services.wishes.rates import (
    BannerKind,
    BannerRates,
    primogems_per_wish,
    radiance_win_rates,
    rates_for,
)

#: Constellations C0..C6 — seven copies of a character.
MAX_CONSTELLATION = 6
#: Refinements R1..R5 — five copies of a weapon.
MAX_REFINEMENT = 5


class UnreachableStateError(ValueError):
    """Raised for a banner state the game cannot produce.

    There is exactly one: **guaranteed with no 50/50s lost**. Arming the guarantee requires
    losing a 50/50, and that same loss increments the Capturing Radiance counter, so the two
    cannot disagree. Accepting it would answer a question about a situation no player can be
    in, which is worse than refusing.
    """


@dataclass(frozen=True, slots=True)
class PlanInput:
    """Everything the planner needs to know about a player's position."""

    banner: BannerKind
    #: Wishes since the last 5-star on this banner, 0..hard_pity-1.
    pity: int = 0
    #: Whether the next 5-star is guaranteed to be the promotional item.
    guaranteed: bool = False
    #: 50/50s lost since the last *won* one. Character banner only; see `UnreachableStateError`.
    lost_fifty_fifties: int = 0
    #: Copies already owned — C2 is 3 copies, R3 is 3 copies.
    owned_copies: int = 0


@dataclass(frozen=True, slots=True)
class Milestone:
    """One rung of the ladder: the chance of reaching it and what it costs."""

    #: Copies of the item owned once this rung is reached, counting from 1.
    copies: int
    #: "C3" or "R2" — what a player calls this rung.
    label: str
    #: Chance of reaching it within the budget.
    success_chance: float
    #: Expected wishes to reach it, from the current position.
    average_wishes: float
    #: Wishes at which the chance first reaches 50%, or None if it never does.
    median_wishes: int | None


@dataclass(frozen=True, slots=True)
class WishPlan:
    """The whole ladder, plus what it was measured against."""

    budget: int
    milestones: list[Milestone] = field(default_factory=list)


def wishes_from(primogems: int, intertwined_fate: int) -> int:
    """Convert a wallet to whole wishes.

    Acquaint Fate is deliberately absent: it buys the standard banner, and this planner is
    about the limited ones (owner ruling, 2026-09-22).
    """
    if primogems < 0 or intertwined_fate < 0:
        raise ValueError("primogems and intertwined_fate must not be negative")
    return primogems // primogems_per_wish() + intertwined_fate


def first_passage_pmf(rates: BannerRates) -> np.ndarray:
    """Distribution of wishes until the next 5-star.

    Returns:
        An array where index *k* is the probability of needing exactly *k* wishes. Index 0 is
        0.0 — a 5-star cannot arrive in zero wishes — and the array ends at `hard_pity`.
    """
    curve = rates.drop_curve()
    pmf = np.zeros(len(curve) + 1)
    survival = 1.0
    for pity, rate in enumerate(curve, start=1):
        pmf[pity] = survival * rate
        survival *= 1.0 - rate
    return pmf


def _conditioned_on_pity(pmf: np.ndarray, pity: int) -> np.ndarray:
    """Re-express `pmf` as wishes *remaining* for someone already `pity` wishes in.

    Slicing keeps the 1-indexing — index 0 of the result is "0 more wishes", which is still
    impossible — and renormalising is the conditioning on having had no 5-star yet.
    """
    if not 0 <= pity < len(pmf) - 1:
        raise ValueError(f"pity must be within [0, {len(pmf) - 2}]")
    tail = np.concatenate(([0.0], pmf[pity + 1 :]))
    total = tail.sum()
    if total <= 0.0:
        raise ValueError("pity leaves no probability mass; the curve is malformed")
    return tail / total


def _win_rate(rates: BannerRates, radiance: int) -> float:
    """Chance the next 5-star is the wanted one, given `radiance` banked losses."""
    if not rates.capturing_radiance:
        return rates.featured_rate
    table = radiance_win_rates()
    return table[min(radiance, len(table) - 1)]


def plan_wishes(position: PlanInput, budget: int) -> WishPlan:
    """Return the full ladder of remaining milestones for `position` on `budget` wishes.

    Args:
        position: Where the player currently stands.
        budget: Wishes available.

    Returns:
        One `Milestone` per rung still to be reached, in order.

    Raises:
        UnreachableStateError: For `guaranteed` with no 50/50s lost — see the class docstring.
        ValueError: For a pity, copy count or budget outside its valid range.
    """
    rates = rates_for(position.banner)
    max_copies = (
        MAX_CONSTELLATION + 1 if position.banner is BannerKind.CHARACTER else MAX_REFINEMENT
    )
    _validate(position, budget, rates, max_copies)

    fresh = first_passage_pmf(rates)
    start = _conditioned_on_pity(fresh, position.pity)
    radiance_states = len(radiance_win_rates())

    # state[r] is the PMF of wishes spent so far, conditioned on the counter now reading r.
    # Without Capturing Radiance only index 0 is ever occupied and this degenerates to
    # Fribbels' single-PMF form.
    state: list[np.ndarray | None] = [None] * radiance_states
    state[min(position.lost_fifty_fifties, radiance_states - 1)] = np.array([1.0])

    milestones: list[Milestone] = []
    for step in range(max_copies - position.owned_copies):
        first = step == 0
        cost = start if first else fresh
        guaranteed = position.guaranteed if first else False
        state = _advance(state, cost, fresh, rates, guaranteed, radiance_states)

        total = _collapse(state)
        copies = position.owned_copies + step + 1
        milestones.append(
            Milestone(
                copies=copies,
                label=_label(position.banner, copies),
                success_chance=float(total[: budget + 1].sum()) if budget >= 0 else 0.0,
                average_wishes=float((np.arange(len(total)) * total).sum()),
                median_wishes=_quantile(total, 0.5),
            )
        )
    return WishPlan(budget=budget, milestones=milestones)


def _advance(
    state: list[np.ndarray | None],
    cost: np.ndarray,
    fresh: np.ndarray,
    rates: BannerRates,
    guaranteed: bool,
    radiance_states: int,
) -> list[np.ndarray | None]:
    """Spend one more copy, carrying the Capturing Radiance counter through it."""
    nxt: list[np.ndarray | None] = [None] * radiance_states
    for radiance, pmf in enumerate(state):
        if pmf is None:
            continue
        if guaranteed:
            # The guarantee is spent on this 5-star. Winning through it does *not* reset the
            # counter, which is the whole asymmetry Capturing Radiance rests on.
            _add(nxt, radiance, np.convolve(pmf, cost), 1.0)
            continue

        win = _win_rate(rates, radiance)
        _add(nxt, 0, np.convolve(pmf, cost), win)
        if win < 1.0:
            # Lost: the counter advances and the *next* 5-star is guaranteed, so this copy
            # costs two cycles.
            _add(nxt, min(radiance + 1, radiance_states - 1),
                 np.convolve(pmf, np.convolve(cost, fresh)), 1.0 - win)
    return nxt


def _add(state: list[np.ndarray | None], index: int, pmf: np.ndarray, weight: float) -> None:
    """Accumulate `pmf * weight` into `state[index]`, growing it as needed."""
    if weight <= 0.0:
        return
    scaled = pmf * weight
    current = state[index]
    if current is None:
        state[index] = scaled
        return
    if len(current) < len(scaled):
        current, scaled = scaled, current
    combined = current.copy()
    combined[: len(scaled)] += scaled
    state[index] = combined


def _collapse(state: list[np.ndarray | None]) -> np.ndarray:
    """Sum the radiance-indexed PMFs into the marginal distribution of wishes spent."""
    width = max((len(pmf) for pmf in state if pmf is not None), default=1)
    total = np.zeros(width)
    for pmf in state:
        if pmf is not None:
            total[: len(pmf)] += pmf
    return total


def _quantile(pmf: np.ndarray, q: float) -> int | None:
    """First wish count at which the cumulative probability reaches `q`, or None."""
    cumulative = np.cumsum(pmf)
    reached = np.flatnonzero(cumulative >= q)
    return int(reached[0]) if reached.size else None


def _label(banner: BannerKind, copies: int) -> str:
    """"C3" for the fourth copy of a character, "R2" for the second of a weapon."""
    return f"C{copies - 1}" if banner is BannerKind.CHARACTER else f"R{copies}"


def _validate(position: PlanInput, budget: int, rates: BannerRates, max_copies: int) -> None:
    """Reject inputs the game cannot produce, rather than answering them."""
    if budget < 0:
        raise ValueError("budget must not be negative")
    if not 0 <= position.pity < rates.hard_pity:
        raise ValueError(f"pity must be within [0, {rates.hard_pity - 1}]")
    if not 0 <= position.owned_copies < max_copies:
        raise ValueError(f"owned_copies must be within [0, {max_copies - 1}]")
    if position.lost_fifty_fifties < 0:
        raise ValueError("lost_fifty_fifties must not be negative")
    if position.lost_fifty_fifties and not rates.capturing_radiance:
        raise ValueError(
            "lost_fifty_fifties applies to the character banner only: the weapon banner's "
            "Epitomized Path has no Capturing Radiance equivalent"
        )
    if position.guaranteed and rates.capturing_radiance and position.lost_fifty_fifties == 0:
        raise UnreachableStateError(
            "guaranteed with no 50/50s lost is not a state the game can produce: arming the "
            "guarantee requires losing a 50/50, and that loss increments the Capturing "
            "Radiance counter"
        )
