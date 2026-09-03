"""What the converter rewrites, and what it deliberately hands on to be refused.

Owner ruling (`DECISIONS.md` §21): refuse, **plus a converter** — "whatever the four need", the
four being the real gcsim database configs under `references/gcsim_db/`.

**The four are the specification, and they are committed**, so the tests at the bottom read
them rather than paraphrasing them. A paraphrase of a config is a config nobody published.
"""

from __future__ import annotations

import pathlib

import pytest

from app.services.rotation_converter import convert
from app.services.rotation_parser import RotationParseError, parse_action_block

DB = pathlib.Path(__file__).resolve().parents[2].parent / "references" / "gcsim_db"


def test_the_committed_configs_are_where_this_file_thinks_they_are() -> None:
    """**A `skipif` here would be a lie.** These five files are committed, so their absence is
    a wrong path in this test rather than an environment without them — and a skip would report
    green for a check that never ran, which this repo treats as a failure.
    """
    assert DB.is_dir(), f"{DB} does not exist"
    assert len(list(DB.glob("*.txt"))) == 5


class _Character:
    def __init__(self, nanoka_id: str, name: str, element: str) -> None:
        self.nanoka_id, self.name, self.element = nanoka_id, name, element


# ── the rewrites ─────────────────────────────────────────────────────────────


def test_a_bounded_loop_keeps_its_own_bound() -> None:
    """`for i<4` says the author wants four cycles, and that is the one number they wrote.

    This used to rewrite the header to `while 1 {` and note that *"how long to run for is
    stated separately"* — true while `duration=90` stated it, and a silent discard of the
    author's count. `group_repeat` holds it now.
    """
    text, notes = convert("active a;\nfor let i=0; i<4; i=i+1 {\n    a skill;\n}\n")

    assert "for let i=0; i<4; i=i+1 {" in text
    assert "while 1" not in text
    assert notes == []


def test_a_sequence_written_across_several_lines_is_rejoined() -> None:
    """**A statement ends at `;`, not at a newline.** Arlecchino's config lays its combo out
    over four lines for readability; line-by-line the converter saw one statement and three
    orphans, and refused all four as "not a statement this model can express" — a refusal true
    of the lines and false of the config."""
    text, _ = convert(
        "active a;\nwhile 1 {\n    a charge,\n         attack:6,\n         attack:3;\n}\n",
    )

    assert text.count("a attack") == 2
    assert "a attack:6;" in text
    assert "a charge;" in text


def test_a_comma_sequence_becomes_one_step_each() -> None:
    text, notes = convert("active a;\nwhile 1 {\n    a burst, skill, attack:3;\n}\n")

    assert text.count("a burst;") == 1
    assert text.count("a skill;") == 1
    assert text.count("a attack:3;") == 1
    assert "a attack:3;" in text
    assert any("3 steps" in note for note in notes)


def test_comments_are_dropped_in_both_dialects() -> None:
    """The real configs use `#` and `//`, sometimes on the same line as an action."""
    text, _ = convert("active a;\n# a note\nwhile 1 {\n    a skill; // trailing\n}\n")

    assert "note" not in text
    assert "trailing" not in text
    assert "a skill" in text


def test_every_rewrite_is_named() -> None:
    """**Nothing changes silently.** Splitting one comma sequence into two steps is a real
    change to somebody else's config, and they should meet it in a list rather than in a
    damage number.

    The `for` header no longer contributes a note, because it is no longer rewritten.
    """
    _, notes = convert("active a;\nfor let i=0; i<2; i=i+1 {\n    a burst, skill;\n}\n")

    assert notes == ["'a burst, skill;' became 2 steps."]


def test_a_config_we_emitted_survives_untouched() -> None:
    """Already gated, already `while 1`. Re-gating would nest, and our own output must
    round-trip — which is the whole of tier 1."""
    ours = (
        "active noelle;\nwhile 1 {\n    if .noelle.skill.ready { noelle skill; }\n}\n"
    )
    text, notes = convert(ours)

    assert "if .noelle.skill.ready { noelle skill; }" in text
    assert notes == []


