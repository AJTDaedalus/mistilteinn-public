"""A context key must follow the *content* of a run, not the rows it was assembled from.

Reported by the owner, twice: editing a rotation in place and swapping a team member left
the optimizer serving the previous answer instantly. Both edits keep the same `rotation.id`
and the same `team.id`, so anything keyed on those ids cannot tell the two runs apart.

These are the two edits that were actually made, not hypothetical ones.
"""

from app.services.sim_context import context_key

BASE = {
    "character_key": "skirk",
    "weapon_key": "azurelight",
    "character_level": 90,
    "constellation": 0,
    "weapon_level": 90,
    "refinement": 1,
    "talent_levels": {"attack": 9, "skill": 9, "burst": 9},
    "rotation": ["skirk skill", "skirk attack", "skirk burst"],
    "target": {"level": 100, "resist": 0.1},
    "gcsim_pin": "p" * 40,
    "team": ["skirk", "citlali", "yelan", "furina"],
}


def _key(**overrides: object) -> str:
    return context_key(**{**BASE, **overrides})  # type: ignore[arg-type]


def test_editing_a_rotations_steps_is_a_different_run() -> None:
    """The owner's rotation grew about tenfold and scored identically. It must not."""
    longer = BASE["rotation"] * 10  # type: ignore[operator]
    assert _key(rotation=longer) != _key()


def test_reordering_a_rotation_is_a_different_run() -> None:
    """A rotation is a sequence: the same actions in another order are another rotation."""
    reversed_steps = list(reversed(BASE["rotation"]))  # type: ignore[call-overload]
    assert _key(rotation=reversed_steps) != _key()


def test_swapping_a_team_member_is_a_different_run() -> None:
    """Same team row, same team name, one member replaced."""
    assert _key(team=["skirk", "citlali", "yelan", "escoffier"]) != _key()


def test_listing_the_same_team_in_another_order_is_the_same_run() -> None:
    """The one ordering deliberately discarded -- a team is a set, so this must still hit."""
    assert _key(team=["furina", "yelan", "citlali", "skirk"]) == _key()
