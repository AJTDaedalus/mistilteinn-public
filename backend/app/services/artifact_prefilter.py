"""Make the artifact search smaller without making it different.

Two layers sit in front of `artifact_optimizer.optimize`, and the difference between them
is the whole point:

**Pareto dominance is lossless.** If artifact A gives at least as much of every stat that
can change this hit's damage as artifact B, and they are in the same slot and the same set,
then no combination containing B beats the same combination with A substituted in. B can be
dropped with no error bound, no tuning parameter, and nothing to disclose. It is arithmetic,
not a heuristic.

**Budget-K is a heuristic and says so.** When the Cartesian product is too large to search,
each slot keeps its best K candidates by a cheap solo score. That *can* drop the winner —
a piece that is unremarkable alone but completes a set, say. So every result carries
`prefiltered` and `effective_k`, and `is_exact` is False whenever the layer fired. A search
that silently returned a near-answer would be worse than a slow one.

## Why the two layers must run in that order

Pareto runs first, because it changes the bucket sizes the budget estimator sees. Running
the lossy layer first would spend the budget on candidates the lossless layer was about to
prove redundant.

## The live-dimension probe

Comparing every artifact stat would make dominance almost impossible to establish — a piece
with one more point of DEF% would be incomparable to a strictly better one. So the
comparison is projected onto the quantities that can actually change *this* hit's damage,
found by probing with the real evaluator (`_probe`), not by a table of assumptions about
which stats matter.

The projection is sound because every factor in the damage chain (`formula/genshin/damage.py`)
is non-negative and non-decreasing in the stats an artifact can contribute — a bigger stat
never buys less damage. A quantity is called dead only when moving it across its **entire
reachable range** changes the score by exactly zero in *both* the others-at-base and the
others-at-max context.

Both contexts are checked, and neither alone would do. Others-at-max is the context where a
quantity's marginal value is largest for the multiplicative factors, so a quantity dead
there is dead below it — but crit rate clamps at 100% (`damage.py:crit_multiplier`), so a
build already at the cap in the others-at-max context shows crit rate as worth exactly zero
there while it is worth a great deal at base. Requiring zero in both keeps it.

Stats named in `min_stats` are kept regardless of what the probe says. The probe measures
damage, and a floor is not about damage: Energy Recharge changes no hit in this chain, so
the probe correctly calls it dead — and dropping it from the comparison would let a piece
that clears an ER floor be dominated by one that does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.data.snapshot import artifact_main_stat_value
from app.formula.genshin import tags
from app.pando.calculator import NodeRegistry
from app.services.damage_calculator import BuildEvaluator
from app.services.stat_calculator import _quantity_for_prop, build_log

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from app.formula.genshin.damage import Hit
    from app.formula.genshin.explain import Contribution
    from app.services.artifact_optimizer import ArtifactCandidate
    from app.services.damage_calculator import Enemy

#: Wall-clock the automatic budget aims to keep an exhaustive search under. A policy
#: choice, not a measurement — the measurement is `SECONDS_PER_COMBINATION`.
COMBINATION_BUDGET_SECONDS: float = 300.0

#: Measured cost of one scored combination, in seconds. Produced by
#: `scripts/bench_optimizer.py` against the real evaluator, not estimated: 5.467e-04 over
#: 5,184 combinations and 5.142e-04 over 9,408 (2026-08-21, G.3). The higher of the two is
#: taken, because the budget is a promise about wall-clock — a search that prunes a little
#: early says so in its result, and one that runs twice as long as promised does not.
#:
#: The ZZZ pipeline's equivalent constant was a fit against a different hot loop and was
#: deliberately **not** ported. A borrowed timing is a fabricated measurement. G.7
#: re-baselines this; the script prints the line to paste here.
SECONDS_PER_COMBINATION: float = 5.5e-4

#: How many pieces per **floor** stat survive budget-K regardless of their damage rank.
#:
#: One, because a floor is a feasibility question and the best piece is what answers it. It
#: is deliberately not a general "keep some variety" knob: variety is the lossless layer's
#: job, and a keep large enough to matter there would swallow K whole — with K=2 and four
#: live stats, a three-per-stat union kept every piece and the lossy layer pruned nothing at
#: all while still reporting a K.
FLOOR_KEEP_PER_QUANTITY: int = 1

#: `prefilter_top_k=EXACT` forces the exhaustive search regardless of how long it will take.
EXACT: int = -1


class Cancelled(Exception):  # noqa: N818 - a signal, not an error; "CancelledError" is asyncio's
    """Raised inside the search when a progress callback asks it to stop."""


@dataclass(frozen=True, slots=True)
class PrefilterReport:
    """What the pruning layers did, in the terms a caller has to disclose."""

    #: Candidates removed by the lossless layer. Removing them cannot change the answer.
    pareto_removed: int = 0
    #: Candidates removed by the lossy layer. Removing them **can** change the answer.
    prefiltered: int = 0
    #: The K that budget-K used, or None when it did not fire.
    effective_k: int | None = None
    #: The quantities the probe found could change this hit, plus the floor stats.
    live_quantities: tuple[str, ...] = ()
    #: Size of the raw per-slot product before either layer ran.
    total_space: int = 0

    @property
    def is_exact(self) -> bool:
        """Whether the returned builds are the true optimum over the given inventory.

        Only the lossy layer can make this False. `pareto_removed` deliberately does not
        appear: saying a Pareto-pruned search is inexact would train a user to ignore the
        flag on the runs where it means something.
        """
        return self.prefiltered == 0

    def summary(self, evaluated: int) -> str:
        """One line a user can read without knowing what a Pareto frontier is."""
        if self.is_exact:
            return f"Searched all {evaluated:,} combinations (exact)."
        return (
            f"Searched {evaluated:,} of ~{self.total_space:,} combinations "
            f"(top-{self.effective_k} per slot; the result is very likely the best build "
            f"but is not proven to be — re-run with prefilter_top_k=EXACT to be sure)."
        )


# ---- The stat vector ------------------------------------------------------


def inventory_quantities(
    by_slot: Mapping[str, Sequence[ArtifactCandidate]],
) -> tuple[str, ...]:
    """Every DAG quantity the pieces in *this* inventory actually carry.

    The comparison has one soundness requirement: it must not compare two artifacts on a
    vocabulary that omits a stat one of them has, or dominance stops meaning what it says.
    Reading the vocabulary off the pieces themselves satisfies that by construction.

    The first attempt built a global list from the committed snapshot instead — main-stat
    pools plus the substat depots — and that turned out to be the wrong question twice over.
    The depot table carries depots the standard sets never use (`FIGHT_PROP_SPEED_PERCENT`,
    `FIGHT_PROP_SKILL_CD_MINUS_RATIO`), so it over-answered with props the DAG has no
    quantity for; and deciding which depots were "real" would have been a judgement about
    game data made here, in a prefilter, rather than read from anywhere.

    Order is fixed, so a vector means the same thing on both sides of a comparison.
    """
    quantities: set[str] = set()
    for bucket in by_slot.values():
        for candidate in bucket:
            props = (candidate.main_stat, *(s.get("stat") for s in candidate.substats))
            for prop in props:
                quantity = _quantity_for_prop(prop, allow_absent=True)
                if quantity is not None:
                    quantities.add(quantity)
    return tuple(sorted(quantities))


def stat_vector(
    candidate: ArtifactCandidate, quantities: Sequence[str],
) -> tuple[float, ...]:
    """One candidate's total contribution to each of `quantities`, in that order."""
    totals = dict.fromkeys(quantities, 0.0)
    main_quantity = _quantity_for_prop(candidate.main_stat, allow_absent=True)
    if main_quantity in totals:
        totals[main_quantity] += artifact_main_stat_value(
            candidate.rarity, candidate.level, candidate.main_stat,
        )
    for substat in candidate.substats:
        quantity = _quantity_for_prop(substat.get("stat"), allow_absent=True)
        if quantity in totals:
            totals[quantity] += float(substat.get("value", 0.0))
    return tuple(totals[quantity] for quantity in quantities)


