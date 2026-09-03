"""The rotation as a tree, rather than a list with a path column.

`DESIGN_rotation_language.md`. A rotation today is `list[RotationStep]` plus `group` (a path),
`group_repeat` and `group_condition` — which is already a tree flattened into a list, and does
not survive `else`, nested loops or user-defined functions.

**The load-bearing decision here is `RawNode`.** Anything the parser cannot model is carried
as its exact source text, emits byte-identically, and blocks nothing. That is what makes
import 100 % from the first phase of this work rather than the last, and it is why no later
phase can regress what a user is able to bring in.

The rule that keeps it honest: **a `raw` node is opaque, never partial.** A production that
cannot complete emits `raw` for its *whole* construct. Reading half a `for` and raw-ing the
body would produce a tree that looks structured and emits something the author did not write,
which is the failure `DESIGN_conditional_steps.md` exists to prevent, arrived at from the
other side.
"""

from __future__ import annotations

from typing import Annotated
from typing import Literal as Lit

from pydantic import BaseModel, Field, field_validator, model_validator

# ── expressions ──────────────────────────────────────────────────────────────
#
# Parsed and re-emitted, **never evaluated here**. The one exception belongs to the converter:
# a condition that is a pure function of a counted loop's index is arithmetic, and unrolling
# it is this repo's own precedent (`_unroll_parity`).

#: Binary operators gcsim's config language uses, grouped by precedence — loosest first.
#:
#: Precedence is not cosmetic. `a && b || c` and `a && (b || c)` are different guards, so an
#: emitter that drops a parenthesis hands gcsim a rotation nobody wrote.
PRECEDENCE: dict[str, int] = {
    "||": 1,
    "&&": 2,
    "==": 3, "!=": 3, "<": 3, "<=": 3, ">": 3, ">=": 3,
    "+": 4, "-": 4,
    "*": 5, "/": 5, "%": 5,
}

UNARY_OPS = frozenset({"!", "-"})


class Literal(BaseModel):
    """A number, a boolean, or a string."""

    kind: Lit["literal"] = "literal"
    value: int | float | bool | str


class Identifier(BaseModel):
    """The config's own variable — a loop index, a `let` binding, a function parameter."""

    kind: Lit["identifier"] = "identifier"
    name: str = Field(..., min_length=1, max_length=64)


class StatePath(BaseModel):
    """A reach into the simulation: `.furina.energy`, `.x.burst.ready`.

    **Deliberately not an `Identifier`.** Only gcsim can answer one of these, and a condition
    editor that treats both as "a string" ends up offering the loop index `i` as a character.
    """

    kind: Lit["state"] = "state"
    segments: list[str] = Field(..., min_length=1)


class Unary(BaseModel):
    """`!x`, `-n`. One operator over one operand."""

    kind: Lit["unary"] = "unary"
    op: str
    operand: Expression

    @field_validator("op")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in UNARY_OPS:
            msg = f"unary op {value!r} is not one gcsim's config language has"
            raise ValueError(msg)
        return value


class Binary(BaseModel):
    """`a && b`, `.x.energy >= 30`. Two operands and an operator with a precedence."""

    kind: Lit["binary"] = "binary"
    op: str
    left: Expression
    right: Expression

    @field_validator("op")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in PRECEDENCE:
            msg = (
                f"op {value!r} is not one gcsim's config language has. The operators are "
                f"{sorted(PRECEDENCE)}."
            )
            raise ValueError(msg)
        return value


Expression = Annotated[
    Literal | Identifier | StatePath | Unary | Binary,
    Field(discriminator="kind"),
]


def _precedence(expr: Expression) -> int:
    """How tightly `expr` binds. A leaf binds tightest; `||` loosest."""
    if isinstance(expr, Binary):
        return PRECEDENCE[expr.op]
    if isinstance(expr, Unary):
        return 6
    return 99


def _render_leaf(expr: Expression) -> str | None:
    """The gcsim source for an expression with no operator, or `None` for the rest."""
    if isinstance(expr, Literal):
        if isinstance(expr.value, bool):
            return "true" if expr.value else "false"
        if isinstance(expr.value, str):
            return f'"{expr.value}"'
        return str(expr.value)
    if isinstance(expr, Identifier):
        return expr.name
    if isinstance(expr, StatePath):
        return "." + ".".join(expr.segments)
    return None


