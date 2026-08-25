"""The successor table in `app/dependencies.py` names factories that exist (N.4).

That comment replaced a chunk-F/G marker which had gone stale *in the direction that
matters*: it listed twelve absent factories, and nine of them had already landed under
Genshin names. It read as a pile of missing wiring long after the wiring was there.

Prose cannot go stale quietly if a test reads it. This one parses the table out of the
comment and checks both halves against the module: every successor must exist, and every
factory listed as deliberately absent must still be absent. A rename that leaves the note
behind fails here rather than at the next reader.
"""

from __future__ import annotations

import re
from pathlib import Path

import app.dependencies as deps

SOURCE = Path(deps.__file__).read_text(encoding="utf-8")

#: `#   get_agent_repo   → get_character_repo` — the successor table's rows.
_MAPPING = re.compile(r"^#\s+(get_\w+)\s+→\s+(get_\w+)", re.MULTILINE)
#: `#   get_attack_repo            ZZZ. …` — the deliberately-absent rows, which have no
#: arrow. The name column is padded to the longest entry, so the shortest gap is a single
#: space; the lookahead is what separates these from the mapping rows above.
_ABSENT = re.compile(r"^#\s+(get_\w+_repo)\s+(?!→)\S", re.MULTILINE)


def test_the_table_was_actually_found() -> None:
    """A regex that matches nothing would make every assertion below vacuously true."""
    assert len(_MAPPING.findall(SOURCE)) >= 9
    assert len(_ABSENT.findall(SOURCE)) == 3


def test_every_successor_named_in_the_comment_exists() -> None:
    for old, new in _MAPPING.findall(SOURCE):
        assert hasattr(deps, new), f"{old} is documented as {new}, which does not exist"


def test_every_predecessor_named_in_the_comment_is_gone() -> None:
    """The left column is ZZZ vocabulary. If one came back, the note is describing history
    as if it were the present — and the BRIEF says delete these concepts, not restore them."""
    for old, new in _MAPPING.findall(SOURCE):
        if old == new:
            # Exactly one row maps a name to itself, and it is named here rather than
            # allowed by shape. A bare `continue` on `old == new` was an escape hatch any
            # row could reach: rewriting a row's left column to match its right column made
            # the row unfalsifiable, and a mutation walked straight through it.
            assert old == "get_owned_build_repo", f"{old} maps to itself; only one row may"
            assert hasattr(deps, old), "the one unchanged factory is missing"
            continue
        assert not hasattr(deps, old), f"{old} exists, but the comment says it became {new}"


def test_the_deliberately_absent_factories_are_absent() -> None:
    """Two are ZZZ concepts; `get_build_repo` is an unscoped build repository, which is a
    tenancy bug one missing `Depends` away. If one appears, it needs a reason, not a comment
    still calling it absent."""
    for name in _ABSENT.findall(SOURCE):
        assert not hasattr(deps, name), f"{name} exists, but the comment lists it as absent"