def reachable_maxima(
    by_slot: Mapping[str, Sequence[ArtifactCandidate]], quantities: Sequence[str],
) -> dict[str, float]:
    """Per-quantity ceiling over the whole inventory: the best piece in each slot, summed.

    A deliberate over-estimate — it ignores whether those five pieces could be worn together
    at all. Over-estimating only makes the probe keep more dimensions, which weakens the
    filter without ever making it wrong; under-estimating would do the reverse.
    """
    maxima = dict.fromkeys(quantities, 0.0)
    for bucket in by_slot.values():
        vectors = [stat_vector(candidate, quantities) for candidate in bucket]
        if not vectors:
            continue
        for index, quantity in enumerate(quantities):
            maxima[quantity] += max(vector[index] for vector in vectors)
    return maxima


# ---- The probe ------------------------------------------------------------


def _probe(
    base_contributions: Sequence[Contribution],
    hit: Hit,
    enemy: Enemy,
    character_level: int,
    extra: Mapping[str, float],
) -> float:
    """Score a hypothetical stat bundle through the same evaluator the search uses.

    Not a cheaper approximation of the scoring function — *the* scoring function. A probe
    that modelled damage its own way could declare a dimension dead that the real chain
    reads, and the pruning built on top of it would be silently lossy.
    """
    log = build_log(NodeRegistry())
    log.replay(base_contributions)
    for quantity, value in extra.items():
        log.add(quantity, value, tags.SRC_ARTIFACT, "prefilter probe")
    evaluator = BuildEvaluator(
        registry=log.registry, enemy=enemy, character_level=character_level,
    )
    return evaluator.evaluate(hit).expected


