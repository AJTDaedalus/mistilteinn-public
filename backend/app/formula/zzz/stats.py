"""ZZZ stats DAG — graph equivalent of :func:`compute_total_stats`.

Exposes pre-built formula nodes (:data:`Q_ATK_NODE`, :data:`Q_HP_NODE`,
:data:`Q_DEF_NODE`, :data:`Q_CRIT_RATE_NODE`, :data:`Q_CRIT_DMG_NODE`, and
:func:`elemental_dmg_node`) that aggregate registered contributions using
the same basis-point math as :func:`app.services.stat_calculator.compute_total_stats`.

The DAG keeps its intermediates as floats; flooring (to mirror the
procedural path) happens at the API boundary. This lets downstream ops
that consume these nodes (damage calc, optimizer scoring) work in the
continuous domain where interval arithmetic and monotonicity analysis are
well-defined.

Two-stage formula, matching ``stat_calculator``::

    pre   = base * (1 + pct/10000) + flat
    final = pre  * (1 + final_pct/10000) + final_flat

where ``base`` is an agent-base sum (ATK additionally includes
W-Engine base), and every term is a ``read(sum)`` over its contribution
tag so modifiers, discs, and set bonuses all add cleanly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.formula.builder import const, prod_, read_, sum_
from app.formula.zzz.tags import (
    ELEMENTS,
    Q_AGENT_BASE_AM,
    Q_AGENT_BASE_ATK,
    Q_AGENT_BASE_DEF,
    Q_AGENT_BASE_HP,
    Q_AM_PCT,
    Q_ANOMALY_MASTERY,
    Q_ANOMALY_PROF,
    Q_ATK_PCT,
    Q_CRIT_DMG,
    Q_CRIT_RATE,
    Q_DEF_PCT,
    Q_ENERGY_REGEN,
    Q_FINAL_ATK_PCT,
    Q_FINAL_DEF_PCT,
    Q_FINAL_FLAT_ATK,
    Q_FINAL_FLAT_DEF,
    Q_FINAL_FLAT_HP,
    Q_FINAL_HP_PCT,
    Q_FLAT_ATK,
    Q_FLAT_DEF,
    Q_FLAT_HP,
    Q_HP_PCT,
    Q_IMPACT,
    Q_PEN_FLAT,
    Q_PEN_RATIO,
    Q_WENGINE_BASE_ATK,
    elem_dmg_tag,
    stat_tag,
)

if TYPE_CHECKING:
    from app.formula.nodes import AnyNode
    from app.pando.calculator import NodeRegistry
    from app.services.stat_calculator import StatInputs


# ---- Base / contribution reads --------------------------------------------
# Each read gathers every registered contribution at its tag with a sum
# accumulator — empty = 0, so missing inputs don't blow up the formula.

_AGENT_BASE_ATK = read_(stat_tag(Q_AGENT_BASE_ATK), "sum")
_WENGINE_BASE_ATK = read_(stat_tag(Q_WENGINE_BASE_ATK), "sum")
_AGENT_BASE_HP = read_(stat_tag(Q_AGENT_BASE_HP), "sum")
_AGENT_BASE_DEF = read_(stat_tag(Q_AGENT_BASE_DEF), "sum")

_ATK_PCT = read_(stat_tag(Q_ATK_PCT), "sum")
_HP_PCT = read_(stat_tag(Q_HP_PCT), "sum")
_DEF_PCT = read_(stat_tag(Q_DEF_PCT), "sum")

_FLAT_ATK = read_(stat_tag(Q_FLAT_ATK), "sum")
_FLAT_HP = read_(stat_tag(Q_FLAT_HP), "sum")
_FLAT_DEF = read_(stat_tag(Q_FLAT_DEF), "sum")

_FINAL_ATK_PCT = read_(stat_tag(Q_FINAL_ATK_PCT), "sum")
_FINAL_HP_PCT = read_(stat_tag(Q_FINAL_HP_PCT), "sum")
_FINAL_DEF_PCT = read_(stat_tag(Q_FINAL_DEF_PCT), "sum")

_FINAL_FLAT_ATK = read_(stat_tag(Q_FINAL_FLAT_ATK), "sum")
_FINAL_FLAT_HP = read_(stat_tag(Q_FINAL_FLAT_HP), "sum")
_FINAL_FLAT_DEF = read_(stat_tag(Q_FINAL_FLAT_DEF), "sum")


# ---- Formula assembly ------------------------------------------------------

# Basis-point → fraction: 2000 (20%) * 0.0001 = 0.20.
_BP = 0.0001


def _two_stage(
    base: AnyNode,
    pct: AnyNode,
    flat: AnyNode,
    final_pct: AnyNode,
    final_flat: AnyNode,
) -> AnyNode:
    """``((base * (1 + pct*BP)) + flat) * (1 + final_pct*BP) + final_flat``."""
    pre = sum_(prod_(base, sum_(1, prod_(pct, _BP))), flat)
    return sum_(prod_(pre, sum_(1, prod_(final_pct, _BP))), final_flat)


_BASE_ATK_SUM = sum_(_AGENT_BASE_ATK, _WENGINE_BASE_ATK)


# ---- Top-level stat nodes --------------------------------------------------

Q_ATK_NODE: AnyNode = _two_stage(
    _BASE_ATK_SUM,
    _ATK_PCT,
    _FLAT_ATK,
    _FINAL_ATK_PCT,
    _FINAL_FLAT_ATK,
)

Q_HP_NODE: AnyNode = _two_stage(
    _AGENT_BASE_HP,
    _HP_PCT,
    _FLAT_HP,
    _FINAL_HP_PCT,
    _FINAL_FLAT_HP,
)

Q_DEF_NODE: AnyNode = _two_stage(
    _AGENT_BASE_DEF,
    _DEF_PCT,
    _FLAT_DEF,
    _FINAL_DEF_PCT,
    _FINAL_FLAT_DEF,
)

# Passthrough stats — ``compute_total_stats`` doesn't aggregate these, but
# the DAG treats them as sums so downstream buffs can add on top.
Q_CRIT_RATE_NODE: AnyNode = read_(stat_tag(Q_CRIT_RATE), "sum")
Q_CRIT_DMG_NODE: AnyNode = read_(stat_tag(Q_CRIT_DMG), "sum")
Q_ANOMALY_PROF_NODE: AnyNode = read_(stat_tag(Q_ANOMALY_PROF), "sum")


def elemental_dmg_node(element: str) -> AnyNode:
    """Return a DAG node for the ``<element>_dmg`` bonus (sum accumulator)."""
    return read_(elem_dmg_tag(element), "sum")


# ---- Registry population ---------------------------------------------------


_ELEMENTS = ELEMENTS


def register_base_stats(registry: NodeRegistry, inputs: StatInputs) -> None:
    """Register one ``Const(value)`` per non-zero field of ``inputs``.

    Pairs with the top-level formula nodes above — after this call,
    evaluating :data:`Q_ATK_NODE` on a ``Calculator`` backed by ``registry``
    produces the same ATK value :func:`compute_total_stats` returns (up to
    flooring, which the DAG leaves to the API boundary).
    """
    contributions: tuple[tuple[str, int], ...] = (
        (Q_AGENT_BASE_ATK, inputs.agent_base_atk),
        (Q_WENGINE_BASE_ATK, inputs.wengine_base_atk),
        (Q_AGENT_BASE_HP, inputs.agent_base_hp),
        (Q_AGENT_BASE_DEF, inputs.agent_base_def),
        (Q_ATK_PCT, inputs.atk_pct),
        (Q_HP_PCT, inputs.hp_pct),
        (Q_DEF_PCT, inputs.def_pct),
        (Q_FLAT_ATK, inputs.flat_atk),
        (Q_FLAT_HP, inputs.flat_hp),
        (Q_FLAT_DEF, inputs.flat_def),
        (Q_FINAL_ATK_PCT, inputs.final_atk_pct),
        (Q_FINAL_HP_PCT, inputs.final_hp_pct),
        (Q_FINAL_DEF_PCT, inputs.final_def_pct),
        (Q_FINAL_FLAT_ATK, inputs.final_flat_atk),
        (Q_FINAL_FLAT_HP, inputs.final_flat_hp),
        (Q_FINAL_FLAT_DEF, inputs.final_flat_def),
        (Q_CRIT_RATE, inputs.crit_rate),
        (Q_CRIT_DMG, inputs.crit_dmg),
        (Q_ANOMALY_MASTERY, inputs.anomaly_mastery),
        (Q_AGENT_BASE_AM, inputs.agent_base_am),
        (Q_AM_PCT, inputs.am_pct),
        (Q_ANOMALY_PROF, inputs.anomaly_proficiency),
        (Q_IMPACT, inputs.impact),
        (Q_ENERGY_REGEN, inputs.energy_regen),
        (Q_PEN_FLAT, inputs.pen_flat),
        (Q_PEN_RATIO, inputs.pen_ratio),
    )
    for quantity, value in contributions:
        if value != 0:
            registry.register(stat_tag(quantity), const(value))

    for element in _ELEMENTS:
        value = getattr(inputs, f"{element}_dmg", 0)
        if value != 0:
            registry.register(elem_dmg_tag(element), const(value))
