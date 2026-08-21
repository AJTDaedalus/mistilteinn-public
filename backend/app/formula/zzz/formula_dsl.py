"""JSON → DAG mini-DSL compiler for per-agent formula sheets.

Agent JSONs declare conditional multiplier trees that pair with
:func:`app.formula.zzz.sheets.register_custom_standard_dmg` and
:func:`~app.formula.zzz.sheets.register_custom_anom_buildup`. The DSL is
a thin mirror over the DAG builder ops — it exists so ``/translate-kit``
can emit JSON directly rather than Python, keeping agent kits as pure
data for checkouts, diffs, and (eventually) LLM-assisted authoring.

Expression shape (recursive JSON):

* ``{"op": "const", "value": <num>}`` — literal
* ``{"op": "sum" | "prod" | "min" | "max", "args": [<expr>, ...]}`` — n-ary
* ``{"op": "sumfrac", "numer": <expr>, "denom_extra": <expr>}`` — a/(a+b)
* ``{"op": "subscript", "index": <expr>, "table": [v0, v1, ...]}`` — table lookup
* ``{"op": "cmp_ge", "left": <expr>, "right": <expr>, "if_ge": <expr>, "if_lt": <expr>?}``
* ``{"op": "read", "q": "<quantity>"}`` — read ``Tag.of(q=<quantity>)`` with sum accumulator
* ``{"op": "stat", "name": "atk" | "hp" | "def" | "crit_rate" | "crit_dmg"}``
  — aggregated stat node

Bare numbers in nested positions auto-wrap to ``const``. Strings are
rejected — they'd be ambiguous (stat name? quantity? literal?) and the
explicit form is only two extra tokens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.formula.builder import (
    const,
    max_,
    min_,
    prod_,
    read_,
    subscript,
    sum_,
    sumfrac,
    threshold,
)
from app.formula.tags import Tag
from app.formula.zzz.stats import (
    Q_ATK_NODE,
    Q_CRIT_DMG_NODE,
    Q_CRIT_RATE_NODE,
    Q_DEF_NODE,
    Q_HP_NODE,
)
from app.formula.zzz.tags import Q

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.formula.nodes import AnyNode

_STAT_NODES: dict[str, AnyNode] = {
    "atk": Q_ATK_NODE,
    "hp": Q_HP_NODE,
    "def": Q_DEF_NODE,
    "defense": Q_DEF_NODE,
    "crit_rate": Q_CRIT_RATE_NODE,
    "crit_dmg": Q_CRIT_DMG_NODE,
}


def _compile_const(e: dict) -> AnyNode:
    return const(e["value"])


def _compile_nary(builder: Callable[..., AnyNode]) -> Callable[[dict], AnyNode]:
    def inner(e: dict) -> AnyNode:
        return builder(*(compile_dsl(a) for a in e["args"]))

    return inner


def _compile_sumfrac(e: dict) -> AnyNode:
    return sumfrac(compile_dsl(e["numer"]), compile_dsl(e["denom_extra"]))


def _compile_subscript(e: dict) -> AnyNode:
    return subscript(compile_dsl(e["index"]), tuple(e["table"]))


def _compile_cmp_ge(e: dict) -> AnyNode:
    if_lt = compile_dsl(e["if_lt"]) if "if_lt" in e else const(0)
    return threshold(
        compile_dsl(e["left"]),
        compile_dsl(e["right"]),
        compile_dsl(e["if_ge"]),
        if_lt,
    )


def _compile_read(e: dict) -> AnyNode:
    return read_(Tag.of(**{Q: e["q"]}), "sum")


def _compile_stat(e: dict) -> AnyNode:
    name = e["name"]
    if name not in _STAT_NODES:
        raise ValueError(f"unknown stat {name!r} (expected one of {sorted(_STAT_NODES)})")
    return _STAT_NODES[name]


_OPS: dict[str, Callable[[dict], AnyNode]] = {
    "const": _compile_const,
    "sum": _compile_nary(sum_),
    "prod": _compile_nary(prod_),
    "min": _compile_nary(min_),
    "max": _compile_nary(max_),
    "sumfrac": _compile_sumfrac,
    "subscript": _compile_subscript,
    "cmp_ge": _compile_cmp_ge,
    "read": _compile_read,
    "stat": _compile_stat,
}


def compile_dsl(expr: Any) -> AnyNode:
    """Compile a DSL expression (dict or bare number) to a DAG node.

    Raises ``ValueError`` for unknown/missing ``op`` and ``TypeError`` for
    non-dict, non-numeric input.
    """
    if isinstance(expr, (int, float)) and not isinstance(expr, bool):
        return const(expr)
    if not isinstance(expr, dict):
        raise TypeError(f"DSL expression must be a dict or a number, got {type(expr).__name__}")
    if "op" not in expr:
        raise ValueError(f"DSL expression missing 'op' key: {expr!r}")

    op = expr["op"]
    handler = _OPS.get(op)
    if handler is None:
        raise ValueError(f"unknown op {op!r} in DSL expression: {expr!r}")
    return handler(expr)


def compile_dsl_optional(expr: Any | None) -> AnyNode | None:
    """Variant that returns ``None`` for ``None`` input.

    JSONs often mark optional formulas by omitting the key entirely; the
    loader reads the value with ``.get()`` and passes it through here so
    missing formulas don't need special-casing at the call site.
    """
    if expr is None:
        return None
    return compile_dsl(expr)
