"""A rotation tree back into gcsim source.

`DESIGN_rotation_language.md`. The property that governs this file and `gcsim_parser`
together is **`parse(emit(tree)) == tree`**, tested over generated trees and over every config
in the corpus.

**A `RawNode` emits its source byte for byte.** That is not an optimisation; it is what makes
the round trip mean anything. A raw node re-rendered from its own tokens would be a different
file that happens to mean the same thing, and the gate could then no longer tell a formatting
change from a meaning change — which is the one distinction it exists to make.
"""

from __future__ import annotations

from app.schemas.rotation_nodes import (
    ActionNode,
    AssignNode,
    BranchNode,
    CallNode,
    FnNode,
    LetNode,
    LoopNode,
    Node,
    RawNode,
    RotationTree,
    SwapNode,
    WaitNode,
    render_expression,
)

INDENT = "    "


def emit_tree(tree: RotationTree) -> str:
    """The gcsim source for `tree`, one statement per line."""
    return "\n".join(_emit_nodes(tree.nodes, 0)) + "\n"


def _emit_nodes(nodes: list[Node], depth: int) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.extend(_emit(node, depth))
    return lines


def _emit(node: Node, depth: int) -> list[str]:
    pad = INDENT * depth
    if isinstance(node, RawNode):
        # **Byte for byte.** Indentation is not re-applied either: the author's own layout is
        # part of what `raw` promises to reproduce.
        return node.source.splitlines()
    if isinstance(node, LoopNode):
        return _loop(node, depth)
    if isinstance(node, BranchNode):
        return _branch(node, depth)
    if isinstance(node, FnNode):
        parameters = ", ".join(node.parameters)
        return [f"{pad}fn {node.name}({parameters}) {{",
                *_emit_nodes(node.body, depth + 1), f"{pad}}}"]
    line = _SIMPLE.get(type(node))
    if line is None:
        msg = f"no emitter for node kind {node.kind!r}"
        raise ValueError(msg)
    return [pad + line(node)]


def _action(node: ActionNode) -> str:
    params = ""
    if node.params:
        inner = ",".join(f"{k}={v}" for k, v in node.params.items())
        params = f"[{inner}]"
    repeat = f":{node.repeat}" if node.repeat != 1 else ""
    return f"{node.character} {node.action}{params}{repeat};"


#: The node kinds that emit one line and hold no body.
_SIMPLE = {
    ActionNode: _action,
    SwapNode: lambda n: f"{n.character} swap;",
    WaitNode: lambda n: f"{n.mode}({n.frames});",
    LetNode: lambda n: f"let {n.name} = {render_expression(n.value)};",
    AssignNode: lambda n: f"{n.name} = {render_expression(n.value)};",
    CallNode: lambda n: (
        f"{n.function}({', '.join(render_expression(a) for a in n.arguments)});"
    ),
}


def _loop(node: LoopNode, depth: int) -> list[str]:
    pad = INDENT * depth
    if node.loop == "counted":
        variable = node.variable or "i"
        header = (
            f"{pad}for let {variable}=0; {variable}<"
            f"{render_expression(node.bound)}; {variable}={variable}+1 {{"
        )
    else:
        header = f"{pad}while {render_expression(node.condition)} {{"
    return [header, *_emit_nodes(node.body, depth + 1), f"{pad}}}"]


def _branch(node: BranchNode, depth: int) -> list[str]:
    """`if` / `else if` / `else`, emitted as gcsim's own chain.

    The `}` and the `else` share a line, which is how gcsim's own parser expects them and how
    every config in the corpus writes it.
    """
    pad = INDENT * depth
    lines: list[str] = []
    for index, (condition, body) in enumerate(node.arms):
        keyword = "if" if index == 0 else "} else if"
        lines.append(f"{pad}{keyword} {render_expression(condition)} {{")
        lines.extend(_emit_nodes(body, depth + 1))
    if node.otherwise is not None:
        lines.append(f"{pad}}} else {{")
        lines.extend(_emit_nodes(node.otherwise, depth + 1))
    lines.append(f"{pad}}}")
    return lines
