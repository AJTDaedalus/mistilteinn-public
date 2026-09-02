"""Reading a gcsim action block back into rotation steps — the inverse of `rotation_compiler`.

`docs/DESIGN_rotation_library.md` §1. The compiler's own docstring said *"one direction only:
gcsim's config is a build artifact, not a format this repo reads back"*, and that was right
for as long as the only configs in play were ones this app had just emitted. The owner asked
for import, so there is now a reason to read.

**What makes this safe is that it refuses.** gcsim's language is far larger than the ten
actions a rotation step can name: conditional guards on energy and status, `wait`, nested
loops, per-character options. A parser that skipped what it could not express would produce a
rotation that *looks* like the author's and simulates to a different number — the failure
`unmodelled_passives` and the substat `isExact` flag exist to prevent, in a place where the
user has even less chance of noticing. So every line is either understood or the whole import
is refused, naming each line at fault.
"""

from __future__ import annotations

import pytest

from app.services.rotation_compiler import compile_rotation
from app.services.rotation_parser import RotationParseError, parse_action_block


class _Character:
    """The three fields `gcsim_keys.character_key` reads. A real row would do; this keeps the
    parser's tests free of a database, exactly as the compiler's are."""

    def __init__(self, nanoka_id: str, name: str, element: str) -> None:
        self.nanoka_id = nanoka_id
        self.name = name
        self.element = element


NOELLE = _Character("10000034", "Noelle", "Geo")
XIANGLING = _Character("10000023", "Xiangling", "Pyro")
ROSTER = [NOELLE, XIANGLING]


# ── the round trip ───────────────────────────────────────────────────────────


def test_a_config_this_app_emitted_parses_back_to_its_steps() -> None:
    """Tier 1 of the import, and the only tier that can claim exactness.

    Configs `compile_rotation` produces are a regular subset of gcsim: `while 1`, one
    `.ready` gate per step, no waits and no other conditionals.
    """
    steps = [
        {"character": "10000034", "action": "skill", "repeat": 1},
        {"character": "10000023", "action": "burst", "repeat": 1},
        {"character": "10000034", "action": "attack", "repeat": 3},
    ]
    parsed = parse_action_block(compile_rotation(steps, {c.nanoka_id: c for c in ROSTER}), ROSTER)

    assert [(s["character"], s["action"], s["repeat"]) for s in parsed] == [
        ("10000034", "skill", 1),
        ("10000023", "burst", 1),
        ("10000034", "attack", 3),
    ]


def test_the_round_trip_is_stable_through_a_second_compile() -> None:
    """The property that actually matters: parsing then recompiling must reproduce the text.

    Comparing the parsed steps to the originals only proves this file agrees with itself.
    Comparing the *emitted config* proves the two functions are inverses over the subset —
    including the parts a step dict does not carry, like which character `active` names.
    """
    characters = {c.nanoka_id: c for c in ROSTER}
    steps = [
        {"character": "10000023", "action": "burst", "repeat": 1},
        {"character": "10000034", "action": "attack", "repeat": 5},
    ]
    once = compile_rotation(steps, characters)

    assert compile_rotation(parse_action_block(once, ROSTER), characters) == once


def test_a_note_does_not_survive_and_is_not_invented() -> None:
    """A gcsim config has nowhere to put the user's own label for a step, so an import cannot
    recover one. It comes back empty rather than filled with the action name, which would be
    a note the author never wrote."""
    steps = [{"character": "10000034", "action": "skill", "repeat": 1, "note": "hold for shred"}]
    parsed = parse_action_block(
        compile_rotation(steps, {c.nanoka_id: c for c in ROSTER}), ROSTER,
    )

    assert parsed[0]["note"] == ""


def test_a_full_config_is_read_through_its_surrounding_lines() -> None:
    """`build_config` wraps the action block in options, character stanzas and a target. An
    import is given the whole file, not the block someone cut out of it."""
    config = (
        "options iteration=100 duration=90;\n"
        "target lvl=90 resist=0.1;\n"
        "noelle char lvl=90/90 cons=6 talent=9,9,9;\n"
        "\n"
        "active noelle;\n"
        "while 1 {\n"
        "    if .noelle.burst.ready { noelle burst; }\n"
        "}\n"
    )

    assert [s["action"] for s in parse_action_block(config, ROSTER)] == ["burst"]


