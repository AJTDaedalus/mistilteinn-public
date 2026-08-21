"""Single-shot Pando Calculator.

Recursive evaluator over the node IR (:mod:`app.formula.nodes`). Port of
``libs/pando/engine/src/node/calc.ts``'s ``Calculator`` class, adapted for
Python value semantics and Fairy's idioms.

Responsibilities:

* Evaluate any ``AnyNode`` to a concrete ``int``/``float``/``str``.
* Maintain an implicit tag context that ``TagOverride`` pushes onto and
  ``Read``/``TagValRead`` consult.
* Gather registered nodes (via :class:`NodeRegistry`) for ``Read`` ops,
  following ``ReRead`` sentinels transitively.
* Cache results per (node, tag-context) pair within a single ``compute()``
  so a DAG with shared subtrees is evaluated once per context.

This is the *correctness path* — it must match the eventual compiled hot
loop (Phase 6.5) op-for-op. The compiler will specialize this same graph
into a Numba-JIT function.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

from app.formula.nodes import (
    Const,
    Custom,
    Lookup,
    Match,
    Max,
    Min,
    Prod,
    Read,
    ReRead,
    Subscript,
    Sum,
    SumFrac,
    TagOverride,
    TagValRead,
    Threshold,
)
from app.formula.tags import Tag

if TYPE_CHECKING:
    from app.formula.nodes import AnyNode


# ---- Custom-op registry ----------------------------------------------------

CUSTOM_OPS: dict[str, Callable[..., int | float | str]] = {
    "floor": math.floor,
    "ceil": math.ceil,
    "abs": abs,
}
"""Named Python functions callable from ``Custom`` nodes.

