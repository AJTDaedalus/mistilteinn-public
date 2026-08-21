"""Modifier → NodeRegistry translator.

Converts the existing :class:`app.services.modifiers.Modifier` + the
:class:`app.services.modifiers.ActiveConditions` toggles into DAG entries
so the Calculator can resolve buffs the same way
:func:`app.services.buff_resolver.resolve_modifiers` does — but as a
*graph* instead of a procedure.

Design: condition indicators live at ``{q: cond_active, cond: <name>}``
as literal ``Const(1)`` entries when active (absent when inactive, so a
``read(sum)`` on the indicator tag yields 0 via the empty-accumulator
identity). Each conditional modifier registers a gated node that
multiplies its value by the product of its condition indicators — that
way the solver's interval arithmetic can later treat each condition as a
candidate variable and bound the gated value at ``[0, value]``.

Scope filtering is done at *translation* time here, rather than as a DAG
structure, because the Calculator path evaluates one ``attack_scope`` per
call. A future DAG-native scope system (Phase 6.4+) would keep scope as a
tag dimension and push ``Tag.of(scope=...)`` into the context per-step;
for now this keeps parity with :func:`resolve_modifiers`.

The ``_DMG_BONUS_STATS`` and ``_COMBAT_STATS`` sets are re-imported from
:mod:`app.services.buff_resolver` so the routing map stays in one place.
Eventually these become just more tag destinations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.formula.builder import const
from app.formula.tags import Tag
from app.formula.zzz.tags import (
    Q_DMG_BONUS,
    Q,
    cond_tag,
    stack_tag,
    stat_tag,
)
from app.services.buff_resolver import _DMG_BONUS_STATS
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierTarget,
)

if TYPE_CHECKING:
    from app.pando.calculator import NodeRegistry
    from app.services.modifiers import ActiveConditions


def _route_tag(stat: str) -> Tag:
    """Return the tag a modifier with stat=``stat`` should register under.

    All ``*_dmg_bonus`` stats collapse to a single ``{q: dmg_bonus}`` tag —
    scope filtering happens at translation time (matching ``buff_resolver``
    semantics), so the flat aggregate is what the damage DAG will read.
    A Phase 6.4+ revision will promote ``scope`` to a DAG tag dimension and
    split this back out.
    """
    if stat in _DMG_BONUS_STATS:
        return Tag.of(**{Q: Q_DMG_BONUS})
    return stat_tag(stat)


def _conditions_satisfied(
    conditions: ActiveConditions,
    needed: tuple[Condition, ...],
) -> bool:
    return all(c in conditions.active for c in needed)


def translate_modifiers(
    registry: NodeRegistry,
    modifiers: list[Modifier],
    conditions: ActiveConditions,
    *,
    attack_scope: AttackScope = AttackScope.ALL,
    target_filter: ModifierTarget = ModifierTarget.SELF,
) -> None:
    """Populate ``registry`` with DAG entries for every active modifier.

    Mirrors the filtering logic of
    :func:`app.services.buff_resolver.resolve_modifiers` exactly: target
    filter (SELF matches SELF + TEAM), condition gate (all must be active),
    scope gate (ALL matches any, or exact match required).

    Also writes two meta tables:
    * **condition indicators** — one ``Const(1)`` per active condition.
    * **stack counts** — one ``Const(n)`` per ``(source_label, n)`` in
      ``conditions.stack_counts``.
    """
    _write_condition_indicators(registry, conditions)
    _write_stack_counts(registry, conditions)

    for mod in modifiers:
        if not _passes_target_filter(mod, target_filter):
            continue
        if not _conditions_satisfied(conditions, mod.conditions):
            continue
        if not _passes_scope(mod, attack_scope):
            continue

        effective_value = _effective_value(mod, conditions)
        if effective_value == 0:
            continue

        registry.register(_route_tag(mod.stat), const(effective_value))


# ---- helpers ---------------------------------------------------------------


def _passes_target_filter(mod: Modifier, target_filter: ModifierTarget) -> bool:
    # buff_resolver.py line 96: ``if mod.target not in {target_filter, TEAM}``
    return mod.target in {target_filter, ModifierTarget.TEAM}


def _passes_scope(mod: Modifier, attack_scope: AttackScope) -> bool:
    if AttackScope.ALL in mod.scopes:
        return True
    if attack_scope == AttackScope.ALL:
        return True
    return attack_scope in mod.scopes


def _effective_value(mod: Modifier, conditions: ActiveConditions) -> int:
    if mod.max_stacks > 1:
        stacks = conditions.get_stacks(mod.source_label, mod.max_stacks)
        return mod.value * stacks
    return mod.value


def _write_condition_indicators(
    registry: NodeRegistry,
    conditions: ActiveConditions,
) -> None:
    """Register ``Const(1)`` under ``{q: cond_active, cond: <name>}`` for each active."""
    for cond in conditions.active:
        registry.register(cond_tag(cond.value), const(1))


def _write_stack_counts(
    registry: NodeRegistry,
    conditions: ActiveConditions,
) -> None:
    """Register ``Const(count)`` under ``{q: stack, label: <label>}`` for each entry."""
    for label, count in conditions.stack_counts.items():
        if count > 0:
            registry.register(stack_tag(label), const(count))
