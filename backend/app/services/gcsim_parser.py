"""gcsim source into a rotation tree.

`DESIGN_rotation_language.md`. Recursive descent over `gcsim_tokenizer`'s tokens, producing
`RotationTree`.

**The containment rule is the whole design, and it is easy to get wrong in the direction that
looks better.** A production that cannot complete emits a `RawNode` for its *whole* construct,
never for the part it failed on. Reading a `for` header, failing on its body and raw-ing only
the body would leave a tree that looks structured — an editable loop around an opaque middle —
and emitting it could reorder or re-gate what the author wrote. A construct is understood
whole or carried whole; there is no third option.

That rule is what lets import be **100 %** from this phase onward: anything unfamiliar is
carried exactly rather than refused, and no later phase can regress what a user can bring in.
"""

from __future__ import annotations

import re

from app.schemas.rotation_nodes import (
    PRECEDENCE,
    UNARY_OPS,
    ActionNode,
    AssignNode,
    Binary,
    BranchNode,
    CallNode,
    Expression,
    FnNode,
    Identifier,
    LetNode,
    Literal,
    LoopNode,
    Node,
    RawNode,
    RotationTree,
    StatePath,
    SwapNode,
    Unary,
    WaitNode,
)
from app.services.gcsim_tokenizer import GcsimSyntaxError, Token, TokenKind, tokenize

#: Statements that configure the simulation rather than act in it.
#:
#: `active` is here rather than in the tree because the compiler emits it from the team, so a
#: tree carrying one too would emit it twice. The rest name a character's gear or the
#: environment, and the optimizer regenerates all of them — that is what makes an imported
#: rotation scoreable against *this* user's build rather than its author's.
_BUILD_LINE = re.compile(
    r"^\s*(?:[a-z0-9_]+\s+(?:char|add)\s|target\s|options\s|energy\s|hurt\s|active\s)",
    re.IGNORECASE,
)


def split_config(source: str) -> tuple[str, str]:
    """`(build lines, rotation lines)`, preserving order within each side.

    Measured over all 223 configs this importer refused on 2026-09-03: **0 lines lost**, with
    16 of them interleaving the two kinds. The partition is what lets `build_config`
    regenerate a user's own gear around somebody else's rotation.
    """
    build, rotation = [], []
    for line in source.splitlines():
        stripped = line.split("#")[0].split("//")[0].strip()
        if not stripped:
            (rotation if rotation else build).append(line)
        elif _BUILD_LINE.match(stripped):
            build.append(line)
        else:
            rotation.append(line)
    return "\n".join(build), "\n".join(rotation)


