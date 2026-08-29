"""Which rows are the training mannequins, and how they are told apart.

The rule is a **body id**, not a name, and that choice is the whole content of this module —
so it is what these tests are about.
"""

from __future__ import annotations

import pytest

from app.services.practice_dummies import DUMMY_BODIES, is_practice_dummy


@pytest.mark.parametrize(
    "nanoka_id",
    ["10000117-2", "10000117-8", "10000118-2", "10000118-8", "10000117", "10000118"],
)
def test_every_mannequin_variant_is_recognised(nanoka_id: str) -> None:
    """Seven elemental variants of each, so fourteen rows — matching the body catches them
    all, including one this repo has not seen."""
    assert is_practice_dummy(nanoka_id)


@pytest.mark.parametrize("nanoka_id", ["10000002", "10000005-2", "10000007-8", "10000034"])
def test_a_real_character_is_not_one(nanoka_id: str) -> None:
    """Including the Traveler, whose ids are the same *shape* — `10000005-2` — and which is
    the row a body-prefix rule is most likely to catch by accident."""
    assert not is_practice_dummy(nanoka_id)


def test_a_body_that_merely_starts_the_same_is_not_one() -> None:
    """**The reason the split is on the dash and not a `startswith`.** `1000011` is a prefix
    of both mannequin bodies, and a prefix match would take any future id beginning with it.
    """
    assert not is_practice_dummy("100001170")
    assert not is_practice_dummy("1000011")


def test_nothing_is_not_a_mannequin() -> None:
    assert not is_practice_dummy(None)
    assert not is_practice_dummy("")


def test_the_rule_names_exactly_two_bodies() -> None:
    """A guard on the constant itself. Growing this set is a decision about what the catalogue
    shows, and it should not happen as a side effect of an edit somewhere else."""
    assert set(DUMMY_BODIES) == {"10000117", "10000118"}