def live_quantities(
    *,
    base_contributions: Sequence[Contribution],
    hit: Hit,
    enemy: Enemy,
    character_level: int,
    maxima: Mapping[str, float],
    always_keep: Iterable[str] = (),
) -> tuple[str, ...]:
    """The quantities worth comparing artifacts on for this hit. See the module docstring."""
    kept = {quantity for quantity in always_keep if quantity in maxima}

    at_base = _probe(base_contributions, hit, enemy, character_level, {})
    others_max = dict(maxima)
    at_max = _probe(base_contributions, hit, enemy, character_level, others_max)

    for quantity, ceiling in maxima.items():
        if quantity in kept:
            continue
        if ceiling <= 0:
            # Nothing in the inventory carries it, so it cannot separate two candidates.
            continue
        base_delta = (
            _probe(base_contributions, hit, enemy, character_level, {quantity: ceiling})
            - at_base
        )
        without = {q: v for q, v in others_max.items() if q != quantity}
        max_delta = at_max - _probe(
            base_contributions, hit, enemy, character_level, without,
        )
        if base_delta != 0.0 or max_delta != 0.0:
            kept.add(quantity)
    return tuple(sorted(kept))


# ---- Layer one: lossless --------------------------------------------------


def dominates(
    left: tuple[float, ...], right: tuple[float, ...], left_id: str, right_id: str,
) -> bool:
    """Whether `left` makes `right` redundant.

    Weak dominance in every dimension plus strict in at least one. An exact tie qualifies
    too — two identical vectors cannot differ in damage — with the lower id kept, so that a
    group of duplicates collapses to exactly one survivor instead of all of them removing
    each other.
    """
    if any(a < b for a, b in zip(left, right, strict=True)):
        return False
    if any(a > b for a, b in zip(left, right, strict=True)):
        return True
    return left_id < right_id


