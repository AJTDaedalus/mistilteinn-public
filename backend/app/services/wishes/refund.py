"""The starglitter a campaign pays back, computed exactly.

**Nothing here samples.** `docs/DESIGN_wish_planner.md` §9.7 has the argument; this is the
implementation. It looks like a simulation problem because a featured 4-star crosses C6
*during* a campaign and its payout changes from 2 starglitter to 5 — but given a character's
own draw count the payout is a deterministic function, and every count distribution in the
chain is exactly computable:

1. **How many 4-stars in N pulls** — the same first-passage convolution the 5-star ladder
   uses, on the 4-star curve.
2. **How many of them are featured** — a two-state Markov chain: featured with probability
   *p*, and if not, the next one is guaranteed. 50 % on the character banner, 75 % on the
   weapon banner.
3. **How the featured draws split over the featured items** — multinomial, so the counts are
   *not* independent. Handled by nesting the binomials exactly rather than by sampling.
4. **How the non-featured draws split** — Bernoulli into characters and weapons, then the
   same nesting over the roster.

The result is a distribution, not a point estimate, and it is the population rather than a
sample: no standard error, identical on every run.

## What a pull pays

Read off the wiki's quantity table (cited in `banner_rates.json`): a **duplicate** character
below max constellation pays 2, at max pays 5, and any weapon pays 2. A character you do not
own yet pays **nothing** — you get the character. That last row is why the axis is
two-dimensional and why no constant is right for long.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import comb
from typing import TYPE_CHECKING

import numpy as np

from app.services.wishes.planner import first_passage_pmf
from app.services.wishes.rates import BannerKind, BannerRates, four_star_rates

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: Probabilities below this are dropped from an intermediate distribution. Well under the
#: rounding of anything displayed, and it keeps the nested enumeration finite in practice.
EPSILON = 1e-12

#: Starglitter a fate costs, and the constellation a character tops out at.
FATE_COST = 5
MAX_CONSTELLATION = 6


@dataclass(frozen=True, slots=True)
class RefundInputs:
    """Everything the refund depends on."""

    banner: BannerKind
    #: Constellation of each **featured** 4-star, or None for one not owned. Three on the
    #: character banner. On the weapon banner the featured 4-stars are weapons, so this is
    #: empty and every featured draw pays a flat 2.
    featured: tuple[int | None, ...] = ()
    #: Constellation of every **non-featured** 4-star character the roster knows about.
    #: An unknown constellation is left out by the caller rather than guessed at — see
    #: `docs/DESIGN_wish_planner.md` §9.4.
    roster: tuple[int | None, ...] = ()
    #: Share of non-featured 4-stars that are characters rather than weapons.
    non_featured_character_share: float = 0.15


def payout(draws: int, constellation: int | None) -> int:
    """Starglitter from drawing one character `draws` times, from a known constellation.

    `None` means not owned: the first copy is the character itself and pays nothing.

        g(k) = 2·min(k − u, 6 − c)⁺ + 5·(k − u − (6 − c))⁺,   u = 1 if unowned
    """
    if draws <= 0:
        return 0
    if constellation is None:
        free, headroom = 1, MAX_CONSTELLATION
    else:
        free, headroom = 0, MAX_CONSTELLATION - constellation
    below = min(max(draws - free, 0), headroom)
    at_max = max(draws - free - below, 0)
    return below * 2 + at_max * 5


def four_star_count_pmf(rates: BannerRates, pulls: int, cap: int = 120) -> np.ndarray:
    """P(exactly *k* four-stars within `pulls` wishes).

    A renewal process: *k* four-stars fit in `pulls` when the sum of *k* cycle lengths does.
    Convolving the cycle PMF with itself gives each `P(at least k)` exactly.
    """
    if pulls < 0:
        raise ValueError("pulls must not be negative")
    cycle = first_passage_pmf(rates)
    alive = np.zeros(pulls + 1)
    alive[0] = 1.0
    at_least = []
    for _ in range(cap + 1):
        at_least.append(float(alive.sum()))
        if at_least[-1] < EPSILON:
            break
        alive = np.convolve(alive, cycle)[: pulls + 1]
    at_least.append(0.0)
    exactly = np.array([at_least[k] - at_least[k + 1] for k in range(len(at_least) - 1)])
    total = exactly.sum()
    return exactly / total if total else exactly


def featured_split_pmf(count: int, featured_rate: float) -> np.ndarray:
    """P(*f* of `count` four-stars are featured).

    A two-state chain — featured at `featured_rate`, and a miss guarantees the next one. The
    consolidated featured share this implies is `1 / (1 + (1 − rate))`, which is 66.67 % at
    a half and 80 % at three quarters, matching what HoYoverse publishes.
    """
    # state[guaranteed][featured so far]
    state = np.zeros((2, count + 1))
    state[0, 0] = 1.0
    for _ in range(count):
        nxt = np.zeros_like(state)
        # Guarantee pending: this one is featured, and the guarantee is spent.
        nxt[0, 1:] += state[1, :-1]
        # No guarantee: featured at `rate`, else the next one is guaranteed.
        nxt[0, 1:] += state[0, :-1] * featured_rate
        nxt[1, :] += state[0, :] * (1.0 - featured_rate)
        state = nxt
    return state.sum(axis=0)


def roster_payout_pmf(draws: int, constellations: Sequence[int | None]) -> np.ndarray:
    """Exact starglitter distribution from `draws` landing uniformly over `constellations`.

    Returned as an array indexed by starglitter. The counts are multinomial and therefore
    **dependent**, which is what makes this look like a sampling problem. It is not: process
    one character at a time, conditioning on the draws left, and the joint is enumerated
    exactly.

    Kept in numpy rather than dictionaries because the caller asks for it once per draw count
    and the dictionary version spent eleven seconds on a long campaign.
    """
    width = draws * 5 + 1
    if draws <= 0 or not constellations:
        out = np.zeros(1)
        out[0] = 1.0
        return out

    # Rows are draws allocated so far, columns are starglitter accumulated.
    state = np.zeros((draws + 1, width))
    state[0, 0] = 1.0
    remaining = len(constellations)
    for constellation in constellations:
        remaining -= 1
        nxt = np.zeros_like(state)
        for used in range(draws + 1):
            row = state[used]
            if not row.any():
                continue
            left = draws - used
            for taken in range(left + 1):
                if remaining == 0 and taken != left:
                    continue  # the last character absorbs whatever is left
                if remaining:
                    share = 1.0 / (remaining + 1)
                    weight = (
                        comb(left, taken) * share**taken * (1.0 - share) ** (left - taken)
                    )
                else:
                    weight = 1.0
                if weight < EPSILON:
                    continue
                gain = payout(taken, constellation)
                if gain:
                    nxt[used + taken, gain:] += row[:-gain] * weight
                else:
                    nxt[used + taken] += row * weight
        state = nxt
    return state[draws]


def _non_featured_pmf(
    count: int, share: float, roster_for: Callable[[int], np.ndarray],
) -> np.ndarray:
    """Starglitter from `count` non-featured four-stars.

    Each is a character with probability `share` (paying 0, 2 or 5 depending on the roster)
    and a weapon otherwise (a flat 2). Depends only on `count`, which is why it is built once
    per count rather than inside the marginalisation.
    """
    width = count * 5 + 1
    out = np.zeros(max(width, 1))
    for characters in range(count + 1):
        weight = (
            comb(count, characters) * share**characters * (1.0 - share) ** (count - characters)
        )
        if weight < EPSILON:
            continue
        weapons = (count - characters) * 2
        roster = roster_for(characters)
        end = weapons + len(roster)
        if end > len(out):
            out = np.pad(out, (0, end - len(out)))
        out[weapons:end] += roster * weight
    return out


@lru_cache(maxsize=256)
def refund_pmf(inputs: RefundInputs, pulls: int) -> dict[int, float]:
    """Exact distribution of **wishes** the starglitter pays back over `pulls` wishes.

    Cached because the page recomputes on a debounce: between keystrokes the banner and the
    roster are identical and only `pulls` moves, so the second request through is free.
    `RefundInputs` is frozen with tuple fields precisely so it can be a key.
    """
    rates = four_star_rates(inputs.banner)
    counts = four_star_count_pmf(rates, pulls)
    # Counts whose probability is already negligible still cost O(k²) apiece to build a
    # payout distribution for. Trimming the tail is most of what makes this a request.
    live = np.flatnonzero(counts >= EPSILON)
    counts = counts[: int(live[-1]) + 1] if live.size else counts[:1]
    featured_rate = rates.featured_rate

    # **Precomputed, not recomputed.** Both payout distributions depend only on a draw
    # count, and the nested loop below asks for the same counts thousands of times. Building
    # them once took this from 5.4 s to milliseconds, which is the difference between a
    # request and a job.
    # **Everything below depends only on a draw count.** Built once, because the
    # marginalisation asks for the same counts thousands of times; recomputing them inside
    # the loop was the difference between eleven seconds and a request.
    reach = len(counts)

    # **Lazy, not eager.** Only 15 % of non-featured four-stars are characters, so over 700
    # pulls the roster is asked for a dozen draws and never for seventy — and building all
    # seventy over a 45-strong roster costs O(45·k²) each. Eager construction spent thirty
    # seconds computing distributions whose binomial weight was already below EPSILON.
    roster_cache: dict[int, np.ndarray] = {}

    def roster_for(draws: int) -> np.ndarray:
        if draws not in roster_cache:
            roster_cache[draws] = roster_payout_pmf(draws, inputs.roster)
        return roster_cache[draws]

    featured_by_count = (
        [roster_payout_pmf(k, inputs.featured) for k in range(reach)]
        if inputs.featured
        # Featured 4-stars on the weapon banner are weapons: a flat 2 each.
        else [_point_mass(k * 2) for k in range(reach)]
    )
    non_featured_by_count = [
        _non_featured_pmf(k, inputs.non_featured_character_share, roster_for)
        for k in range(reach)
    ]

    starglitter = np.zeros(1)
    for count, count_probability in enumerate(counts):
        if count_probability < EPSILON:
            continue
        split = featured_split_pmf(count, featured_rate)
        for featured, featured_probability in enumerate(split):
            joint = count_probability * featured_probability
            if joint < EPSILON:
                continue
            combined = np.convolve(
                featured_by_count[featured], non_featured_by_count[count - featured],
            )
            if len(combined) > len(starglitter):
                starglitter = np.pad(starglitter, (0, len(combined) - len(starglitter)))
            starglitter[: len(combined)] += combined * joint

    # Starglitter buys whole fates only, and the remainder does not round up: a planner that
    # promises a wish a player cannot buy is worse than a pessimistic one.
    wishes: dict[int, float] = {}
    for total, probability in enumerate(starglitter):
        if probability < EPSILON:
            continue
        key = total // FATE_COST
        wishes[key] = wishes.get(key, 0.0) + float(probability)
    mass = sum(wishes.values())
    return {k: v / mass for k, v in wishes.items()} if mass else {0: 1.0}


def _point_mass(value: int) -> np.ndarray:
    out = np.zeros(value + 1)
    out[value] = 1.0
    return out


def expected_refund(inputs: RefundInputs, pulls: int) -> float:
    """Mean wishes returned, for the places that want one number."""
    return sum(value * probability for value, probability in refund_pmf(inputs, pulls).items())
