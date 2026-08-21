"""Evaluate hits against an enemy, from a build's registered contributions.

The join between the two halves of Chunk F: `app.formula.genshin.stats` aggregates a build
into totals (with scope gating), and `app.formula.genshin.damage` multiplies them into a
number. This module reads the first with the hit's scope in context and hands the result to
the second.

**It contains no game constants.** Every multiplier lives in `damage.py` beside its
citation; everything here is plumbing. That separation is what keeps "where does this number
come from" answerable in one file rather than two.

## Where base resistance lives, and why it is not in the DAG

`Enemy.resistances` carries the enemy's own resistance; the `*_res_shred` pool carries only
what the *build* does to it. One home each. The PR #7 review found them being added
together — a 10% enemy read as 20%, understating every hit by ~11% with no error — and the
names now make that hard to re-introduce.

The split is not arbitrary: an optimizer varies the build across millions of candidates
while the enemy stays fixed, so registering the enemy into every candidate's graph would be
work done a million times for a value that never changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING

from app.formula.genshin import stats, tags
from app.formula.genshin.damage import (
    DamageInputError,
    DamageResult,
    Hit,
    ScalingStat,
    compute_damage,
)
from app.pando.calculator import Calculator

if TYPE_CHECKING:
    from app.formula.nodes import AnyNode
    from app.pando.calculator import NodeRegistry

#: Which resolved stat a hit's `ScalingStat` reads. One place, so a talent scaling off HP
#: needs no branch in the chain and no second lookup table.
_SCALING_NODES = {
    ScalingStat.ATK: stats.ATK_NODE,
    ScalingStat.HP: stats.HP_NODE,
    ScalingStat.DEF: stats.DEF_NODE,
    ScalingStat.ELEMENTAL_MASTERY: stats.ELEMENTAL_MASTERY_NODE,
}


@cache
def _dmg_bonus_node(channel: str) -> AnyNode:
    """The per-channel bonus node, built once.

    Node construction is pure and the graph is immutable, so rebuilding this subtree per hit
    was work an optimizer would repeat millions of times. Cached by channel — eight entries,
    for the lifetime of the process.
    """
    return stats.hit_dmg_bonus_node(channel)


@dataclass(frozen=True, slots=True)
class Enemy:
    """The target of a hit.

    `resistances` must name **all eight** damage channels. A partial profile used to be
    accepted at construction and to fail much later, mid-calculation; the guard belongs at
    the boundary that exists to catch it. Treating an unlisted channel as 0% RES would
    overstate every hit against it by around 10%, in the direction nobody questions.
    """

    level: int
    resistances: dict[str, float]
    def_reduction: float = 0.0
    def_ignore: float = 0.0

    def __post_init__(self) -> None:
        missing = sorted(set(tags.DAMAGE_CHANNELS) - set(self.resistances))
        unknown = sorted(set(self.resistances) - set(tags.DAMAGE_CHANNELS))
        if unknown:
            msg = f"{unknown} are not damage channels; the eight are {tags.DAMAGE_CHANNELS}"
            raise DamageInputError(msg)
        if missing:
            msg = (
                f"this enemy profile gives no resistance for {missing}. All eight channels "
                f"are required: treating a missing one as 0% would overstate every hit "
                f"against it."
            )
            raise DamageInputError(msg)

    def resistance_for(self, channel: str) -> float:
        """This enemy's own resistance in one channel, before the build's shred."""
        return self.resistances[channel]


@dataclass
class BuildEvaluator:
    """One build, evaluated against one enemy, for as many hits as you like.

    Holds the `Calculator` — and therefore its memo cache — across hits. `evaluate_hit`
    below rebuilds one per call, which is fine for a single figure and wrong for an
    optimizer; `damage.py`'s docstring promises the chain can be called millions of times
    without rebuilding a graph, and this is the object that keeps that promise.
    """

    registry: NodeRegistry
    enemy: Enemy
    character_level: int
    _calculator: Calculator = field(init=False)

    def __post_init__(self) -> None:
        self._calculator = Calculator(registry=self.registry)

    def _value(self, node: AnyNode, scope: str) -> float:
        """Resolve a node with the hit's scope in context.

        **Every** read goes through here. Scope used to be applied to the DMG-bonus read
        alone, which made a scope-gated contribution to any other quantity — a scope-gated
        crit rate, say, which Ganyu's first ascension passive is — invisible under every
        scope and silently worth nothing.
        """
        return float(self._calculator.compute(stats.scoped(node, scope)))

    def evaluate(self, hit: Hit) -> DamageResult:
        """Resolve the stats this hit needs and run the damage chain."""
        scope = hit.scope
        resistance = self.enemy.resistance_for(hit.channel) + self._value(
            stats.res_shred_node(hit.channel), scope,
        )
        return compute_damage(
            hit,
            scaling_value=self._value(_SCALING_NODES[hit.scaling_stat], scope),
            dmg_bonus=self._value(_dmg_bonus_node(hit.channel), scope),
            crit_rate=self._value(stats.CRIT_RATE_NODE, scope),
            crit_dmg=self._value(stats.CRIT_DMG_NODE, scope),
            elemental_mastery=self._value(stats.ELEMENTAL_MASTERY_NODE, scope),
            character_level=self.character_level,
            enemy_level=self.enemy.level,
            resistance=resistance,
            # Both enemy-side DEF mechanics read the same way RES shred does: the profile's
            # own value plus whatever the build registers. They used to come from the
            # dataclass only, so a DEF shred registered the natural way was dropped.
            def_reduction=self.enemy.def_reduction
            + self._value(stats.def_reduction_node(), scope),
            def_ignore=self.enemy.def_ignore + self._value(stats.def_ignore_node(), scope),
        )


def evaluate_hit(
    registry: NodeRegistry, hit: Hit, enemy: Enemy, character_level: int,
) -> DamageResult:
    """One hit, one figure. Sugar over `BuildEvaluator` for callers evaluating a single hit.

    Use `BuildEvaluator` directly when evaluating many hits against one build — it keeps the
    calculator's memo cache instead of discarding it per call.
    """
    return BuildEvaluator(
        registry=registry, enemy=enemy, character_level=character_level,
    ).evaluate(hit)


def enemy_from_profile(
    level: int, resistances: dict[str, float], **modifiers: float,
) -> Enemy:
    """Build an `Enemy` from a stored profile's eight resistance columns.

    Kept here rather than on the model so that `EnemyProfile`'s ORM row and this dataclass
    stay independent — the optimizer evaluates enemies that were never in the database.
    """
    return Enemy(level=level, resistances=dict(resistances), **modifiers)