def pareto_filter(
    by_slot: Mapping[str, Sequence[ArtifactCandidate]], quantities: Sequence[str],
) -> tuple[dict[str, list[ArtifactCandidate]], int]:
    """Drop every candidate dominated within its `(slot, set_id)` group.

    Grouping by set as well as slot is what keeps this lossless: a strictly weaker piece of
    a different set is not redundant, because it may be the fourth piece of a set bonus that
    is worth more than the stats it gives up. Main stat needs no such grouping — once the
    comparison is projected onto the live quantities, a main stat is just a large
    contribution to one of them, and a piece with a dead main stat is comparable to one with
    a live one on exactly the terms that matter.
    """
    groups: dict[tuple[str, int], list[ArtifactCandidate]] = {}
    for slot, bucket in by_slot.items():
        for candidate in bucket:
            groups.setdefault((slot, candidate.set_id), []).append(candidate)

    dominated: set[str] = set()
    for group in groups.values():
        vectors = {c.artifact_id: stat_vector(c, quantities) for c in group}
        for candidate in group:
            mine = vectors[candidate.artifact_id]
            if any(
                dominates(vectors[other.artifact_id], mine, other.artifact_id,
                          candidate.artifact_id)
                for other in group
                if other.artifact_id != candidate.artifact_id
            ):
                dominated.add(candidate.artifact_id)

    kept: dict[str, list[ArtifactCandidate]] = {}
    removed = 0
    for slot, bucket in by_slot.items():
        survivors = [c for c in bucket if c.artifact_id not in dominated]
        removed += len(bucket) - len(survivors)
        kept[slot] = survivors
    return kept, removed


# ---- Layer two: lossy -----------------------------------------------------


def combination_count(by_slot: Mapping[str, Sequence[ArtifactCandidate]]) -> int:
    """Size of the Cartesian product over the buckets."""
    total = 1
    for bucket in by_slot.values():
        total *= len(bucket)
    return total


def budget_k(
    by_slot: Mapping[str, Sequence[ArtifactCandidate]],
    requested: int | None,
    budget: int,
) -> int | None:
    """The K budget-K should use, or None to search exhaustively.

    A caller's explicit K wins, `EXACT` forces the full search, and `None` means "decide" —
    in which case an inventory that already fits inside the budget is searched exactly and
    one that does not gets the **largest** K that fits, found by bisection rather than by a
    fixed step, so the search gives up as little as the budget allows.
    """
    if requested == EXACT:
        return None
    if requested is not None:
        return requested
    if combination_count(by_slot) <= budget:
        return None
    sizes = [len(bucket) for bucket in by_slot.values()]
    low, high = 1, max(sizes, default=1)
    while low < high:
        mid = (low + high + 1) // 2
        product = 1
        for size in sizes:
            product *= min(size, mid)
        if product <= budget:
            low = mid
        else:
            high = mid - 1
    return low


def automatic_budget() -> int:
    """How many combinations fit in the wall-clock target, from the measured per-combo cost."""
    return max(1, int(COMBINATION_BUDGET_SECONDS / SECONDS_PER_COMBINATION))


def _reference_filler(
    by_slot: Mapping[str, Sequence[ArtifactCandidate]], quantities: Sequence[str],
) -> dict[str, float]:
    """The average inventory piece, scaled to the **four** slots a candidate does not fill.

    Solo scores are compared against each other, so what matters is that each candidate is
    valued at a realistic operating point rather than against a bare character. Crit DMG on
    a build with no crit rate is worth nothing, and ranking pieces in that context would put
    every crit DMG goblet at the bottom of the list.

    Four, not five (the ZZZ version's factor): the candidate being scored fills the fifth
    slot itself, and scaling to five would count it twice.
    """
    filler_slots = 4.0
    totals = dict.fromkeys(quantities, 0.0)
    count = 0
    for bucket in by_slot.values():
        for candidate in bucket:
            count += 1
            for quantity, value in zip(quantities, stat_vector(candidate, quantities),
                                       strict=True):
                totals[quantity] += value
    if not count:
        return {}
    scale = filler_slots / count
    return {q: v * scale for q, v in totals.items() if v}