class _Parser:
    """Token cursor plus the productions. One instance per parse."""

    def __init__(self, source: str, tokens: list[Token]) -> None:
        self.source = source
        self.tokens = tokens
        self.i = 0
        #: Where each node came from, keyed by `id(node)`.
        #:
        #: **A side table rather than fields on the node**, because a node carrying its own
        #: line and column would break `parse(emit(t)) == t` — the emitted text has different
        #: positions, so two trees meaning the same rotation would compare unequal and the
        #: round-trip gate would fail for a reason that has nothing to do with meaning.
        #: Pydantic v2 compares private attributes too, so that escape does not exist.
        self.spans: dict[int, tuple[int, int, int]] = {}

    def _record(self, node: object, start_index: int) -> None:
        """Remember where `node` began and how far it ran."""
        if start_index >= len(self.tokens):
            return
        first = self.tokens[start_index]
        last = self.tokens[min(self.i, len(self.tokens)) - 1]
        self.spans[id(node)] = (first.line, first.column, max(last.end - first.start, 1))

    # ── cursor ───────────────────────────────────────────────────────────────

    def done(self) -> bool:
        return self.i >= len(self.tokens)

    def peek(self, offset: int = 0) -> Token | None:
        j = self.i + offset
        return self.tokens[j] if j < len(self.tokens) else None

    def text(self, offset: int = 0) -> str:
        token = self.peek(offset)
        return token.text if token else ""

    def take(self) -> Token:
        token = self.tokens[self.i]
        self.i += 1
        return token

    def accept(self, text: str) -> bool:
        if self.text() == text:
            self.i += 1
            return True
        return False

    # ── raw ──────────────────────────────────────────────────────────────────

    def raw_from(self, start_index: int, reason: str) -> RawNode:
        """Everything from `start_index` to the cursor, as the author wrote it.

        Sliced from the **source** rather than rebuilt from tokens, so comments, spacing and
        line endings survive. A re-rendered `raw` would be a different file that happens to
        mean the same thing, and the round-trip gate could then no longer tell a formatting
        change from a meaning change.
        """
        start = self.tokens[start_index].start
        end = self.tokens[self.i - 1].end if self.i > start_index else start
        node = RawNode(kind="raw", source=self.source[start:end], reason=reason)
        # Recorded like any other node: a carried construct is exactly the thing a reader
        # most wants pointed at, and reporting it at line 1 would send them to the top of
        # the file instead.
        self._record(node, start_index)
        return node

    def skip_construct(self, start_index: int, *, braced: bool = False) -> None:
        """Advance past the construct beginning at `start_index`.

        Without this a raw node would swallow the rest of the file, and the statement after an
        unreadable one would vanish — silent loss wearing the shape of a refusal.

        **`braced` is not a convenience.** A `for` header holds two `;` at depth zero, so
        stopping at the first one cut `for let i=0;` off as its own construct and left the
        body and step clause as two more raw nodes. That is the containment rule broken in the
        direction that looks tidiest: three plausible nodes instead of one honest one. A
        braced construct ends at its matching `}`; everything else ends at its `;`.
        """
        self.i = start_index
        depth = 0
        seen_brace = False
        while not self.done():
            text = self.text()
            self.take()
            if text == "{":
                depth += 1
                seen_brace = True
            elif text == "}":
                depth -= 1
                if seen_brace and depth <= 0:
                    return
            elif text == ";" and depth == 0 and not braced:
                return

    # ── expressions ──────────────────────────────────────────────────────────

    def expression(self, min_precedence: int = 1) -> Expression | None:
        left = self.unary()
        if left is None:
            return None
        while not self.done():
            op = self.text()
            precedence = PRECEDENCE.get(op)
            if precedence is None or precedence < min_precedence:
                break
            self.take()
            right = self.expression(precedence + 1)
            if right is None:
                return None
            left = Binary(kind="binary", op=op, left=left, right=right)
        return left

    def unary(self) -> Expression | None:
        if self.text() in UNARY_OPS and self.peek() and \
                self.peek().kind is TokenKind.OPERATOR:
            op = self.take().text
            operand = self.unary()
            return None if operand is None else Unary(kind="unary", op=op, operand=operand)
        if self.accept("("):
            inner = self.expression()
            return inner if self.accept(")") else None
        return self.atom()

    def atom(self) -> Expression | None:
        """A path, a number, a string, a boolean or an identifier."""
        token = self.peek()
        if token is None:
            return None
        # A call inside an expression — `f() - StartFrame` — is not a shape this model holds,
        # so the caller raws the whole construct rather than reading half of it.
        if token.kind is TokenKind.IDENT and self.text(1) == "(":
            return None
        reader = _ATOMS.get(token.kind)
        if reader is None:
            return None
        self.take()
        return reader(token)

    # ── statements ───────────────────────────────────────────────────────────

    def block(self) -> list[Node] | None:
        """A `{ … }` body, or `None` if any statement inside could not be read.

        `None` propagates the containment rule outward: the *enclosing* construct raws itself,
        so a half-read body never becomes a tree.
        """
        if not self.accept("{"):
            return None
        nodes: list[Node] = []
        while not self.done() and self.text() != "}":
            before = self.i
            node = self.statement()
            if node is None or isinstance(node, RawNode):
                return None
            if self.i == before:  # no progress — refuse rather than spin
                return None
            _extend(nodes, node)
        return nodes if self.accept("}") else None

    def statement(self) -> Node | None:
        """One statement, or a `RawNode` carrying it whole."""
        start = self.i
        token = self.peek()
        if token is None:
            return None

        for keyword, production in (
            ("for", self.counted_loop), ("while", self.guarded_loop),
            ("if", self.branch), ("fn", self.function), ("let", self.binding),
        ):
            if token.text == keyword:
                node = production()
                if node is not None:
                    self._record(node, start)
                    return node
                self.skip_construct(start, braced=True)
                return self.raw_from(start, _REASONS[keyword])

        node = self.simple_statement()
        if node is not None:
            for produced in (node if isinstance(node, _Sequence) else [node]):
                self._record(produced, start)
            return node
        self.skip_construct(start)
        return self.raw_from(start, "a statement this model does not have a shape for")

    def counted_loop(self) -> LoopNode | None:  # noqa: PLR0911 — a production is guard clauses
        self.take()
        if not self.accept("let"):
            return None
        variable = self.take().text
        if not (self.accept("=") and self.peek()):
            return None
        self.take()                                   # the start value
        if not self.accept(";"):
            return None
        if self.text() != variable:
            return None
        self.take()
        if self.text() not in {"<", "<=" }:
            return None
        self.take()
        bound = self.expression()
        if bound is None or not self.accept(";"):
            return None
        while not self.done() and self.text() != "{":  # the step clause, `i = i + 1`
            self.take()
        body = self.block()
        if body is None:
            return None
        return LoopNode(kind="loop", loop="counted", variable=variable,
                        bound=bound, body=body)

    def guarded_loop(self) -> LoopNode | None:
        self.take()
        condition = self.expression()
        if condition is None:
            return None
        body = self.block()
        if body is None:
            return None
        return LoopNode(kind="loop", loop="guarded", condition=condition, body=body)

    def branch(self) -> BranchNode | None:
        """`if` / `else if` / `else`, as **one** node.

        Separate `if`s would re-test each condition after the previous arm ran, and an action
        inside an arm can change what the next one tests — `flins/skill.go:56` deletes the
        very status its block is guarded on. Closes OQ-C3.
        """
        arms: list[tuple[Expression, list[Node]]] = []
        otherwise: list[Node] | None = None
        while True:
            self.take()                                # `if`
            condition = self.expression()
            if condition is None:
                return None
            body = self.block()
            if body is None:
                return None
            arms.append((condition, body))
            if self.text() != "else":
                break
            self.take()
            if self.text() == "if":
                continue
            otherwise = self.block()
            if otherwise is None:
                return None
            break
        return BranchNode(kind="branch", arms=arms, otherwise=otherwise)

    def function(self) -> FnNode | None:
        self.take()
        name = self.take().text
        if not self.accept("("):
            return None
        parameters: list[str] = []
        while not self.done() and self.text() != ")":
            if self.peek().kind is not TokenKind.IDENT:
                self.take()
                continue
            parameters.append(self.take().text)
            # **A parameter may carry a type**: `fn f(char_id number, p map)` is real gcsim
            # syntax and appears in 17 corpus configs. Reading the type as a second parameter
            # name got both the arity and the body's scope wrong, and the visible symptom was
            # 17 false "not in scope" reports pointing at the *caller*.
            if self.peek() and self.peek().kind is TokenKind.IDENT:
                self.take()
        if not self.accept(")"):
            return None
        body = self.block()
        if body is None:
            return None
        return FnNode(kind="fn", name=name, parameters=parameters, body=body)

    def binding(self) -> LetNode | None:
        self.take()
        name = self.take().text
        if not self.accept("="):
            return None
        value = self.expression()
        if value is None or not self.accept(";"):
            return None
        return LetNode(kind="let", name=name, value=value)

    def simple_statement(self) -> Node | None:
        """A statement with no body: an action sequence, a wait, a call, an assignment."""
        token = self.peek()
        if token is None or token.kind is not TokenKind.IDENT:
            return None

        if token.text in {"wait", "delay"} and self.text(1) == "(":
            return self.pause(token.text)
        if self.text(1) == "(":                        # `f(args);`
            return self.call()
        if self.text(1) == "=":                        # `i = i + 1;`
            return self.assignment()
        if self.peek(1) and self.peek(1).kind is TokenKind.IDENT:
            return self.action_sequence()
        return None

    def pause(self, mode: str) -> WaitNode | None:
        """`wait(n);` or `delay(n);` — 32 corpus configs use one."""
        self.take()
        self.take()
        frames = self.peek()
        if frames is None or frames.kind is not TokenKind.NUMBER:
            return None
        self.take()
        if not (self.accept(")") and self.accept(";")):
            return None
        return WaitNode(kind="wait", frames=int(float(frames.text)), mode=mode)

    def assignment(self) -> AssignNode | None:
        name = self.take().text
        self.take()
        value = self.expression()
        if value is None or not self.accept(";"):
            return None
        return AssignNode(kind="assign", name=name, value=value)

    def call(self) -> CallNode | None:
        name = self.take().text
        self.take()
        arguments: list[Expression] = []
        while not self.done() and self.text() != ")":
            argument = self.expression()
            if argument is None:
                return None
            arguments.append(argument)
            if not self.accept(","):
                break
        if not (self.accept(")") and self.accept(";")):
            return None
        return CallNode(kind="call", function=name, arguments=arguments)

    def action_params(self) -> dict[str, str] | None:
        """`[hold=1]`, or `{}` when there is no bracket. `None` if the bracket is malformed.

        An unrecognised parameter is **carried**, not a reason to give up on the statement:
        `NOT_OFFERED_PARAMS` lists 50 of them and none names a different move.
        """
        params: dict[str, str] = {}
        if not self.accept("["):
            return params
        while not self.done() and self.text() != "]":
            key = self.take().text
            if not self.accept("="):
                return None
            params[key] = self.take().text
            self.accept(",")
        return params if self.accept("]") else None

    def action_repeat(self) -> int | None:
        """`:3`, or 1 when absent. `None` for `:0`, which is not an attack.

        Reading `attack:0` as an attack would import a step the config does not have, so the
        caller carries the statement as raw instead.
        """
        if not self.accept(":"):
            return 1
        count = self.peek()
        if count is None or count.kind is not TokenKind.NUMBER:
            return None
        self.take()
        repeat = int(float(count.text))
        return repeat if repeat >= 1 else None

    def action_sequence(self) -> Node | None:  # noqa: PLR0911 — a production is guard clauses
        """`razor skill[hold=1], dash, attack:3;` — one node per action.

        The comma sequence is the shape #246 fixed in the regex importer: a variant inside one
        used to abandon the whole line. Here it is the ordinary case, and an unrecognised
        parameter is *carried* rather than being a reason to give up on the statement.
        """
        character = self.take().text
        nodes: list[Node] = []
        while True:
            token = self.peek()
            if token is None or token.kind is not TokenKind.IDENT:
                return None
            name = self.take().text
            if name == "swap":
                if not self.accept(";"):
                    return None
                return SwapNode(kind="swap", character=character)
            params = self.action_params()
            if params is None:
                return None
            repeat = self.action_repeat()
            if repeat is None:
                return None
            nodes.append(ActionNode(kind="action", character=character, action=name,
                                    repeat=repeat, params=params))
            if self.accept(","):
                continue
            if self.accept(";"):
                break
            return None
        return nodes[0] if len(nodes) == 1 else _Sequence(nodes)


