"""Query/aggregate the merged Dimbreath TextMap by key grammar (read-only).

Supporting toolkit for Phase 1 of the cartography plan. The TextMap is a flat
``{key: value}`` map of ~394k entries; the mechanically-relevant slice follows a
key grammar::

    {Entity}_{Category}_{Sub...}_{NN}

where ``Entity`` is an agent **code name** (``Velina``, ``Anbi``, ``SPBilly``) or
a system namespace (``Bangboo``, ``Weapon``, ``Common``, ``Main``, ``Activity``,
…), ``Category`` is ``Property`` / ``Skill`` / ``Talent`` / ``NounPrompts`` /
``SkillList`` / ``UniqueSkill`` / ``MathSkill`` / …, and the trailing ``_NN`` is a
1-based index.

These helpers power the schema generators; they do not write anything.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from scripts.dimbreath.fetch import load_textmap

if TYPE_CHECKING:
    from collections.abc import Iterable

# Trailing 1- or 2-segment numeric index, e.g. ``_01`` or ``_5300303_01``.
_INDEX_RE = re.compile(r"(?:_\d+)+$")
_VALUE_TOKEN = "_Property_"  # noqa: S105 - TextMap namespace token, not a secret


def split_key(key: str) -> tuple[str, str | None, str | None]:
    """Return ``(entity, category, remainder_without_trailing_index)``.

    ``entity`` = first segment. ``category`` = second segment (or ``None``).
    ``remainder`` = everything between category and the trailing numeric index.
    """
    parts = key.split("_")
    entity = parts[0]
    category = parts[1] if len(parts) > 1 else None
    body = key
    body = _INDEX_RE.sub("", body)
    rem_parts = body.split("_")[2:]
    remainder = "_".join(rem_parts) or None
    return entity, category, remainder


def trailing_index(key: str) -> str | None:
    m = _INDEX_RE.search(key)
    return m.group(0).lstrip("_") if m else None


def query(textmap: dict[str, str], pattern: str) -> dict[str, str]:
    """Return the subset of ``textmap`` whose keys match ``pattern`` (regex)."""
    rx = re.compile(pattern)
    return {k: v for k, v in textmap.items() if rx.search(k)}


def entity_of_property(key: str) -> str:
    """Entity code-name for a ``*_Property_*`` key (the part before ``_Property_``
    is **not** reliable — e.g. ``Alice_Skill_Special_02_Property_*`` — so we take
    the leading code-name run instead)."""
    return key.split("_", 1)[0]


def property_families(textmap: dict[str, str]) -> Counter:
    """Count the sub-family head token immediately after ``_Property_``."""
    fam: Counter = Counter()
    for k in textmap:
        if _VALUE_TOKEN in k:
            tail = k.split(_VALUE_TOKEN, 1)[1]
            fam[tail.split("_")[0]] += 1
    return fam


def category_counts(textmap: dict[str, str]) -> Counter:
    cats: Counter = Counter()
    for k in textmap:
        _, cat, _ = split_key(k)
        cats[cat or "<single-segment>"] += 1
    return cats


def cost_value_keys(textmap: dict[str, str]) -> dict[str, str]:
    """All ``*_Property_*CostValue*`` keys (the resource-cost numbers)."""
    return query(textmap, r"_Property_.*CostValue")


def iter_entities(keys: Iterable[str]) -> set[str]:
    return {k.split("_", 1)[0] for k in keys}


def load() -> dict[str, str]:
    """Convenience: the merged EN TextMap at the pinned SHA."""
    return load_textmap("en")
