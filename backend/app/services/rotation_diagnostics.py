"""What is wrong with a rotation, and where.

`TASKS_rotation_language.md` Phase 6, and it ships **before** the source view of Phase 7 on
purpose: the owner's ruling allows a typed surface, and *a typed surface is only as friendly
as its errors*. This repo already writes refusals better than most of what it does; this is
that discipline given a position and a severity so an editor can underline.

**Error against warning is not a style choice.** An error means gcsim will not run this. A
warning means it will run and probably not do what the author meant — `attack:0` is not an
attack, and a `raw` node is a construct carried rather than understood. Collapsing the two
would make a user either ignore both or fear both.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.rotation_nodes import (
    ActionNode,
    AssignNode,
    Binary,
    BranchNode,
    CallNode,
    Expression,
    FnNode,
    Identifier,
    LetNode,
    LoopNode,
    Node,
    RawNode,
    RotationTree,
    SwapNode,
    Unary,
)
from app.services import gcsim_keys
from app.services.gcsim_parser import parse_with_positions
from app.services.rotation_parser import _canonical, _roster_keys

#: Calls gcsim itself provides, which no `fn` in a config declares.
#:
#: **Measured over the 500-config corpus, not guessed**: these are the call names that appear
#: with no matching definition anywhere in their own file, and reporting them as undefined
#: would have produced a false error in 118 configs. `print` and `sleep` are debug and timing
#: controls; `pick_up_crystallize` is a real simulation action.
GCSIM_BUILTINS: frozenset[str] = frozenset({"print", "sleep", "pick_up_crystallize"})

#: A `fn` declaration inside a `raw` node's source.
#:
#: A function whose *body* this parser cannot model is carried whole, so it never becomes an
#: `FnNode` — and then every call to it looked undefined. That was 35 more false errors across
#: the corpus, all of them pointing at the caller rather than at the construct actually
#: responsible. The name is recovered from the carried source so the call resolves; its
#: parameters are not, so arity is not checked for one of these.
_RAW_FN = re.compile(r"\bfn\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)


class Severity(StrEnum):
    """How much a diagnostic matters."""

    #: gcsim will not run this.
    ERROR = "error"
    #: gcsim will run it, and it probably does not do what the author meant.
    WARNING = "warning"


class Diagnostic(BaseModel):
    """One problem, with the position an editor underlines."""

    severity: Severity
    message: str
    #: 1-based, so it matches what an editor's gutter shows.
    line: int = 1
    column: int = 1
    length: int = 1
    #: The path into the tree this is about, when it is about a node.
    path: list[str] = Field(default_factory=list)


#: How a diagnostic is built: a tree path, a severity and a message, positioned by the caller.
_Report = Callable[[tuple, "Severity", str], "Diagnostic"]


def _walk(nodes: Iterable[Node], prefix: tuple) -> Iterable[tuple[tuple, Node]]:
    """Every node with its path, depth first, in source order."""
    for index, node in enumerate(nodes):
        path = (*prefix, index)
        yield path, node
        if isinstance(node, LoopNode | FnNode):
            yield from _walk(node.body, (*path, "body"))
        elif isinstance(node, BranchNode):
            for arm, (_, body) in enumerate(node.arms):
                yield from _walk(body, (*path, "arms", arm))
            if node.otherwise is not None:
                yield from _walk(node.otherwise, (*path, "otherwise"))


def _identifiers(expression: Expression) -> set[str]:
    """Every plain identifier `expression` reads — not state paths, which gcsim answers."""
    if isinstance(expression, Identifier):
        return {expression.name}
    if isinstance(expression, Unary):
        return _identifiers(expression.operand)
    if isinstance(expression, Binary):
        return _identifiers(expression.left) | _identifiers(expression.right)
    return set()


def _reads(node: Node) -> set[str]:
    """Every identifier `node` reads in its own header or value."""
    if isinstance(node, LetNode | AssignNode):
        return _identifiers(node.value)
    if isinstance(node, CallNode):
        return {n for a in node.arguments for n in _identifiers(a)}
    if isinstance(node, LoopNode):
        return {
            n for part in (node.bound, node.condition) if part is not None
            for n in _identifiers(part)
        }
    if isinstance(node, BranchNode):
        return {n for cond, _ in node.arms for n in _identifiers(cond)}
    return set()


def _bound_names(nodes: Iterable[Node]) -> set[str]:
    """Names a `let`, an assignment or a loop header introduces at this level."""
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, LetNode | AssignNode):
            names.add(node.name)
        elif isinstance(node, LoopNode) and node.variable:
            names.add(node.variable)
    return names


def _functions(tree: RotationTree) -> dict[str, FnNode]:
    """Every function the config declares, `FnNode` or carried."""
    return {
        node.name: node for _, node in _walk(tree.nodes, ()) if isinstance(node, FnNode)
    }


def _carried_function_names(tree: RotationTree) -> set[str]:
    """Names declared inside `raw` nodes, so a call to one is not reported as undefined."""
    return {
        match.group(1)
        for _, node in _walk(tree.nodes, ()) if isinstance(node, RawNode)
        for match in _RAW_FN.finditer(node.source)
    }


def _reaches(name: str, defined: dict[str, FnNode], seen: set[str]) -> bool:
    """Does `name` call itself, directly or through others?

    gcsim's config language has no recursion, so a cycle is not a deep rotation — it is a
    config that will not run, and saying "undefined" or nothing at all would send the author
    looking in the wrong place.
    """
    if name in seen:
        return True
    body = defined.get(name)
    if body is None:
        return False
    seen = seen | {name}
    return any(
        _reaches(node.function, defined, seen)
        for _, node in _walk(body.body, ()) if isinstance(node, CallNode)
    )


def _call_diagnostics(tree: RotationTree, at: _Report) -> list[Diagnostic]:
    """Tasks 6.1 — undefined function, arity mismatch, recursion."""
    defined = _functions(tree)
    carried = _carried_function_names(tree)
    out: list[Diagnostic] = []
    for path, node in _walk(tree.nodes, ()):
        if not isinstance(node, CallNode):
            continue
        if node.function in GCSIM_BUILTINS or node.function in carried:
            continue
        target = defined.get(node.function)
        if target is None:
            out.append(at(path, Severity.ERROR, (
                f"nothing defines `{node.function}`. gcsim resolves a call against the "
                f"config's own `fn` declarations, so this one has nowhere to go."
            )))
            continue
        if len(node.arguments) != len(target.parameters):
            out.append(at(path, Severity.ERROR, (
                f"`{node.function}` takes {len(target.parameters)} argument(s) and this call "
                f"passes {len(node.arguments)}."
            )))
    for path, node in _walk(tree.nodes, ()):
        if isinstance(node, FnNode) and _reaches(node.name, defined, set()):
            out.append(at(path, Severity.ERROR, (
                f"`{node.name}` calls itself, directly or through another function. gcsim's "
                f"config language has no recursion, so this will not run."
            )))
    return out


def _scope_diagnostics(tree: RotationTree, at: _Report) -> list[Diagnostic]:
    """Task 6.2 — an identifier nothing brought into scope.

    Reported rather than emitted, because gcsim rejects the config and the author would
    otherwise meet the problem as a failed run with no line number.
    """
    out: list[Diagnostic] = []

    def visit(nodes: list[Node], prefix: tuple, scope: set[str]) -> None:
        here = scope | _bound_names(nodes)
        for index, node in enumerate(nodes):
            path = (*prefix, index)
            out.extend(
                at(path, Severity.ERROR, (
                    f"`{name}` is not in scope here. Nothing in this rotation declares it, so "
                    f"gcsim has no value to read."
                ))
                for name in sorted(_reads(node) - here)
            )
            if isinstance(node, LoopNode):
                inner = here | ({node.variable} if node.variable else set())
                visit(node.body, (*path, "body"), inner)
            elif isinstance(node, FnNode):
                visit(node.body, (*path, "body"), here | set(node.parameters))
            elif isinstance(node, BranchNode):
                for arm, (_, body) in enumerate(node.arms):
                    visit(body, (*path, "arms", arm), here)
                if node.otherwise is not None:
                    visit(node.otherwise, (*path, "otherwise"), here)

    # **A function's own name is in scope as a value.** `let _f = f;` takes a reference to
    # one, which real configs do; without this every such binding read as an undeclared name.
    visit(list(tree.nodes), (), set(_functions(tree)) | _carried_function_names(tree)
          | GCSIM_BUILTINS)
    return out


def _reference_diagnostics(
    tree: RotationTree, roster: Mapping[str, Any], at: _Report,
) -> list[Diagnostic]:
    """Task 6.3 — an unknown character or action, resolved against the team."""
    known_keys = _roster_keys(roster.values()) if roster else {}
    actions = set(gcsim_keys.all_offerable_actions())
    out: list[Diagnostic] = []
    for path, node in _walk(tree.nodes, ()):
        if not isinstance(node, ActionNode | SwapNode):
            continue
        name = node.character
        if known_keys and name not in roster and _canonical(name, known_keys) not in known_keys:
            out.append(at(path, Severity.ERROR, (
                f"`{name}` is not on this team. A rotation is compiled against the team's "
                f"builds, so there is nobody for this step to act as."
            )))
        if isinstance(node, ActionNode) and node.action not in actions:
            out.append(at(path, Severity.ERROR, (
                f"`{node.action}` is not an action a rotation step can name."
            )))
    return out


def _carried_diagnostics(tree: RotationTree, at: _Report) -> list[Diagnostic]:
    """A `raw` node is a **warning**, not an error: it runs, and it is not editable here."""
    return [
        at(path, Severity.WARNING, (
            f"carried as written rather than understood — {node.reason}. It will run exactly "
            f"as typed, and can be edited in the source view but not in the builder."
        ))
        for path, node in _walk(tree.nodes, ()) if isinstance(node, RawNode)
    ]


def validate_rotation(
    source: str, roster: Mapping[str, Any] | None = None,
) -> tuple[RotationTree, list[Diagnostic]]:
    """`(tree, diagnostics)` for gcsim `source`.

    Task 6.6: **returned rather than raised**, so the editor and the importer report
    identically. A validator that raises can only ever report its first problem, and an author
    fixing an imported rotation should learn what is wrong with it once.
    """
    tree, positions = parse_with_positions(source)

    def at(path: tuple, severity: Severity, message: str) -> Diagnostic:
        line, column, length = positions.get(path, (1, 1, 1))
        return Diagnostic(
            severity=severity, message=message,
            line=line, column=column, length=length,
            path=[str(part) for part in path],
        )

    diagnostics = [
        *_call_diagnostics(tree, at),
        *_scope_diagnostics(tree, at),
        *_reference_diagnostics(tree, roster or {}, at),
        *_carried_diagnostics(tree, at),
    ]
    diagnostics.sort(key=lambda d: (d.line, d.column))
    return tree, diagnostics
