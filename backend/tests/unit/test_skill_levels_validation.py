"""`skill_levels` validation (#156, spun out of #153).

The field was a free-form string with no validation of any kind: shape, range, or
relationship to mindscape. That is not hypothetical laxity — the live DB contains
two builds that are **internally self-contradicting** because of it:

    Anby    mindscape_level=0  skill_levels="13,11,13,11,4"   # 13 needs M3+
    Nicole  mindscape_level=0  skill_levels="13,11,14,15,6"   # 15 needs M5+

Both are really M6 per the scanner, so their skill levels are right and their
mindscape is stale. A validator would have made that loud the day it appeared,
instead of leaving it to be found by an audit reasoning about damage.

The legal maximum is `12 + mindscape bonus` — the game caps skills at 12 at L60
(ZO `consts/src/common.ts:279-287`), and M3 adds +2, M5 another +2. `skill_levels`
stores the **effective** level, mindscape bonus included (established in #153 from
a real scanner export), which is what makes the bound checkable at all.
"""

import pytest
from pydantic import ValidationError

from app.schemas.build import BuildCreate, BuildUpdate

_AGENT = "019ef07b-44f2-7a42-b152-11f774c72704"


def _create(**kw):
    return BuildCreate(agent_id=_AGENT, **kw)


# --- shape and range, checkable without knowing the mindscape -------------------


@pytest.mark.parametrize(
    "bad",
    [
        "12,12,12,12",  # four entries
        "12,12,12,12,12,12",  # six
        "",  # empty
        "12,12,x,12,12",  # non-numeric
        "12,12,,12,12",  # empty field
    ],
)
def test_malformed_skill_levels_are_rejected(bad):
    with pytest.raises(ValidationError):
        _create(skill_levels=bad)


@pytest.mark.parametrize(
    "bad",
    ["51,12,12,12,12", "12,12,12,12,99", "0,12,12,12,12", "-1,12,12,12,12"],
)
def test_out_of_range_skill_levels_are_rejected(bad):
    """A typo'd 51 was previously indistinguishable from a legitimate 15."""
    with pytest.raises(ValidationError):
        _create(skill_levels=bad)


def test_the_default_is_valid():
    assert _create().skill_levels == "12,12,12,12,12"


# --- the mindscape relationship, where both fields are present ------------------


def test_skill_above_12_requires_m3():
    with pytest.raises(ValidationError, match="mindscape"):
        _create(mindscape_level=0, skill_levels="13,11,13,11,4")


def test_skill_above_14_requires_m5():
    with pytest.raises(ValidationError, match="mindscape"):
        _create(mindscape_level=3, skill_levels="15,11,12,11,6")


@pytest.mark.parametrize(
    ("mc", "levels"),
    [
        (0, "12,12,12,12,12"),
        (3, "14,12,12,12,12"),
        (4, "14,14,14,14,6"),
        (5, "16,16,16,16,6"),
        (6, "15,8,15,15,5"),  # Anton's real build
    ],
)
def test_levels_within_the_mindscape_allowance_are_accepted(mc, levels):
    assert _create(mindscape_level=mc, skill_levels=levels).mindscape_level == mc


def test_anbys_real_m6_build_is_valid_once_the_mindscape_is_right():
    """The same skill levels that are illegal at M0 are fine at her true M6 —
    the validator points at the stale field, not at the correct one."""
    assert _create(mindscape_level=6, skill_levels="13,11,13,11,4")


# --- partial updates ------------------------------------------------------------


def test_update_validates_shape_even_without_a_mindscape():
    with pytest.raises(ValidationError):
        BuildUpdate(skill_levels="12,12,12")


def test_update_cross_checks_when_both_fields_are_supplied():
    with pytest.raises(ValidationError, match="mindscape"):
        BuildUpdate(mindscape_level=0, skill_levels="15,12,12,12,12")


def test_update_with_skill_levels_alone_cannot_cross_check():
    """Documented gap: a PATCH carrying only `skill_levels` has no mindscape to
    check against — the persisted row is not visible here. Shape and the absolute
    ceiling still apply, so the value cannot be nonsense, only optimistic."""
    assert BuildUpdate(skill_levels="16,16,16,16,6").skill_levels == "16,16,16,16,6"
