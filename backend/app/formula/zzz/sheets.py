"""Per-agent formula sheets — primitives for registering DAG formulas.

A ZZZ agent sheet exposes named formulas (``basic_0``, ``ex_special_1``,
``core_afterburn_dmg``, …) each tagged ``{sheet: <slug>, name: <formula>,
q: <quantity>}``. Three quantities are the backbone of a standard hit:

* :data:`~app.formula.zzz.tags.Q_STANDARD_DMG` — crit-averaged damage number
* :data:`~app.formula.zzz.tags.Q_DAZE_BUILDUP` — daze gauge per hit
* :data:`~app.formula.zzz.tags.Q_ANOM_BUILDUP` — anomaly gauge per hit

A single attack row from the DB maps to three formula registrations via
:func:`register_attack_hit`. Agent-specific custom formulas (Burnice's
Afterburn, Vivian's Abloom) register one or more quantities with a
bespoke multiplier tree built from the formula DSL.

Design notes:

* Scope gating is applied at registration time by wrapping the damage
  node in a ``tag_`` override carrying ``{scope: <scope>}``. Scope-gated
  modifiers (e.g. M4 "EX Special CRIT Rate +30%") register under that
  scope tag and the damage node's internal reads pick them up because the
  evaluation context now carries the scope.
* ``scaling_stat_quantity`` selects which aggregated stat drives the
  damage — ``"atk"`` for most agents, ``"hp"`` for HP-scalers (Caesar),
  ``"def"`` for DEF-scalers. The stats DAG exposes one node per quantity.
* Multiplier inputs accept either ``float`` (constant bp value from DB)
  or ``AnyNode`` (DSL-expressed conditional from JSON). The two-branch
  compilation keeps constants folded at build time when possible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

from app.formula.builder import const, prod_, tag_
from app.formula.nodes import AnyNode
from app.formula.tags import Tag
from app.formula.zzz.damage import (
    boost_area_node,
    crit_area_node,
    def_area_node,
    res_area_node,
    stun_area_node,
    vulnerability_area_node,
)
from app.formula.zzz.stats import (
    Q_ANOMALY_PROF_NODE,
    Q_ATK_NODE,
    Q_DEF_NODE,
    Q_HP_NODE,
)
from app.formula.zzz.tags import (
    Q_ANOM_BUILDUP,
    Q_DAZE_BUILDUP,
    Q_STANDARD_DMG,
    SCOPE,
    formula_tag,
)

if TYPE_CHECKING:
    from app.pando.calculator import NodeRegistry
    from app.services.damage_calculator import CritMode


_BP = 0.0001

# Map scaling-stat slug → aggregated stat DAG node. The stats DAG exposes
# one pre-built node per final stat; sheets choose which one drives the
# scaling term of ``base_damage = scaling_stat * multiplier``.
_SCALING_NODES: dict[str, AnyNode] = {
    "atk": Q_ATK_NODE,
    "hp": Q_HP_NODE,
    "def": Q_DEF_NODE,
    "defense": Q_DEF_NODE,  # alias — some data sources use 'defense'
    "anomaly_proficiency": Q_ANOMALY_PROF_NODE,
    "anom_prof": Q_ANOMALY_PROF_NODE,  # alias — terse form used by some sheets
}


MultBP = Union[float, int, AnyNode]  # noqa: UP007 — needed by runtime isinstance()


def _wrap_mult(mult: MultBP) -> AnyNode:
    """Convert a bp scalar (e.g. ``3120``) or a pre-built node into a
    fractional-space ``AnyNode``. Scalars get folded to ``Const(mult * BP)``
    so ``prod_`` sees one constant instead of two; nodes get wrapped by a
    multiply with ``_BP`` to shift into fractional space."""
    if isinstance(mult, (int, float)):
        return const(mult * _BP)
    return prod_(mult, _BP)


def _standard_damage(
    scaling: AnyNode,
    multiplier_bp: MultBP,
    element: str,
    crit_mode: CritMode | None = None,
) -> AnyNode:
    """Assemble a standard-damage product with a constant-or-node multiplier.

    Unlike :func:`app.formula.zzz.damage.standard_damage_node`, this variant
    accepts an ``AnyNode`` multiplier so DSL-expressed conditional formulas
    (subscript tables, cmp_ge gates) can drop in without a separate API.
    """
    from app.services.damage_calculator import CritMode  # noqa: PLC0415

    mode = crit_mode if crit_mode is not None else CritMode.EXPECTED
    base = prod_(scaling, _wrap_mult(multiplier_bp))
    return prod_(
        base,
        boost_area_node(element),
        crit_area_node(mode),
        def_area_node(),
        res_area_node(),
        vulnerability_area_node(),
        stun_area_node(),
    )


def _buildup_number(scaling: AnyNode, mult_bp: MultBP) -> AnyNode:
    """Buildup numbers (daze/anom) are raw ``scaling * mult`` products — no
    multiplier zones apply. Same DSL-friendly signature as damage."""
    return prod_(scaling, _wrap_mult(mult_bp))


def register_attack_hit(
    registry: NodeRegistry,
    *,
    sheet: str,
    name: str,
    scope: str,
    element: str,
    scaling_stat: str = "atk",
    damage_mult_bp: MultBP,
    daze_mult_bp: MultBP = 0.0,
    anom_buildup_bp: MultBP = 0.0,
    crit_mode: CritMode | None = None,
) -> None:
    """Register the three standard formula nodes for one attack hit.

    Produces:
      ``{sheet, name, q: standard_dmg}`` — 7-zone composite damage
      ``{sheet, name, q: daze_buildup}`` — daze gauge (scaling * mult)
      ``{sheet, name, q: anom_buildup}`` — anomaly gauge (scaling * mult)

    Each registered node is wrapped in a ``tag_`` override carrying
    ``{scope: <scope>}`` so scope-gated reads inside the composite (e.g.
    ``{q: dmg_bonus, scope: ex_special}``) match when this formula is
    evaluated. Callers don't need to push a scope context themselves.

    Scaling stat defaults to ``"atk"`` — override for Hugo-family (HP)
    or Caesar-family (DEF) agents. Daze/anom buildup multipliers default
    to ``0`` so callers don't have to explicitly register empty buildups.
    """
    if scaling_stat not in _SCALING_NODES:
        raise ValueError(
            f"unknown scaling_stat {scaling_stat!r} (expected one of {sorted(_SCALING_NODES)})"
        )
    scope_tag = Tag.of(**{SCOPE: scope})
    scaling = _SCALING_NODES[scaling_stat]

    damage_node = tag_(
        _standard_damage(scaling, damage_mult_bp, element, crit_mode),
        scope_tag,
    )
    daze_node = tag_(_buildup_number(scaling, daze_mult_bp), scope_tag)
    anom_node = tag_(_buildup_number(scaling, anom_buildup_bp), scope_tag)

    registry.register(formula_tag(sheet, name, Q_STANDARD_DMG), damage_node)
    registry.register(formula_tag(sheet, name, Q_DAZE_BUILDUP), daze_node)
    registry.register(formula_tag(sheet, name, Q_ANOM_BUILDUP), anom_node)


def register_custom_standard_dmg(
    registry: NodeRegistry,
    *,
    sheet: str,
    name: str,
    scope: str,
    element: str,
    scaling_stat: str = "atk",
    multiplier: AnyNode,
    crit_mode: CritMode | None = None,
) -> None:
    """Register a bespoke ``{sheet, name, q: standard_dmg}`` formula.

    Used for agent-specific damage that doesn't correspond to a row in
    the ``attacks`` table — Burnice's Afterburn, Vivian's Abloom ticks,
    mindscape-gated extra hits. The ``multiplier`` is a pre-built DAG
    subtree (typically from the JSON DSL loader) that evaluates to a
    bp-space fractional multiplier.
    """
    if scaling_stat not in _SCALING_NODES:
        raise ValueError(
            f"unknown scaling_stat {scaling_stat!r} (expected one of {sorted(_SCALING_NODES)})"
        )
    scope_tag = Tag.of(**{SCOPE: scope})
    scaling = _SCALING_NODES[scaling_stat]
    damage_node = tag_(
        _standard_damage(scaling, multiplier, element, crit_mode),
        scope_tag,
    )
    registry.register(formula_tag(sheet, name, Q_STANDARD_DMG), damage_node)


def register_custom_anom_buildup(
    registry: NodeRegistry,
    *,
    sheet: str,
    name: str,
    scope: str,
    value: AnyNode | float | int,
) -> None:
    """Register a flat anomaly-gauge number at ``{sheet, name, q: anom_buildup}``.

    Some custom formulas (Burnice ``core_afterburn_anomBuildup`` = 60)
    have a constant buildup independent of the damage formula. ``value``
    is used as-is — no bp conversion, no multiplier zones — since this
    is a gauge number rather than a damage computation.
    """
    scope_tag = Tag.of(**{SCOPE: scope})
    inner = const(value) if isinstance(value, (int, float)) else value
    registry.register(formula_tag(sheet, name, Q_ANOM_BUILDUP), tag_(inner, scope_tag))
