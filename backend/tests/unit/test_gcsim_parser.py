"""gcsim source into a rotation tree — tasks 2.2 to 2.11.

The gate on this phase is that **import reaches 100 %**: anything the parser cannot model
becomes a `RawNode` carrying its exact source, so nothing is ever refused for being
unfamiliar.
"""
from __future__ import annotations

import pytest

from app.schemas.rotation_nodes import (
    ActionNode,
    BranchNode,
    CallNode,
    FnNode,
    LetNode,
    LoopNode,
    RawNode,
    SwapNode,
    WaitNode,
)
from app.services.gcsim_parser import parse_rotation, split_config


def only(source: str):
    tree = parse_rotation(source)
    assert len(tree.nodes) == 1, [n.kind for n in tree.nodes]
    return tree.nodes[0]


# ── the partition (task 2.2) ─────────────────────────────────────────────────


def test_build_lines_and_rotation_lines_are_separated_without_loss() -> None:
    """Measured over all 223 refused configs on 2026-09-03: **0 lines lost**."""
    source = (
        "options iteration=100;\n"
        "furina char lvl=90/90;\n"
        "furina add weapon=\"x\";\n"
        "target lvl=100 hp=999;\n"
        "active furina;\n"
        "furina skill;\n"
    )
    build, rotation = split_config(source)

    assert "options iteration=100;" in build
    assert "active furina;" in build
    assert "furina skill;" in rotation
    assert "char" not in rotation


# ── actions ──────────────────────────────────────────────────────────────────


def test_a_plain_action() -> None:
    node = only("furina skill;")

    assert isinstance(node, ActionNode)
    assert (node.character, node.action, node.repeat) == ("furina", "skill", 1)


def test_an_action_with_a_repeat() -> None:
    assert only("skirk attack:3;").repeat == 3


def test_a_variant_becomes_a_param_rather_than_a_different_action() -> None:
    node = only("razor skill[hold=1];")

    assert node.params == {"hold": "1"}
    assert node.action == "skill"


def test_an_unoffered_param_is_carried_not_refused() -> None:
    """`NOT_OFFERED_PARAMS` has 50 of these. Refusing one costs the whole rotation."""
    assert only("mavuika charge[final=1];").params == {"final": "1"}


def test_a_comma_sequence_becomes_one_node_each() -> None:
    tree = parse_rotation("razor skill[hold=1], dash, attack:3, burst;")

    assert [n.action for n in tree.nodes] == ["skill", "dash", "attack", "burst"]
    assert tree.nodes[0].params == {"hold": "1"}


def test_an_explicit_swap() -> None:
    assert isinstance(only("sucrose swap;"), SwapNode)


# ── control flow ─────────────────────────────────────────────────────────────


def test_a_counted_loop() -> None:
    node = only("for let i=0; i<6; i=i+1 {\n  furina skill;\n}")

    assert isinstance(node, LoopNode)
    assert node.loop == "counted"
    assert node.variable == "i"
    assert len(node.body) == 1


def test_a_guarded_loop() -> None:
    node = only("while .clorinde.status.night-watch {\n  clorinde attack;\n}")

    assert isinstance(node, LoopNode)
    assert node.loop == "guarded"


def test_an_if_else_chain_is_one_branch_node() -> None:
    node = only(
        "if .x.burst.ready {\n  x burst;\n} else if .x.skill.ready {\n  x skill;\n}"
        " else {\n  x attack;\n}",
    )

    assert isinstance(node, BranchNode)
    assert len(node.arms) == 2
    assert node.otherwise is not None


def test_an_if_without_an_else_has_no_otherwise() -> None:
    node = only("if .x.burst.ready {\n  x burst;\n}")

    assert node.otherwise is None


def test_wait_and_delay() -> None:
    assert isinstance(only("wait(173);"), WaitNode)
    assert only("delay(30);").mode == "delay"


def test_a_let_binding() -> None:
    assert isinstance(only("let x = 1;"), LetNode)


def test_a_call() -> None:
    node = only("mav_dc_cancel(6);")

    assert isinstance(node, CallNode)
    assert node.function == "mav_dc_cancel"


def test_a_function_definition_keeps_its_parameter_and_body() -> None:
    node = only("fn f(d) {\n  x attack;\n}")

    assert isinstance(node, FnNode)
    assert node.parameters == ["d"]
    assert len(node.body) == 1


# ── raw: the containment rule (task 2.10) ────────────────────────────────────


def test_a_builtin_call_parses_as_a_call() -> None:
    node = only('pick_up_crystallize("geo");')

    assert isinstance(node, CallNode)
    assert node.function == "pick_up_crystallize"


def test_something_unrecognised_becomes_raw_with_a_reason() -> None:
    node = only("999;")

    assert isinstance(node, RawNode)
    assert node.reason


def test_an_unreadable_loop_body_raws_the_whole_loop_not_just_the_body() -> None:
    """**The containment rule, and the sharpest test in this file.**

    Reading a `for` header, failing on its body and raw-ing only the body would leave a tree
    that *looks* structured — an editable loop around an opaque middle — and emitting it could
    reorder or re-gate what the author wrote. A construct is understood whole or carried whole.
    """
    source = "for let i=0; i<3; i=i+1 {\n  999;\n}"
    node = only(source)

    assert isinstance(node, RawNode)
    assert node.source.strip() == source.strip()
    assert node.reason


def test_raw_reproduces_its_source_byte_for_byte_including_comments() -> None:
    """Sliced from the source, never re-rendered from tokens.

    A re-rendered `raw` would be a different file that happens to mean the same thing, and the
    round-trip gate could then no longer tell a formatting change from a meaning change.
    """
    source = 'fn f(a) {  # a comment with https://x/y\n  999;\n}'
    node = only(source)

    assert isinstance(node, RawNode)
    assert node.source.strip() == source.strip()
    assert "# a comment with https://x/y" in node.source


def test_a_raw_node_never_swallows_the_statement_after_it() -> None:
    """Without `skip_construct` a raw node runs to end of file and the statement after an
    unreadable one vanishes — silent loss wearing the shape of a refusal."""
    tree = parse_rotation("999;\nfurina skill;")

    assert len(tree.nodes) == 2
    assert isinstance(tree.nodes[1], ActionNode)


@pytest.mark.parametrize(
    "source",
    [
        "if i > 0 && .x.burst.ready {\n  x burst;\n}",
        "for let j = 0; j < amt; j = j + 1 {\n  x attack;\n}",
        "while f() - StartFrame < 300 {\n  x attack;\n}",
    ],
)
def test_the_harder_real_shapes_parse_or_raw_but_never_crash(source: str) -> None:
    """Every one of these is in the corpus. None may raise."""
    tree = parse_rotation(source)

    assert len(tree.nodes) == 1