def render_expression(expr: Expression) -> str:
    """Gcsim source for `expr`, parenthesised **only where precedence requires it**.

    Emitting more parentheses than the author wrote would be harmless for gcsim and wrong for
    this repo: a round-trip that does not reproduce the source cannot tell a formatting change
    from a meaning change, and the round trip is this design's main gate.
    """
    leaf = _render_leaf(expr)
    if leaf is not None:
        return leaf
    if isinstance(expr, Unary):
        inner = render_expression(expr.operand)
        if _precedence(expr.operand) < _precedence(expr):
            inner = f"({inner})"
        return f"{expr.op}{inner}"

    mine = PRECEDENCE[expr.op]
    left = render_expression(expr.left)
    right = render_expression(expr.right)
    if _precedence(expr.left) < mine:
        left = f"({left})"
    # **Strictly less on the left, less-or-equal on the right.** These operators are all
    # left-associative, so `a - (b - c)` needs its parentheses and `(a - b) - c` does not.
    if _precedence(expr.right) <= mine:
        right = f"({right})"
    return f"{left} {expr.op} {right}"


Unary.model_rebuild()
Binary.model_rebuild()


# ── nodes ────────────────────────────────────────────────────────────────────

#: How deep a rotation may nest. A real one nests two or three; the bound exists so a
#: malformed tree reports **by name** instead of arriving as a `RecursionError`.
MAX_DEPTH = 32

#: How many nodes one rotation may hold, counted through the whole tree.
#:
#: Larger than `MAX_STEPS` because a tree keeps a loop rather than unrolling it, so the same
#: rotation is fewer nodes — and because an imported config carries its author's structure
#: rather than ours. The corpus's largest is well under this.
MAX_NODES = 2000


class ActionNode(BaseModel):
    """One action by one character — what a `RotationStep` was."""

    kind: Lit["action"] = "action"
    character: str = Field(..., min_length=1, max_length=32)
    action: str = Field(..., min_length=1, max_length=64)
    repeat: int = Field(default=1, ge=1, le=99)
    note: str = Field(default="", max_length=200)
    #: gcsim parameters this builder offers no control for, carried verbatim.
    #:
    #: **Carried rather than refused or dropped.** `gcsim_keys.NOT_OFFERED_PARAMS` lists 50 of
    #: them — hit geometry, delays, kit minutiae — and none names a different move. Refusing
    #: one costs the whole rotation; dropping one changes it in silence. Carrying re-emits
    #: exactly what the author wrote while the builder shows the step without a control for it.
    params: dict[str, str] = Field(default_factory=dict)


class LoopNode(BaseModel):
    """A `for` with a bound, or a `while` with a guard."""

    kind: Lit["loop"] = "loop"
    loop: Lit["counted", "guarded"]
    #: The block's own name, when it has one.
    #:
    #: Carried because `Rotation.steps` stores `group` as a **path of names** the author or
    #: importer chose (`"flame/energy"`), and a tree that kept only the structure could not be
    #: converted back to the steps it came from — which is the Phase 4 gate. It reads better in
    #: the builder's outline than "block 2" besides. Never interpreted.
    label: str = Field(default="", max_length=64)

    #: The index variable, for a counted loop only.
    variable: str | None = None
    #: The bound, as an **expression** — nine corpus configs use a variable rather than a
    #: literal (`for let j = 0; j < amt; ...`), and an `int` field would refuse them for no
    #: reason beyond its own type.
    bound: Expression | None = None
    condition: Expression | None = None
    body: list[Node] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape_matches_the_kind(self) -> LoopNode:
        """A counted loop needs a bound and a guarded one needs a condition.

        A `model_validator` rather than two `field_validator`s: in Pydantic v2 a field
        validator does not run for an **absent** field, so validating `bound` never fired for
        exactly the case that matters — a counted loop that forgot to say what it counts to.
        """
        if self.loop == "counted" and self.bound is None:
            msg = "a counted loop needs a bound; without one there is nothing to count to"
            raise ValueError(msg)
        if self.loop == "guarded" and self.condition is None:
            msg = "a guarded loop needs a condition; without one it never terminates"
            raise ValueError(msg)
        return self


class BranchNode(BaseModel):
    """An `if` / `else if` / `else` chain, as **one** node.

    gcsim evaluates the chain once and takes one arm. Modelling it as separate `if`s would
    re-test each condition after the previous arm ran, and an action inside an arm can change
    what the next one tests — `internal/characters/flins/skill.go:56` deletes the very status
    its block is guarded on. `DESIGN_conditional_steps.md` records that hazard; this closes
    **OQ-C3** by giving the `else` somewhere to live.
    """

    kind: Lit["branch"] = "branch"
    #: The block's own name, when it has one.
    #:
    #: Carried because `Rotation.steps` stores `group` as a **path of names** the author or
    #: importer chose (`"flame/energy"`), and a tree that kept only the structure could not be
    #: converted back to the steps it came from — which is the Phase 4 gate. It reads better in
    #: the builder's outline than "block 2" besides. Never interpreted.
    label: str = Field(default="", max_length=64)
    arms: list[tuple[Expression, list[Node]]] = Field(..., min_length=1)
    otherwise: list[Node] | None = None


