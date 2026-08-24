"""R.2 — the compiler, and the two silent gcsim behaviours it exists to absorb.

Both were met for real while building D.2's ER sweep, and both produced a plausible config
with exactly one burst in it:

1. a bare action list runs **once**;
2. `while 1` **deadlocks** on an ungated action, because gcsim waits for something not ready.

Neither errored. That is why these are tests rather than documentation.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.enums import Element
from app.services.rotation_compiler import RotationCompileError, compile_rotation

AYAKA = SimpleNamespace(nanoka_id="10000002", name="Kamisato Ayaka", element=Element.CRYO)
BARBARA = SimpleNamespace(nanoka_id="10000014", name="Barbara", element=Element.HYDRO)
ROSTER = {"10000002": AYAKA, "10000014": BARBARA}


def _step(character: str = "10000002", action: str = "burst", repeat: int = 1) -> dict:
    return {"character": character, "action": action, "repeat": repeat}


# ── Failure 1: the config must cycle ─────────────────────────────────────────


def test_the_rotation_is_wrapped_in_a_loop():
    """Without it the whole rotation happens once in ninety seconds.

    That is not a subtle error — it is most of the DPS figure — and gcsim reports it as a
    perfectly ordinary run.
    """
    out = compile_rotation([_step()], ROSTER)

    assert "while 1 {" in out
    assert out.rstrip().endswith("}")


# ── Failure 2: every step is gated ───────────────────────────────────────────


def test_every_step_carries_a_readiness_gate():
    """`.ready` calls gcsim's own `ActionReady`, so it covers cooldown *and* burst energy.

    The user never types an energy threshold and cannot write the deadlock.
    """
    out = compile_rotation(
        [_step(action="burst"), _step(action="skill"), _step(action="attack")], ROSTER,
    )

    assert out.count("if .kamisatoayaka.") == 3
    assert ".burst.ready" in out
    assert ".skill.ready" in out


def test_even_attack_is_gated():
    """An attack is essentially always ready, so its gate is noise — deliberately.

    Gating selectively needs a hand-maintained table of "which actions can stall", and a
    wrong entry there brings the deadlock back silently. A redundant `if` is the cheaper
    mistake.
    """
    assert "if .kamisatoayaka.attack.ready" in compile_rotation([_step(action="attack")], ROSTER)


# ── The rest of the emission ─────────────────────────────────────────────────


def test_repeat_uses_gcsims_own_colon_syntax():
    out = compile_rotation([_step(action="attack", repeat=3)], ROSTER)

    assert "kamisatoayaka attack:3;" in out


def test_a_single_repeat_omits_the_colon():
    """`attack:1` is legal and noisy; the plain form is what a human writes."""
    out = compile_rotation([_step(action="attack", repeat=1)], ROSTER)

    assert "kamisatoayaka attack;" in out
    assert "attack:1" not in out


def test_no_swap_actions_are_emitted():
    """`run.go:154`: the evaluator inserts swaps when the next character is not active.

    Emitting our own would double them.
    """
    out = compile_rotation(
        [_step(character="10000014", action="skill"), _step(action="burst")], ROSTER,
    )

    assert " swap" not in out
    assert "barbara skill" in out
    assert "kamisatoayaka burst" in out


def test_active_is_the_first_actor_not_the_first_roster_entry():
    """Otherwise the rotation opens with an implicit swap gcsim has to pay for, before the
    user's first intended action — a cost they did not write and cannot see."""
    out = compile_rotation([_step(character="10000014", action="skill")], ROSTER)

    assert out.startswith("active barbara;")


def test_characters_are_named_by_their_gcsim_key():
    """gcsim's key for Ayaka is `kamisatoayaka`, not her package name `ayaka`."""
    assert "kamisatoayaka" in compile_rotation([_step()], ROSTER)


# ── Refusals ─────────────────────────────────────────────────────────────────


def test_an_empty_rotation_is_refused():
    """gcsim would accept it and simulate someone standing still — a plausible number for a
    question nobody asked."""
    with pytest.raises(RotationCompileError, match="nothing to do"):
        compile_rotation([], ROSTER)


def test_a_stale_step_is_refused_rather_than_dropped():
    """OQ-R2. Dropping it deletes the user's work so a compile can succeed."""
    with pytest.raises(RotationCompileError) as exc:
        compile_rotation([_step(), _step(character="10000030")], ROSTER)

    assert "does not have" in str(exc.value)
    assert "10000030" in str(exc.value)


def test_every_stale_step_is_named_not_just_the_first():
    """A user who removed two characters should learn that once, not go round twice."""
    with pytest.raises(RotationCompileError) as exc:
        compile_rotation(
            [_step(character="10000030"), _step(), _step(character="10000031")], ROSTER,
        )

    message = str(exc.value)
    assert "10000030" in message
    assert "10000031" in message


def test_the_refusal_says_where_the_bad_step_is():
    """Position, because that is how a user finds it in their own list."""
    with pytest.raises(RotationCompileError, match=r"step 2"):
        compile_rotation([_step(), _step(character="10000030")], ROSTER)
