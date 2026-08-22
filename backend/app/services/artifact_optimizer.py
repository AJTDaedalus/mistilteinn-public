"""Search a user's artifacts for the build that does the most damage.

Five slots, a pool of owned pieces per slot, and one question: which combination maximises
the damage of a described hit. The search is exhaustive here; the pruning machinery
(top-K prefilter, Pareto, budget-K) is G.3's port and slots in around this.

## What this does not contain

**No damage math and no stat math.** Scoring a candidate goes through
`app.services.stat_calculator` and `app.services.damage_calculator`, the same path a single
build's figure takes. That is DESIGN §1 A6's "one mechanic, one implementation": an
optimizer with its own scoring shortcut is how a tool ends up recommending builds its own
calculator disagrees with, and the disagreement is invisible until a user notices.

The cost is real — a full stat resolution per candidate — and it is the right cost to pay
first. G.3's prefilters make the search smaller; they do not make the scoring cheaper by
making it different.

## Set bonuses

A set's piece thresholds are **data** (C.5): 60 of the 65 sets at 7.0.51 are `[2, 4]` and
five are `[1]` — the "Prayers" circlets. The optimizer reads each set's own thresholds, so
the five one-piece sets are searched correctly rather than being invisible.

Only an affix's **static** `add_props` are applied. A conditional bonus ("after using an
Elemental Skill…") has `FIGHT_PROP_NONE` for every prop and its numbers live in
`param_list`; turning that text into a modifier is Chunk H's job, and guessing at it here
would silently score builds on effects this repo cannot yet model. The count of skipped
conditional affixes is reported, so "why is my 4pc not showing up" has an answer.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.data.snapshot import main_stat_pools
from app.formula.genshin import tags
from app.pando.calculator import NodeRegistry
from app.services.damage_calculator import BuildEvaluator
from app.services.stat_calculator import (
    ArtifactStats,
    StatInputError,
    _quantity_for_prop,
    add_artifact,
    build_log,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from app.formula.genshin.damage import Hit
    from app.formula.genshin.explain import Contribution, ContributionLog
    from app.services.damage_calculator import Enemy

#: Slot order, and the only slot vocabulary this module knows. Values are
#: `app.models.enums.ArtifactSlot`'s, which are the payload's `parts` keys.
SLOTS: tuple[str, ...] = (
    "equip_bracer",     # flower
    "equip_necklace",   # plume
    "equip_shoes",      # sands
    "equip_ring",       # goblet
    "equip_dress",      # circlet
)

#: The absent-prop marker a conditional affix uses for every one of its props (C.5).
_NO_PROP = "FIGHT_PROP_NONE"


class OptimizerInputError(ValueError):
    """A search was described in a way that cannot be run."""


@dataclass(frozen=True, slots=True)
class ArtifactCandidate:
    """One owned artifact, ready to be searched over."""

    artifact_id: str
    slot: str
    set_id: int
    rarity: int
    level: int
    main_stat: str
    substats: tuple[dict[str, object], ...] = ()

    def as_stats(self) -> ArtifactStats:
        """The shape `stat_calculator` consumes."""
        return ArtifactStats(
            slot=self.slot,
            rarity=self.rarity,
            level=self.level,
            main_stat=self.main_stat,
            substats=list(self.substats),
        )


@dataclass(frozen=True, slots=True)
class SetBonus:
    """One tier of one set's bonus, as the importer stored it."""

    set_id: int
    pieces_required: int
    #: `[{prop_type, value}, …]` — the affix's static props. A conditional affix's are all
    #: `FIGHT_PROP_NONE`, and this optimizer skips those; see the module docstring.
    add_props: tuple[dict[str, object], ...] = ()

    @property
    def is_conditional(self) -> bool:
        """True when the affix grants nothing this repo can apply yet."""
        return all(
            str(prop.get("prop_type", _NO_PROP)).upper() == _NO_PROP
            for prop in self.add_props
        ) if self.add_props else True


@dataclass(frozen=True, slots=True)
class OptimizerConstraints:
    """What the search is allowed to return.

    `locked_slots` pins a slot to one artifact — the "I am not re-rolling my flower" case,
    and the cheapest possible pruning.
    """

    locked_slots: dict[str, str] = field(default_factory=dict)
    #: `{set_id: minimum pieces}`. Rejected before scoring.
    required_sets: dict[int, int] = field(default_factory=dict)
    #: `{quantity: minimum}` over resolved stats — an energy-recharge floor, typically.
    min_stats: dict[str, float] = field(default_factory=dict)
    top_n: int = 10


