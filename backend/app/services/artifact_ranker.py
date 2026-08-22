"""Rank artifacts by what they are worth, not by what they look like.

The optimizer answers "what is my best build". This answers the question a player actually
has in front of a full inventory: **"which of these is worth keeping, and which slot should
I farm next?"** They are different questions and the second one is not a by-product of the
first — a piece can be absent from the single best build and still be the second-best
goblet by a wide margin, or be worthless for one character and the clear winner for another.

## The measure

For each artifact, swap it into its own slot in a build that is otherwise unchanged, and
compare the damage to the same build with whatever is currently equipped there. The
difference is that piece's **marginal value**, in that context.

Marginal, because that is the decision being made. A flat "score" that ignores what the
piece is replacing tells a player their worst flower is excellent, which is true and
useless: they already have a better one.

## Contexts

A ranking over one character is a ranking that will be wrong the next time the player pulls
someone. So a `RankContext` is one (build, hit, enemy) triple, several can be supplied, and
each artifact reports its improvement in every one of them plus the mean and the best. The
mean says "worth keeping"; the best-and-where says "worth keeping *for Ganyu*", which is
what decides whether it gets locked or fed to a mountain.

Contexts carry a `weight` so a main team can outvote an experiment without being the only
thing counted.

## What this deliberately does not do

**No upgrade simulation.** "What could this +0 piece become at +20" needs the number of
substat rolls a piece gains as it levels, and that rule is not in the committed snapshot —
`app/data/yuanshen/snapshot/artifact_substat_values.json` publishes the roll *values* and
the depots, not the schedule. Writing the schedule from memory is exactly what this repo
forbids, and a potential score built on a guessed roll count would be a confident number
with nothing behind it. It stays out until the rule can be cited. `TODO(chunk-G.9)`.

**No scoring of its own.** Every damage figure here comes from
`artifact_optimizer.build_combination_log` and `BuildEvaluator` — the same path the search
and the single-build display use.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.artifact_optimizer import (
    SLOTS,
    OptimizerInputError,
    bonuses_by_set,
    build_combination_log,
    validated_stats,
)
from app.services.damage_calculator import BuildEvaluator

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from app.formula.genshin.damage import Hit
    from app.formula.genshin.explain import Contribution
    from app.services.artifact_optimizer import ArtifactCandidate, SetBonus
    from app.services.damage_calculator import Enemy
    from app.services.stat_calculator import ArtifactStats

#: How often the ranking offers the callback a chance to look at it, and to cancel.
PROGRESS_TICK_SECONDS: float = 2.0


@dataclass(frozen=True, slots=True)
class RankContext:
    """One build the ranking should care about, and the hit it is judged on."""

    #: What a user calls this — "Ganyu melt", "Nahida quicken". Appears in the result, so it
    #: has to mean something to the person reading it.
    name: str
    base_contributions: tuple[Contribution, ...]
    #: The five artifacts currently worn. One per slot; that is what makes a swap a swap.
    equipped: tuple[ArtifactCandidate, ...]
    hit: Hit
    enemy: Enemy
    character_level: int
    #: Relative importance. A main team should outvote an experiment without silencing it.
    weight: float = 1.0

    def __post_init__(self) -> None:
        worn = {candidate.slot for candidate in self.equipped}
        if worn != set(SLOTS):
            missing = sorted(set(SLOTS) - worn)
            msg = (
                f"context {self.name!r} has no artifact in {missing}. A ranking measures "
                f"what a piece is worth *instead of* what is worn, so every slot must be "
                f"filled."
            )
            raise OptimizerInputError(msg)
        if len(self.equipped) != len(SLOTS):
            msg = f"context {self.name!r} wears two artifacts in one slot"
            raise OptimizerInputError(msg)
        if self.weight <= 0:
            msg = f"context {self.name!r} has weight {self.weight}; it must be positive"
            raise OptimizerInputError(msg)


@dataclass(frozen=True, slots=True)
class ContextScore:
    """One artifact's value in one context."""

    context: str
    #: Damage of the build with this piece swapped in.
    damage: float
    #: Damage of that context's build as currently equipped.
    baseline: float

    @property
    def improvement(self) -> float:
        """Raw damage gained by wearing this piece instead of the equipped one."""
        return self.damage - self.baseline

    @property
    def improvement_pct(self) -> float:
        """Improvement as a percentage of the baseline.

        Zero baseline gives zero rather than an exception or an infinity: a context whose
        equipped build does no damage is a real thing to hand this (an unbuilt character),
        and every candidate is equally "infinitely better" there, which is not a ranking.
        """
        if self.baseline == 0.0:
            return 0.0
        return self.improvement / self.baseline * 100.0


@dataclass(frozen=True, slots=True)
class RankedArtifact:
    """One artifact, and what it is worth across every context."""

    artifact_id: str
    slot: str
    scores: tuple[ContextScore, ...]
    #: Weighted mean improvement percentage. The "is this worth keeping at all" number.
    mean_improvement_pct: float
    #: Its best context and that context's improvement. The "keep it *for whom*" number,
    #: which the mean hides — a piece that is superb for one character and useless for four
    #: averages out to unremarkable, and a player who fed it away would be right to be cross.
    best_improvement_pct: float
    best_context: str

    def __lt__(self, other: RankedArtifact) -> bool:
        return self.mean_improvement_pct < other.mean_improvement_pct


