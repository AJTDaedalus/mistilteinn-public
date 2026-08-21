"""Node IR for the Pando DAG.

Frozen dataclasses describing every operation. Base shape mirrors
``libs/pando/engine/src/node/type.ts``:

    { op: str, x: tuple[Node, ...], br: tuple[Node, ...], ex: Any, tag: Tag }

Every field is ``Hashable``/immutable so nodes can be used as cache keys
by the calculator and later by the DAG compiler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.formula.tags import Tag


# ---- Const -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Const:
    """Literal value node. ``ex`` is the value (number or string)."""

    ex: int | float | str
    op: Literal["const"] = "const"
    x: tuple[()] = ()
    br: tuple[()] = ()


# ---- Arithmetic ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Sum:
    """``x[0] + x[1] + …``"""

    x: tuple[AnyNode, ...]
    op: Literal["sum"] = "sum"
    br: tuple[()] = ()


@dataclass(frozen=True, slots=True)
class Prod:
    """``x[0] * x[1] * …``"""

    x: tuple[AnyNode, ...]
    op: Literal["prod"] = "prod"
    br: tuple[()] = ()


@dataclass(frozen=True, slots=True)
class Min:
    """``min(x[0], x[1], …)``"""

    x: tuple[AnyNode, ...]
    op: Literal["min"] = "min"
    br: tuple[()] = ()


@dataclass(frozen=True, slots=True)
class Max:
    """``max(x[0], x[1], …)``"""

    x: tuple[AnyNode, ...]
    op: Literal["max"] = "max"
    br: tuple[()] = ()


@dataclass(frozen=True, slots=True)
class SumFrac:
    """``x[0] / (x[0] + x[1])``. Used by DEF formula."""

    x: tuple[AnyNode, AnyNode]
    op: Literal["sumfrac"] = "sumfrac"
    br: tuple[()] = ()


# ---- Branching -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Threshold:
    """``br[0] >= br[1] ? x[0] : x[1]``"""

    br: tuple[AnyNode, AnyNode]
    x: tuple[AnyNode, AnyNode]
    op: Literal["thres"] = "thres"


@dataclass(frozen=True, slots=True)
class Match:
    """``br[0] == br[1] ? x[0] : x[1]``"""

    br: tuple[AnyNode, AnyNode]
    x: tuple[AnyNode, AnyNode]
    op: Literal["match"] = "match"


@dataclass(frozen=True, slots=True)
class Lookup:
    """``x[ex[br[0]]] ?? x[x.len-1]`` (fallback = last entry).

    ``ex`` maps a string value → index into ``x``.
    """

    br: tuple[AnyNode]
    x: tuple[AnyNode, ...]
    ex: dict[str, int]
    op: Literal["lookup"] = "lookup"

    def __hash__(self) -> int:
        return hash((self.op, self.br, self.x, tuple(sorted(self.ex.items()))))


@dataclass(frozen=True, slots=True)
class Subscript:
    """``ex[br[0]]`` — direct array indexing (no fallback)."""

    br: tuple[AnyNode]
    ex: tuple[int | float | str, ...]
    op: Literal["subscript"] = "subscript"
    x: tuple[()] = ()


# ---- Tag manipulation ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TagOverride:
    """Evaluate ``x[0]`` with ``tag`` merged into the context."""

    x: tuple[AnyNode]
    tag: Tag
    op: Literal["tag"] = "tag"
    br: tuple[()] = ()


@dataclass(frozen=True, slots=True)
class TagValRead:
    """Read the current tag's value for category ``ex`` (string, '' if absent)."""

    ex: str
    op: Literal["vtag"] = "vtag"
    x: tuple[()] = ()
    br: tuple[()] = ()


# ---- Read / ReRead ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Read:
    """Gather all nodes registered under tags subset of ``current`` merged with ``tag``.

    ``ex`` is the accumulator over matches: ``sum``/``prod``/``min``/``max``
    or ``unique``. ``None`` means "infer from tag" — the Calculator can
    expose a ``default_accu()`` hook.
    """

    tag: Tag
    ex: Literal["sum", "prod", "min", "max", "unique"] | None = None
    op: Literal["read"] = "read"
    x: tuple[()] = ()
    br: tuple[()] = ()


@dataclass(frozen=True, slots=True)
class ReRead:
    """Registry-only sentinel: "re-gather at this tag".

    Not evaluated directly — it appears as a *registered* entry and the
    gather algorithm inlines its targets.
    """

    tag: Tag
    op: Literal["reread"] = "reread"


# ---- Custom ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Custom:
    """Escape hatch: named Python function with ``len(x)`` inputs.

    ``ex`` is the name registered in :mod:`app.pando.calculator`'s
    ``CUSTOM_OPS`` table. Used for ops that don't fit the primitives
    (e.g. ``floor`` for discrete thresholds).
    """

    x: tuple[AnyNode, ...]
    ex: str
    op: Literal["custom"] = "custom"
    br: tuple[()] = ()


# ---- Unions ----------------------------------------------------------------

ArithNode = Sum | Prod | Min | Max | SumFrac
BranchNode = Threshold | Match | Lookup | Subscript
TagNode = TagOverride | TagValRead
AnyNode = (
    Const
    | Sum
    | Prod
    | Min
    | Max
    | SumFrac
    | Threshold
    | Match
    | Lookup
    | Subscript
    | TagOverride
    | TagValRead
    | Read
    | Custom
)
"""Any node that can appear as an input (``x`` or ``br``). ``ReRead`` is not
an ``AnyNode`` — it only appears as a registry entry."""


# Silence "field unused" — `field` is re-exported for downstream builder modules.
_ = field
