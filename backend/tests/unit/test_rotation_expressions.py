"""The expression model — task 1.6.

Conditions and loop bounds stop being short strings matched by regex and become a tree.
**Parsed and re-emitted, never evaluated by us**, with one exception the converter already
owns: arithmetic over a counted loop's index.
"""
from __future__ import annotations

import pytest

from app.schemas.rotation_nodes import (
    Binary,
    Identifier,
    Literal,
    StatePath,
    Unary,
    render_expression,
)


def test_a_literal_carries_its_own_kind() -> None:
    assert render_expression(Literal(value=30)) == "30"
    assert render_expression(Literal(value=True)) == "true"
    assert render_expression(Literal(value="hi")) == '"hi"'


def test_a_state_path_is_not_an_identifier() -> None:
    """`.furina.energy` and `i` are different things and must not share a shape.

    A state path reaches into the simulation and only gcsim can answer it; an identifier is
    the config's own variable. Flattening both to "a string" is how a condition editor ends
    up offering `i` as a character.
    """
    path = StatePath(segments=["furina", "energy"])

    assert render_expression(path) == ".furina.energy"
    assert render_expression(Identifier(name="i")) == "i"


def test_a_comparison_round_trips() -> None:
    expr = Binary(
        op=">=", left=StatePath(segments=["furina", "energy"]), right=Literal(value=30),
    )

    assert render_expression(expr) == ".furina.energy >= 30"


def test_a_compound_condition_parenthesises_only_where_it_must() -> None:
    """`a && b || c` and `a && (b || c)` are different rotations.

    Precedence is not a formatting preference here: emitting the second as the first would
    hand gcsim a guard the author did not write.
    """
    a = StatePath(segments=["x", "status", "s"])
    b = Identifier(name="b")
    c = Identifier(name="c")

    flat = Binary(op="||", left=Binary(op="&&", left=a, right=b), right=c)
    nested = Binary(op="&&", left=a, right=Binary(op="||", left=b, right=c))

    assert render_expression(flat) == ".x.status.s && b || c"
    assert render_expression(nested) == ".x.status.s && (b || c)"


def test_negation_binds_tighter_than_comparison() -> None:
    expr = Unary(op="!", operand=StatePath(segments=["x", "burst", "ready"]))

    assert render_expression(expr) == "!.x.burst.ready"


def test_negating_a_compound_keeps_its_parentheses() -> None:
    expr = Unary(op="!", operand=Binary(op="&&", left=Identifier(name="a"),
                                        right=Identifier(name="b")))

    assert render_expression(expr) == "!(a && b)"


def test_an_unknown_operator_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="op"):
        Binary(op="**", left=Identifier(name="a"), right=Identifier(name="b"))


def test_an_empty_state_path_is_refused() -> None:
    """`.` names nothing, and emitting it would produce a config gcsim rejects."""
    with pytest.raises(ValueError, match="segments"):
        StatePath(segments=[])


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        (Binary(op="-", left=Identifier(name="a"),
                right=Binary(op="-", left=Identifier(name="b"),
                             right=Identifier(name="c"))), "a - (b - c)"),
        (Binary(op="-", left=Binary(op="-", left=Identifier(name="a"),
                                    right=Identifier(name="b")),
                right=Identifier(name="c")), "a - b - c"),
        (Binary(op="*", left=Binary(op="+", left=Identifier(name="a"),
                                    right=Identifier(name="b")),
                right=Identifier(name="c")), "(a + b) * c"),
        (Binary(op="+", left=Identifier(name="a"),
                right=Binary(op="*", left=Identifier(name="b"),
                             right=Identifier(name="c"))), "a + b * c"),
        (Binary(op="&&", left=Binary(op="||", left=Identifier(name="a"),
                                     right=Identifier(name="b")),
                right=Identifier(name="c")), "(a || b) && c"),
    ],
)
def test_associativity_decides_which_side_needs_brackets(expr, expected: str) -> None:
    """These operators are left-associative, so `a - (b - c)` needs its brackets and
    `(a - b) - c` does not. Getting this backwards emits arithmetic nobody wrote, and it is
    the kind of error a round-trip test over real configs would only find by luck."""
    assert render_expression(expr) == expected
