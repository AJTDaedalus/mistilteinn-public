"""Structural guard: no call site may re-derive the support list by slot index alone.

Issue #133. Seven call sites had independently written
``[m for i, m in enumerate(members) if i != active_index]``, and every one of them
carried the same defect — a build occupying two slots comes back as its own support.
They now share `select_support_members`.

**Why a structural test and not only behavioural ones.** The defect class here is
"someone writes the filter inline again", and the behavioural cost of that is invisible:
it only shows on a team row that `assert_slots_distinct` no longer lets anyone create,
so no ordinary test would go red. A per-site behavioural test also cannot cover the site
that does not exist yet. This test fails the moment the *comprehension* pattern reappears
anywhere under ``app/``, which is what the #133 acceptance criteria asked for — "a test
must fail if any single site is reverted", verified against each of the seven.

**What it does not cover, deliberately.** It matches comprehensions filtered by a slot
index. It cannot see a support list derived some other way — a ``members[1:]`` slice, a
``for``/``append`` loop, a ``filter()`` call, or a comprehension whose index variable is
named something this file does not know. `teams.py::_evaluate_team` was exactly such a
site (``all_members[1:]``); it is pinned behaviourally instead, by
`tests/unit/test_teams_calculate_support_selection.py`. Treat this as a tripwire on the
one spelling that has actually recurred seven times, not as proof that no other spelling
exists.

`tests/integration/test_self_support_exclusion.py` carries the behavioural half: that
the helper is genuinely wired into the pipelines rather than merely imported.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

# `i != active_index` / `i != idx` — the comparison at the heart of every one of the
# seven original sites. Matching the *comparison* rather than the whole comprehension
# keeps this robust to reformatting.
#
# Deliberately only the *team-slot* names. Widening this to bare ``i``/``slot`` makes the
# check fire on unrelated index arithmetic — ``disc_scorer``'s
# ``_slot_int(d) != candidate.slot`` (disc slots) and ``disc_optimizer``'s
# ``d.set_id == assignment[i]`` both trip it — and a guard that cries wolf gets weakened
# by the next person to hit it.
_INDEX_NAMES = {"active_index", "idx", "_idx", "primary_index"}

# Attributes/names that identify a *build*, as opposed to a slot. A comparison against
# one of these is what makes an inline selection safe.
_IDENTITY_NAMES = {"id", "build_id", "target_id", "target_build_id", "_target_id"}


def _iter_python_files() -> list[Path]:
    return sorted(p for p in APP_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _mentions(node: ast.AST, names: set[str]) -> bool:
    """Does any `Name`/`Attribute` under *node* resolve to one of *names*?"""
    return any(
        (isinstance(n, ast.Name) and n.id in names)
        or (isinstance(n, ast.Attribute) and n.attr in names)
        for n in ast.walk(node)
    )


def _equality_compares(node: ast.AST) -> list[ast.Compare]:
    """Every ``==``/``!=`` comparison under *node* that is not against a literal.

    Restricting to equality is what separates a *selection* rule from an incidental
    mention. ``m.build_id is not None`` names an identity attribute but does not
    compare identities, so it must not count as a guard — that loophole is how a
    genuinely index-only filter could slip past this check.
    """
    out: list[ast.Compare] = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Compare):
            continue
        if not all(isinstance(op, ast.Eq | ast.NotEq) for op in n.ops):
            continue
        if any(isinstance(side, ast.Constant) for side in (n.left, *n.comparators)):
            continue
        out.append(n)
    return out


def _index_only_filters(tree: ast.AST) -> list[int]:
    """Line numbers of comprehensions whose only member filter is a slot-index compare.

    A comprehension that *also* compares build identity is fine — that is what the old
    hand-guarded `scorer.py` rank-job site did before #133 folded it into the helper —
    so the check is for an index compare with no identity compare alongside it.
    """
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            continue
        conditions = [cond for gen in node.generators for cond in gen.ifs]
        if not conditions:
            continue

        compares = [c for cond in conditions for c in _equality_compares(cond)]
        if not any(_mentions(c, _INDEX_NAMES) for c in compares):
            continue
        # An identity comparison alongside it makes the selection safe.
        if any(_mentions(c, _IDENTITY_NAMES) for c in compares):
            continue
        hits.append(node.lineno)
    return hits


@pytest.mark.parametrize("path", _iter_python_files(), ids=lambda p: str(p.name))
def test_no_module_selects_supports_by_slot_index_alone(path: Path) -> None:
    """Every support list must come from `select_support_members`.

    If this fails on a comprehension that is genuinely not selecting team supports
    (some other list filtered by an index), give that comprehension an identity
    comparison or restructure it — do not weaken this test. The whole point is that
    the seven original sites all looked locally reasonable.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    hits = _index_only_filters(tree)

    assert not hits, (
        f"{path.relative_to(APP_ROOT.parent)} filters a list by slot index alone at "
        f"line(s) {hits}. If this is a team support list, use "
        f"`select_support_members(members, active_index)` — selecting by index alone "
        f"returns a build occupying two slots as its own support (issue #133)."
    )


def test_the_guard_would_catch_a_reintroduced_site() -> None:
    """The test above is only worth having if it fires on the pattern it describes.

    This is the exact shape all seven original call sites had.
    """
    reintroduced = ast.parse(
        "supports = [m for i, m in enumerate(members) "
        "if i != body.active_index and m is not None]"
    )

    assert _index_only_filters(reintroduced), (
        "the structural guard no longer detects the pattern it exists to prevent"
    )


def test_an_identity_guarded_comprehension_is_accepted() -> None:
    """The pre-#133 hand-guarded form must not be reported — it was already correct."""
    guarded = ast.parse(
        "supports = [m for i, m in enumerate(members) "
        "if i != idx and m is not None and str(m.id) != target_id]"
    )

    assert not _index_only_filters(guarded)


def test_merely_naming_an_identity_attribute_is_not_a_guard() -> None:
    """The escape hatch needs a *comparison* of identities, not a mention of one.

    ``m.build_id is not None`` reads like a guard and is not one — the filter is still
    index-only, so a build in two slots still comes back as its own support. An earlier
    form of this check looked for the substring ``build_id`` anywhere in the condition
    and accepted exactly this.
    """
    _head = "supports = [m for i, m in enumerate(members) if i != active_index and "
    for src in (
        f"{_head}m.build_id is not None]",
        f"{_head}m.id]",
        f"{_head}m.build_id not in seen]",
    ):
        assert _index_only_filters(ast.parse(src)), src


def test_the_guard_covers_generator_dict_and_set_comprehensions() -> None:
    """Swapping the brackets must not be a way out."""
    for src in (
        "supports = {m for i, m in enumerate(members) if i != active_index}",
        "supports = {m.name: m for i, m in enumerate(members) if i != active_index}",
        "total = sum(m.atk for i, m in enumerate(members) if i != active_index)",
    ):
        assert _index_only_filters(ast.parse(src)), src
