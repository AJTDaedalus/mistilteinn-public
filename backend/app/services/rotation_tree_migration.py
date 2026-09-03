"""`Rotation.steps` into a `RotationTree`, and back.

`TASKS_rotation_language.md` Phase 4. The gate on that phase is that **no saved rotation
changes meaning**, so this conversion has to be lossless in both directions before the
compiler is allowed to read a tree.

The correspondence is exact rather than approximate, which is what makes the gate checkable:

| step field | node |
|---|---|
| `group` (a path) | one wrapper per segment, outermost first |
| `group_repeat` | `LoopNode(counted)` with a literal bound |
| `group_condition` | `BranchNode` with a single arm and no `else` |
| everything else | `ActionNode` |

**A group that both repeats and guards nests the loop inside the branch**, matching what the
compiler already emits: `unroll` expands the repeat *inside* the `if` block that `_blocked`
opens, so the guard is tested once and the repeated steps run within it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence  # noqa: TC003 — used at runtime by Pydantic
from typing import Any

from app.schemas.rotation_nodes import (
    ActionNode,
    BranchNode,
    Expression,
    Identifier,
    Literal,
    LoopNode,
    Node,
    RotationTree,
)
from app.services.gcsim_tokenizer import GcsimSyntaxError


def _condition(text: str) -> Expression:
    """The stored condition string as an expression.

    Parsed with the real parser rather than a second reader, so a condition the importer
    accepts and one a migration accepts cannot diverge. An unreadable one becomes an
    `Identifier` holding the original text — which re-emits exactly and so keeps the
    conversion lossless even for a condition nothing else understands.
    """
    from app.services.gcsim_parser import _Parser  # noqa: PLC0415 — avoids a cycle
    from app.services.gcsim_tokenizer import tokenize  # noqa: PLC0415

    try:
        parser = _Parser(text, tokenize(text))
    except GcsimSyntaxError:
        return Identifier(kind="identifier", name=text)
    expression = parser.expression()
    if expression is None or not parser.done():
        return Identifier(kind="identifier", name=text)
    return expression


def _render_condition(expression: Expression) -> str:
    """The stored form of a condition, undoing `_condition` exactly."""
    from app.schemas.rotation_nodes import render_expression  # noqa: PLC0415

    if isinstance(expression, Identifier):
        return expression.name
    return render_expression(expression)


def _action_node(step: Mapping[str, Any]) -> ActionNode:
    return ActionNode(
        kind="action",
        character=str(step["character"]),
        action=str(step["action"]),
        repeat=int(step.get("repeat") or 1),
        note=str(step.get("note") or ""),
    )


def _wrap(body: list[Node], repeat: int, condition: str, label: str) -> list[Node]:
    """One group level's wrappers around `body`, innermost applied first.

    Both wrappers carry the group's own `label`, so `steps_from_tree` can rebuild the path
    this level came from. Without it the conversion is structure-preserving and **not**
    lossless, which is not good enough for a gate that says no saved rotation changes.
    """
    wrapped = body
    if repeat and repeat > 1:
        wrapped = [LoopNode(kind="loop", loop="counted", variable="i", label=label,
                            bound=Literal(kind="literal", value=repeat), body=wrapped)]
    if condition:
        wrapped = [BranchNode(kind="branch", label=label,
                              arms=[(_condition(condition), wrapped)], otherwise=None)]
    return wrapped


def _convert(steps: Sequence[Mapping[str, Any]], depth: int) -> list[Node]:
    """Nodes for `steps`, treating group path segment `depth` as this level's blocks."""
    nodes: list[Node] = []
    index = 0
    while index < len(steps):
        path = (str(steps[index].get("group") or "")).split("/") if steps[index].get(
            "group") else []
        if len(path) <= depth:
            nodes.append(_action_node(steps[index]))
            index += 1
            continue

        segment = path[depth]
        run_end = index
        while run_end < len(steps):
            other = (str(steps[run_end].get("group") or "")).split("/") if steps[
                run_end].get("group") else []
            if len(other) <= depth or other[depth] != segment:
                break
            run_end += 1

        member = steps[index]
        nodes.extend(_wrap(
            _convert(steps[index:run_end], depth + 1),
            int(member.get("group_repeat") or 1),
            str(member.get("group_condition") or ""),
            segment,
        ))
        index = run_end
    return nodes


