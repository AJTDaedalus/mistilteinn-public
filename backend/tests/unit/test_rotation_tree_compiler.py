"""Compiling a tree — tasks 5.1 and 5.5.

The gate is that **a rotation that already exists compiles to exactly what it compiled to
before**. Everything else in this phase is downstream of that.
"""
from __future__ import annotations

from app.services.gcsim_parser import parse_rotation
from app.services.rotation_compiler import compile_rotation
from app.services.rotation_tree_compiler import compile_tree, gate_bursts, tree_signature
from app.services.rotation_tree_migration import tree_from_steps


class Character:
    def __init__(self, nanoka_id: str, name: str, element: str) -> None:
        self.nanoka_id, self.name, self.element = nanoka_id, name, element


ROSTER = {
    "1": Character("1", "Noelle", "geo"),
    "2": Character("2", "Xiangling", "pyro"),
}


def step(**over) -> dict:
    base = {"character": "1", "action": "burst", "repeat": 1, "note": "",
            "group": "", "group_repeat": 1, "group_condition": ""}
    return {**base, **over}


def test_a_tree_from_steps_compiles_byte_identically() -> None:
    """**The Phase 4/5 gate.** A saved rotation may not change meaning, and the cheapest proof
    is that its text does not change at all."""
    steps = [
        step(action="attack", repeat=3),
        step(action="skill", character="2"),
        step(group="cycle", group_repeat=2, action="burst"),
        step(group="cycle", group_repeat=2, action="attack"),
    ]

    assert compile_tree(tree_from_steps(steps), ROSTER) == compile_rotation(steps, ROSTER)


def test_a_guarded_group_compiles_byte_identically() -> None:
    steps = [step(group="g", group_condition=".noelle.burst.ready", action="burst")]

    assert compile_tree(tree_from_steps(steps), ROSTER) == compile_rotation(steps, ROSTER)


def test_a_tree_steps_cannot_hold_still_compiles() -> None:
    """An imported rotation with a user function has no `steps` form, and must still run."""
    tree = parse_rotation("fn f() {\n  999;\n}\nnoelle skill;")

    text = compile_tree(tree, ROSTER)

    assert "noelle skill;" in text


# ── burst gating (task 5.5) ──────────────────────────────────────────────────


def test_a_bare_burst_is_gated_on_readiness() -> None:
    """Energy may never arrive and gcsim has no watchdog, so an ungated burst can hang the
    simulation. A cooldown always expires; energy may not."""
    tree = parse_rotation("noelle burst;")

    assert ".noelle.burst.ready" in compile_tree(tree, ROSTER)


def test_the_waiting_model_leaves_the_burst_ungated() -> None:
    tree = parse_rotation("noelle burst;")

    assert ".ready" not in compile_tree(tree, ROSTER, wait_for_energy=True)


def test_a_burst_the_author_already_guarded_is_not_gated_twice() -> None:
    """The author's own guard is their energy model, and re-gating it would nest a second
    condition inside one gcsim already evaluates once."""
    tree = parse_rotation("if .noelle.burst.ready {\n  noelle burst;\n}")

    assert compile_tree(tree, ROSTER).count(".noelle.burst.ready") == 1


def test_a_burst_guarded_on_energy_is_left_alone() -> None:
    tree = parse_rotation("if .noelle.energy >= 60 {\n  noelle burst;\n}")

    assert ".noelle.burst.ready" not in compile_tree(tree, ROSTER)


def test_gating_only_touches_bursts() -> None:
    tree = parse_rotation("noelle skill;\nnoelle attack;")

    assert ".ready" not in compile_tree(gate_bursts(tree, wait_for_energy=False), ROSTER)


# ── the signature (task 5.3) ─────────────────────────────────────────────────


def test_a_tree_signature_matches_the_steps_it_came_from() -> None:
    """A signature and a config that disagree about who a step names is the failure
    `context_key` exists to prevent, so both go through the same code."""
    from app.services.rotation_compiler import rotation_signature

    steps = [step(action="attack", repeat=3), step(action="burst")]

    assert tree_signature(tree_from_steps(steps), ROSTER) == rotation_signature(steps, ROSTER)


def test_a_signature_is_stable_under_reformatting() -> None:
    """Hashing the text would make a comment edit look like a new rotation, so a user tidying
    their config would pay for a fresh gcsim run every time."""
    spaced = parse_rotation("noelle   skill;   # a note\n\n\nnoelle attack;")
    tight = parse_rotation("noelle skill;\nnoelle attack;")

    assert tree_signature(spaced, ROSTER) == tree_signature(tight, ROSTER)


def test_a_signature_changes_when_the_rotation_does() -> None:
    a = parse_rotation("noelle skill;\nnoelle attack;")
    b = parse_rotation("noelle attack;\nnoelle skill;")

    assert tree_signature(a, ROSTER) != tree_signature(b, ROSTER)
