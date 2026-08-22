"""Run an artifact search as a background job.

The search is CPU-bound and synchronous; the request that starts it is neither. This module
is the seam: it resolves everything the search needs while it still has a database session,
then hands a **plain callable over plain data** to `JobRunner`, which runs it on a worker
thread with no session at all.

That async-resolve → sync-search split is the one genuinely reusable idea in fairy's
`optimizer_pipeline.py` (deleted in G.8), and it is here rather than in the route because
the route should not know that a search has two phases.

## When a job is used at all

`POST /builds/{id}/optimize` stays **synchronous** for a search that will finish inside
`SYNC_COMBINATION_LIMIT`. A user with one character's worth of artifacts should get an
answer, not a job id to poll — and a contract that always returned a job id would make the
common case worse to use in order to serve the rare one.

The threshold is derived from the measured `SECONDS_PER_COMBINATION`, not chosen: it is how
many combinations fit in `SYNC_SECONDS`. If the damage chain gets slower the threshold falls
with it, so the promise the number encodes — "this returns quickly" — stays true without
anyone remembering to re-tune it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.services import artifact_optimizer, artifact_prefilter

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Sequence

    from app.formula.genshin.damage import Hit
    from app.formula.genshin.explain import Contribution
    from app.services.artifact_optimizer import (
        ArtifactCandidate,
        OptimizerConstraints,
        OptimizerProgress,
        SetBonus,
    )
    from app.services.damage_calculator import Enemy

#: How long a synchronous optimize is allowed to take before it becomes a job instead.
#: Five seconds: long enough that an ordinary inventory never round-trips through a job,
#: short enough that nothing sits on a connection waiting.
SYNC_SECONDS: float = 5.0


def sync_combination_limit() -> int:
    """Combinations that fit in `SYNC_SECONDS`, from the measured per-combination cost.

    Derived rather than chosen, so the threshold tracks the thing it is a promise about.
    `tests/perf` is what keeps `SECONDS_PER_COMBINATION` honest.
    """
    return max(1, int(SYNC_SECONDS / artifact_prefilter.SECONDS_PER_COMBINATION))


def estimated_combinations(candidates: Sequence[ArtifactCandidate]) -> int:
    """The raw per-slot product, before any pruning.

    Deliberately an over-estimate: the Pareto layer will remove some of it, and budget-K may
    remove more. Over-estimating sends a borderline search to a job, which is the safe
    direction — the other way round is a request that times out.
    """
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.slot] = counts.get(candidate.slot, 0) + 1
    if len(counts) < len(artifact_optimizer.SLOTS):
        # A missing slot makes the product zero, which would read as "trivially small" and
        # send an unsatisfiable search down the synchronous path. It is unsatisfiable either
        # way; running it synchronously is how the caller gets told so immediately.
        return 0
    total = 1
    for count in counts.values():
        total *= count
    return total


@dataclass(frozen=True, slots=True)
class SearchPayload:
    """Everything a search needs, with nothing that holds a database session.

    Frozen and made of plain values on purpose: it crosses onto a worker thread, and an ORM
    object crossing with it would lazy-load off a closed session — the failure G.11 turned
    into a loud error rather than a 500.
    """

    base_contributions: tuple[Contribution, ...]
    candidates: tuple[ArtifactCandidate, ...]
    hit: Hit
    enemy: Enemy
    character_level: int
    set_bonuses: tuple[SetBonus, ...]
    constraints: OptimizerConstraints


def search_fn(
    payload: SearchPayload,
    to_response: Callable[[artifact_optimizer.OptimizerResult], dict[str, Any]],
) -> Callable[[threading.Event, Callable[[OptimizerProgress], None]], dict[str, Any]]:
    """The callable `JobRunner.submit_search` runs.

    Cancellation is cooperative and goes through the progress callback: the optimizer offers
    one every couple of seconds and stops when it raises. There is no other way into a
    synchronous loop, which is why `optimize` was built to take the callback in the first
    place.
    """
    def run(
        cancel_event: threading.Event,
        report: Callable[[OptimizerProgress], None],
    ) -> dict[str, Any]:
        def on_progress(progress: OptimizerProgress) -> None:
            if cancel_event.is_set():
                raise artifact_prefilter.Cancelled
            report(progress)

        result = artifact_optimizer.optimize(
            payload.base_contributions,
            payload.candidates,
            payload.hit,
            payload.enemy,
            character_level=payload.character_level,
            set_bonuses=payload.set_bonuses,
            constraints=payload.constraints,
            progress_callback=on_progress,
        )
        return to_response(result)

    return run
