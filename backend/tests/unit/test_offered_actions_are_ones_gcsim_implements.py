"""A character is offered the moves gcsim implements for them, and no others.

Found by driving, not by reading: authoring a rotation for each newly simulatable character
and running it produced

    error encountered on iansan executing aim: iansan: action aimed not implemented

Every character was offered all ten base actions. `aim` exists for bow users, plunges exist
for some characters and not others, and Ganyu has no `charge` at all — her charged attack
**is** the aimed shot. So a user could pick a move from the builder, have it validate, and
watch the run die minutes later inside somebody else's engine.

The table is captured from gcsim's source and **checked against gcsim itself** by
`scripts/gcsim/probe_implemented_actions.py`, over every character/action pair. That probe is
what found the four Traveler plunges gcsim refuses at run time from inside a method that
exists (`traveler/common/cryo/plunge.go:67`), which no parse of the source can see.
"""

from __future__ import annotations

import pytest

from app.services.gcsim_keys import (
    authorable_actions,
    character_key,
    characters_with_action_params,
    implemented_actions,
    offerable_actions,
    split_variant,
)


def test_a_polearm_user_is_not_offered_an_aimed_shot():
    """The case that was live: Iansan, offered `aim`, refused by gcsim at run time."""
    assert "aim" not in offerable_actions("iansan")
    assert "aim" in authorable_actions(), "still a real action — just not hers"


def test_a_bow_user_is_offered_an_aimed_shot_and_no_charged_attack():
    """Ganyu's charged attack *is* the aimed shot, so gcsim implements no `charge` for her.

    This is why the filter cannot be "bows get aim, everyone else gets charge": the two are
    not complementary, and the only authority is what her package implements.
    """
    offered = offerable_actions("ganyu")

    assert "aim" in offered
    assert "charge" not in offered


def test_plunges_are_offered_to_whoever_has_them():
    """Ayaka plunges; Iansan does not. Same weapon class is not the question."""
    assert "high_plunge" in offerable_actions("kamisatoayaka")
    assert "high_plunge" not in offerable_actions("iansan")


def test_the_aether_travelers_gcsim_refuses_at_runtime_are_not_offered():
    """`if c.gender == 0 { … "not implemented" }`, inside a method that exists.

    Lumine runs the same method and plunges fine. A parse of the source says both have it;
    only running gcsim says otherwise, which is the whole argument for the probe.
    """
    assert "low_plunge" not in offerable_actions("aethercryo")
    assert "low_plunge" in offerable_actions("luminecryo")


@pytest.mark.parametrize("key", characters_with_action_params())
def test_every_offered_action_is_implemented_for_that_character(key: str):
    """The invariant, over the whole roster rather than over the examples above."""
    implemented = implemented_actions(key)
    for action in offerable_actions(key):
        base, _variant = split_variant(action)
        assert base in implemented, f"{key} is offered {action}, which gcsim does not implement"


def test_a_character_gcsim_cannot_run_is_still_offered_everything():
    """The deliberate exception: report the real problem, not a derived one.

    A character with no gcsim key cannot be simulated at all. Narrowing their action list
    would answer a question nobody asked — the rotation fails because gcsim has never heard
    of them, and that is what the message should say.
    """
    assert offerable_actions(None) == authorable_actions()


def test_the_roster_did_not_quietly_lose_its_moves():
    """A filter that emptied every list would pass every test above.

    Each assertion so far says an action is *absent*; this one holds the other direction, so
    a capture that broke and returned nothing fails here rather than silently offering a
    builder with three actions in it.
    """
    keys = characters_with_action_params()
    full = [k for k in keys if len(offerable_actions(k)) >= 6]

    assert len(full) > len(keys) * 0.9, (
        f"only {len(full)} of {len(keys)} characters are offered a usable set of actions"
    )


def test_a_traveler_resolves_through_its_element():
    """The path a Traveler actually takes into this lookup, end to end."""
    key = character_key("10000007-5", "Traveler", "Cryo")

    assert key == "luminecryo"
    assert "skill" in offerable_actions(key)
