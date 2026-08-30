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
from app.services.rotation_compiler import (
    RotationCompileError,
    compile_rotation,
    rotation_signature,
    unroll,
)

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


# ── Kit variants: the parameter exists here and nowhere else ─────────────────


def test_a_variant_action_becomes_a_gcsim_parameter():
    """`skill_hold` is a *move* in this model and `skill[hold=1]` in gcsim's syntax.

    The form is not invented: `references/gcsim_db/clorinde-chevreuse-nicole-durin.txt:48`
    carries `chev burst, skill[hold=1]:2;` — a real community config.
    """
    out = compile_rotation([_step(action="skill_hold")], ROSTER)

    assert "kamisatoayaka skill[hold=1];" in out


def test_the_gate_names_the_base_action_not_the_variant():
    """There is no `.skill_hold.ready` in gcsim, and a hold shares the tap's cooldown.

    Gating on the variant would emit a condition gcsim's parser does not know — which fails
    loudly, but only once someone simulates. This keeps it impossible.
    """
    out = compile_rotation([_step(action="skill_hold")], ROSTER)

    assert "if .kamisatoayaka.skill.ready {" in out
    assert "skill_hold.ready" not in out


def test_a_variant_still_takes_gcsims_repetition():
    out = compile_rotation([_step(action="skill_hold", repeat=2)], ROSTER)

    assert "kamisatoayaka skill[hold=1]:2;" in out


def test_short_hold_renders_its_own_parameter():
    """Not `hold=1`. Dahlia's press is a different parameter and gcsim would refuse `hold`."""
    out = compile_rotation([_step(action="skill_short_hold")], ROSTER)

    assert "skill[short_hold=1]" in out


# ── Groups: unrolled before anything downstream sees them ────────────────────


def test_a_group_repeats_its_steps_in_place():
    """`DECISIONS.md` §27. The chunk repeats where it stands, in order."""
    steps = [
        {"character": "10000002", "action": "skill", "group": "g", "group_repeat": 3},
        {"character": "10000002", "action": "burst", "group": "g", "group_repeat": 3},
    ]

    out = compile_rotation(steps, ROSTER)

    assert out.count("kamisatoayaka skill;") == 3
    assert out.count("kamisatoayaka burst;") == 3


def test_a_grouped_rotation_compiles_identically_to_its_unrolled_equal():
    """The acceptance criterion for T.7b, and the reason a group costs no grammar.

    gcsim receives character-for-character what it received before groups existed — so nothing
    downstream of the compiler has to know groups exist at all.
    """
    grouped = [
        {"character": "10000002", "action": "skill", "group": "g", "group_repeat": 2},
        {"character": "10000014", "action": "burst", "group": "g", "group_repeat": 2},
        {"character": "10000002", "action": "attack", "repeat": 3},
    ]
    flat = [
        {"character": "10000002", "action": "skill"},
        {"character": "10000014", "action": "burst"},
        {"character": "10000002", "action": "skill"},
        {"character": "10000014", "action": "burst"},
        {"character": "10000002", "action": "attack", "repeat": 3},
    ]

    assert compile_rotation(grouped, ROSTER) == compile_rotation(flat, ROSTER)


def test_a_grouped_rotation_signs_identically_to_its_unrolled_equal():
    """Same rotation, same `context_key`, one cached run.

    The unroll sits in front of **both** `compile_rotation` and `rotation_signature` for
    exactly this: the key describes what gcsim ran, and two keys for one config would mean a
    rotation missing a cache entry computed from itself.
    """
    grouped = [
        {"character": "10000002", "action": "skill", "group": "g", "group_repeat": 2},
    ]
    flat = [
        {"character": "10000002", "action": "skill"},
        {"character": "10000002", "action": "skill"},
    ]

    assert rotation_signature(grouped, ROSTER) == rotation_signature(flat, ROSTER)


def test_an_ungrouped_rotation_unrolls_to_itself():
    """Every rotation authored before groups existed still compiles to what it always did."""
    steps = [_step(), _step(action="skill"), _step(character="10000014", action="attack")]

    assert unroll(steps) == steps


def test_the_first_actor_is_read_after_unrolling():
    """`active` names step one, and step one of a grouped rotation is inside the group.

    Reading it before the unroll would work by accident here and break the moment a group
    started the rotation with a different character than the flat list did.
    """
    steps = [
        {"character": "10000014", "action": "skill", "group": "g", "group_repeat": 2},
        {"character": "10000002", "action": "burst"},
    ]

    assert compile_rotation(steps, ROSTER).startswith("active barbara;")


def test_a_group_cannot_route_around_the_repeat_cap():
    """`MAX_STEPS` and `MAX_REPEAT` are checked on the authored list; `unroll` runs after.

    200 steps each in a group repeating 20 times is 4,000 gated statements, every one of which
    may itself carry `:20`. `MAX_REPEAT` exists "so a typo cannot compile to a config that runs
    for an hour", and groups walked straight around it.
    """
    steps = [
        {"character": "10000002", "action": "attack", "group": "g", "group_repeat": 20}
        for _ in range(200)
    ]

    with pytest.raises(RotationCompileError) as raised:
        compile_rotation(steps, ROSTER)

    assert "4000" in str(raised.value)


def test_a_rotation_inside_the_cap_still_compiles():
    """The bound is generous on purpose: no rotation anyone writes should meet it."""
    steps = [
        {"character": "10000002", "action": "attack", "group": "g", "group_repeat": 20}
        for _ in range(10)
    ]

    assert compile_rotation(steps, ROSTER).count("kamisatoayaka attack;") == 200