@dataclass(frozen=True, slots=True)
class OptimizedBuild:
    """One scored combination."""

    damage: float
    artifact_ids: tuple[str, ...]
    set_counts: dict[int, int]
    #: The winning build's account of itself — A6 reaches the optimizer too: a
    #: recommendation nobody can interrogate is a recommendation nobody should act on.
    contributions: tuple[Contribution, ...] = ()

    def __lt__(self, other: OptimizedBuild) -> bool:
        """Ordering for the top-N heap, by damage."""
        return self.damage < other.damage


@dataclass(frozen=True, slots=True)
class OptimizerResult:
    """The ranked builds, and what the search did to get them."""

    builds: tuple[OptimizedBuild, ...]
    evaluated: int
    rejected_by_sets: int
    rejected_by_stats: int
    #: Set affixes skipped because their effect is conditional text (Chunk H). Reported so
    #: "why is my 4-piece not showing up" has an answer that is not a shrug.
    skipped_conditional_bonuses: int = 0


def optimize(
    base_contributions: Sequence[Contribution],
    candidates: Iterable[ArtifactCandidate],
    hit: Hit,
    enemy: Enemy,
    character_level: int,
    set_bonuses: Iterable[SetBonus] = (),
    constraints: OptimizerConstraints | None = None,
) -> OptimizerResult:
    """Score every allowed five-piece combination and return the best.

    `base_contributions` is the character-and-weapon half of the build, already resolved by
    `stat_calculator` — it does not change across candidates, so it is computed once and
    replayed rather than rebuilt.
    """
    constraints = constraints or OptimizerConstraints()
    by_slot = _bucket_by_slot(candidates, constraints)
    bonuses = _bonuses_by_set(set_bonuses)

    evaluated = 0
    rejected_by_sets = 0
    rejected_by_stats = 0
    skipped_conditional = 0
    best: list[OptimizedBuild] = []

    for combination in itertools.product(*(by_slot[slot] for slot in SLOTS)):
        counts = _count_sets(combination)
        if not _satisfies_sets(counts, constraints.required_sets):
            rejected_by_sets += 1
            continue

        log = build_log(NodeRegistry())
        for contribution in base_contributions:
            log.add(
                contribution.quantity, contribution.value, contribution.source,
                contribution.note, tag=contribution.tag,
            )
        for candidate in combination:
            add_artifact(log, candidate.as_stats())
        skipped_conditional += _apply_set_bonuses(log, counts, bonuses)

        evaluator = BuildEvaluator(
            registry=log.registry, enemy=enemy, character_level=character_level,
        )
        if not _meets_floors(evaluator, constraints.min_stats, hit.scope):
            rejected_by_stats += 1
            continue

        evaluated += 1
        build = OptimizedBuild(
            damage=evaluator.evaluate(hit).expected,
            artifact_ids=tuple(candidate.artifact_id for candidate in combination),
            set_counts=counts,
            contributions=tuple(log.contributions),
        )
        # A bounded heap, so a search over a large inventory holds `top_n` builds rather
        # than every build it has ever scored.
        if len(best) < constraints.top_n:
            heapq.heappush(best, build)
        elif build.damage > best[0].damage:
            heapq.heappushpop(best, build)

    return OptimizerResult(
        builds=tuple(sorted(best, key=lambda entry: entry.damage, reverse=True)),
        evaluated=evaluated,
        rejected_by_sets=rejected_by_sets,
        rejected_by_stats=rejected_by_stats,
        skipped_conditional_bonuses=skipped_conditional,
    )


def _bucket_by_slot(
    candidates: Iterable[ArtifactCandidate], constraints: OptimizerConstraints,
) -> dict[str, list[ArtifactCandidate]]:
    """Group the inventory by slot, honouring locks, and refuse an unfillable search."""
    buckets: dict[str, list[ArtifactCandidate]] = {slot: [] for slot in SLOTS}
    for candidate in candidates:
        if candidate.slot not in buckets:
            msg = f"{candidate.artifact_id} is in slot {candidate.slot!r}; the five are {SLOTS}"
            raise OptimizerInputError(msg)
        buckets[candidate.slot].append(candidate)

    for slot, locked_id in constraints.locked_slots.items():
        if slot not in buckets:
            msg = f"cannot lock unknown slot {slot!r}; the five are {SLOTS}"
            raise OptimizerInputError(msg)
        pinned = [c for c in buckets[slot] if c.artifact_id == locked_id]
        if not pinned:
            msg = f"slot {slot} is locked to {locked_id!r}, which is not in the candidates"
            raise OptimizerInputError(msg)
        buckets[slot] = pinned

    empty = sorted(slot for slot, bucket in buckets.items() if not bucket)
    if empty:
        # An empty slot makes the Cartesian product empty, so the search would return no
        # builds and no reason. A user missing a goblet should be told that.
        msg = f"no candidates for {empty}; every slot needs at least one artifact"
        raise OptimizerInputError(msg)
    return buckets


