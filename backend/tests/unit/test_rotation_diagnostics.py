"""Validation and diagnostics — Phase 6.

Ships before the source view that needs it: the owner's ruling allows a typed surface, and a
typed surface is only as friendly as its errors.
"""
from __future__ import annotations

from app.services.rotation_diagnostics import Severity, validate_rotation


class Character:
    def __init__(self, nanoka_id: str, name: str, element: str) -> None:
        self.nanoka_id, self.name, self.element = nanoka_id, name, element


ROSTER = {"1": Character("1", "Noelle", "geo")}


def messages(source: str, roster=None) -> list[str]:
    return [d.message for d in validate_rotation(source, roster)[1]]


def only(source: str, roster=None):
    diagnostics = validate_rotation(source, roster)[1]
    assert len(diagnostics) == 1, [d.message for d in diagnostics]
    return diagnostics[0]


# ── 6.1 the call graph ───────────────────────────────────────────────────────


def test_a_call_to_nothing_is_an_error() -> None:
    assert "nothing defines `f`" in only("f(1);").message


def test_an_arity_mismatch_is_an_error() -> None:
    source = "fn g(a) {\n  noelle skill;\n}\ng();"

    assert "takes 1 argument" in only(source).message


def test_recursion_is_named_as_recursion() -> None:
    """Saying "undefined" or nothing at all would send the author looking in the wrong place."""
    assert "calls itself" in only("fn r() {\n  r();\n}\nr();").message


def test_mutual_recursion_is_found_too() -> None:
    source = "fn a() {\n  b();\n}\nfn b() {\n  a();\n}\na();"

    assert any("calls itself" in m for m in messages(source))


def test_a_function_that_calls_another_once_is_fine() -> None:
    source = "fn a() {\n  noelle skill;\n}\nfn b() {\n  a();\n}\nb();"

    assert messages(source) == []


# ── 6.2 scope ───────────────────────────────────────────────────────────────


def test_an_identifier_nothing_declares_is_an_error() -> None:
    assert "not in scope" in only("let x = y + 1;").message


def test_a_loop_index_is_in_scope_inside_its_own_loop() -> None:
    source = "for let i=0; i<3; i=i+1 {\n  if i {\n    noelle skill;\n  }\n}"

    assert messages(source) == []


def test_a_function_parameter_is_in_scope_in_its_body() -> None:
    source = "fn f(d) {\n  let x = d;\n}"

    assert messages(source) == []


def test_a_let_earlier_in_the_file_is_in_scope_later() -> None:
    assert messages("let x = 1;\nlet y = x;") == []


# ── 6.3 references ──────────────────────────────────────────────────────────


def test_a_character_off_the_team_is_an_error() -> None:
    assert "not on this team" in only("xiangling skill;", ROSTER).message


def test_a_character_on_the_team_is_fine() -> None:
    assert messages("noelle skill;", ROSTER) == []


def test_an_alias_resolves_against_the_roster() -> None:
    """gcsim accepts 60 short names and this repo emits none of them, so an alias only ever
    arrives from somebody else's config — which is the case import exists for."""
    assert messages("noelle burst;", ROSTER) == []


def test_no_roster_means_no_character_checking() -> None:
    """Validating a config before a team is chosen is a real state, and reporting every
    character as a stranger would be noise rather than help."""
    assert messages("whoever skill;") == []


# ── 6.4 and 6.5 position and severity ───────────────────────────────────────


def test_a_diagnostic_carries_the_position_an_editor_underlines() -> None:
    diagnostic = only("noelle skill;\n999;")

    assert (diagnostic.line, diagnostic.column) == (2, 1)
    assert diagnostic.length >= 1


def test_a_carried_construct_is_a_warning_not_an_error() -> None:
    """It runs. Collapsing warning into error would make a user either ignore both or fear
    both."""
    assert only("999;").severity is Severity.WARNING


def test_an_undefined_call_is_an_error_not_a_warning() -> None:
    assert only("f();").severity is Severity.ERROR


def test_diagnostics_are_sorted_by_position() -> None:
    source = "999;\nlet x = y;"
    lines = [d.line for d in validate_rotation(source)[1]]

    assert lines == sorted(lines)


# ── 6.6 returned, not raised ────────────────────────────────────────────────


def test_every_problem_is_reported_not_just_the_first() -> None:
    """A validator that raises can only ever report one problem, and an author fixing an
    imported rotation should learn what is wrong with it once."""
    source = "f();\nlet x = y;\n999;"

    assert len(validate_rotation(source)[1]) == 3


def test_a_clean_rotation_reports_nothing() -> None:
    assert messages("noelle skill;\nnoelle attack:3;", ROSTER) == []


# ── what the corpus taught this file ────────────────────────────────────────


def test_a_gcsim_builtin_is_not_reported_as_undefined() -> None:
    """`print`, `sleep` and `pick_up_crystallize` are gcsim's own, declared by no `fn`.
    Reporting them would have produced a false error in 118 of 500 real configs."""
    assert messages('print("hi");\nsleep(30);\npick_up_crystallize("geo");') == []


def test_a_call_to_a_function_whose_body_was_carried_still_resolves() -> None:
    """A function whose *body* cannot be modelled is carried whole, so it never becomes an
    `FnNode` — and every call to it then looked undefined. 35 false errors across the corpus,
    every one pointing at the caller rather than the construct responsible."""
    source = "fn DulicPlunge() {\n  999;\n}\nDulicPlunge();"

    assert not [m for m in messages(source) if "nothing defines" in m]


def test_a_typed_parameter_is_one_parameter_not_two() -> None:
    """`fn f(char_id number, p map)` is real gcsim syntax, in 17 corpus configs. Reading the
    type as a second name got both the arity and the body's scope wrong."""
    source = "fn f(char_id number, p map) {\n  let x = char_id;\n}\nf(1, 2);"

    assert messages(source) == []


def test_a_function_name_can_be_used_as_a_value() -> None:
    """`let _f = f;` takes a reference to one, which real configs do."""
    source = "fn f() {\n  noelle skill;\n}\nlet g = f;"

    assert messages(source) == []