@dataclass(frozen=True, slots=True)
class RankProgress:
    """Where the ranking has got to."""

    scored: int
    total: int
    elapsed_seconds: float

    @property
    def fraction(self) -> float:
        """Progress in 0..1."""
        if self.total <= 0:
            return 1.0
        return self.scored / self.total


@dataclass(frozen=True, slots=True)
class RankResult:
    """Every candidate, best first, plus each context's baseline."""

    artifacts: tuple[RankedArtifact, ...]
    baselines: dict[str, float] = field(default_factory=dict)
    #: Set affixes met during the ranking whose effect is conditional text (Chunk H), by
    #: `(set_id, pieces)`. The optimizer reports these; a ranking that dropped them would
    #: leave "why is this 4-piece worth nothing" unanswerable in exactly the tool a player
    #: consults *before* deciding to keep the piece.
    skipped_conditional_bonuses: int = 0

    def for_slot(self, slot: str) -> tuple[RankedArtifact, ...]:
        """Just one slot's ranking — "what should I farm" is asked a slot at a time."""
        if slot not in SLOTS:
            msg = f"{slot!r} is not an artifact slot; the five are {SLOTS}"
            raise OptimizerInputError(msg)
        return tuple(a for a in self.artifacts if a.slot == slot)


def rank(
    candidates: Iterable[ArtifactCandidate],
    contexts: Sequence[RankContext],
    set_bonuses: Iterable[SetBonus] = (),
    progress_callback: Callable[[RankProgress], None] | None = None,
) -> RankResult:
    """Rank every candidate by its marginal value across `contexts`.

    Cost is `len(candidates) * len(contexts)` build evaluations — linear in the inventory,
    not the fifth power of it, which is why this can run over a full account when a search
    over the same inventory cannot.
    """
    if not contexts:
        msg = "a ranking needs at least one context; there is nothing to be worth more than"
        raise OptimizerInputError(msg)

    bonuses = bonuses_by_set(set_bonuses)
    inventory = list(candidates)

    # Every piece is validated and its stat record built **once**, not once per swap. The
    # unchanged four-fifths of a build were being re-validated for every candidate in every
    # context — the same repeated-immutable-work finding the PR #9 review raised against the
    # search, at a smaller exponent and no more justified for it.
    resolved: dict[str, ArtifactStats] = {}
    for candidate in (*inventory, *(worn for c in contexts for worn in c.equipped)):
        if candidate.artifact_id not in resolved:
            resolved[candidate.artifact_id] = validated_stats(candidate)

    skipped: set[tuple[int, int]] = set()
    baselines = {}
    for context in contexts:
        baselines[context.name] = _damage(
            context, context.equipped, bonuses, resolved, skipped,
        )
    total_weight = sum(context.weight for context in contexts)
    total = len(inventory) * len(contexts)
    started = time.monotonic()
    next_tick = started + PROGRESS_TICK_SECONDS
    scored = 0

    ranked: list[RankedArtifact] = []
    for candidate in inventory:
        # No slot check here: `validated_stats` above already refuses a slot that is not one
        # of the five, with the same list in the message. A second copy would be a second
        # place for that list to be right.
        scores = []
        for context in contexts:
            swapped = tuple(
                candidate if worn.slot == candidate.slot else worn
                for worn in context.equipped
            )
            scores.append(ContextScore(
                context=context.name,
                damage=_damage(context, swapped, bonuses, resolved, skipped),
                baseline=baselines[context.name],
            ))
            scored += 1
            if progress_callback is not None:
                now = time.monotonic()
                if now >= next_tick:
                    next_tick = now + PROGRESS_TICK_SECONDS
                    progress_callback(RankProgress(scored, total, now - started))

        best = max(scores, key=lambda s: s.improvement_pct)
        weighted = sum(
            score.improvement_pct * context.weight
            for score, context in zip(scores, contexts, strict=True)
        )
        ranked.append(RankedArtifact(
            artifact_id=candidate.artifact_id,
            slot=candidate.slot,
            scores=tuple(scores),
            mean_improvement_pct=weighted / total_weight,
            best_improvement_pct=best.improvement_pct,
            best_context=best.context,
        ))

    if progress_callback is not None:
        progress_callback(RankProgress(scored, total, time.monotonic() - started))

    return RankResult(
        artifacts=tuple(sorted(ranked, reverse=True)),
        baselines=baselines,
        skipped_conditional_bonuses=len(skipped),
    )


def _damage(
    context: RankContext,
    combination: Sequence[ArtifactCandidate],
    bonuses: dict[int, list[SetBonus]],
    resolved: dict[str, ArtifactStats],
    skipped: set[tuple[int, int]],
) -> float:
    """One build's damage, through the one path that defines what a build is worth.

    `skipped` is accumulated into, by tier identity rather than by count — the same
    correction the PR #9 review made to the search, where summing per combination turned
    one conditional 4-piece into a report of millions.
    """
    log, tiers = build_combination_log(
        context.base_contributions, combination, bonuses, resolved=resolved,
    )
    skipped |= tiers
    evaluator = BuildEvaluator(
        registry=log.registry,
        enemy=context.enemy,
        character_level=context.character_level,
    )
    return evaluator.evaluate(context.hit).expected
