"""How deep rotation source may nest before the parser is asked to read it.

Security audit F4. `gcsim_parser` is recursive descent, and the tree and its serializer are
recursive too, so input shaped to nest deeply — 500 open parentheses, a 5,000-term `1+1+…`,
a tower of `if 1 {` — fails in three different ways depending on where the depth runs out:
`RecursionError` in the parser, a tree-depth `ValidationError`, or a response the serializer
cannot write. Each was a 500, and each cost CPU before failing. `/rotations/validate` runs on
every keystroke and `/rotations/import` reads 100 KB, so both check this first.

The check is a **flat scan over tokens** — no recursion, linear in the source — and asks two
questions a real rotation never comes near:

- **bracket nesting** across `(`, `[` and `{` together, and
- **operators in one statement**, since a binary or unary chain nests the expression tree as
  deeply as brackets do without using any.

Measured against every committed real config (`tests/unit/test_source_limits.py`). The bounds
sit far below where the parser or serializer fails (around 300 for an operator chain, 500 for
parentheses) and far above a real rotation, which nests two or three blocks deep and writes
conditions of a handful of terms.
"""

from __future__ import annotations

from app.services.gcsim_tokenizer import GcsimSyntaxError, TokenKind, tokenize

#: `(`, `[` and `{` combined. `RotationTree` already refuses more than 32 nested blocks.
MAX_NESTING = 32
#: Operators between two statement boundaries (`;`, `{`, `}`).
MAX_OPERATORS_PER_STATEMENT = 64

_OPEN = frozenset("([{")
_CLOSE = frozenset(")]}")
_BOUNDARY = frozenset(";{}")


def nesting_refusal(source: str) -> str | None:
    """A sentence saying why *source* is too deep to parse, or `None` when it is fine.

    Source that does not tokenize at all is left to the validator, which reports it as a
    positioned diagnostic — half-typed text is the editor's normal state, not an attack.
    """
    try:
        tokens = tokenize(source)
    except GcsimSyntaxError:
        return None

    depth = deepest = operators = most = 0
    for token in tokens:
        if token.kind is TokenKind.OPERATOR:
            operators += 1
            most = max(most, operators)
        elif token.kind is TokenKind.PUNCT:
            if token.text in _OPEN:
                depth += 1
                deepest = max(deepest, depth)
            elif token.text in _CLOSE:
                depth = max(depth - 1, 0)
            if token.text in _BOUNDARY:
                operators = 0
        if deepest > MAX_NESTING:
            return (
                f"this source nests brackets more than {MAX_NESTING} deep. A real rotation "
                f"nests two or three; past {MAX_NESTING} it is not read."
            )
        if most > MAX_OPERATORS_PER_STATEMENT:
            return (
                f"one statement in this source has more than {MAX_OPERATORS_PER_STATEMENT} "
                f"operators. A real condition has a handful; past "
                f"{MAX_OPERATORS_PER_STATEMENT} it is not read."
            )
    return None
