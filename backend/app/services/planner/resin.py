"""Resin: what a plan costs to farm, as an average and as a distribution.

## What is known and what is modelled

**The average is derived.** `RewardPreviewExcelConfigData` publishes an expected drop per run
for 94 of the materials a plan can need, and the published 3:1 crafting tree carries that to
120 more. Twelve rates are curated with citations; anything else has no rate and is reported
as unknown rather than guessed.

**The spread comes from the source's own shape where one is known, and is modelled where it
is not.** Nothing in the pinned dump resolves a `drop_id` — the randomised drop tables are
server-side — so the game publishes means and nothing else. A curated source may declare its
shape instead, and three do: a ley-line run gives 6-7 blue books and 4-5 purple (four
outcomes), a trounce run gives 2 or 3 items each randomly one of the boss's three (so a named
material is a binomial mixture, and 41% of runs yield none of it), and a Blossom of Wealth
gives a flat 60,000 mora with no variation at all.

Everything else falls back to the **two-point integer distribution matching the published
mean** — `floor(mu)` or `ceil(mu)`, the latter with probability `mu - floor(mu)`. That is the
*minimum-variance* distribution with that mean, so a histogram drawn from it is **narrower
than reality**; it is a floor on the spread, not a prediction, and every surface that renders
it says so.

**The fallback is not universally safe and that is why shapes exist.** For a domain it is
exactly right: a run really does give 2 or 3 books, so a published mean of 2.2 is `{2: 0.8,
3: 0.2}`. For a mean that is already a whole number it collapses — 122,500 EXP has
`floor == ceil`, so the ley line became a point mass and its run count came out certain.

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

from app.services.planner.economy import MaterialSource

if TYPE_CHECKING:
    from app.services.planner.economy import DropRate, Economy

#: Tail mass to discard per root when turning a run-count distribution into a finite one.
#: A negative-binomial tail is infinite; 1e-6 keeps the histogram honest to six figures while
#: bounding the convolution.
_TAIL = 1e-6

#: Ceiling on runs considered for one material. A plan needing more than this is not a plan,
#: and an unbounded loop on a malformed rate must not hang a request.
_MAX_RUNS = 20_000

#: Largest first-passage state space walked exactly, after scaling by the common divisor.
#: Above this the mean survives and the shape does not, which is said rather than hidden.
_MAX_STATES = 100_000

#: How many bars the rendered histogram carries. Enough to show a shape, few enough to read.
_BINS = 12

#: Stand-in id for "character EXP points" when pricing a ley line. Hero's Wit is the largest
#: denomination and classifies as `LEY_LINE_EXP`, so asking the economy for *its* rate returns
#: the blossom's rate — which is published per EXP point, not per book.
EXP_PROBE = 104003


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
    #: Not obtainable with resin at all — elemental gems, common enemy drops and local
    #: specialties. Their resin cost really is zero, and saying so is not a guess.
    not_farmable: list[int] = field(default_factory=list)
    #: Non-material costs with no rate: `"mora"`, `"character EXP"`. Same meaning as
    #: `unpriced` — resin-farmable, rate not supplied.
    unpriced_sources: list[str] = field(default_factory=list)
    histogram: list[HistogramBin] = field(default_factory=list)
    #: `{probe id: expected resin}` for the two costs priced as a ley-line pool rather than per
    #: row — mora under the mora id, character EXP under `EXP_PROBE`. Kept so the rows can be
    #: given their share and a Resin column sums to `expected`.
    pooled: dict[int, float] = field(default_factory=dict)
    #: `(runs distribution, resin per run)` per craft root, kept so a caller can combine
    #: sections without re-deriving them.
    _roots: dict[int, tuple[list[float], int]] = field(default_factory=dict, repr=False)

    @property
    def has_unpriced(self) -> bool:
        """True when some resin-farmable material in this section carries no rate."""
        return bool(self.unpriced)


def per_run_outcomes(rate: DropRate) -> tuple[tuple[float, float], ...]:
    """The per-run yield distribution to count runs against.

    A curated source that declares its shape gets that shape. Everything else — the domain
    and world-boss rates, which come from the game's own reward previews and are means with
    no published shape — falls back to the **two-point integer distribution matching the
    mean**: `floor(mu)` or `ceil(mu)`, the latter with probability `mu - floor(mu)`.

    That fallback is the *minimum-variance* distribution with the right average, so a
    histogram drawn from it is **narrower than reality**. For a domain it happens to be
    exactly right — a run really does give 2 or 3 books, and a published mean of 2.2 is
    `{2: 0.8, 3: 0.2}` — which is why it was not obviously wrong until a source arrived whose
    mean was a large integer. A mean of 122,500 EXP has `floor == ceil`, so the fallback
    collapsed to a point mass and the run count came out certain.
    """
    if rate.distribution:
        return rate.distribution
    mean = rate.expected_per_run
    low = math.floor(mean)
    remainder = mean - low
    if remainder <= 0:
        return ((float(low), 1.0),)
    return ((float(low), 1.0 - remainder), (float(low + 1), remainder))


def runs_distribution(needed: int, rate: DropRate) -> list[float]:
    """`P(N = n)` for the number of runs to obtain `needed` units, index `n` from 0.

    A first-passage time over the per-run distribution, computed by walking the accumulated
    total forward one run at a time and absorbing the mass that crosses the requirement.

    **Values are scaled by their common divisor first.** A ley-line run yields EXP in
    multiples of 5,000 against a requirement in the millions; without scaling the state space
    would be the requirement itself. With it, the same problem is a few hundred states.
    """
    if needed <= 0:
        return [1.0]
    outcomes = [
        (value, probability)
        for value, probability in per_run_outcomes(rate)
        if probability > 0
    ]
    positive = [int(value) for value, _ in outcomes if value > 0]
    if not positive:
        return []

    # **Zero-yield outcomes are kept.** A trounce run drops one of the boss's three materials,
    # so 41% of runs yield none of the one you came for — and that run still costs 30 resin.
    # Dropping those outcomes leaks their probability out of the walk, which showed up as a
    # weekly-boss plan needing 0.01 runs.
    divisor = math.gcd(*positive, needed) or 1
    target = -(-needed // divisor)
    steps = [(int(value) // divisor, probability) for value, probability in outcomes]
    if target > _MAX_STATES:
        # Too fine-grained to walk exactly. The mean is still right; only the shape is lost,
        # and saying so beats spending a second on a histogram nobody asked to be exact.
        return _mean_only_distribution(target, steps)

    probabilities: list[float] = [0.0]
    live: dict[int, float] = {0: 1.0}
    for _ in range(_MAX_RUNS):
        nxt: dict[int, float] = {}
        finished = 0.0
        for total, carried in live.items():
            for step, probability in steps:
                moved = carried * probability
                if total + step >= target:
                    finished += moved
                else:
                    nxt[total + step] = nxt.get(total + step, 0.0) + moved
        probabilities.append(finished)
        # **Not pruned per state.** Dropping individual low-probability states would shed
        # mass from a long tail a little at a time; only the total decides when to stop.
        live = nxt
        if sum(live.values()) < _TAIL:
            break
    return probabilities


def _mean_only_distribution(target: int, steps: list[tuple[int, float]]) -> list[float]:
    """A point mass at the expected number of runs, for a state space too large to walk."""
    mean = sum(step * probability for step, probability in steps)
    if mean <= 0:
        return []
    runs = max(1, round(target / mean))
    return [0.0] * runs + [1.0]


def estimate(
    economy: Economy, material_id: int, needed: int, *, craft_multiplier: float = 1.0,
) -> ResinEstimate | None:
    """Expected resin for `needed` of a material, or `None` when nothing prices it.

    The need is reduced to its craft root first, so a Gemstone is priced as the 27 Slivers it
    is actually farmed as.
    """
    if needed <= 0:
        return None
    root_id, root_needed, _mora = economy.reduce_to_root(
        material_id, needed, craft_multiplier=craft_multiplier,
    )
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


def total(
    economy: Economy,
    needs: dict[int, int],
    *,
    mora: int = 0,
    character_exp: int = 0,
    craft_multipliers: dict[int, float] | None = None,
) -> ResinTotal:
    """Price a whole set of `{material id: count}` needs together, plus mora and EXP.

    Needs sharing a craft root are **summed before any run is counted**, because a domain run
    that drops three tiers of one book family satisfies all of them at once. Pricing them
    apart would bill the same run more than once.

    **Mora and character EXP are resin too.** Both are farmed at ley-line blossoms at 20 resin
    a run (`BlossomChestExcelConfigData`), so a plan's mora bill has a resin price like
    anything else. EXP is priced in *points* rather than in books, because that is the unit a
    blossom yields -- so the EXP denominations are skipped in the material loop and accounted
    here instead, or they would be counted twice in the wrong unit.
    """
    out = ResinTotal()
    by_root: dict[int, int] = {}
    for material_id, count in needs.items():
        if count <= 0:
            continue
        source = economy.source_of(material_id)
        if source is MaterialSource.LEY_LINE_EXP:
            continue  # priced from `character_exp`, in points
        if source is MaterialSource.NONE:
            out.not_farmable.append(material_id)
            continue
        root_id, root_needed, _mora = economy.reduce_to_root(
            material_id, count, craft_multiplier=(craft_multipliers or {}).get(material_id, 1.0),
        )
        rate = economy.rate(root_id)
        if rate is None or rate.expected_per_run <= 0:
            out.unpriced.append(material_id)
            continue
        by_root[root_id] = by_root.get(root_id, 0) + root_needed

    for amount, probe, label in (
        (mora, economy.mora_item_id, "mora"),
        (character_exp, EXP_PROBE, "character EXP"),
    ):
        if amount <= 0:
            continue
        rate = economy.rate(probe)
        if rate is None or rate.expected_per_run <= 0:
            out.unpriced_sources.append(label)
            continue
        by_root[probe] = by_root.get(probe, 0) + amount
        out.pooled[probe] = (amount / rate.expected_per_run) * rate.resin

    for root_id, root_needed in by_root.items():
        rate = economy.rate(root_id)
        if rate is None:  # pragma: no cover - filtered above
            continue
        out.expected += (root_needed / rate.expected_per_run) * rate.resin
        distribution = runs_distribution(root_needed, rate)
        if distribution:
            out._roots[root_id] = (distribution, rate.resin)  # noqa: SLF001
    out.unpriced.sort()
    out.not_farmable.sort()
    out.unpriced_sources.sort()
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
