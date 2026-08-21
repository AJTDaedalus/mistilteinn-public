"""Unit tests for the Dimbreath {CAL:} evaluator (cartography toolkit).

Pure-arithmetic; no network. Guards the grammar/eval semantics documented in
docs/MAP_cal_grammar.md so they don't silently drift.
"""

from __future__ import annotations

import pytest

from scripts.dimbreath import cal


def test_parse_standalone():
    c = cal.parse("{CAL:0.08+AvatarSkillLevel(1)*0.01,100,2}%")
    assert c is not None
    assert c.expr == "0.08+AvatarSkillLevel(1)*0.01"
    assert c.scale == 100.0
    assert c.decimals == 2
    assert c.suffix == "%"
    assert c.slots == {1}


def test_parse_embedded_in_description():
    # 41 of 54 formulas live inside longer _Skill_*Desc strings.
    raw = "additional <color=#2BAD00>{CAL:5+AvatarSkillLevel(3)*2.25,100,2}%</color> of AP."
    c = cal.parse(raw)
    assert c is not None
    assert c.scale == 100.0
    assert c.suffix == "%"
    assert c.slots == {3}


def test_parse_non_cal_returns_none():
    assert cal.parse("just a label") is None
    assert cal.parse("45") is None


def test_ratio_scale_100_to_percent():
    # Astra AddedDamageRatio at core level 12 → ratio 0.20 ×100 = 20%.
    c = cal.parse("{CAL:0.08+AvatarSkillLevel(1)*0.01,100,2}%")
    assert cal.evaluate(c, {1: 12}) == 20.0
    assert cal.render(c, {1: 12}) == "20%"


def test_flat_scale_1():
    # Astra ExQTE HP recover, slot 3 level 12: -50 + 12*250 = 2950 (flat).
    c = cal.parse("{CAL:-50+AvatarSkillLevel(3)*250,1,2}")
    assert cal.evaluate(c, {3: 12}) == 2950.0
    assert cal.render(c, {3: 12}) == "2950"


def test_large_ap_multiplier():
    # Yanagi Polarity-Disorder % of AP, slot 1 level 1: (5+2.25)*100 = 725%.
    c = cal.parse("{CAL:5+AvatarSkillLevel(1)*2.25,100,2}%")
    assert cal.evaluate(c, {1: 1}) == 725.0
    assert cal.render(c, {1: 1}) == "725%"


def test_missing_slot_is_explicit():
    c = cal.parse("{CAL:0.08+AvatarSkillLevel(1)*0.01,100,2}%")
    with pytest.raises(KeyError):
        cal.evaluate(c, {})


def test_safe_eval_rejects_arbitrary_code():
    # The arithmetic evaluator must not execute names/calls beyond the substituted
    # AvatarSkillLevel(...) (which is regex-replaced before eval).
    c = cal.parse("{CAL:__import__('os'),1,0}")
    # parse captures it, but evaluation of a non-arithmetic node must raise.
    with pytest.raises((ValueError, KeyError, SyntaxError)):
        cal.evaluate(c, {})
