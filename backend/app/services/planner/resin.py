"""Resin: what a plan costs to farm, as an average and as a distribution.

## What is known and what is modelled

**The average is derived.** `RewardPreviewExcelConfigData` publishes an expected drop per run
for 94 of the materials a plan can need, and the published 3:1 crafting tree carries that to
120 more. Twelve rates are curated with citations; anything else has no rate and is reported
as unknown rather than guessed.

**The spread is modelled, and the model is stated.** Nothing in the pinned dump resolves a
`drop_id` — the randomised drop tables are server-side — so the true per-run distribution is
not available at any price. This module assumes the **two-point integer distribution matching
the published mean**: a run yields `floor(mu)` or `ceil(mu)`, the latter with probability
`mu - floor(mu)`.

That is the *minimum-variance* distribution with that mean, so **the histogram it draws is
narrower than reality**. It is a floor on the spread, not a prediction, and every surface that
renders it has to say so. The alternative — drawing nothing — hides that farming variance
exists at all, which is the thing a resin estimate is most often wrong about.

## Why runs are counted against the craft root

A domain drops several tiers of one family and you convert upward, so a plan needing both
Guides and Philosophies of the same book is farming *one* thing. Needs are reduced to their
craft root through the published ratios before any run is counted; otherwise the same run is
billed twice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.planner.economy import Economy

#: Tail mass to discard per root when turning a run-count distribution into a finite one.
#: A negative-binomial tail is infinite; 1e-6 keeps the histogram honest to six figures while
#: bounding the convolution.
_TAIL = 1e-6

#: Ceiling on runs considered for one material. A plan needing more than this is not a plan,
#: and an unbounded loop on a malformed rate must not hang a request.
_MAX_RUNS = 20_000

#: How many bars the rendered histogram carries. Enough to show a shape, few enough to read.
_BINS = 12


@dataclass(frozen=True)
class ResinEstimate:
    """The expected resin for one material, and where the number came from."""

    material_id: int
    #: The tier actually farmed. Differs from `material_id` whenever the material is crafted.
    root_id: int
    source_type: str
    resin_per_run: int
    expected_per_run: float
    expected_runs: float
    expected_resin: float
    #: Resin per single unit of the *requested* material, which is what a per-item column
    #: shows. Already accounts for the crafting ratio.
    resin_per_unit: float
    #: True when the rate came from `curated_rates.json` rather than the game's own preview.
    curated: bool


@dataclass(frozen=True)
class HistogramBin:
    """One bar: resin in `[low, high)`, holding `probability` of the mass."""

    low: int
    high: int
    probability: float


@dataclass
class ResinTotal:
    """Everything resin-priced in a section, plus everything that could not be.

    **Two different kinds of "no number" and they must not be one field.** A Sakura Bloom
    costs no resin because you walk around picking it; a Shivada Jade Sliver costs resin at a
    rate nobody publishes. Folding those together would tell a user their local specialties
    are an unknown farming cost, and tell them the gems are free — both wrong, in opposite
    directions.
    """

    expected: float = 0.0
    #: Resin-farmable, but at a rate no table publishes and `curated_rates.json` has not been
    #: given. Named, never folded into the total as zero.
    unpriced: list[int] = field(default_factory=list)
    #: Not obtainable with resin at all — overworld drops and local specialties. Their resin
    #: cost really is zero, and saying so is not a guess.
    not_farmable: list[int] = field(default_factory=list)
    histogram: list[HistogramBin] = field(default_factory=list)
    #: `(runs distribution, resin per run)` per craft root, kept so a caller can combine
    #: sections without re-deriving them.
    _roots: dict[int, tuple[list[float], int]] = field(default_factory=dict, repr=False)

    @property
    def has_unpriced(self) -> bool:
        """True when some resin-farmable material in this section carries no rate."""
        return bool(self.unpriced)


def _binomial_tail_below(n: int, p: float, threshold: int) -> float:
    """`P(Binomial(n, p) < threshold)`, computed directly.

    Small `n` and no SciPy, so the sum is exact rather than approximated. `threshold <= 0`
    means the requirement is already met and the probability of falling short is zero.
    """
    if threshold <= 0:
        return 0.0
    if threshold > n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    total = 0.0
    for k in range(threshold):
        total += math.comb(n, k) * (p**k) * ((1 - p) ** (n - k))
    return min(1.0, total)


def runs_distribution(needed: int, expected_per_run: float) -> list[float]:
    """`P(N = n)` for the number of runs to obtain `needed` units, index `n` from 0.

    With the two-point model a run yields `a = floor(mu)` plus a Bernoulli(`p`) bonus, so the
    total after `n` runs is `n*a + Binomial(n, p)` and

        P(N > n) = P(n*a + Bin(n, p) < needed)

    which is a binomial tail. The distribution is truncated once its remaining mass falls
    below `_TAIL`.
    """
    if needed <= 0:
        return [1.0]
    if expected_per_run <= 0:
        return []
    floor_yield = math.floor(expected_per_run)
    bonus_p = expected_per_run - floor_yield

    probabilities: list[float] = []
    survive_previous = 1.0  # P(N > n-1), starting at P(N > -1) = 1
    for n in range(_MAX_RUNS + 1):
        survive = _binomial_tail_below(n, bonus_p, needed - n * floor_yield)
        probabilities.append(max(0.0, survive_previous - survive))
        survive_previous = survive
        if survive < _TAIL:
            break
    return probabilities


def estimate(economy: Economy, material_id: int, needed: int) -> ResinEstimate | None:
    """Expected resin for `needed` of a material, or `None` when nothing prices it.

    The need is reduced to its craft root first, so a Gemstone is priced as the 27 Slivers it
    is actually farmed as.
    """
    if needed <= 0:
        return None
    root_id, root_needed, _mora = economy.reduce_to_root(material_id, needed)
    rate = economy.rate(root_id)
    if rate is None or rate.expected_per_run <= 0:
        return None
    runs = root_needed / rate.expected_per_run
    resin = runs * rate.resin
    return ResinEstimate(
        material_id=material_id,
        root_id=root_id,
        source_type=rate.source_type,
        resin_per_run=rate.resin,
        expected_per_run=rate.expected_per_run,
        expected_runs=runs,
        expected_resin=resin,
        resin_per_unit=resin / needed,
        curated=rate.curated,
    )


def total(economy: Economy, needs: dict[int, int]) -> ResinTotal:
    """Price a whole set of `{material id: count}` needs together.

    Needs sharing a craft root are **summed before any run is counted**, because a domain run
    that drops three tiers of one book family satisfies all of them at once. Pricing them
    separately would bill the same run more than once.
    """
    out = ResinTotal()
    by_root: dict[int, int] = {}
    for material_id, count in needs.items():
        if count <= 0:
            continue
        root_id, root_needed, _mora = economy.reduce_to_root(material_id, count)
        rate = economy.rate(root_id)
        if rate is None or rate.expected_per_run <= 0:
            if root_id in set(economy.uncurated()):
                out.unpriced.append(material_id)
            else:
                out.not_farmable.append(material_id)
            continue
        by_root[root_id] = by_root.get(root_id, 0) + root_needed

    for root_id, root_needed in by_root.items():
        rate = economy.rate(root_id)
        if rate is None:  # pragma: no cover - filtered above
            continue
        out.expected += (root_needed / rate.expected_per_run) * rate.resin
        distribution = runs_distribution(root_needed, rate.expected_per_run)
        if distribution:
            out._roots[root_id] = (distribution, rate.resin)  # noqa: SLF001
    out.unpriced.sort()
    out.not_farmable.sort()
    out.histogram = histogram(out._roots)  # noqa: SLF001
    return out


def _convolve(roots: dict[int, tuple[list[float], int]]) -> dict[int, float]:
    """Combine per-root run counts into one distribution over total resin.

    Roots are independent — they are different domains and bosses — so the totals convolve.
    """
    combined: dict[int, float] = {0: 1.0}
    for distribution, resin_per_run in roots.values():
        nxt: dict[int, float] = {}
        for base, base_p in combined.items():
            if base_p < _TAIL:
                continue
            for runs, run_p in enumerate(distribution):
                if run_p < _TAIL:
                    continue
                key = base + runs * resin_per_run
                nxt[key] = nxt.get(key, 0.0) + base_p * run_p
        combined = nxt or combined
    return combined


def histogram(roots: dict[int, tuple[list[float], int]], bins: int = _BINS) -> list[HistogramBin]:
    """Bin the combined resin distribution into `bins` bars.

    Returns `[]` when nothing is priced, and a single bar when the plan is already met —
    both of which a renderer should show as "no farming needed" rather than as an empty chart.
    """
    if not roots:
        return []
    combined = _convolve(roots)
    mass = sum(combined.values())
    if mass <= 0:
        return []
    values = sorted(combined)
    low, high = values[0], values[-1]
    if low == high:
        return [HistogramBin(low=low, high=low, probability=1.0)]
    width = max(1, math.ceil((high - low + 1) / bins))
    out: list[HistogramBin] = []
    for index in range(bins):
        start = low + index * width
        if start > high:
            break
        stop = start + width
        probability = sum(p for value, p in combined.items() if start <= value < stop)
        out.append(HistogramBin(low=start, high=stop, probability=probability / mass))
    return out
