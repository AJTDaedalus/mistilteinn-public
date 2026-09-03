"""Compile a rotation tree to a gcsim action block.

`TASKS_rotation_language.md` Phase 5. Two paths, and the split is deliberate:

- **A tree that has a faithful `steps` form is compiled by `compile_rotation`**, unchanged.
  That is not laziness; it is the cheapest possible proof of the Phase 4 gate. Every rotation
  saved before this work existed produces byte-identical gcsim text afterwards, because it goes
  through byte-identical code.
- **A tree that does not** — one holding a user function, a `wait`, an `else`, or a `raw` node
  — is emitted directly. These are the rotations `steps` could never hold, so there is nothing
  to preserve and no regression to risk.

**Burst gating is applied to the tree, which is what a verbatim passthrough could not do.**
gcsim has no watchdog: `actionReadyCheckPhase` retries a frame forever, so an unfundable burst
grows a per-frame stats slice until the kernel kills it — measured at 2.4 GB. A cooldown always
expires and waiting on one models a player; energy may never arrive. So a burst is gated unless
the author already guarded it, or the waiting model is on.
"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003 — a runtime annotation
from typing import Any

from app.schemas.rotation_nodes import (
    ActionNode,
    BranchNode,
    Expression,
    FnNode,
    LoopNode,
    Node,
    RotationTree,
    StatePath,
    render_expression,
)
from app.services.gcsim_emitter import emit_tree
from app.services.rotation_compiler import compile_rotation, rotation_signature
from app.services.rotation_tree_migration import steps_from_tree

#: `.<character>.<property>` — the shortest path that can name a character's state.
_PATH_MIN = 2

#: The one action whose readiness the rotation cannot make true on its own.
_ENERGY_GATED_ACTION = "burst"


def _mentions(expression: Expression, character: str) -> bool:
    """Does `expression` already test this character's energy or burst readiness?

    Read structurally rather than by substring: `.noelle.energy` and `.noelleX.energy` differ
    by one character and a substring test would confuse them.
    """
    if isinstance(expression, StatePath):
        segments = expression.segments
        return len(segments) >= _PATH_MIN and segments[0] == character and (
            segments[1] == "energy"
            or (segments[1] == _ENERGY_GATED_ACTION and "ready" in segments)
        )
    left = getattr(expression, "left", None)
    right = getattr(expression, "right", None)
    operand = getattr(expression, "operand", None)
    return any(
        _mentions(part, character)
        for part in (left, right, operand) if part is not None
    )


def _gate(nodes: list[Node], guards: list[Expression]) -> list[Node]:
    out: list[Node] = []
    for node in nodes:
        if isinstance(node, ActionNode) and node.action == _ENERGY_GATED_ACTION:
            if any(_mentions(g, node.character) for g in guards):
                out.append(node)          # the author's own guard is their energy model
                continue
            out.append(BranchNode(
                kind="branch",
                arms=[(StatePath(kind="state",
                                 segments=[node.character, "burst", "ready"]), [node])],
                otherwise=None,
            ))
        elif isinstance(node, BranchNode):
            arms = [(cond, _gate(body, [*guards, cond])) for cond, body in node.arms]
            otherwise = _gate(node.otherwise, guards) if node.otherwise is not None else None
            out.append(node.model_copy(update={"arms": arms, "otherwise": otherwise}))
        elif isinstance(node, LoopNode):
            inner = [*guards, node.condition] if node.condition is not None else guards
            out.append(node.model_copy(update={"body": _gate(node.body, inner)}))
        elif isinstance(node, FnNode):
            out.append(node.model_copy(update={"body": _gate(node.body, guards)}))
        else:
            out.append(node)
    return out


def gate_bursts(tree: RotationTree, *, wait_for_energy: bool) -> RotationTree:
    """`tree` with a readiness gate on every burst the author did not already guard.

    Under the waiting model nothing is gated: gcsim then *waits* for the energy, which is what
    a player at a keyboard does, and the cited energy drip is what bounds the wait
    (`DESIGN_waiting_for_energy.md`).
    """
    if wait_for_energy:
        return tree
    return RotationTree(nodes=_gate(list(tree.nodes), []))


def _characters(nodes: list[Node]) -> set[str]:
    """Every character named anywhere in `nodes`."""
    found: set[str] = set()
    for node in nodes:
        if isinstance(node, ActionNode):
            found.add(node.character)
        elif isinstance(node, BranchNode):
            for _, body in node.arms:
                found |= _characters(body)
            if node.otherwise is not None:
                found |= _characters(node.otherwise)
        elif isinstance(node, LoopNode | FnNode):
            found |= _characters(node.body)
    return found


def compile_tree(
    tree: RotationTree,
    characters: Mapping[str, Any],
    *,
    wait_for_energy: bool = False,
) -> str:
    """The gcsim action block for `tree`.

    **A tree carries its source's vocabulary, and the two are not the same.** One converted
    from `steps` names characters by *nanoka id*, because that is what a step stores; one
    parsed from a config names them by *gcsim key*, because that is what the author wrote.
    Resolving is `compile_rotation`'s job and it only knows the first, so the steps path is
    taken **only when every character is one the roster can resolve**. Otherwise the tree is
    emitted directly, where gcsim keys are already what belongs in the output.

    Checking rather than assuming matters: a parsed tree fed to `compile_rotation` raises on
    the first unknown key, which is a loud failure — but the reverse mistake, emitting nanoka
    ids into a config, would be a silent one that gcsim rejects much later.
    """
    gated = gate_bursts(tree, wait_for_energy=wait_for_energy)
    if not _characters(list(tree.nodes)) <= set(characters):
        return emit_tree(gated)
    try:
        steps = steps_from_tree(tree)
    except ValueError:
        return emit_tree(gated)
    return compile_rotation(steps, characters, wait_for_energy=wait_for_energy)


def tree_signature(
    tree: RotationTree,
    characters: Mapping[str, Any],
) -> list[str]:
    """The rotation as `sim_context.context_key` sees it — task 5.3.

    **Structural, so it is stable under reformatting and changes when meaning changes.** A key
    hashed from the *text* would miss the recipe cache for a whitespace edit and — worse — a
    comment change would look like a new rotation, so a user tidying their config would pay for
    a fresh gcsim run every time.

    It goes through `rotation_signature` for a tree that has a steps form, for the same reason
    `compile_tree` does: a signature and a config that disagree about who a step names is the
    exact failure `context_key` exists to prevent, and sharing the code is the only way to
    guarantee they cannot. For a tree that has no steps form, the emitted block is the
    signature — it is what gcsim will actually run.
    """
    if _characters(list(tree.nodes)) <= set(characters):
        try:
            return rotation_signature(steps_from_tree(tree), characters)
        except ValueError:
            pass
    return [line for line in emit_tree(tree).splitlines() if line.strip()]


__all__ = ["compile_tree", "gate_bursts", "render_expression", "tree_signature"]
