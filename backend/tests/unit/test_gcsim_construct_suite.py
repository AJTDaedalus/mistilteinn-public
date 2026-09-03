"""One config per construct, written here so it is ours to licence — tasks 11.2 and 11.3.

**This is what CI runs.** The 500-config corpus is deliberately not committed: gcsim's
database states no licence for submitted configs (`references/gcsim_db/PROVENANCE.md`), and
five files vendored with full provenance is a different proposition from five hundred. So the
sweep (`scripts/sweep_gcsim_db.py`) is a tool a person runs, and this suite is the gate.

Every construct below was observed in that corpus. The *shapes* are real; the text is ours.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.rotation_nodes import RawNode
from app.services.gcsim_emitter import emit_tree
from app.services.gcsim_parser import parse_rotation, split_config
from app.services.rotation_diagnostics import Severity, validate_rotation

#: `(name, source)`, one per construct the corpus contains.
CONSTRUCTS: list[tuple[str, str]] = [
    ("a plain action", "noelle skill;"),
    ("a repeat", "noelle attack:3;"),
    ("a comma sequence", "noelle skill, attack:2, dash, burst;"),
    ("a kit variant", "razor skill[hold=1];"),
    ("a variant inside a sequence", "razor skill[hold=1], dash, attack, burst;"),
    ("an unoffered parameter, carried", "mavuika charge[final=1];"),
    ("an explicit swap", "sucrose swap;"),
    ("a counted loop", "for let i=0; i<6; i=i+1 {\n  noelle skill;\n}"),
    ("a loop with a variable bound",
     "let amt = 3;\nfor let j=0; j<amt; j=j+1 {\n  noelle attack;\n}"),
    ("a state-guarded loop",
     "while .clorinde.status.night-watch {\n  clorinde attack;\n}"),
    ("a branch", "if .noelle.burst.ready {\n  noelle burst;\n}"),
    ("an else", "if .noelle.burst.ready {\n  noelle burst;\n} else {\n  noelle attack;\n}"),
    (
        "an else-if chain",
        (
            "if .a.burst.ready {\n  a burst;\n} else if .a.skill.ready {\n  a skill;\n}"
            " else {\n  a attack;\n}"
        ),
    ),
    ("an energy guard", "if .flins.energy >= 30 {\n  flins burst;\n}"),
    ("a compound condition",
     "if .a.burst.ready && !.b.burst.ready {\n  a burst;\n}"),
    ("a wait", "wait(173);"),
    ("a delay", "delay(30);"),
    ("a let binding", "let x = 1;"),
    ("an assignment", "let i = 0;\ni = i + 1;"),
    ("a builtin call", 'pick_up_crystallize("geo");'),
    ("a debug print", 'print("hello");'),
    ("a user function", "fn helper(n) {\n  noelle attack:n;\n}\nhelper(3);"),
    ("a typed parameter", "fn f(char_id number, p map) {\n  let x = char_id;\n}\nf(1, 2);"),
    ("a nested block",
     "for let i=0; i<3; i=i+1 {\n  if .a.burst.ready {\n    a burst;\n  }\n}"),
    ("a comment in both syntaxes", "# one\nnoelle skill; // two"),
    ("a leading-decimal number", "if .a.energy >= 0.5 {\n  a burst;\n}"),
    ("something unmodelled, carried whole", "for let i=0; i<3; i=i+1 {\n  999;\n}"),
]


@pytest.mark.parametrize(("name", "source"), CONSTRUCTS, ids=[c[0] for c in CONSTRUCTS])
def test_every_construct_round_trips(name: str, source: str) -> None:
    """**The gate.** `parse(emit(t)) == t` for every shape the corpus contains."""
    once = parse_rotation(source)

    assert parse_rotation(emit_tree(once)) == once, name


@pytest.mark.parametrize(("name", "source"), CONSTRUCTS, ids=[c[0] for c in CONSTRUCTS])
def test_no_construct_produces_a_false_error(name: str, source: str) -> None:
    """These are all valid gcsim. An error-level diagnostic on one is a bug in the validator,
    and the corpus found four such classes worth 170 configs before this suite existed."""
    _, diagnostics = validate_rotation(source)

    assert [d.message for d in diagnostics if d.severity is Severity.ERROR] == [], name


@pytest.mark.parametrize(("name", "source"), CONSTRUCTS, ids=[c[0] for c in CONSTRUCTS])
def test_no_construct_is_lost(name: str, source: str) -> None:
    """Every construct produces at least one node. Silence is the failure mode this whole
    design refuses, and an empty tree is the silent version of a refusal."""
    assert parse_rotation(source).nodes, name


def test_a_carried_node_reproduces_its_source_exactly() -> None:
    source = "for let i=0; i<3; i=i+1 {\n  999;   # kept\n}"
    tree = parse_rotation(source)

    assert isinstance(tree.nodes[0], RawNode)
    assert emit_tree(tree).strip() == source.strip()


# ── the five vendored configs, which are real and licensed as recorded ──────


VENDORED = sorted(
    (Path(__file__).resolve().parents[3] / "references" / "gcsim_db").glob("*.txt"),
)


@pytest.mark.parametrize("path", VENDORED, ids=[p.stem for p in VENDORED])
def test_a_vendored_config_round_trips(path: Path) -> None:
    """CRLF and LF alike — four of the five are CRLF, and that is the API's own payload."""
    _, rotation = split_config(path.read_text(encoding="utf-8"))
    once = parse_rotation(rotation)

    assert parse_rotation(emit_tree(once)) == once


def test_the_vendored_corpus_is_actually_present() -> None:
    """A parametrised test over an empty glob passes by running nothing.

    This repo has already shipped a query-count test that passed while counting zero; the
    same shape here would make the vendored suite green by absence.
    """
    assert len(VENDORED) == 5
