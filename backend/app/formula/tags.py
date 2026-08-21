"""Tag type for the Pando DAG.

A ``Tag`` is a multi-axis coordinate — e.g. ``{src: "Anby", q: "atk_"}``
labels a node as "Anby's ATK%". The calculator carries an implicit tag
context while traversing the graph; ``tag``/``dtag`` ops push overrides,
``read`` ops query all nodes whose registration tag is a subset of the
current context.

Semantics (port of ``libs/pando/engine/src/tag/type.ts``):

* A category missing from the tag = "no constraint".
* A category mapped to ``None`` = "clear this category when merging"
  (only meaningful during ``merge``; stripped from the effective view).
* Two tags are equal when their canonical (sorted, ``None``-stripped)
  form matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

# A tag entry: (category, value). value=None means "clear on merge".
_Entry = tuple[str, str | None]


def _canonical(items: dict[str, str | None]) -> tuple[_Entry, ...]:
    """Canonicalize: sort by key; preserve ``None`` (carries merge intent)."""
    return tuple(sorted(items.items()))


@dataclass(frozen=True, slots=True)
class Tag:
    """Hashable, immutable tag — a sorted tuple of ``(category, value)``.

    Build with :meth:`of`. Combine with :meth:`merge`. Equality and hashing
    use the canonical form, so order of construction is irrelevant.
    """

    items: tuple[_Entry, ...] = ()

    @classmethod
    def of(cls, **kwargs: str | None) -> Self:
        """Construct a tag from keyword arguments.

        >>> Tag.of(src="Anby", q="atk_")
        Tag(src=Anby, q=atk_)
        """
        return cls(items=_canonical(kwargs))

    def merge(self, other: Tag) -> Tag:
        """Return ``self`` overlaid with ``other``.

        * ``other`` values overwrite ``self`` values on the same category.
        * ``other`` values that are ``None`` remove the category entirely.
        * ``self`` is not mutated.
        """
        merged: dict[str, str | None] = dict(self.items)
        for k, v in other.items:
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        return Tag(items=_canonical(merged))

    def get(self, category: str) -> str:
        """Return the value for ``category``, or ``""`` if absent.

        Pando convention: missing → empty string (makes ``vtag`` total).
        """
        for k, v in self.items:
            if k == category:
                return v or ""
        return ""

    def is_subset_of(self, other: Tag) -> bool:
        """Is every concrete (non-None) entry in ``self`` present in ``other``?

        Used by ``read``-op gathering: a node registered under tag ``R`` is
        gathered by a read whose effective tag ``Q`` satisfies
        ``R.is_subset_of(Q)``.
        """
        other_map = dict(other.items)
        for k, v in self.items:
            if v is None:
                continue
            if other_map.get(k) != v:
                return False
        return True

    def __repr__(self) -> str:
        if not self.items:
            return "Tag()"
        body = ", ".join(f"{k}={v}" for k, v in self.items if v is not None)
        return f"Tag({body})"