Each op takes ``len(node.x)`` positional args (already evaluated) and
returns a number or string. Add new entries here; keep functions pure.
"""


# ---- Node registry ---------------------------------------------------------


@dataclass
class NodeRegistry:
    """Maps ``Tag`` → list of nodes; consumed by ``Read`` ops.

    Multiple nodes may register under the same (or overlapping) tag — the
    ``Read``'s accumulator reduces them to a single value. ``ReRead``
    entries redirect gathering to a different tag (used for aliases and
    modifier-target fanout).
    """

    _entries: list[tuple[Tag, AnyNode | ReRead]] = field(default_factory=list)

    def register(self, tag: Tag, node: AnyNode | ReRead) -> None:
        """Record ``node`` under ``tag`` so a later ``gather`` can find it."""
        self._entries.append((tag, node))

    def gather(self, query: Tag) -> list[AnyNode | ReRead]:
        """All entries whose registration tag is a subset of ``query``."""
        return [n for t, n in self._entries if t.is_subset_of(query)]


# ---- Calculator ------------------------------------------------------------

_Accu = Literal["sum", "prod", "min", "max", "unique"]


class Calculator:
    """Evaluates a DAG node to its concrete value.

    Construct once per (build snapshot, enemy context); call :meth:`compute`
    for as many root nodes as needed. Cache is per-instance so repeated
    ``compute`` on the same node is cheap.
    """

    def __init__(self, registry: NodeRegistry | None = None) -> None:
        self.registry = registry or NodeRegistry()
        # (node, tag) → value cache. Frozen dataclass nodes are hashable by
        # value, so two structurally-equal Read nodes share a cache slot —
        # this is the Pando DedupTag pattern. Using id() breaks when temp
        # nodes are GC'd and Python recycles their memory for a new node.
        self._cache: dict[tuple[AnyNode, Tag], int | float | str] = {}

    def compute(self, node: AnyNode) -> int | float | str:
        """Evaluate ``node`` under an empty initial tag context."""
        return self._compute(node, Tag())

    # ---- dispatch ----

    def _compute(self, node: AnyNode, ctx: Tag) -> int | float | str:
        key = (node, ctx)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        val = self._dispatch(node, ctx)
        self._cache[key] = val
        return val

    def _dispatch(self, node: AnyNode, ctx: Tag) -> int | float | str:  # noqa: PLR0911, PLR0912
        match node:
            case Const():
                return node.ex
            case Sum():
                return sum(self._compute(c, ctx) for c in node.x)  # type: ignore[misc]
            case Prod():
                acc: int | float = 1
                for c in node.x:
                    acc = acc * self._compute(c, ctx)  # type: ignore[operator,assignment]
                return acc
            case Min():
                return min(self._compute(c, ctx) for c in node.x)  # type: ignore[type-var]
            case Max():
                return max(self._compute(c, ctx) for c in node.x)  # type: ignore[type-var]
            case SumFrac():
                a = self._compute(node.x[0], ctx)
                b = self._compute(node.x[1], ctx)
                denom = a + b  # type: ignore[operator]
                if denom == 0:
                    return 0
                return a / denom  # type: ignore[operator,return-value]
            case Threshold():
                left = self._compute(node.br[0], ctx)
                right = self._compute(node.br[1], ctx)
                chosen = node.x[0] if left >= right else node.x[1]  # type: ignore[operator]
                return self._compute(chosen, ctx)
            case Match():
                left = self._compute(node.br[0], ctx)
                right = self._compute(node.br[1], ctx)
                chosen = node.x[0] if left == right else node.x[1]
                return self._compute(chosen, ctx)
            case Lookup():
                key_val = self._compute(node.br[0], ctx)
                idx = node.ex.get(str(key_val))
                # Fallback: last entry in x (per ``builder.lookup`` contract).
                chosen = node.x[idx] if idx is not None else node.x[-1]
                return self._compute(chosen, ctx)
            case Subscript():
                idx_val = self._compute(node.br[0], ctx)
                return node.ex[int(idx_val)]  # type: ignore[arg-type]
            case TagOverride():
                return self._compute(node.x[0], ctx.merge(node.tag))
            case TagValRead():
                return ctx.get(node.ex)
            case Read():
                return self._read(node, ctx)
            case Custom():
                args = [self._compute(c, ctx) for c in node.x]
                fn = CUSTOM_OPS.get(node.ex)
                if fn is None:
                    raise KeyError(f"Custom op not registered: {node.ex!r}")
                return fn(*args)
            case _:
                raise TypeError(f"Unknown node type: {type(node).__name__}")

    # ---- read / gather ----

    def _read(self, node: Read, ctx: Tag) -> int | float | str:
        effective_tag = ctx.merge(node.tag)
        values = self._gather_values(effective_tag)
        accu: _Accu = node.ex or "unique"
        return self._accumulate(values, accu, effective_tag)

    def _gather_values(self, tag: Tag) -> list[int | float | str]:
        """Gather all registered numeric/string values matching ``tag``.

        ``ReRead`` entries are expanded transitively: if a ReRead at some
        sub-tag redirects to another tag, its values are inlined.
        """
        out: list[int | float | str] = []
        self._gather_into(tag, out, seen=set())
        return out

    def _gather_into(
        self,
        tag: Tag,
        out: list[int | float | str],
        seen: set[Tag],
    ) -> None:
        if tag in seen:  # cycle guard
            return
        seen.add(tag)
        for entry in self.registry.gather(tag):
            if isinstance(entry, ReRead):
                self._gather_into(tag.merge(entry.tag), out, seen)
            else:
                out.append(self._compute(entry, tag))

    @staticmethod
    def _accumulate(
        values: list[int | float | str],
        accu: _Accu,
        tag: Tag,
    ) -> int | float | str:
        if accu == "unique":
            if len(values) != 1:
                raise ValueError(
                    f"Read with accu='unique' expected exactly 1 match for {tag!r}, "
                    f"got {len(values)} (no match — register a node or specify an accumulator)",
                )
            return values[0]
        if not values:
            # Identity for empty accumulators: keeps formulas total.
            return {"sum": 0, "prod": 1, "min": math.inf, "max": -math.inf}[accu]
        if accu == "sum":
            return sum(values)  # type: ignore[misc]
        if accu == "prod":
            acc: int | float = 1
            for v in values:
                acc = acc * v  # type: ignore[operator,assignment]
            return acc
        if accu == "min":
            return min(values)  # type: ignore[type-var]
        if accu == "max":
            return max(values)  # type: ignore[type-var]
        raise ValueError(f"Unknown accumulator: {accu!r}")