def tree_from_steps(steps: Sequence[Mapping[str, Any]]) -> RotationTree:
    """The tree for a stored rotation's `steps`."""
    return RotationTree(nodes=_convert(list(steps), 0))


def steps_from_tree(tree: RotationTree) -> list[dict[str, Any]]:
    """`steps` for a tree that came from one — the inverse of `tree_from_steps`.

    Exists for the rollout, where the read path prefers a tree and old rows still hold steps,
    and for the gate: a conversion that cannot be inverted has not been shown to be lossless.
    A tree holding a node kind `steps` has no field for raises, because silently dropping one
    is exactly what this whole design refuses.
    """
    steps: list[dict[str, Any]] = []
    _flatten(tree.nodes, "", 1, "", steps, _Names())

    # **The conversion checks itself.** A step carries only its *deepest* group condition, so
    # a tree that nests a branch inside a loop can come back with the branch's guard applied
    # to steps that were never inside it — 2 of the 69 convertible corpus configs, and the
    # rotation would then run differently while looking like the one that was imported.
    # Refusing is the same contract as the node kinds below: a rotation that cannot be
    # represented as steps keeps its tree.
    if steps and steps_from_tree_unchecked(tree_from_steps(steps)) != steps:
        msg = (
            "this rotation's block nesting has no faithful `steps` form — a step records only "
            "the innermost condition it is under, so an outer block's guard would move. It "
            "must keep its tree."
        )
        raise ValueError(msg)
    return steps


def steps_from_tree_unchecked(tree: RotationTree) -> list[dict[str, Any]]:
    """`steps_from_tree` without the self-check, so the check itself can use it."""
    steps: list[dict[str, Any]] = []
    _flatten(tree.nodes, "", 1, "", steps, _Names())
    return steps


class _Names:
    """Supplies a group name for a block that has none.

    **A block without a name cannot be stored as steps.** `group` is what carries a repeat and
    a condition, so a loop whose members have `group=""` loses its count entirely — the steps
    come back as plain actions and the rotation runs once instead of six times. An *imported*
    tree has no labels at all, so this is the normal case rather than an edge one: it was 69 of
    69 convertible corpus configs, silently, and the synthetic tests missed it because every
    block in them was built from steps that already had a name.
    """

    def __init__(self) -> None:
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"block{self.n}"


def _flatten(nodes: Sequence[Node], group: str, repeat: int, condition: str,
             out: list[dict[str, Any]], names: _Names) -> None:
    for node in nodes:
        if isinstance(node, ActionNode):
            out.append({
                "character": node.character, "action": node.action, "repeat": node.repeat,
                "note": node.note, "group": group,
                "group_repeat": repeat, "group_condition": condition,
            })
        elif isinstance(node, BranchNode) and len(node.arms) == 1 and node.otherwise is None:
            expression, body = node.arms[0]
            _flatten(body, _join(group, node.label or names.next()), repeat,
                     _render_condition(expression), out, names)
        elif isinstance(node, LoopNode) and node.loop == "counted":
            bound = node.bound
            count = int(bound.value) if isinstance(bound, Literal) else 1
            _flatten(node.body, _join(group, node.label or names.next()), count,
                     condition, out, names)
        else:
            msg = (
                f"a {node.kind!r} node has no `steps` equivalent. Converting it would drop "
                f"what it says, and this rotation must keep its tree."
            )
            raise ValueError(msg)


def _join(group: str, label: str) -> str:
    """This block's contribution to its members' group path.

    A branch wrapping a loop with the *same* label is one group level written as two nodes, so
    the label is appended once rather than twice — otherwise `"g"` would come back as `"g/g"`.
    """
    if not label:
        return group
    if group.rsplit("/", maxsplit=1)[-1] == label:
        return group
    return f"{group}/{label}" if group else label


def tree_for(rotation: Any) -> RotationTree:
    """The tree for a stored rotation, **preferring the column and falling back to steps**.

    Task 4.5. The fallback is what lets the column be nullable and the rollout be uncoordinated:
    a row written before `rotations.tree` existed, or one whose backfill was refused, is still
    readable — it is converted on the way out instead. Nothing has to be migrated before the
    code that reads trees can ship.
    """
    stored = getattr(rotation, "tree", None)
    if stored:
        return RotationTree.model_validate(stored)
    return tree_from_steps(list(getattr(rotation, "steps", None) or []))