def _number(token: Token) -> Literal:
    text = token.text
    return Literal(kind="literal", value=float(text) if "." in text else int(text))


def _identifier(token: Token) -> Expression:
    if token.text in {"true", "false"}:
        return Literal(kind="literal", value=token.text == "true")
    return Identifier(kind="identifier", name=token.text)


#: How each token kind becomes an expression leaf. A table rather than a chain of `if`s: the
#: chain was the shape the linter objected to, and this reads better besides.
_ATOMS = {
    TokenKind.PATH: lambda t: StatePath(kind="state", segments=t.text.lstrip(".").split(".")),
    TokenKind.NUMBER: _number,
    TokenKind.STRING: lambda t: Literal(kind="literal", value=t.value),
    TokenKind.IDENT: _identifier,
}


class _Sequence(list):
    """Several nodes produced by one statement, flattened by the caller.

    A comma sequence is one statement and several nodes. Rather than give the tree a node kind
    that exists only to hold a comma, the parser returns this and `parse_rotation` flattens it.
    """


def _extend(nodes: list[Node], node: Node | _Sequence) -> None:
    """Append `node`, flattening a comma sequence.

    **One place, because two was a bug.** Flattening only at the top level left a `_Sequence`
    sitting inside a loop or branch body, where Pydantic rejected it for having no `kind` —
    374 of 505 corpus configs, none of them caught by a unit test, because every sequence in
    the tests was at the top level.
    """
    if isinstance(node, _Sequence):
        nodes.extend(node)
    else:
        nodes.append(node)