# ── what it refuses ──────────────────────────────────────────────────────────


def test_a_conditional_this_model_cannot_express_is_refused() -> None:
    """**The central refusal.** Dropping `if .noelle.energy > 40` leaves a rotation that
    looks like the author's and does something else — it bursts every cycle instead of when
    the energy is there, and simulates to a number they never published."""
    config = (
        "active noelle;\n"
        "while 1 {\n"
        "    if .noelle.energy > 40 { noelle burst; }\n"
        "}\n"
    )

    with pytest.raises(RotationParseError, match="energy"):
        parse_action_block(config, ROSTER)


def test_a_wait_is_refused_rather_than_dropped() -> None:
    """`wait` is deliberately not authorable, and it is not decoration: it aligns a rotation
    to a buff window. A rotation missing its waits is a different rotation."""
    config = (
        "active noelle;\n"
        "while 1 {\n"
        "    noelle skill;\n"
        "    wait 30;\n"
        "}\n"
    )

    with pytest.raises(RotationParseError, match="wait"):
        parse_action_block(config, ROSTER)


def test_a_character_the_roster_does_not_have_is_refused_by_name() -> None:
    """The importer cannot invent a team. Naming the key is what lets the user fix it."""
    config = (
        "active noelle;\n"
        "while 1 {\n"
        "    if .noelle.skill.ready { noelle skill; }\n"
        "    if .bennett.burst.ready { bennett burst; }\n"
        "}\n"
    )

    with pytest.raises(RotationParseError, match="bennett"):
        parse_action_block(config, ROSTER)


def test_every_unreadable_line_is_named_not_just_the_first() -> None:
    """The same ethic as `rotation_compiler._resolve` and the GOOD importer: a user fixing an
    import should learn everything wrong with it once, not be sent round the loop per line."""
    config = (
        "active noelle;\n"
        "while 1 {\n"
        "    if .noelle.energy > 40 { noelle burst; }\n"
        "    wait 30;\n"
        "    if .xiangling.skill.ready { xiangling skill; }\n"
        "}\n"
    )

    with pytest.raises(RotationParseError) as caught:
        parse_action_block(config, ROSTER)

    assert "energy" in str(caught.value)
    assert "wait" in str(caught.value)


def test_a_helper_function_is_told_apart_from_two_rotations() -> None:
    """**The message has to be true**, the same lesson as the `for` one above.

    Two of the four community configs under `references/gcsim_db/` refuse here, and both have
    exactly one top-level cycle plus a `while` **inside a user-defined function** — a helper
    that waits on a cooldown, not a second rotation. Telling their author "2 loops, which of
    these is it?" sends them looking for an ambiguity their file does not have.

    Measured rather than assumed: the two that refuse are exactly the two carrying an `fn`.
    """
    config = (
        "fn wait_for_dash() {\n"
        "    while !.mavuika.dash.ready {\n"
        "        wait(1);\n"
        "    }\n"
        "}\n"
        "active noelle;\n"
        "while 1 {\n"
        "    noelle skill;\n"
        "}\n"
    )

    with pytest.raises(RotationParseError, match="defines its own functions"):
        parse_action_block(config, ROSTER)


def test_two_top_level_cycles_are_still_refused_as_two_cycles() -> None:
    """The other message stays, for the case it was written about: no helper, two cycles, and
    a genuine question about which one the rotation is."""
    config = (
        "active noelle;\n"
        "while 1 {\n"
        "    noelle skill;\n"
        "}\n"
        "while 1 {\n"
        "    noelle burst;\n"
        "}\n"
    )

    with pytest.raises(RotationParseError, match="2 loops"):
        parse_action_block(config, ROSTER)