def solo_scores(
    *,
    by_slot: Mapping[str, Sequence[ArtifactCandidate]],
    quantities: Sequence[str],
    base_contributions: Sequence[Contribution],
    hit: Hit,
    enemy: Enemy,
    character_level: int,
) -> dict[str, float]:
    """Rank each candidate by what it is worth on an average build. O(inventory).

    This is the heuristic. It cannot see set bonuses — they need pieces this scoring does
    not have — which is exactly why dropping candidates on the strength of it is disclosed
    rather than assumed away.
    """
    filler = _reference_filler(by_slot, quantities)
    scores: dict[str, float] = {}
    for bucket in by_slot.values():
        for candidate in bucket:
            extra = dict(filler)
            for quantity, value in zip(quantities, stat_vector(candidate, quantities),
                                       strict=True):
                if value:
                    extra[quantity] = extra.get(quantity, 0.0) + value
            scores[candidate.artifact_id] = _probe(
                base_contributions, hit, enemy, character_level, extra,
            )
    return scores


def apply_budget_k(
    by_slot: Mapping[str, Sequence[ArtifactCandidate]],
    k: int,
    scores: Mapping[str, float],
    floor_quantities: Sequence[str] = (),
) -> tuple[dict[str, list[ArtifactCandidate]], int]:
    """Keep each slot's best K by solo score, plus whatever a stat floor needs.

    The floor keep is the one exception to the damage ranking, and it is not a matter of
    taste: a piece can rank last on damage and still be the only one in the slot that gets
    the build over an Energy Recharge floor. Dropping it turns a constraint the caller
    asked for into "no builds found", which reads as a bug in the inventory rather than in
    the accelerator that caused it.
    """
    kept: dict[str, list[ArtifactCandidate]] = {}
    removed = 0
    for slot, bucket in by_slot.items():
        if len(bucket) <= k:
            kept[slot] = list(bucket)
            continue
        by_damage = sorted(bucket, key=lambda c: scores.get(c.artifact_id, 0.0),
                           reverse=True)
        survivors = {c.artifact_id: c for c in by_damage[:k]}
        for index, _quantity in enumerate(floor_quantities):
            best = sorted(
                bucket,
                key=lambda c, i=index: stat_vector(c, floor_quantities)[i],
                reverse=True,
            )
            for candidate in best[:FLOOR_KEEP_PER_QUANTITY]:
                survivors.setdefault(candidate.artifact_id, candidate)
        # Original order, so a run is reproducible and a diff of two runs is readable.
        ordered = [c for c in bucket if c.artifact_id in survivors]
        removed += len(bucket) - len(ordered)
        kept[slot] = ordered
    return kept, removed


def prune(
    *,
    by_slot: Mapping[str, Sequence[ArtifactCandidate]],
    base_contributions: Sequence[Contribution],
    hit: Hit,
    enemy: Enemy,
    character_level: int,
    floor_quantities: Iterable[str] = (),
    prefilter_top_k: int | None = None,
    budget: int | None = None,
) -> tuple[dict[str, list[ArtifactCandidate]], PrefilterReport]:
    """Run both layers, lossless first, and report what each one did."""
    quantities = inventory_quantities(by_slot)
    total_space = combination_count(by_slot)
    maxima = reachable_maxima(by_slot, quantities)
    live = live_quantities(
        base_contributions=base_contributions,
        hit=hit,
        enemy=enemy,
        character_level=character_level,
        maxima=maxima,
        always_keep=floor_quantities,
    )

    # Lossless first: it shrinks the buckets the budget estimator then sizes K against.
    survivors, pareto_removed = pareto_filter(by_slot, live)

    k = budget_k(survivors, prefilter_top_k,
                 automatic_budget() if budget is None else budget)
    prefiltered = 0
    if k is not None:
        scores = solo_scores(
            by_slot=survivors, quantities=live, base_contributions=base_contributions,
            hit=hit, enemy=enemy, character_level=character_level,
        )
        survivors, prefiltered = apply_budget_k(
            survivors, k, scores, tuple(floor_quantities),
        )

    return survivors, PrefilterReport(
        pareto_removed=pareto_removed,
        prefiltered=prefiltered,
        effective_k=k if prefiltered else None,
        live_quantities=live,
        total_space=total_space,
    )
