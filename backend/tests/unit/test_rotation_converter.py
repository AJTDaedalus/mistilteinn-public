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
    """**A `skipif` here would be a lie.** These four files are committed, so their absence is
    a wrong path in this test rather than an environment without them — and a skip would report
    green for a check that never ran, which this repo treats as a failure.
    """
    assert DB.is_dir(), f"{DB} does not exist"
    assert len(list(DB.glob("*.txt"))) == 4


class _Character:
    def __init__(self, nanoka_id: str, name: str, element: str) -> None:
        self.nanoka_id, self.name, self.element = nanoka_id, name, element


# ── the rewrites ─────────────────────────────────────────────────────────────


def test_a_bounded_loop_becomes_the_cycle_it_describes() -> None:
    """`for i<4` four times over 90 seconds *is* a cycle; how long to run is stated elsewhere."""
    text, notes = convert("active a;\nfor let i=0; i<4; i=i+1 {\n    a skill;\n}\n")

    assert "while 1 {" in text
    assert "for" not in text
    assert any("while 1" in note for note in notes)


def test_a_sequence_written_across_several_lines_is_rejoined() -> None:
    """**A statement ends at `;`, not at a newline.** Arlecchino's config lays its combo out
    over four lines for readability; line-by-line the converter saw one statement and three
    orphans, and refused all four as "not a statement this model can express" — a refusal true
    of the lines and false of the config."""
    text, _ = convert(
        "active a;\nwhile 1 {\n    a charge,\n         attack:6,\n         attack:3;\n}\n",
    )

    assert text.count("if .a.") == 3
    assert "a attack:6;" in text


def test_a_comma_sequence_becomes_one_step_each() -> None:
    text, notes = convert("active a;\nwhile 1 {\n    a burst, skill, attack:3;\n}\n")

    assert text.count("if .a.") == 3
    assert "a attack:3;" in text
    assert any("3 steps" in note for note in notes)


def test_comments_are_dropped_in_both_dialects() -> None:
    """The real configs use `#` and `//`, sometimes on the same line as an action."""
    text, _ = convert("active a;\n# a note\nwhile 1 {\n    a skill; // trailing\n}\n")

    assert "note" not in text
    assert "trailing" not in text
    assert "a skill" in text


def test_every_rewrite_is_named() -> None:
    """**Nothing changes silently.** A `for` becoming a `while 1` is a real change to somebody
    else's config, and they should meet it in a list rather than in a damage number."""
    _, notes = convert("active a;\nfor let i=0; i<2; i=i+1 {\n    a burst, skill;\n}\n")

    assert len(notes) == 2


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