# ── what it hands on rather than swallowing ──────────────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        "    chev skill[hold=1]:2;",     # a parameterised action
        "    clorinde_combo();",          # a user-defined function
        "    mav_dc_cancel(6);",          # …with an argument
    ],
)
def test_an_inexpressible_line_is_passed_through_not_converted(line: str) -> None:
    """**Passed through so the parser refuses it by name.**

    A converter that swallowed these would turn a refusal into a silent omission — the failure
    the whole refuse-don't-degrade design exists to prevent.
    """
    text, _ = convert(f"active a;\nwhile 1 {{\n{line}\n}}\n")

    assert line.strip() in text


# ── the four, as published ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "roster", "expected"),
    [
        (
            "neuvillette-furina-citlali-escoffier.txt",
            [
                ("10000087", "Neuvillette", "Hydro"), ("10000089", "Furina", "Hydro"),
                ("10000107", "Citlali", "Cryo"), ("10000112", "Escoffier", "Cryo"),
            ],
            16,
        ),
        (
            # **Aliases and a multi-line sequence.** This config writes `arle` and `esco`,
            # which gcsim accepts and the key snapshot did not carry, and it lays out
            # `arle charge,\n attack:6,\n …;` across four lines for readability.
            "arlecchino-citlali-escoffier-bennett.txt",
            [
                ("10000096", "Arlecchino", "Pyro"), ("10000107", "Citlali", "Cryo"),
                ("10000112", "Escoffier", "Cryo"), ("10000032", "Bennett", "Pyro"),
            ],
            12,
        ),
    ],
)
def test_a_real_community_config_imports(
    name: str, roster: list[tuple[str, str, str]], expected: int,
) -> None:
    """Two of gcsim's own database configs, byte-for-byte as published.

    This is the evidence behind the ruling: the blockers on a real config were the loop
    keyword, the sequence syntax and gcsim's short aliases — **not** the conditional guards the
    design originally worried about.
    """
    text, _ = convert((DB / name).read_text())

    steps = parse_action_block(text, [_Character(*row) for row in roster])

    assert len(steps) == expected


@pytest.mark.parametrize(
    "name",
    [
        "clorinde-chevreuse-nicole-durin.txt",
        "mavuika-escoffier-citlali-bennett.txt",
    ],
)
def test_a_config_built_on_user_functions_is_still_refused(name: str) -> None:
    """These two are **different rotations, not different spellings**.

    `if !is_even(i)` runs a branch on alternate cycles and this model has no cycle index;
    `clorinde_combo()` and `mav_dc_cancel(6)` are named sequences with their own bodies. No
    larger converter fixes that — it would be inventing the author's intent.
    """
    text, _ = convert((DB / name).read_text())

    with pytest.raises(RotationParseError):
        parse_action_block(text, [])


# ── the opener ───────────────────────────────────────────────────────────────


def test_the_openers_statements_are_imported_not_dropped_or_refused() -> None:
    """`skirk-furina-citlali-escoffier.txt` is the config the owner linked, end to end.

    It runs 19 statements once — Furina's opener, Citlali, Escoffier, then Skirk's burst and
    four `attack:5` strings — before entering a `for` loop of 32.

    Its history is the whole argument for this test. It first imported **silently as 32
    steps**: a clean-looking result, the right character on field, and none of the opener. A
    head guard turned that into a refusal, which was honest and still left the config
    unimportable. Both halves are now held: the opener as ungrouped steps, the cycle as a
    group carrying the `for`'s own bound.
    """
    roster = [
        _Character("10000114", "Skirk", "cryo"),
        _Character("10000089", "Furina", "hydro"),
        _Character("10000107", "Citlali", "cryo"),
        _Character("10000112", "Escoffier", "cryo"),
    ]
    text, _ = convert((DB / "skirk-furina-citlali-escoffier.txt").read_text())

    steps = parse_action_block(text, roster)

    opener = [s for s in steps if s["group"] == ""]
    cycle = [s for s in steps if s["group"] == "loop"]
    assert len(opener) == 19, "the opener is what silently vanished the first time"
    assert len(cycle) == 32
    # The `for let a=0; a<5; a=a+1` bound, which `group_repeat` is exactly the field for.
    assert {s["group_repeat"] for s in cycle} == {5}
    # Skirk's burst is in the opener and nowhere else — the statement a reader would most
    # notice missing, and the one the old refusal named.
    assert ("10000114", "burst") in [(s["character"], s["action"]) for s in opener]