class WaitNode(BaseModel):
    """gcsim's `wait(n)` or `delay(n)` — 32 corpus configs use one."""

    kind: Lit["wait"] = "wait"
    frames: int = Field(..., ge=0)
    mode: Lit["wait", "delay"] = "wait"


class SwapNode(BaseModel):
    """An explicit `x swap;`. gcsim also inserts one implicitly; this is the written kind."""

    kind: Lit["swap"] = "swap"
    character: str = Field(..., min_length=1, max_length=32)


class LetNode(BaseModel):
    """`let x = expr;`."""

    kind: Lit["let"] = "let"
    name: str = Field(..., min_length=1, max_length=64)
    value: Expression


class AssignNode(BaseModel):
    """`x = expr;` outside a loop header."""

    kind: Lit["assign"] = "assign"
    name: str = Field(..., min_length=1, max_length=64)
    value: Expression


class CallNode(BaseModel):
    """`f(a, b);` — a call to a user-defined function."""

    kind: Lit["call"] = "call"
    function: str = Field(..., min_length=1, max_length=64)
    arguments: list[Expression] = Field(default_factory=list)


class FnNode(BaseModel):
    """`fn name(params) { body }`.

    Structural here, and **authored as text** — owner, 2026-09-03: *"user defined functions
    almost need to be written… they'll have to author them themselves."* Measured: of the 41
    corpus configs defining one, 41 have control flow in the body and 30 take a parameter, so
    there is no simple-function case a form could have covered.
    """

    kind: Lit["fn"] = "fn"
    name: str = Field(..., min_length=1, max_length=64)
    parameters: list[str] = Field(default_factory=list)
    body: list[Node] = Field(default_factory=list)


class RawNode(BaseModel):
    """Source this parser did not model, carried exactly.

    **The piece the whole design rests on.** Import reaches 100 % at the parser's first phase
    because anything unmodelled becomes one of these, emits byte-identically, and blocks
    nothing.

    Two rules keep it from being silent degradation:

    - **`reason` is required.** A user must be able to see *which* construct is carried rather
      than understood, because that is the difference between editing it in the builder and
      editing it as text.
    - **It is opaque, never partial.** A production that cannot complete raws its *whole*
      construct. Reading half a `for` and raw-ing the body would produce a tree that looks
      structured and emits something the author did not write.
    """

    kind: Lit["raw"] = "raw"
    source: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


Node = Annotated[
    ActionNode | LoopNode | BranchNode | WaitNode | SwapNode
    | LetNode | AssignNode | CallNode | FnNode | RawNode,
    Field(discriminator="kind"),
]


def _walk(nodes: list[Node], depth: int = 1) -> tuple[int, int]:
    """`(node count, deepest nesting)` for a list of nodes."""
    count, deepest = 0, depth
    for node in nodes:
        count += 1
        for child in _children(node):
            sub_count, sub_depth = _walk(child, depth + 1)
            count += sub_count
            deepest = max(deepest, sub_depth)
    return count, deepest


def _children(node: Node) -> list[list[Node]]:
    """Every body hanging off `node`, as a list of node-lists.

    **`otherwise` is appended only when it exists.** `[node.otherwise] or []` looks like it
    guards against `None` and does not: a one-element list is truthy, so a branch with no
    `else` yielded `[None]` and the walk below iterated it. Caught by the linter, not by a
    test, because every branch in the tests had an `else`.
    """
    if isinstance(node, BranchNode):
        bodies = [body for _, body in node.arms]
        if node.otherwise is not None:
            bodies.append(node.otherwise)
        return bodies
    if isinstance(node, LoopNode | FnNode):
        return [node.body]
    return []


class RotationTree(BaseModel):
    """A rotation, as an ordered tree."""

    nodes: list[Node] = Field(default_factory=list)

    @field_validator("nodes")
    @classmethod
    def _within_limits(cls, value: list[Node]) -> list[Node]:
        count, depth = _walk(value)
        if depth > MAX_DEPTH:
            msg = (
                f"this rotation nests {depth} deep and the limit is {MAX_DEPTH}. A real "
                f"rotation nests two or three; past this the tree is almost certainly "
                f"malformed rather than ambitious."
            )
            raise ValueError(msg)
        if count > MAX_NODES:
            msg = f"this rotation holds {count} nodes and the limit is {MAX_NODES}."
            raise ValueError(msg)
        return value


for _model in (LoopNode, BranchNode, FnNode, RotationTree):
    _model.model_rebuild()
