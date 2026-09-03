"""The emitter, and the round-trip property — tasks 3.1 to 3.4."""
from __future__ import annotations

import pytest

from app.schemas.rotation_nodes import RawNode, RotationTree
from app.services.gcsim_emitter import emit_tree
from app.services.gcsim_parser import parse_rotation


def roundtrip(source: str) -> RotationTree:
    return parse_rotation(emit_tree(parse_rotation(source)))


@pytest.mark.parametrize(
    "source",
    [
        "furina skill;",
        "skirk attack:3;",
        "razor skill[hold=1];",
        "razor skill[hold=1], dash, attack:3, burst;",
        "sucrose swap;",
        "wait(173);",
        "delay(30);",
        "let x = 1;",
        "i = i + 1;",
        "mav_dc_cancel(6);",
        "for let i=0; i<6; i=i+1 {\n  furina skill;\n}",
        "while .clorinde.status.night-watch {\n  clorinde attack;\n}",
        "if .x.burst.ready {\n  x burst;\n}",
        "if .x.burst.ready {\n  x burst;\n} else {\n  x attack;\n}",
        (
            "if .x.burst.ready {\n  x burst;\n} else if .x.skill.ready {\n  x skill;\n}"
            " else {\n  x attack;\n}"
        ),
        "fn f(d) {\n  x attack;\n}",
        "if .x.energy >= 30 && !.x.burst.ready {\n  x skill;\n}",
        "for let i=0; i<3; i=i+1 {\n  if .x.burst.ready {\n    x burst;\n  }\n}",
    ],
)
def test_a_tree_survives_emit_and_reparse(source: str) -> None:
    """**The gate on this whole design.** `parse(emit(t)) == t`."""
    once = parse_rotation(source)

    assert roundtrip(source) == once


def test_emitting_twice_is_stable() -> None:
    """A second pass must change nothing, or the round trip is only accidentally true."""
    tree = parse_rotation("for let i=0; i<6; i=i+1 {\n  a skill, dash;\n}")
    first = emit_tree(tree)

    assert emit_tree(parse_rotation(first)) == first


def test_a_raw_node_emits_its_source_byte_for_byte() -> None:
    """Task 3.2. Re-rendering it would make the round trip unable to tell a formatting
    change from a meaning change, which is the one distinction it exists to make."""
    source = "for let i=0; i<3; i=i+1 {\n  999;   # kept exactly\n}"
    tree = parse_rotation(source)

    assert isinstance(tree.nodes[0], RawNode)
    assert emit_tree(tree).strip() == source.strip()


def test_a_branch_emits_gcsim_s_own_chain_shape() -> None:
    emitted = emit_tree(parse_rotation(
        "if .x.burst.ready {\n x burst;\n} else {\n x attack;\n}",
    ))

    assert "} else {" in emitted