def test_an_empty_loop_is_refused() -> None:
    """A rotation with no steps compiles to nothing to do, and the compiler already refuses
    to emit one. Importing one would create by the back door what authoring cannot."""
    config = "active noelle;\nwhile 1 {\n}\n"

    with pytest.raises(RotationParseError, match="no steps"):
        parse_action_block(config, ROSTER)


def test_a_gate_naming_a_different_action_than_it_guards_is_refused() -> None:
    """`if .noelle.skill.ready { noelle burst; }` is legal gcsim and is **not** what the
    compiler emits. Reading it as a burst step would silently discard the condition; reading
    it as a skill step would discard the action. Neither is recoverable, so it is refused."""
    config = (
        "active noelle;\nwhile 1 {\n    if .noelle.skill.ready { noelle burst; }\n}\n"
    )

    with pytest.raises(RotationParseError):
        parse_action_block(config, ROSTER)


def test_a_gate_on_one_character_guarding_another_is_refused() -> None:
    """Same shape, across characters, and the same reason."""
    config = (
        "active noelle;\n"
        "while 1 {\n"
        "    if .noelle.skill.ready { xiangling skill; }\n"
        "}\n"
    )

    with pytest.raises(RotationParseError):
        parse_action_block(config, ROSTER)


@pytest.mark.parametrize("repeat", ["0", "-2", "abc"])
def test_a_repeat_that_is_not_a_positive_count_is_refused(repeat: str) -> None:
    """`attack:0` is not an attack, and the schema's own bound is `ge=1`. Coercing it to 1
    would import a step the config did not ask for."""
    config = (
        "active noelle;\n"
        "while 1 {\n"
        f"    if .noelle.attack.ready {{ noelle attack:{repeat}; }}\n"
        "}\n"
    )

    with pytest.raises(RotationParseError):
        parse_action_block(config, ROSTER)


def test_nothing_at_all_is_refused() -> None:
    with pytest.raises(RotationParseError):
        parse_action_block("", ROSTER)


# ── kit variants survive the round trip ─────────────────────────────────────
#
# A config **this repo emits** must be readable by **this repo's** importer. Before the
# variant group was added to `_GATED`, `skill[hold=1]` was refused — and the refusal blamed
# the condition, which was not what was wrong.

CHEVREUSE = _Character("10000090", "Chevreuse", "Pyro")


def _gated(action: str, key: str = "chevreuse") -> str:
    base = action.split("[", maxsplit=1)[0].split(":", maxsplit=1)[0]
    return (
        f"active {key};\nwhile 1 {{\n"
        f"    if .{key}.{base}.ready {{ {key} {action}; }}\n}}"
    )


def test_a_hold_is_read_back_as_the_action_it_is():
    steps = parse_action_block(_gated("skill[hold=1]"), [CHEVREUSE])

    assert [s["action"] for s in steps] == ["skill_hold"]


def test_a_hold_keeps_its_repetition():
    steps = parse_action_block(_gated("skill[hold=1]:2"), [CHEVREUSE])

    assert steps[0]["repeat"] == 2


def test_what_the_compiler_emits_is_what_the_parser_reads():
    """The round trip, on the whole shape rather than on one line.

    A rotation published to the library and imported elsewhere goes out through
    `compile_rotation` and comes back through here. If the two disagreed, a hold-E would be
    refused on import — or worse, quietly read as a tap.
    """
    steps = [
        {"character": "10000090", "action": "skill_hold", "repeat": 1, "note": "",
         "group": "", "group_repeat": 1},
        {"character": "10000090", "action": "burst", "repeat": 1, "note": "",
         "group": "", "group_repeat": 1},
        {"character": "10000090", "action": "attack", "repeat": 3, "note": "",
         "group": "", "group_repeat": 1},
    ]
    roster = {"10000090": CHEVREUSE}

    read_back = parse_action_block(compile_rotation(steps, roster), [CHEVREUSE])

    assert read_back == steps


