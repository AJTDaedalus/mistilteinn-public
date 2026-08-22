"""G.7 — the performance baseline for the five-slot artifact search.

**Ported in structure, not in numbers.** fairy's version timed `optimize_discs` over a
six-slot ZZZ inventory and reasoned about the *ratio* between two step shapes rather than
absolute milliseconds, because run-to-run spread on a shared runner was ~35%. That reasoning
ports; the build, the enemy and every import did not, and B.12 skipped the file rather than
deleting it so this task had the harness that produced fairy's numbers to work from.

## What is asserted, and why it is not just "is it fast"

The load-bearing assertion is that the measured cost per combination still matches
**`artifact_prefilter.SECONDS_PER_COMBINATION`** — the constant the automatic budget divides
a 300-second target by. That constant is the only thing standing between a large inventory
and a search that either runs for twenty minutes or prunes lossily when it did not need to.
A perf test that only said "under N seconds" would let it drift silently.

The band is deliberately wide (`_TOLERANCE`). This runs on shared CI hardware where noise is
one-directional — it only ever adds time — so the assertion is an order-of-magnitude
regression guard, not a benchmark. The measured value is printed either way, so
re-baselining is reading one line rather than instrumenting anything.

Two further assertions are **exact**, because they are structural rather than timed: the
lossless layer must actually remove work, and budget-K must actually keep the search inside
its budget. Those are the properties the timing depends on, and they cannot be flaky.

## It runs in CI

`-m perf` is opt-in locally, and `.github/workflows/test.yml` runs it. A perf test nobody
runs is fairy's green-by-absence failure in a new costume — and this repo's rule is that a
check which did not run is not a pass.
"""

from __future__ import annotations

import time

import pytest

from app.formula.genshin import tags
from app.formula.genshin.damage import Hit
from app.services import artifact_prefilter
from app.services.artifact_optimizer import SLOTS, OptimizerConstraints, optimize
from app.services.damage_calculator import Enemy
from scripts.bench_optimizer import base_contributions, build_inventory

pytestmark = pytest.mark.perf

#: Best-of-N, not mean. Noise on a shared runner only ever *adds* time, so the minimum is
#: the closest estimate of the real cost; the mean would mostly measure the box.
_REPEATS = 3

#: How far over `SECONDS_PER_COMBINATION` the measured cost may run before this fails.
#: Eight, because the constant was measured on a developer machine and CI is slower and
#: noisier — this catches "the damage chain got an order of magnitude more expensive",
#: which is what would silently break the budget, and nothing finer.
_TOLERANCE = 8.0

_ENEMY = Enemy(level=90, resistances=dict.fromkeys(tags.DAMAGE_CHANNELS, 0.1))
_HIT = Hit(multiplier=2.0, channel="cryo", scope="burst")
_SEED = 20260821


def _run(inventory, **constraint_kwargs):
    return optimize(
        base_contributions(), inventory, _HIT, _ENEMY, character_level=90,
        constraints=OptimizerConstraints(**constraint_kwargs),
    )


def _time(inventory, **constraint_kwargs) -> tuple[float, object]:
    """Seconds for the best of `_REPEATS` runs, and that run's result."""
    best = float("inf")
    result = None
    for _ in range(_REPEATS):
        started = time.perf_counter()
        result = _run(inventory, **constraint_kwargs)
        best = min(best, time.perf_counter() - started)
    return best, result


def test_cost_per_combination_still_matches_the_budget_constant():
    """`SECONDS_PER_COMBINATION` is what the automatic budget divides 300 seconds by.

    If the real cost drifts above it the budget over-promises and a search runs long; if it
    drifts far below, the budget prunes lossily on inventories it could have searched
    exactly. Either way the number stops describing this program, and nothing else in the
    suite would notice.
    """
    inventory = build_inventory(per_slot=6, seed=_SEED)
    elapsed, result = _time(inventory, prefilter_top_k=artifact_prefilter.EXACT)

    scored = result.evaluated + result.rejected_by_sets + result.rejected_by_stats
    per_combination = elapsed / scored
    ceiling = artifact_prefilter.SECONDS_PER_COMBINATION * _TOLERANCE

    print(
        f"\n[perf] {len(inventory)} pieces, {scored:,} combinations in {elapsed:.3f}s "
        f"→ {per_combination:.3e} s/combination "
        f"(constant {artifact_prefilter.SECONDS_PER_COMBINATION:.3e}, "
        f"ceiling {ceiling:.3e}). Re-baseline with "
        f"`python -m scripts.bench_optimizer`.",
    )

    assert scored > 0
    assert per_combination < ceiling, (
        f"{per_combination:.3e} s/combination is more than {_TOLERANCE}x the constant the "
        f"auto-budget is computed from. Re-measure with scripts/bench_optimizer.py and "
        f"update artifact_prefilter.SECONDS_PER_COMBINATION, or find what got slower."
    )


def test_the_lossless_layer_removes_work_the_search_would_otherwise_do():
    """Exact, not timed. If Pareto stops pruning, the timing above starts measuring a
    different search and the budget constant quietly becomes wrong for the real one."""
    inventory = build_inventory(per_slot=6, seed=_SEED)
    # Every piece duplicated with a strictly worse copy: same slot, same set, same main,
    # each substat reduced. None of them can appear in an optimal build.
    inventory += [
        type(piece)(
            artifact_id=f"{piece.artifact_id}-worse",
            slot=piece.slot, set_id=piece.set_id, rarity=piece.rarity, level=piece.level,
            main_stat=piece.main_stat,
            substats=tuple(
                {**sub, "value": float(sub["value"]) * 0.5} for sub in piece.substats
            ),
        )
        for piece in list(inventory)
    ]

    result = _run(inventory, prefilter_top_k=artifact_prefilter.EXACT)

    assert result.prefilter.pareto_removed > 0
    # Still exact: the lossless layer removing work does not make an answer approximate.
    assert result.is_exact
    assert all(not i.endswith("-worse") for i in result.builds[0].artifact_ids)


def test_budget_k_keeps_the_search_inside_the_budget_it_was_given():
    """Exact, not timed. The budget exists so a large inventory finishes; a K that does not
    actually bound the product would leave that promise unkept while reporting a K."""
    inventory = build_inventory(per_slot=8, seed=_SEED)
    budget = 200

    kept, report = artifact_prefilter.prune(
        by_slot=_by_slot(inventory),
        base_contributions=base_contributions(),
        hit=_HIT,
        enemy=_ENEMY,
        character_level=90,
        budget=budget,
    )

    assert report.effective_k is not None, "this inventory does not fit in the budget"
    assert artifact_prefilter.combination_count(kept) <= budget
    assert not report.is_exact, "a lossy search must say so"


def _by_slot(inventory):
    buckets = {slot: [] for slot in SLOTS}
    for piece in inventory:
        buckets[piece.slot].append(piece)
    return buckets
