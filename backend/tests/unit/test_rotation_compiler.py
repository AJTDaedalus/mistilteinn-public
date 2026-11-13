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


# ── What replaced the loop and the gates (2026-09-01) ────────────────────────
#
# Owner ruling: *"The optimizer should run through the rotation as defined to completion,
# regardless of how short/long it is, and score ER appropriately."*
#
# The two failures the loop and the gates answered are still real, and the module docstring
# keeps the argument. They are answered differently now: `unroll` already expands the
# rotation's own repeats, so "a bare list runs once" is the ask rather than the bug; and the
# deadlock belonged to `while 1`, which a finite list cannot reproduce.


def test_the_rotation_is_emitted_as_written_with_no_loop_wrapper():
    """The list *is* the rotation, so wrapping it would repeat what the user already sized.

    `while 1` made the rotation's length irrelevant and handed the decision to `duration=90` —
    a constant nobody chose, which is what every damage figure was then divided by.
    """
    out = compile_rotation([_step()], ROSTER)

    assert "while 1" not in out
    assert out == (
        "active kamisatoayaka;\n"
        "if .kamisatoayaka.burst.ready { kamisatoayaka burst; }\n"
    )


def test_a_group_repeat_is_what_makes_the_rotation_long():
    """Length comes from the rotation's own definition, never from this file.

    An opener plus a core loop is exactly the shape of a real gcsim database config, and it is
    expressible here because `unroll` runs in front of the emitter.
    """
    opener = {"character": "10000002", "action": "burst", "repeat": 1}
    core = [
        {"character": "10000002", "action": "skill", "repeat": 1,
         "group": "loop", "group_repeat": 4},
        {"character": "10000002", "action": "attack", "repeat": 2,
         "group": "loop", "group_repeat": 4},
    ]

    out = compile_rotation([opener, *core], ROSTER)

    assert out.count("kamisatoayaka skill;") == 4
    assert out.count("kamisatoayaka attack:2;") == 4
    assert out.count("kamisatoayaka burst;") == 1


def test_only_a_burst_carries_a_readiness_gate():
    """The gate is about what a wait is waiting *for*, not about caution.

    A cooldown always expires, so waiting on one is safe and models a player. Energy may never
    arrive: a burst nobody can fund blocks the simulation, so nothing later runs, so no
    particles drop, so the energy never comes. gcsim has no watchdog for that — it retries the
    frame forever and grows a per-frame stats slice until the kernel kills it (2.4 GB, measured
    2026-09-01 on the owner's own rotation, at `escoffier burst` in the fourth cycle).

    So the burst is gated and nothing else is. Gating everything was the older mistake: it
    turned every cooldown wait into a silent skip.
    """
    out = compile_rotation(
        [_step(action="burst"), _step(action="skill"), _step(action="attack")], ROSTER,
    )

    assert out.count("if .") == 1
    assert "if .kamisatoayaka.burst.ready { kamisatoayaka burst; }" in out
    assert "kamisatoayaka skill;" in out
    assert "kamisatoayaka attack;" in out


def test_a_gated_burst_still_hides_insufficient_energy_so_bursts_are_counted_instead():
    """Recorded because the gate has a real cost and the cost has a named replacement.

    gcsim populates `insufficient_energy` only for an action it **attempted** and could not pay
    for. A gated burst is never attempted, so that field reads 0 for a team plainly starved.
    The observable signal is the **burst count**: a burst that did not fire is a burst that is
    not in the log, and unlike `insufficient_energy` it cannot be confused with a rotation that
    never asked for one.
    """
    starved = compile_rotation([_step(action="burst")], ROSTER)

    assert ".burst.ready" in starved

def test_repeat_uses_gcsims_own_colon_syntax():
    out = compile_rotation([_step(action="attack", repeat=3)], ROSTER)

    assert "kamisatoayaka attack:3;" in out


def test_a_single_repeat_omits_the_colon():
    """`attack:1` is legal and noisy; the plain form is what a human writes."""
    out = compile_rotation([_step(action="attack", repeat=1)], ROSTER)

    assert "kamisatoayaka attack;" in out
    assert "attack:1" not in out


def test_no_swap_actions_are_emitted():
    """`run.go:248`: the evaluator inserts swaps when the next character is not active.

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
    # The model's word for the action never reaches gcsim, which has no `skill_hold`. This used
    # to be guarded by the gate test as well; the gate is gone and the mapping is not.
    assert "skill_hold" not in out


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


def test_waiting_leaves_the_burst_ungated_and_skipping_gates_it() -> None:
    """**The gate is the whole difference between the two models.**

    Gated, gcsim skips a burst nobody can pay for and the rotation carries on. Ungated it
    *waits*, holding the entire simulation until the energy arrives — which is what a person at
    a keyboard does, and what the owner's *"without the ER% she doesn't burst on time"*
    describes.

    Measured on their own team and rotation: the two models price Energy Recharge **+7.3 %
    against +44.4 %** from her real gear to 1.6, and under waiting her real gear costs **50
    seconds of delay** on a 101-second rotation. `DESIGN_waiting_for_energy.md`.
    """
    steps = [_step(action="burst"), _step(action="attack")]

    skipping = compile_rotation(steps, ROSTER)
    waiting = compile_rotation(steps, ROSTER, wait_for_energy=True)

    assert "if .kamisatoayaka.burst.ready { kamisatoayaka burst; }" in skipping
    assert "if ." not in waiting
    assert "kamisatoayaka burst;" in waiting
    # Everything else is identical: one switch, not two emitters.
    assert skipping.replace("if .kamisatoayaka.burst.ready { ", "").replace(" }", "") == waiting
