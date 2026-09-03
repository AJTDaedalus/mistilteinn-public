"""The node kinds — tasks 1.1 to 1.5, 1.7 and 1.8.

`DESIGN_rotation_language.md`. A rotation becomes an ordered tree; the piece that carries the
design is `RawNode`, which is why most of the sharp tests here are about it.
"""
from __future__ import annotations

import pytest

from app.schemas.rotation_nodes import (
    MAX_DEPTH,
    MAX_NODES,
    ActionNode,
    AssignNode,
    BranchNode,
    CallNode,
    FnNode,
    Identifier,
    LetNode,
    Literal,
    LoopNode,
    RawNode,
    RotationTree,
    StatePath,
    SwapNode,
    WaitNode,
)


def action(**over) -> ActionNode:
    base = {"character": "10000042", "action": "burst"}
    return ActionNode(**{**base, **over})


# ── the action node still holds what a step held ─────────────────────────────


def test_an_action_carries_an_opaque_param_bag() -> None:
    """**Carried, not refused, and not dropped.**

    `NOT_OFFERED_PARAMS` lists 50 parameters gcsim declares that this builder deliberately
    offers no control for — hit geometry, delays, kit minutiae. Refusing them costs the whole
    rotation; dropping them changes it silently. Carrying re-emits exactly what was written
    while the builder shows the step read-only.
    """
    node = action(params={"final": "1", "c2_travel": "20"})

    assert node.params == {"final": "1", "c2_travel": "20"}


def test_an_action_defaults_to_no_params_and_one_repeat() -> None:
    node = action()

    assert node.params == {}
    assert node.repeat == 1


# ── the shapes a list could not hold ─────────────────────────────────────────


def test_a_counted_loop_keeps_a_non_integer_bound_as_an_expression() -> None:
    """`for let j = 0; j < amt; j = j + 1` — the bound is a variable.

    Nine corpus configs do this. Storing bounds as `int` would refuse them for no reason
    beyond the field's type.
    """
    node = LoopNode(
        kind="loop", loop="counted", variable="j",
        bound=Identifier(name="amt"), body=[action()],
    )

    assert node.bound.name == "amt"


def test_a_guarded_loop_carries_a_condition_and_no_variable() -> None:
    node = LoopNode(
        kind="loop", loop="guarded",
        condition=StatePath(segments=["clorinde", "status", "night-watch"]),
        body=[action()],
    )

    assert node.variable is None


def test_a_counted_loop_without_a_bound_is_refused() -> None:
    with pytest.raises(ValueError, match="bound"):
        LoopNode(kind="loop", loop="counted", variable="i", body=[action()])


def test_a_guarded_loop_without_a_condition_is_refused() -> None:
    with pytest.raises(ValueError, match="condition"):
        LoopNode(kind="loop", loop="guarded", body=[action()])


def test_an_if_else_if_else_chain_is_one_node() -> None:
    """**One node, not three.** gcsim evaluates the chain once and takes one arm.

    Modelling it as separate `if`s would re-test each condition after the previous arm ran —
    the exact hazard `DESIGN_conditional_steps.md` records, where Flins's skill deletes the
    status its own block is guarded on. Closes OQ-C3.
    """
    node = BranchNode(
        kind="branch",
        arms=[
            (StatePath(segments=["x", "burst", "ready"]), [action()]),
            (StatePath(segments=["x", "skill", "ready"]), [action(action="skill")]),
        ],
        otherwise=[action(action="attack")],
    )

    assert len(node.arms) == 2
    assert node.otherwise is not None


def test_a_branch_needs_at_least_one_arm() -> None:
    with pytest.raises(ValueError, match="arm"):
        BranchNode(kind="branch", arms=[], otherwise=[action()])


@pytest.mark.parametrize(
    "node",
    [
        WaitNode(kind="wait", frames=173),
        WaitNode(kind="wait", frames=30, mode="delay"),
        SwapNode(kind="swap", character="10000042"),
        LetNode(kind="let", name="x", value=Literal(value=1)),
        AssignNode(kind="assign", name="i", value=Literal(value=2)),
        CallNode(kind="call", function="mav_dc_cancel", arguments=[Literal(value=6)]),
    ],
)
def test_the_smaller_node_kinds_validate(node) -> None:
    assert node.kind


def test_a_function_carries_its_parameters_and_body() -> None:
    node = FnNode(
        kind="fn", name="mav_dc_cancel", parameters=["d_travel_f"], body=[action()],
    )

    assert node.parameters == ["d_travel_f"]


# ── raw: the escape hatch, and the rule that keeps it honest ─────────────────


def test_a_raw_node_must_say_what_it_could_not_read() -> None:
    """A `raw` with no reason is the silent degradation this whole design refuses.

    The user has to be able to see *which* construct is being carried rather than understood,
    because that is the difference between "edit this in the builder" and "edit this as text".
    """
    with pytest.raises(ValueError, match="reason"):
        RawNode(kind="raw", source="whatever();", reason="")


def test_a_raw_node_keeps_its_source_byte_for_byte() -> None:
    source = "fn f(a) {\r\n  x attack;\r\n}\r\n"

    assert RawNode(kind="raw", source=source, reason="a user function").source == source


# ── the tree ─────────────────────────────────────────────────────────────────


def test_a_tree_of_mixed_nodes_round_trips_through_the_union() -> None:
    tree = RotationTree(nodes=[
        action(),
        LoopNode(kind="loop", loop="counted", variable="i",
                 bound=Literal(value=6), body=[action(action="skill")]),
        RawNode(kind="raw", source="pick_up_crystallize();", reason="a builtin call"),
    ])

    again = RotationTree.model_validate(tree.model_dump())

    assert again == tree


def test_a_tree_deeper_than_the_limit_is_refused_by_name() -> None:
    """By name, rather than by `RecursionError`. A limit that reports as a crash is a limit
    nobody can act on."""
    node = action()
    for _ in range(MAX_DEPTH + 2):
        node = LoopNode(kind="loop", loop="counted", variable="i",
                        bound=Literal(value=2), body=[node])

    with pytest.raises(ValueError, match="deep"):
        RotationTree(nodes=[node])


def test_a_tree_with_too_many_nodes_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="nodes"):
        RotationTree(nodes=[action() for _ in range(MAX_NODES + 1)])


def test_a_branch_with_no_else_is_walked_without_tripping_over_it() -> None:
    """The linter found this, not a test — every branch in the tests above has an `else`.

    `_children` used `[node.otherwise] or []`, which looks like a `None` guard and is not: a
    one-element list is truthy, so a branch with no `else` yielded `[None]` and the limit walk
    iterated `None`. Building one is the reproduction.
    """
    tree = RotationTree(nodes=[
        BranchNode(
            kind="branch",
            arms=[(StatePath(segments=["x", "burst", "ready"]), [action()])],
            otherwise=None,
        ),
    ])

    assert len(tree.nodes) == 1


def test_the_tree_publishes_a_discriminated_schema() -> None:
    """Task 1.7. A generated client must get a union it can narrow on `kind`, not `object`."""
    schema = RotationTree.model_json_schema()

    assert "discriminator" in str(schema)
    assert "RawNode" in str(schema["$defs"])
