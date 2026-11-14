"""The formula estimate's default rule for kit conditions (owner ruling 2026-11-14,
`DECISIONS.md` §40 (ii)): teammates' buffs and the usual situational self-buffs default on at
their usual values, every one stays a visible toggle, and none is off without a reason.

The rule lives in one place, `sheets.SheetCondition.resolve`; these tests hold it there."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.formula.genshin import sheets


def _condition(slug: str, key: str) -> sheets.SheetCondition:
    sheet = next(s for s in sheets.all_sheets().values() if s.slug == slug)
    return next(c for c in sheet.conditions if c.key == key)


def _all() -> list[tuple[str, sheets.SheetCondition]]:
    return [(s.slug, c) for s in sheets.all_sheets().values() for c in s.conditions]


@pytest.mark.parametrize("subject", [True, False])
def test_every_kit_condition_defaults_by_the_rule_and_says_why_when_it_is_not_its_own(subject):
    """Self-triggered: on at the maximum. A teammate's: on (usual, or the maximum, said). Off
    only with a reason. A curated usual value always carries its reason."""
    for slug, condition in _all():
        c = condition.resolve(giver_is_subject=subject, receiver_element="pyro")
        where = f"{slug}/{condition.key}"
        if condition.usual is not None:
            assert c.default_note, where
            assert c.default_reason in ("usual", "situational"), where
        elif condition.default_by == "self" or subject:
            assert c.default_reason == "self", where
        else:
            assert (c.default_reason, bool(c.default_note)) == ("teammate", True), where
        if c.default_reason == "situational":
            assert c.default in (0, ""), where
            assert c.default_note, where


def test_no_situational_condition_is_off_without_a_reason():
    for slug, condition in _all():
        if condition.default_by == "situational":
            assert condition.usual is not None, f"{slug}/{condition.key}"
            assert condition.usual.reason, f"{slug}/{condition.key}"


def test_a_situational_condition_without_a_usual_value_is_refused():
    c = _condition("bennett", "below_70_hp").model_dump()
    c.pop("usual")
    with pytest.raises(ValidationError, match="names its usual value"):
        sheets.SheetCondition.model_validate(c)


def test_a_usual_value_outside_the_range_is_refused():
    c = _condition("arlecchino", "bond").model_dump()
    c["usual"] = {**c["usual"], "value": 250}
    with pytest.raises(ValidationError, match="outside"):
        sheets.SheetCondition.model_validate(c)


def test_the_named_cases_default_on_at_their_usual_values():
    """The owner's examples (§40 (ii)) and the batches' open questions, resolved by the rule."""
    expect = {
        ("neuvillette", "a1_stacks"): 2,
        ("skirk", "a4_stacks"): 3,
        ("bennett", "in_field"): 1,
        ("zhongli", "shielded"): 1,
        ("clorinde", "a1_stacks"): 3,
        ("arlecchino", "bond"): 130,
        ("alhaitham", "mirrors_consumed"): 0,
    }
    for (slug, key), value in expect.items():
        c = _condition(slug, key).resolve(giver_is_subject=False)
        assert c.default == value, (slug, key)
        assert c.default_note, (slug, key)
    fanfare = _condition("furina", "fanfare")
    assert fanfare.resolve(giver_is_subject=False).default == 300
    assert fanfare.resolve(giver_is_subject=False, raised=100).default == 400


def test_kazuhas_swirl_follows_the_element_of_the_carry_he_buffs():
    pyro = _condition("kaedehara_kazuha", "swirl_pyro")
    on = pyro.resolve(giver_is_subject=False, receiver_element="Pyro")
    off = pyro.resolve(giver_is_subject=False, receiver_element="hydro")
    assert (on.default, on.default_reason) == (1, "usual")
    assert (off.default, off.default_reason) == (0, "situational")
    assert "not Pyro" in (off.default_note or "")
    assert pyro.resolve(giver_is_subject=False).default == 0


def test_sucroses_c6_follows_the_receivers_element_when_it_is_an_option():
    c6 = _condition("sucrose", "c6_absorbed")
    assert c6.resolve(giver_is_subject=False, receiver_element="cryo").default == "cryo"
    dendro = c6.resolve(giver_is_subject=False, receiver_element="dendro")
    assert (dendro.default, dendro.default_reason) == ("", "situational")


def test_a_teammates_buff_with_no_curated_value_is_on_at_its_maximum_and_says_so():
    c = _condition("xianyun", "a1_stacks").resolve(giver_is_subject=False)
    assert (c.default, c.default_reason, c.max) == (4, "teammate", 4)
    assert "no usual value is curated" in (c.default_note or "")
    own = _condition("xianyun", "a1_stacks").resolve(giver_is_subject=True)
    assert (own.default, own.default_reason) == (4, "self")
