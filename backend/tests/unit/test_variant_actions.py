"""The per-character action vocabulary, and the classification that keeps it honest.

`DESIGN_rotation_builder_gui.md` §3. A hold-E is a different move to a tap-E from the player's
side; gcsim calls it a parameter only because its syntax has parameters. The owner's ruling is
that this model stays **parameterless** and says the difference in the action vocabulary, so
`skill_hold` is an action here and becomes `skill[hold=1]` in the compiler and nowhere else.
"""

from __future__ import annotations

import pytest

from app.services import gcsim_keys


def test_every_declared_parameter_is_classified() -> None:
    """A re-pin cannot introduce a kit variant that silently goes unoffered.

    **This is the whole reason the snapshot captures parameters verbatim rather than filtered.**
    If `build_key_snapshot` only kept the three that are offered, a gcsim release adding a
    fourth would produce a snapshot that simply did not mention it — and the builder would go
    on offering a tap-only skill to a character who had gained a hold, with nothing red
    anywhere. Here it is a failing test naming the parameter.
    """
    declared = gcsim_keys.declared_params()
    classified = set(gcsim_keys.VARIANT_PARAMS) | gcsim_keys.NOT_OFFERED_PARAMS

    unclassified = sorted(declared - classified)

    assert not unclassified, (
        f"gcsim declares parameters this repo has not classified: {unclassified}. Decide "
        f"whether each is a kit variant (a different move — add it to VARIANT_PARAMS) or hit "
        f"geometry, a quantity, or kit minutiae (add it to NOT_OFFERED_PARAMS). Both lists are "
        f"in app/services/gcsim_keys.py and both carry the reasoning."
    )


def test_nothing_is_classified_twice() -> None:
    """The two lists partition, so "is this offered?" has one answer."""
    assert not set(gcsim_keys.VARIANT_PARAMS) & gcsim_keys.NOT_OFFERED_PARAMS


def test_no_classified_parameter_has_gone_away() -> None:
    """A parameter listed here that gcsim no longer declares is a stale entry.

    Not fatal — the builder simply never offers it — but it is the same shape as every stale
    marker this repo has had to sweep, and a list that describes a gcsim that no longer exists
    is one nobody can trust to describe the one that does.
    """
    declared = gcsim_keys.declared_params()
    classified = set(gcsim_keys.VARIANT_PARAMS) | gcsim_keys.NOT_OFFERED_PARAMS

    assert not sorted(classified - declared)


def test_a_character_with_a_hold_skill_is_offered_one() -> None:
    """Chevreuse's `skill[hold=1]:2` is in a real committed config, so it must be authorable."""
    offered = gcsim_keys.offerable_actions("chevreuse")

    assert "skill_hold" in offered
    assert "skill" in offered


def test_a_character_without_one_is_not() -> None:
    """Xingqiu's skill takes no parameters, and offering him a hold would be a lie."""
    assert "skill_hold" not in gcsim_keys.offerable_actions("xingqiu")


def test_short_hold_is_offered_where_hold_alone_would_leave_a_character_out() -> None:
    """Dahlia declares `short_hold` and no `hold`.

    **This is why `VARIANT_PARAMS` has three entries and not one.** The owner's requirement was
    that no kit gets left out to keep the GUI tidy, and offering `hold` alone would have left
    out exactly the characters whose alternate press gcsim spells differently.
    """
    offered = gcsim_keys.offerable_actions("dahlia")

    assert "skill_short_hold" in offered
    assert "skill_hold" not in offered


def test_a_character_gcsim_does_not_implement_gets_the_base_ten() -> None:
    """Not an empty list: they cannot be simulated at all, which is a different problem.

    Offering nothing would suggest the character was the wrong kind of thing rather than one
    this pin has no implementation for, and the compile-time refusal already says that clearly.
    """
    assert gcsim_keys.offerable_actions(None) == gcsim_keys.authorable_actions()


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("skill", ("skill", None)),
        ("skill_hold", ("skill", "hold")),
        ("aim_hold", ("aim", "hold")),
        ("skill_recast", ("skill", "recast")),
        ("high_plunge", ("high_plunge", None)),
    ],
)
def test_split_variant(action: str, expected: tuple[str, str | None]) -> None:
    assert gcsim_keys.split_variant(action) == expected


def test_short_hold_splits_to_short_hold_and_not_to_hold() -> None:
    """`skill_short_hold` ends with `_hold`, and resolving it that way would be wrong.

    The base would come out as `skill_short`, which is not an action, and the emitted config
    would name a parameter the character does not declare. Longest suffix first.
    """
    assert gcsim_keys.split_variant("skill_short_hold") == ("skill", "short_hold")


def test_the_superset_contains_every_characters_variants() -> None:
    """The schema validates against this, so a variant missing from it is unsaveable."""
    superset = set(gcsim_keys.all_offerable_actions())
    for key in gcsim_keys.characters_with_action_params():
        assert set(gcsim_keys.offerable_actions(key)) <= superset, key
