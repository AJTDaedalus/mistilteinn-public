"""Evaluate one hit against one enemy, from a build's registered contributions.

The join between the two halves of Chunk F: `app.formula.genshin.stats` aggregates a build
into totals (with scope gating), and `app.formula.genshin.damage` multiplies them into a
number. This module reads the first with the hit's scope in context and hands the result to
the second.

**It contains no game constants.** Every multiplier lives in `damage.py` beside its
citation; everything here is plumbing. That separation is what keeps "where does this number
come from" answerable in one file rather than two.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class Enemy:
    """The target of a hit.

    `resistances` is per damage channel and defaults to nothing, which is **not** the same
    as a defenceless enemy: `resistance_for` raises for a channel the profile does not
    mention, because silently treating an unlisted channel as 0% RES would overstate every
    hit against it by around 10%.
    """

    level: int
    resistances: dict[str, float]
    def_reduction: float = 0.0
    def_ignore: float = 0.0

    def resistance_for(self, channel: str) -> float:
        """This enemy's resistance in one channel."""
        if channel not in self.resistances:
            msg = (
                f"this enemy profile does not give a {channel} resistance (it has "
                f"{sorted(self.resistances)}). Treating a missing channel as 0% would "
                f"overstate every hit against it."
            )
            raise DamageInputError(msg)
        return self.resistances[channel]


def evaluate_hit(
    registry: NodeRegistry, hit: Hit, enemy: Enemy, character_level: int,
) -> DamageResult:
    """Resolve the stats this hit needs and run the damage chain.

    The DMG bonus is read with the hit's **scope** in context, so scope-gated buffs apply to
    exactly the attacks they name. Resistance shred registered against the enemy's channel
    is picked up the same way — it is a negative contribution to the same pool (F.2), so a
    Deepwood 4-piece and the enemy's own 10% resolve to a single number here.
    """
    calculator = Calculator(registry=registry)

    def value(node: AnyNode) -> float:
        return float(calculator.compute(node))

    channel_res = enemy.resistance_for(hit.channel)
    shred = value(stats.res_node(hit.channel))

    return compute_damage(
        hit,
        scaling_value=value(_SCALING_NODES[hit.scaling_stat]),
        dmg_bonus=value(stats.hit_dmg_bonus_node(hit.channel, hit.scope)),
        crit_rate=value(stats.CRIT_RATE_NODE),
        crit_dmg=value(stats.CRIT_DMG_NODE),
        elemental_mastery=value(stats.ELEMENTAL_MASTERY_NODE),
        character_level=character_level,
        enemy_level=enemy.level,
        # The enemy's own resistance plus whatever has been registered against that
        # channel. Shred is negative, which is why RES can go below zero and why the curve
        # has a branch for it.
        resistance=channel_res + shred,
        def_reduction=enemy.def_reduction,
        def_ignore=enemy.def_ignore,
    )


def enemy_from_profile(
    level: int, resistances: dict[str, float], **modifiers: float,
) -> Enemy:
    """Build an `Enemy` from a stored profile's eight resistance columns.

    Kept here rather than on the model so that `EnemyProfile`'s ORM row and this dataclass
    stay independent — the optimizer evaluates enemies that were never in the database.
    """
    unknown = sorted(set(resistances) - set(tags.DAMAGE_CHANNELS))
    if unknown:
        msg = f"{unknown} are not damage channels; the eight are {tags.DAMAGE_CHANNELS}"
        raise DamageInputError(msg)
    return Enemy(level=level, resistances=dict(resistances), **modifiers)