def test_a_config_statement_before_the_loop_is_not_an_opener() -> None:
    """`char`, `add`, `options`, `target`, `energy` and `active` all precede the loop legally.

    The head guard must tell those apart from actions, or it would refuse every config ever
    written. It asks the same `_statement` parser the body uses, so the two cannot disagree.
    """
    roster = [_Character("10000002", "Kamisato Ayaka", "cryo")]
    config = (
        'ayaka char lvl=90/90 cons=0 talent=9,9,9;\n'
        'ayaka add weapon="mistsplitter" refine=1 lvl=90/90;\n'
        "options iteration=100;\n"
        "target lvl=100 resist=0.1;\n"
        "active ayaka;\n"
        "while 1 {\n"
        "if .ayaka.attack.ready { ayaka attack; }\n"
        "}\n"
    )

    assert len(parse_action_block(config, roster)) == 1


def test_a_ready_branch_whose_else_is_the_if_without_the_gate_becomes_a_gated_step() -> None:
    """**The commonest shape in real community configs, and it was refused.**

    Reported by the owner from `gcsim.app/db/bgHjR7MP7Fkn`. Read the branches side by side and
    the `else` is the `if` with the burst taken out, so the construct *means* "burst if it is
    ready, then attack, skill, dash" — which is what a readiness gate says and what this
    repo's own compiler emits. The model was never missing the expressiveness; the importer
    was not recognising the shape.
    """
    text, notes = convert(
        "if .sucrose.burst.ready {\n"
        "  sucrose burst, attack, skill, dash;\n"
        "} else {\n"
        "  sucrose attack, skill, dash;\n"
        "}\n",
    )

    assert text.splitlines() == [
        "if .sucrose.burst.ready { sucrose burst; }",
        "sucrose attack;",
        "sucrose skill;",
        "sucrose dash;",
    ]
    assert any("gated step" in note for note in notes)


def test_a_branch_whose_sides_genuinely_differ_is_left_for_the_parser_to_refuse() -> None:
    """**A branch reduced on a guess is a rotation the author did not write.**

    The reduction holds only when the `else` is the `if` minus the gated action. Anything else
    is two different rotations, and this leaves them whole so the parser refuses them by name —
    the same rule as everywhere else here: refuse, never drop.
    """
    text, notes = convert(
        "if .sucrose.burst.ready {\n  sucrose burst;\n} else {\n  sucrose dash;\n}\n",
    )

    assert "else" in text
    assert notes == []


def test_a_parity_branch_in_a_counted_loop_is_written_out_as_cycles() -> None:
    """**`is_even(i)` is arithmetic, not a runtime condition.**

    Inside `for let i=0; i<N` it asks which cycle this is, and that is known before the
    simulation starts. Cycle 0 takes one branch, cycle 1 the other. Writing them out leaves a
    flat list of steps, which is what this model already is — so refusing it was refusing
    arithmetic. From the owner's report, `gcsim.app/db/bgHjR7MP7Fkn`.
    """
    text, notes = convert(
        "for let i=0; i<4; i=i+1 {\n"
        "  ineffa skill;\n"
        "  if !is_even(i) {\n    ineffa burst;\n  } else {\n    ineffa attack;\n  }\n"
        "}\n",
    )

    assert text.splitlines() == [
        "ineffa skill;", "ineffa attack;",
        "ineffa skill;", "ineffa burst;",
        "ineffa skill;", "ineffa attack;",
        "ineffa skill;", "ineffa burst;",
    ]
    assert any("written out as 4 cycles" in note for note in notes)


def test_a_block_the_unroll_cannot_read_is_carried_through_rather_than_abandoned() -> None:
    """**One unresolvable construct should not cost the resolvable ones.**

    The owner's config has both parity branches and a status guard. Bailing on the guard threw
    away the parity resolution with it, so a config with both got neither. The guard is copied
    into each cycle for the parser to refuse by name; the parity is still resolved.
    """
    text, notes = convert(
        "for let i=0; i<2; i=i+1 {\n"
        "  if is_even(i) {\n    a burst;\n  } else {\n    a attack;\n  }\n"
        "  if .a.status.flame {\n    a skill;\n  }\n"
        "}\n",
    )

    assert any("written out as 2 cycles" in note for note in notes)
    assert text.count("if .a.status.flame {") == 2
    assert "a burst;" in text
    assert "a attack;" in text
