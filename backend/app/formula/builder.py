"""Ergonomic constructors for building DAG nodes.

Hand-written DAGs are verbose with the raw dataclasses — every arg must be
wrapped in ``Const`` and every ``x=`` must be a tuple. This module provides
short constructors that auto-wrap Python scalars, accept varargs, and name
parameters in the order that reads naturally.

Style convention: builder names match Pando's TypeScript helpers
(``sum``/``prod``/``max``/``min``/``sumfrac``) but with a trailing ``_``
to avoid shadowing Python builtins where it matters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from app.formula.nodes import (
    AnyNode,
    Const,
    Custom,
    Lookup,
    Match,
    Max,
    Min,
    Prod,
    Read,
    Subscript,
    Sum,
    SumFrac,
    TagOverride,
    TagValRead,
    Threshold,
)

if TYPE_CHECKING:
    from app.formula.tags import Tag


Num = int | float
Arg = AnyNode | Num | str


def const(value: Num | str) -> Const:
    """Wrap a literal in a ``Const`` node."""
    return Const(ex=value)


def percent(value: Num) -> Const:
    """Alias for ``const`` — reads better for percentage constants.

    Pando convention: all stats are fractions (``0.20`` = 20%). Fairy's
    stored basis points (``2000`` = 20%) get divided on ingest.
    """
    return Const(ex=value)


def _wrap(arg: Arg) -> AnyNode:
    """Auto-wrap scalars/strings in ``Const`` for ergonomic DAG building."""
    if isinstance(arg, (int, float, str)):
        return Const(ex=arg)
    return arg


def _wrap_all(args: tuple[Arg, ...]) -> tuple[AnyNode, ...]:
    return tuple(_wrap(a) for a in args)


# ---- Arithmetic ------------------------------------------------------------


def sum_(*args: Arg) -> Sum:
    """Formula-DAG node summing ``args``, auto-wrapping scalars/strings as ``Const``."""
    return Sum(x=_wrap_all(args))


def prod_(*args: Arg) -> Prod:
    """Formula-DAG node multiplying ``args``, auto-wrapping scalars/strings as ``Const``."""
    return Prod(x=_wrap_all(args))


def max_(*args: Arg) -> Max:
    """Formula-DAG node wrapping Python's ``max()`` so it composes with other Arg nodes."""
    return Max(x=_wrap_all(args))


def min_(*args: Arg) -> Min:
    """Formula-DAG node wrapping Python's ``min()`` so it composes with other Arg nodes."""
    return Min(x=_wrap_all(args))


def sumfrac(numer: Arg, denom_extra: Arg) -> SumFrac:
    """``numer / (numer + denom_extra)``. Used by DEF area formula.

    Named by the *extra* denominator term because Pando's ``sumfrac`` takes
    ``(a, b)`` and returns ``a / (a + b)`` — not the full denominator.
    """
    return SumFrac(x=(_wrap(numer), _wrap(denom_extra)))


# ---- Branching -------------------------------------------------------------


def threshold(left: Arg, right: Arg, if_ge: Arg, if_lt: Arg) -> Threshold:
    """``left >= right ? if_ge : if_lt``."""
    return Threshold(
        br=(_wrap(left), _wrap(right)),
        x=(_wrap(if_ge), _wrap(if_lt)),
    )


def match_(left: Arg, right: Arg, if_eq: Arg, if_ne: Arg) -> Match:
    """``left == right ? if_eq : if_ne``."""
    return Match(
        br=(_wrap(left), _wrap(right)),
        x=(_wrap(if_eq), _wrap(if_ne)),
    )


def lookup(key: Arg, table: dict[str, AnyNode], default: AnyNode) -> Lookup:
    """``table[key]`` with ``default`` fallback when ``key`` is unknown.

    The underlying ``Lookup`` op stores an ``ex: dict[str, int]`` index map
    plus an ``x`` tuple; this helper assembles both from an ordered
    ``{label: node}`` dict.
    """
    labels = list(table.keys())
    values = [*table.values(), default]
    ex: dict[str, int] = {label: i for i, label in enumerate(labels)}
    return Lookup(br=(_wrap(key),), x=tuple(values), ex=ex)


def subscript(index: Arg, table: tuple[int | float | str, ...]) -> Subscript:
    """``table[index]`` as a DAG node (e.g. ``defLevelFactor[level]``)."""
    return Subscript(br=(_wrap(index),), ex=table)


# ---- Tag manipulation ------------------------------------------------------


def tag_(inner: AnyNode, tag: Tag) -> TagOverride:
    """Evaluate ``inner`` under ``tag`` merged into current context."""
    return TagOverride(x=(inner,), tag=tag)


def vtag(category: str) -> TagValRead:
    """Read the current tag's value for ``category`` (empty string if absent)."""
    return TagValRead(ex=category)


# ---- Read ------------------------------------------------------------------


def read_(
    tag: Tag,
    accu: Literal["sum", "prod", "min", "max", "unique"] | None = None,
) -> Read:
    """Gather all registered nodes whose tag is a subset of current-context merged with ``tag``."""
    return Read(tag=tag, ex=accu)


# ---- Custom ----------------------------------------------------------------


def custom(name: str, *args: Arg) -> Custom:
    """Invoke a named Python function registered in ``CUSTOM_OPS``."""
    return Custom(x=_wrap_all(args), ex=name)
