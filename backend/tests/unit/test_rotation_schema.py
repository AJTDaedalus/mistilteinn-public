"""R.1 — what a rotation step will and will not accept.

`DESIGN_rotation.md` §1: gcsim's syntax is hard because two of its behaviours are silent — a
bare action list runs **once**, and `while 1` **deadlocks** on an ungated action — and both
produce a plausible config with exactly one burst in it.

A model that cannot express those mistakes is worth more than a warning about them. These
tests are about what the model refuses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.rotation import MAX_REPEAT, MAX_STEPS, RotationCreate, RotationStep
from app.services.gcsim_keys import authorable_actions, gcsim_actions

KEYS = Path(__file__).resolve().parents[2] / "app" / "data" / "gcsim" / "keys.json"


def _step(**over) -> dict:
    return {"character": "10000002", "action": "burst", **over}


# ── The vocabulary is gcsim's, derived ────────────────────────────────────────


def test_the_action_list_comes_from_gcsim_at_the_pin():
    """Parsed out of `pkg/core/action/action.go`, not restated.

    A restated list drifts in the direction that matters most — offering an action gcsim
    rejects, so the config fails at simulation time with a parser error instead of at
    authoring time with a sentence.
    """
    committed = json.loads(KEYS.read_text())["actions"]

    assert tuple(committed) == gcsim_actions()
    assert "attack" in committed
    assert "burst" in committed
    assert "invalid" not in committed, "the enum's zero value is not something a config names"


def test_the_authorable_set_is_gcsim_minus_three_reasons():
    """Derived by subtraction, so a re-pin adding an action offers it automatically."""
    hidden = set(gcsim_actions()) - set(authorable_actions())

    assert hidden == {"swap", "wait", "delay"}
    assert len(authorable_actions()) == 10


@pytest.mark.parametrize("action", ["skill", "burst", "attack", "charge", "dash", "walk"])
def test_a_real_action_is_accepted(action: str):
    assert RotationStep(**_step(action=action)).action == action


def test_swap_is_refused_because_gcsim_inserts_it():
    """`run.go:154` has the evaluator add swaps when the next character is not active.

    Emitting our own would double them, so a step cannot name one.
    """
    with pytest.raises(ValidationError, match="implicit"):
        RotationStep(**_step(action="swap"))


@pytest.mark.parametrize("action", ["wait", "delay"])
def test_timing_actions_are_refused(action: str):
    """§2 keeps timing out of the model: exposing it invites the user back into frame
    counting, which is the thing being removed."""
    with pytest.raises(ValidationError, match="timing controls"):
        RotationStep(**_step(action=action))


def test_an_unknown_action_is_refused_and_names_the_ten():
    """A user who typed `ult` should be told what exists, not just that they are wrong."""
    with pytest.raises(ValidationError) as exc:
        RotationStep(**_step(action="ult"))

    message = str(exc.value)
    assert "'ult' is not an action" in message
    assert "burst" in message
    assert "skill" in message


# ── Repeat ────────────────────────────────────────────────────────────────────


def test_repeat_defaults_to_one():
    assert RotationStep(**_step()).repeat == 1


def test_repeat_must_be_at_least_one():
    """A step that happens zero times is a step that should have been deleted."""
    with pytest.raises(ValidationError):
        RotationStep(**_step(repeat=0))


def test_repeat_is_bounded():
    """A typo must not compile to a config that runs for an hour."""
    RotationStep(**_step(repeat=MAX_REPEAT))
    with pytest.raises(ValidationError):
        RotationStep(**_step(repeat=MAX_REPEAT + 1))


# ── The rotation itself ───────────────────────────────────────────────────────


def test_a_rotation_needs_a_name():
    with pytest.raises(ValidationError):
        RotationCreate(name="", team_id="t", steps=[])


def test_an_empty_rotation_is_allowed():
    """A rotation is authored incrementally; refusing to save an empty one loses the name
    and the team the user just chose."""
    assert RotationCreate(name="WIP", team_id="t").steps == []


def test_the_step_list_is_bounded():
    """The cap stops a row being used as storage. It is not an opinion about rotations."""
    RotationCreate(name="Long", team_id="t", steps=[_step()] * MAX_STEPS)
    with pytest.raises(ValidationError):
        RotationCreate(name="TooLong", team_id="t", steps=[_step()] * (MAX_STEPS + 1))


def test_a_rotation_cannot_be_moved_between_teams():
    """`RotationUpdate` has no `team_id`, deliberately.

    Moving one would reinterpret every step against a different party, and the steps that no
    longer resolved would surface later, at compile time, far from the edit that caused it.
    """
    from app.schemas.rotation import RotationUpdate

    assert "team_id" not in RotationUpdate.model_fields


def test_a_preview_refuses_a_split_group_exactly_as_a_save_does():
    """`RotationCreate` and `RotationUpdate` both ran `check_groups`; the preview did not.

    So the live preview — and "Run once", which goes through the same endpoint — compiled a
    rotation the save refuses, expanding a scattered group into the chunk repeated in two
    places. The schema's own docstring says a preview that accepted more than the save would is
    a preview of something that cannot exist.
    """
    from app.schemas.rotation import RotationPreviewRequest

    scattered = [
        {"character": "a", "action": "skill", "group": "g1", "group_repeat": 3},
        {"character": "a", "action": "attack"},
        {"character": "a", "action": "burst", "group": "g1", "group_repeat": 3},
    ]

    with pytest.raises(ValidationError):
        RotationPreviewRequest(team_id="t", steps=scattered)
