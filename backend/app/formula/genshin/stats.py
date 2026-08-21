"""The Genshin stat graph: registered contributions in, resolved totals out.

Pre-built DAG nodes that aggregate whatever has been registered under each quantity's tag.
Nothing here knows about characters, weapons or artifacts — those are *sources* that
register contributions (F.3), and the graph is the same shape whatever wrote to it. That
separation is DESIGN §1 A6's "one mechanic, one implementation" at the stat layer: there is
one place ATK is assembled, and a new source of ATK is a new registration, never a new
branch.

## The formula, and why it is one stage

    total = base * (1 + pct) + flat

for HP, ATK and DEF; every other stat is a single additive pool. Source: gcsim
`pkg/core/attributes/stats.go:44-46` at the pin in `docs/CROSSVAL_gcsim.md`:

    func (s Stats) MaxHP() float64    { return s[BaseHP]*(1+s[HPP]) + s[HP] }
    func (s Stats) TotalATK() float64 { return s[BaseATK]*(1+s[ATKP]) + s[ATK] }
    func (s Stats) TotalDEF() float64 { return s[BaseDEF]*(1+s[DEFP]) + s[DEF] }

**This is a real difference from the ZZZ layer it replaces, not a simplification of it.**
fairy's `formula/zzz/stats.py` ran two stages (`pre` then `final`) because ZZZ distinguishes
ordinary buffs from ones that apply after the percentage pass. Genshin has no such split at
the stat level, so porting the two-stage shape "just in case" would have invented a concept
the game does not have and quietly given every future kit a place to put a wrong answer.

## Units

Fractions throughout: `0.15` is 15%. fairy stored basis points and divided on ingest; this
repo's payloads are already fractions (nanoka's `crit_rate: 0.05`, an affix's
`value: 0.15`), so there is **no conversion anywhere** — and therefore no place for one to
be applied twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.formula.builder import prod_, read_, sum_
from app.formula.genshin.tags import (
    DAMAGE_CHANNELS,
    Q_ATK,
    Q_ATK_PCT,
    Q_BASE_ATK,
    Q_BASE_DEF,
    Q_BASE_HP,
    Q_CRIT_DMG,
    Q_CRIT_RATE,
    Q_DEF,
    Q_DEF_PCT,
    Q_ELEMENTAL_MASTERY,
    Q_ENERGY_RECHARGE,
    Q_FLAT_ATK,
    Q_FLAT_DEF,
    Q_FLAT_HP,
    Q_HEALING_BONUS,
    Q_HP,
    Q_HP_PCT,
    Q_INCOMING_HEALING_BONUS,
    Q_SHIELD_STRENGTH,
    dmg_bonus_q,
    res_q,
    stat_tag,
)

if TYPE_CHECKING:
    from app.formula.nodes import AnyNode


def _pool(quantity: str) -> AnyNode:
    """Every contribution registered under `quantity`, summed.

    A `sum` read over an empty tag is 0, so a stat nothing has contributed to resolves to
    zero rather than raising — which is what makes a partially specified build evaluable at
    all, and why the *damage* chain, not this graph, is where a missing input must complain.
    """
    return read_(stat_tag(quantity), "sum")


def _scaling_stat(base: str, pct: str, flat: str) -> AnyNode:
    """`base * (1 + pct) + flat` — the three-term shape HP, ATK and DEF share."""
    return sum_(prod_(_pool(base), sum_(1, _pool(pct))), _pool(flat))


# ---- Resolved totals ------------------------------------------------------

#: A character's max HP. `base_hp` is the level/ascension curve output; a weapon contributes
#: nothing to it, unlike ATK.
HP_NODE: AnyNode = _scaling_stat(Q_BASE_HP, Q_HP_PCT, Q_FLAT_HP)

#: Total ATK. **`base_atk` is a pool, not a single value**: a character's base ATK and the
#: weapon's base ATK both register into it and are summed before the percentage applies.
#: gcsim does the same — one `BaseATK` slot fed from both — and the ordering matters,
#: because `(char + weapon) * (1 + atk%)` is not `char * (1 + atk%) + weapon`.
ATK_NODE: AnyNode = _scaling_stat(Q_BASE_ATK, Q_ATK_PCT, Q_FLAT_ATK)

#: Total DEF.
DEF_NODE: AnyNode = _scaling_stat(Q_BASE_DEF, Q_DEF_PCT, Q_FLAT_DEF)

#: Elemental Mastery — flat, additive, no percentage form. It is a first-class stat here
#: because Genshin's reactions scale on it (F.6), which is why C.2 gave it an enum member
#: and why the ZZZ layer's Anomaly Proficiency is *not* what it was renamed from.
ELEMENTAL_MASTERY_NODE: AnyNode = _pool(Q_ELEMENTAL_MASTERY)

#: Energy Recharge. A character starts at 100%, so the character source registers `1.0` and
#: everything else adds to it — the base belongs to the source, not to this graph, so that
#: a build with no character loaded resolves to 0 rather than to a fictitious 100%.
ENERGY_RECHARGE_NODE: AnyNode = _pool(Q_ENERGY_RECHARGE)

#: Crit rate and crit damage. Both have per-character base values in the payload
#: (`crit_rate: 0.05`, `crit_dmg: 0.5` in `character_10000002.json`) which the character
#: source registers, for the same reason as Energy Recharge.
CRIT_RATE_NODE: AnyNode = _pool(Q_CRIT_RATE)
CRIT_DMG_NODE: AnyNode = _pool(Q_CRIT_DMG)

HEALING_BONUS_NODE: AnyNode = _pool(Q_HEALING_BONUS)
INCOMING_HEALING_BONUS_NODE: AnyNode = _pool(Q_INCOMING_HEALING_BONUS)
SHIELD_STRENGTH_NODE: AnyNode = _pool(Q_SHIELD_STRENGTH)


def dmg_bonus_node(channel: str) -> AnyNode:
    """The DMG bonus for one damage channel (`pyro`, `physical`, …).

    Built rather than enumerated, so the eight channels stay one tuple in `tags.py`. The
    *generic* `dmg_bonus` quantity is deliberately not summed in here: the damage chain adds
    it once, to whichever channel the hit uses (F.5), and folding it in at the stat layer
    would make it invisible in an explained figure and double-counted in a two-element hit.
    """
    return _pool(dmg_bonus_q(channel))


def res_node(channel: str) -> AnyNode:
    """The enemy's resistance in one damage channel, before the RES-to-multiplier curve.

    The curve is F.5's, and it arrives with its own citation. This is the raw fraction the
    enemy profile carries (`0.1` = 10%) plus any shred registered against it — shred is a
    negative contribution to the same pool, which is why RES can go below zero and why the
    curve has a branch for that.
    """
    return _pool(res_q(channel))


#: Every resolved total by quantity name, for callers that want to report a whole stat block
#: rather than name nodes one at a time — the optimizer's scoring pass and the "explain this
#: number" path both want this shape.
TOTALS: dict[str, AnyNode] = {
    Q_HP: HP_NODE,
    Q_ATK: ATK_NODE,
    Q_DEF: DEF_NODE,
    Q_ELEMENTAL_MASTERY: ELEMENTAL_MASTERY_NODE,
    Q_ENERGY_RECHARGE: ENERGY_RECHARGE_NODE,
    Q_CRIT_RATE: CRIT_RATE_NODE,
    Q_CRIT_DMG: CRIT_DMG_NODE,
    Q_HEALING_BONUS: HEALING_BONUS_NODE,
    Q_INCOMING_HEALING_BONUS: INCOMING_HEALING_BONUS_NODE,
    Q_SHIELD_STRENGTH: SHIELD_STRENGTH_NODE,
    **{dmg_bonus_q(channel): dmg_bonus_node(channel) for channel in DAMAGE_CHANNELS},
}
