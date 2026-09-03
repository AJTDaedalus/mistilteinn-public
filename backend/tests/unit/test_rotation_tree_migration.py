"""`steps` into a tree — task 4.2, and the losslessness its gate depends on.

The Phase 4 gate is that **no saved rotation changes meaning**. This file proves the
conversion keeps every step, its order, its repeat, its note, its group nesting, its group
repeat and its group condition; Phase 5's gate then proves the compiler agrees.
"""
from __future__ import annotations

import pytest

from app.schemas.rotation_nodes import ActionNode, BranchNode, LoopNode
from app.services.rotation_tree_migration import steps_from_tree, tree_from_steps


def step(**over) -> dict:
    base = {
        "character": "10000042", "action": "burst", "repeat": 1, "note": "",
        "group": "", "group_repeat": 1, "group_condition": "",
    }
    return {**base, **over}


def test_a_flat_rotation_becomes_flat_action_nodes() -> None:
    tree = tree_from_steps([step(), step(action="skill")])

    assert [n.action for n in tree.nodes] == ["burst", "skill"]
    assert all(isinstance(n, ActionNode) for n in tree.nodes)


def test_a_note_and_a_repeat_survive() -> None:
    node = tree_from_steps([step(repeat=3, note="opener")]).nodes[0]

    assert (node.repeat, node.note) == (3, "opener")


def test_a_group_with_a_repeat_becomes_a_counted_loop() -> None:
    tree = tree_from_steps([
        step(group="cycle", group_repeat=4),
        step(group="cycle", group_repeat=4, action="skill"),
    ])

    assert isinstance(tree.nodes[0], LoopNode)
    assert tree.nodes[0].bound.value == 4
    assert len(tree.nodes[0].body) == 2


def test_a_group_with_a_condition_becomes_a_branch() -> None:
    tree = tree_from_steps([
        step(group="flame", group_condition=".flins.status.manifest-flame"),
    ])

    assert isinstance(tree.nodes[0], BranchNode)
    assert len(tree.nodes[0].arms) == 1
    assert tree.nodes[0].otherwise is None


def test_a_nested_group_path_nests() -> None:
    """`"flame/energy"` is two blocks, and the inner one is inside the outer."""
    tree = tree_from_steps([
        step(group="flame", group_condition=".flins.status.manifest-flame", action="skill"),
        step(group="flame/energy", group_condition=".flins.energy >= 30"),
    ])

    outer = tree.nodes[0]
    assert isinstance(outer, BranchNode)
    inner = outer.arms[0][1][1]
    assert isinstance(inner, BranchNode)


def test_a_group_that_both_repeats_and_guards_keeps_both() -> None:
    tree = tree_from_steps([
        step(group="g", group_repeat=3, group_condition=".x.burst.ready"),
    ])

    branch = tree.nodes[0]
    assert isinstance(branch, BranchNode)
    assert isinstance(branch.arms[0][1][0], LoopNode)


def test_two_separate_groups_do_not_merge() -> None:
    """Consecutive steps with the *same* group name but broken by an ungrouped step are two
    blocks, not one — merging them would reorder the rotation."""
    tree = tree_from_steps([
        step(group="g", group_repeat=2),
        step(),
        step(group="g", group_repeat=2),
    ])

    assert [n.kind for n in tree.nodes] == ["loop", "action", "loop"]


def test_the_conversion_round_trips_back_to_the_same_steps() -> None:
    """**The losslessness the Phase 4 gate rests on.**"""
    steps = [
        step(action="attack", repeat=2, note="opener"),
        step(group="g", group_repeat=3, action="skill"),
        step(group="g", group_repeat=3, action="burst"),
        step(group="h", group_condition=".x.burst.ready", action="dash"),
        step(action="charge"),
    ]

    assert steps_from_tree(tree_from_steps(steps)) == steps


def test_an_imported_tree_keeps_its_loop_count_through_steps() -> None:
    """**Found by the corpus, and it was silent.** A parsed tree's blocks have no label, so
    its steps came back with `group=""` — and `group` is what carries a repeat, so the loop
    count vanished and a six-cycle rotation became a one-pass one. 69 of 69 convertible
    corpus configs, and every synthetic test here missed it because their blocks were built
    from steps that already had names."""
    from app.services.gcsim_parser import parse_rotation

    tree = parse_rotation("for let i=0; i<6; i=i+1 {\n  a skill;\n}")
    steps = steps_from_tree(tree)

    assert steps[0]["group"]
    assert steps[0]["group_repeat"] == 6
    assert steps_from_tree(tree_from_steps(steps)) == steps


def test_a_nesting_steps_cannot_express_is_refused_rather_than_mangled() -> None:
    """A step records only the innermost condition it is under, so a branch nested inside a
    loop can come back with its guard applied to steps that were never inside it. The
    conversion checks itself and refuses, which is the same contract as a node kind `steps`
    has no field for."""
    from app.services.gcsim_parser import parse_rotation

    # The block's **first** member is the one inside the nested branch, so reading the
    # level's condition off it would put `!i` on the whole loop.
    tree = parse_rotation(
        "for let i=0; i<3; i=i+1 {\n  if !i {\n    a burst;\n  }\n  a skill;\n}",
    )

    with pytest.raises(ValueError, match="tree"):
        steps_from_tree(tree)


class _Stored:
    """The two columns `tree_for` reads, and nothing else."""

    def __init__(self, steps: list | None = None, tree: dict | None = None) -> None:
        self.steps, self.tree = steps, tree


def test_the_read_path_prefers_a_stored_tree() -> None:
    from app.services.rotation_tree_migration import tree_for

    stored = tree_from_steps([step(action="burst")]).model_dump(mode="json")
    row = _Stored(steps=[step(action="skill")], tree=stored)

    assert tree_for(row).nodes[0].action == "burst"


def test_the_read_path_falls_back_to_steps() -> None:
    """What makes the column nullable and the rollout uncoordinated: a row written before it
    existed, or one whose backfill was refused, is converted on the way out instead."""
    from app.services.rotation_tree_migration import tree_for

    assert tree_for(_Stored(steps=[step(action="skill")])).nodes[0].action == "skill"