def _count_sets(combination: Sequence[ArtifactCandidate]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for candidate in combination:
        counts[candidate.set_id] = counts.get(candidate.set_id, 0) + 1
    return counts


def _satisfies_sets(counts: dict[int, int], required: dict[int, int]) -> bool:
    return all(counts.get(set_id, 0) >= minimum for set_id, minimum in required.items())


def _bonuses_by_set(bonuses: Iterable[SetBonus]) -> dict[int, list[SetBonus]]:
    """Group bonuses by set, ascending by piece requirement."""
    grouped: dict[int, list[SetBonus]] = {}
    for bonus in bonuses:
        grouped.setdefault(bonus.set_id, []).append(bonus)
    for tiers in grouped.values():
        tiers.sort(key=lambda tier: tier.pieces_required)
    return grouped


def _apply_set_bonuses(
    log: ContributionLog, counts: dict[int, int], bonuses: dict[int, list[SetBonus]],
) -> int:
    """Register every static set bonus the combination earns. Returns the number skipped.

    Thresholds come from the set's own data, so a one-piece "Prayers" set contributes at one
    piece and a `[2, 4]` set does not.
    """
    skipped = 0
    for set_id, pieces in counts.items():
        for tier in bonuses.get(set_id, ()):
            if pieces < tier.pieces_required:
                continue
            if tier.is_conditional:
                skipped += 1
                continue
            for prop in tier.add_props:
                prop_type = str(prop.get("prop_type", ""))
                if prop_type.upper() == _NO_PROP:
                    continue
                log.add(
                    _quantity_for_prop(prop_type),
                    float(prop.get("value", 0.0)),
                    tags.SRC_ARTIFACT_SET,
                    f"set {set_id} {tier.pieces_required}pc",
                )
    return skipped


def _meets_floors(
    evaluator: BuildEvaluator, floors: dict[str, float], scope: str,
) -> bool:
    """Whether a build clears every declared minimum.

    Read with the hit's scope in context, like every other read in the damage path — a floor
    evaluated without it would disagree with the number the build is finally scored on.
    """
    for quantity, minimum in floors.items():
        node = _FLOOR_NODES.get(quantity)
        if node is None:
            msg = (
                f"{quantity!r} is not a stat this optimizer can put a floor on; "
                f"it knows {sorted(_FLOOR_NODES)}"
            )
            raise StatInputError(msg)
        if evaluator._value(node, scope) < minimum:  # noqa: SLF001 - same package concern
            return False
    return True


def _floor_nodes() -> dict[str, object]:
    from app.formula.genshin import stats  # noqa: PLC0415 - avoids an import cycle at module load

    return {
        tags.Q_ATK: stats.ATK_NODE,
        tags.Q_HP: stats.HP_NODE,
        tags.Q_DEF: stats.DEF_NODE,
        tags.Q_CRIT_RATE: stats.CRIT_RATE_NODE,
        tags.Q_CRIT_DMG: stats.CRIT_DMG_NODE,
        tags.Q_ENERGY_RECHARGE: stats.ENERGY_RECHARGE_NODE,
        tags.Q_ELEMENTAL_MASTERY: stats.ELEMENTAL_MASTERY_NODE,
    }


_FLOOR_NODES = _floor_nodes()


def slot_main_stat_pool(slot: str) -> tuple[str, ...]:
    """The main stats `slot` can roll, from the committed snapshot (G.2).

    Exposed here because candidate *generation* — "what could I farm for this slot" — is the
    same question the optimizer answers over owned pieces, and both should read one table.
    """
    pools = main_stat_pools()
    if slot not in pools:
        msg = f"{slot!r} is not an artifact slot; the five are {sorted(pools)}"
        raise OptimizerInputError(msg)
    return pools[slot]
