"""Agent JSON → sheet registration.

Reads the ``formulas`` section of an agent modifier JSON and registers
each formula into a :class:`~app.pando.calculator.NodeRegistry` via
:mod:`app.formula.zzz.sheets`. The JSON's DSL expressions are lowered
by :func:`~app.formula.zzz.formula_dsl.compile_dsl`.

The loader is the pair to :mod:`app.services.modifier_loader` — modifiers
declare stat contributions, formulas declare bespoke damage/buildup
numbers that the auto-derived attack-hit registration can't express
(Burnice's Afterburn, Vivian's Abloom, mindscape-gated extra hits).

Agent JSONs with no ``formulas`` key are a no-op — the ``modifiers``
section still loads normally through its own path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.formula.zzz.formula_dsl import compile_dsl
from app.formula.zzz.sheets import (
    register_custom_anom_buildup,
    register_custom_standard_dmg,
)
from app.formula.zzz.tags import Q_ANOM_BUILDUP, Q_STANDARD_DMG

if TYPE_CHECKING:
    from app.pando.calculator import NodeRegistry


def _load_standard_dmg(registry: NodeRegistry, sheet: str, spec: dict[str, Any]) -> None:
    multiplier = compile_dsl(spec["multiplier"])
    register_custom_standard_dmg(
        registry,
        sheet=sheet,
        name=spec["name"],
        scope=spec["scope"],
        element=spec["element"],
        scaling_stat=spec.get("scaling_stat", "atk"),
        multiplier=multiplier,
    )


def _load_anom_buildup(registry: NodeRegistry, sheet: str, spec: dict[str, Any]) -> None:
    raw_value = spec["value"]
    value = compile_dsl(raw_value) if isinstance(raw_value, dict) else raw_value
    register_custom_anom_buildup(
        registry,
        sheet=sheet,
        name=spec["name"],
        scope=spec["scope"],
        value=value,
    )


_QUANTITY_LOADERS = {
    Q_STANDARD_DMG: _load_standard_dmg,
    Q_ANOM_BUILDUP: _load_anom_buildup,
}


def load_agent_formulas(registry: NodeRegistry, data: dict[str, Any]) -> None:
    """Register every formula in ``data['formulas']`` into ``registry``.

    ``data`` is a loaded agent JSON (the same shape consumed by
    :func:`app.services.modifier_loader.load_agent_modifiers`) extended
    with a ``sheet`` slug and a ``formulas`` list. Silent no-op when
    ``formulas`` is missing so legacy JSONs without this section still
    work unchanged.

    Raises ``ValueError`` for missing ``sheet`` (when formulas are
    present) and for unsupported quantity names.
    """
    formulas = data.get("formulas")
    if not formulas:
        return

    sheet = data.get("sheet")
    if not sheet:
        raise ValueError("agent JSON with 'formulas' section is missing 'sheet' slug")

    for spec in formulas:
        quantity = spec["quantity"]
        loader = _QUANTITY_LOADERS.get(quantity)
        if loader is None:
            raise ValueError(
                f"unsupported quantity {quantity!r} in formula {spec.get('name')!r} "
                f"(expected one of {sorted(_QUANTITY_LOADERS)})"
            )
        loader(registry, sheet, spec)