#: Why a construct was carried rather than understood, by keyword.
#:
#: Named rather than generic, because `reason` is what a user reads to decide whether to edit
#: this rotation in the builder or in the source view.
_REASONS = {
    "for": "a `for` loop whose header or body this model cannot express",
    "while": "a `while` loop whose guard or body this model cannot express",
    "if": "a branch whose condition or body this model cannot express",
    "fn": "a user-defined function",
    "let": "a `let` binding this model cannot express",
}


def parse_with_positions(source: str) -> tuple[RotationTree, dict[tuple, tuple[int, int, int]]]:
    """`(tree, positions)` — the tree, and where each node sits in `source`.

    Positions are keyed by a **path** into the tree: `(0,)` for the first top-level node,
    `(1, "body", 0)` for the first node inside the second one's body, `(2, "arms", 0, 1)` for
    the second node in a branch's first arm. A path rather than an object reference so a
    caller can hold the positions after the tree has been serialised and reloaded, which is
    what the editor does.
    """
    tree = parse_rotation(source)
    parser = _LAST_PARSER.get(id(tree))
    if parser is None:
        return tree, {}
    by_path: dict[tuple, tuple[int, int, int]] = {}
    _paths(tree.nodes, (), parser.spans, by_path)
    return tree, by_path


def _paths(nodes: list[Node], prefix: tuple, spans: dict[int, tuple[int, int, int]],
           out: dict[tuple, tuple[int, int, int]]) -> None:
    for index, node in enumerate(nodes):
        path = (*prefix, index)
        span = spans.get(id(node))
        if span is not None:
            out[path] = span
        if isinstance(node, LoopNode | FnNode):
            _paths(node.body, (*path, "body"), spans, out)
        elif isinstance(node, BranchNode):
            for arm, (_, body) in enumerate(node.arms):
                _paths(body, (*path, "arms", arm), spans, out)
            if node.otherwise is not None:
                _paths(node.otherwise, (*path, "otherwise"), spans, out)


#: The parser behind the most recent `parse_rotation`, so `parse_with_positions` can reach its
#: span table without changing `parse_rotation`'s signature — which every caller already uses.
_LAST_PARSER: dict[int, _Parser] = {}


def parse_rotation(source: str) -> RotationTree:
    """The tree for `source`'s rotation half. Never raises for unfamiliar input.

    A tokenizer error is the one thing that can still fail, and even that becomes a single
    `RawNode`: a config that cannot be tokenized is still a config the user typed, and losing
    it would be worse than carrying it.
    """
    try:
        tokens = tokenize(source)
    except GcsimSyntaxError as exc:
        return RotationTree(nodes=[
            RawNode(kind="raw", source=source, reason=f"could not be read at all: {exc}"),
        ])

    parser = _Parser(source, tokens)
    nodes: list[Node] = []
    while not parser.done():
        before = parser.i
        node = parser.statement()
        if node is None:
            parser.skip_construct(before)
            node = parser.raw_from(before, "a statement this model does not have a shape for")
        if parser.i == before:
            parser.i += 1
            continue
        _extend(nodes, node)
    tree = RotationTree(nodes=nodes)
    _LAST_PARSER.clear()
    _LAST_PARSER[id(tree)] = parser
    return tree
