"""A guarded block's condition is gcsim script, so it is held to the vocabulary everywhere.

Security audit F2. `group_condition` used to be free text up to 120 characters, emitted into
the config verbatim — so a published rotation could close its own block and append arbitrary
gcsim statements that ran in the browser of whoever compiled a copy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.rotation import RotationStep
from app.services import rotation_parser
from app.services.rotation_compiler import RotationCompileError, compile_rotation
from app.services.rotation_conditions import is_allowed_condition

ALLOWED = [
    ".noelle.burst.ready",
    ".flins.status.manifest-flame",
    ".flins.energy >= 30",
    ".xiangling.energy<40",
    ".a.energy == 0",
]

REFUSED = [
    '1 { } while 1 { print("x"); } if 0',
    "1 { } while 1 { } if 0",
    ".noelle.burst.ready { } while 1 {",
    ".noelle.burst.ready; noelle burst",
    ".noelle.burst.ready\nwhile 1 {}",
    ".noelle.burst.ready\n",
    ".flins.energy >= 30 || 1",
    ".flins.energy >= ٣٠",  # Arabic-Indic digits: not ASCII, not gcsim
    "true",
    "1",
    " .noelle.burst.ready",
]


@pytest.mark.parametrize("condition", ALLOWED)
def test_the_vocabulary_is_accepted(condition: str) -> None:
    assert is_allowed_condition(condition)
    step = RotationStep(character="1", action="burst", group="g", group_condition=condition)
    assert step.group_condition == condition


@pytest.mark.parametrize("condition", REFUSED)
def test_anything_else_is_refused_by_the_schema(condition: str) -> None:
    assert not is_allowed_condition(condition)
    with pytest.raises(ValidationError, match="not a condition"):
        RotationStep(character="1", action="burst", group="g", group_condition=condition)


def test_an_unguarded_step_needs_no_condition() -> None:
    assert RotationStep(character="1", action="burst").group_condition == ""


@pytest.mark.parametrize("condition", ALLOWED)
def test_the_importer_reads_the_same_vocabulary(condition: str) -> None:
    """One pattern: the importer must not open a block the schema would then refuse."""
    match = rotation_parser._BLOCK_CONDITION.match(f"if {condition} {{")
    assert match is not None
    assert match.group(1) == condition


@pytest.mark.parametrize("condition", REFUSED)
def test_the_compiler_refuses_to_emit_a_condition_outside_the_vocabulary(
    condition: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth: a raw stored step never reaches the config unchecked."""
    from app.services import rotation_compiler

    monkeypatch.setattr(rotation_compiler, "_resolve", lambda steps, _: ["noelle"] * len(steps))
    steps = [{"character": "1", "action": "burst", "group": "g", "group_condition": condition}]

    with pytest.raises(RotationCompileError, match="not a condition"):
        compile_rotation(steps, {"1": SimpleNamespace()})


def test_the_compiler_still_emits_an_allowed_condition(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import rotation_compiler

    monkeypatch.setattr(rotation_compiler, "_resolve", lambda steps, _: ["noelle"] * len(steps))
    steps = [{"character": "1", "action": "burst", "group": "g",
              "group_condition": ".noelle.energy >= 30"}]

    assert "if .noelle.energy >= 30 {" in compile_rotation(steps, {"1": SimpleNamespace()})