def test_a_parameter_this_model_cannot_hold_is_refused_not_dropped():
    """gcsim **ignores** a parameter it does not recognise for a character — measured.

    `xingqiu skill[hold=1]` and `xingqiu skill` produce byte-identical damage through the
    committed wasm build. So importing `skill[glide_cancel=1]` as a plain `skill` would give
    the user a rotation that looks like the author's and simulates to a different number.
    """
    with pytest.raises(RotationParseError) as raised:
        parse_action_block(_gated("skill[glide_cancel=1]"), [CHEVREUSE])

    assert "glide_cancel" in str(raised.value)


def test_a_parameter_that_is_not_a_flag_is_refused():
    """`hold=3` is a quantity, and this model expresses one boolean variant per action."""
    with pytest.raises(RotationParseError) as raised:
        parse_action_block(_gated("skill[hold=3]"), [CHEVREUSE])

    assert "kit variant" in str(raised.value)


def test_a_variant_no_character_declares_is_refused():
    """`burst[hold=1]` parses as a flag and names a move gcsim has for nobody at this pin."""
    with pytest.raises(RotationParseError) as raised:
        parse_action_block(_gated("burst[hold=1]"), [CHEVREUSE])

    assert "no such move" in str(raised.value)


# ── The three shapes a real config comes in (2026-09-01) ─────────────────────
#
# All three used to be refused. `while 1` was the only importable form, which meant the parser
# could read exactly one config: the one this app had written.


def test_a_bare_action_list_is_the_rotation_run_once():
    """It is what the compiler emits now, so refusing it would refuse our own output.

    The old refusal — *"gcsim runs a bare action list once, over a 90-second duration that is
    one burst"* — was true of a config with `duration=90`. The compiler stopped emitting that.
    """
    steps = parse_action_block(
        "active chevreuse;\nchevreuse skill;\nchevreuse attack:2;\n", [CHEVREUSE],
    )

    assert [s["action"] for s in steps] == ["skill", "attack"]
    assert {s["group"] for s in steps} == {""}
    assert {s["group_repeat"] for s in steps} == {1}


def test_a_for_loop_becomes_a_group_with_its_own_repeat():
    """`group_repeat` is exactly the field the old refusal said did not exist.

    It said *"a bounded loop repeats a rotation a number of times, which is a property of the
    simulation rather than of the rotation, and this model does not carry it"*. Groups landed
    afterwards and nothing revisited this.
    """
    config = (
        "active chevreuse;\n"
        "for let a=0; a<4; a=a+1 {\n"
        "chevreuse skill;\n"
        "chevreuse attack:2;\n"
        "}\n"
    )

    steps = parse_action_block(config, [CHEVREUSE])

    assert [s["group"] for s in steps] == ["loop", "loop"]
    assert [s["group_repeat"] for s in steps] == [4, 4]


def test_an_opener_is_kept_rather_than_dropped_or_refused():
    """gcsim db `kDHmWKmfgqtF` opens with 19 statements before its cycle.

    Those were silently discarded once, then refused, and are now imported: ungrouped steps
    ahead of the group, which is what an opener is.
    """
    config = (
        "active chevreuse;\n"
        "chevreuse burst;\n"
        "for let a=0; a<3; a=a+1 {\n"
        "chevreuse attack;\n"
        "}\n"
    )

    steps = parse_action_block(config, [CHEVREUSE])

    assert [(s["action"], s["group"], s["group_repeat"]) for s in steps] == [
        ("burst", "", 1), ("attack", "loop", 3),
    ]


def test_a_line_inside_the_loop_that_cannot_be_read_is_still_named():
    """The filter that finds the opener must not become a filter that hides bad lines.

    An earlier draft of this decided membership with "does it parse as an action?", which
    swallowed every line a user actually needed told about.
    """
    config = (
        "active chevreuse;\n"
        "for let a=0; a<2; a=a+1 {\n"
        "chevreuse skill;\n"
        "if .chevreuse.energy >= 80 { chevreuse burst; }\n"
        "}\n"
    )

    with pytest.raises(RotationParseError) as caught:
        parse_action_block(config, [CHEVREUSE])

    assert ".chevreuse.energy" in str(caught.value)
