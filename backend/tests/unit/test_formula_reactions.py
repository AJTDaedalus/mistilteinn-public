"""Math-fallback P3 (task 13): the reaction vocabulary and its GO fixtures.

The fixtures themselves are `go_fixtures_reactions.py`, committed to `go_fixtures.json` by
`test_go_formula_fixtures.build()` and replayed by `npm run formula:verify`. These tests hold
what the fixtures cannot say by themselves: the one recorded divergence and nothing else, the
effect vocabulary's refusals, and the set and sheet parts P3 wired.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.formula.genshin import sheets
from app.formula.genshin.formula_effects import (
    ADDITIVE_REACTIONS,
    CRITTABLE_REACTIONS,
    LUNAR_REACTIONS,
    TRANSFORMATIVE_REACTIONS,
    Effect,
)
from app.formula.genshin.reactions import ADDITIVE, LUNAR, TRANSFORMATIVE
from tests.unit import go_fixtures_reactions as fx
from tests.unit import test_go_formula_fixtures as base


def _fixtures() -> dict[str, dict]:
    data = json.loads(base.FIXTURE.read_text(encoding="utf-8"))
    names = {f["name"] for f in fx.reaction_fixtures()}
    return {f["name"]: f for f in data["fixtures"] if f["name"] in names}


def test_the_vocabulary_names_exactly_the_reactions_the_chain_prices():
    assert set(TRANSFORMATIVE_REACTIONS) == {str(r) for r in TRANSFORMATIVE}
    assert set(ADDITIVE_REACTIONS) == {str(r) for r in ADDITIVE}
    assert set(LUNAR_REACTIONS) == {str(r) for r in LUNAR}
    assert set(CRITTABLE_REACTIONS) == {str(r) for r, s in TRANSFORMATIVE.items() if s.crittable}


def test_every_reaction_family_has_a_fixture():
    rows = [r for f in _fixtures().values() for r in f["rows"]]
    priced = {r["reaction"]["reaction"] for r in rows if r.get("reaction")}
    priced |= {r["additive"] for r in rows if r.get("additive")}
    assert {"hyperbloom", "swirl", "burgeon", "burning", "overloaded", "bloom", "superconduct",
            "lunar_charged", "lunar_crystallize", "spread", "aggravate"} <= priced


def test_the_only_divergence_is_gos_transformative_def_term():
    """GO's `enemy.transDef` (`formula.ts:502-509`) against gcsim's ignored DEF: exactly
    `1 - transDef` on every reaction-instance fixture, 0 on an additive one."""
    gap = 1 - fx.GO_TRANS_DEF
    for name, fixture in _fixtures().items():
        has_instance = any(r.get("reaction") for r in fixture["rows"])
        expected_gap = gap / fx.GO_TRANS_DEF if has_instance else 0.0
        got = fixture["relative_divergence_from_go"]
        assert got == pytest.approx(expected_gap, abs=1e-12), name


def test_the_hand_figures_would_catch_a_missing_part():
    """Guards the guard: each part a fixture checks moves its figure by far more than f32."""
    with_crit = fx._hyperbloom(1.0)
    em = base._stats(fx.b8.FISCHL_BASE, fx.FISCHL_ARTIFACTS)["elemental_mastery"] + 220.0
    without_crit = 3 * fx._trans(3.0, em, 0.4, trans_def=1.0)
    assert with_crit / without_crit == pytest.approx(1.2)
    # The VV shred reaches the Pyro swirls only: shredding the Hydro one too would be 15% more.
    swirl = fx._swirl(1.0)
    kazuha_em = base._stats(base.KAZUHA_BASE, base.KAZUHA_ARTIFACTS)["elemental_mastery"]
    all_shredded = 3 * fx._trans(0.6, kazuha_em, 0.6, trans_def=1.0, res=-0.3)
    assert all_shredded > swirl * 1.04


@pytest.mark.parametrize(("effect", "message"), [
    ({"stat": "reaction_crit_rate", "value": 0.2, "reactions": ["overloaded"]}, "can crit"),
    ({"stat": "lunar_base_dmg_bonus", "value": 0.2, "reactions": ["swirl"]}, "Lunar"),
    ({"stat": "reaction_bonus", "value": 0.2, "reactions": ["lunar_bloom"]}, "names reactions"),
    ({"stat": "reaction_bonus", "value": 0.2}, "names reactions"),
    ({"stat": "dmg_bonus", "value": 0.2, "reactions": ["swirl"]}, "reaction-scoped"),
])
def test_the_vocabulary_refuses_what_no_reaction_can_take(effect: dict, message: str):
    with pytest.raises(ValidationError, match=message):
        Effect(**effect)


def test_baizhus_a4_counts_his_hp_to_50000_only():
    """GO `min((maxHp / 1000) × r, prod(r, final.hp, 1 / 1000))` (`pando Baizhu.ts:118-137`)."""
    sheet = sheets.sheet_for("10000082")
    assert sheet is not None
    values = {}
    for hp in (45000.0, 60000.0):
        giver = fx.b6._giver("Baizhu", "10000082", 0, {"base_hp": hp, "hp_pct": 0.0,
                                                         "flat_hp": 0.0})
        kit = sheets.resolve(sheet, giver, giver_is_subject=False, receiver_element="dendro",
                             team_elements=["dendro"])
        values[hp] = {e.reactions: e.value for e in kit.bonus.effects
                      if e.stat == "reaction_bonus"}
    bloom = ("burning", "bloom", "hyperbloom", "burgeon")
    assert values[45000.0][bloom] == pytest.approx(0.02 * 45)
    assert values[60000.0][bloom] == pytest.approx(0.02 * 50)
    assert values[60000.0][("spread", "aggravate")] == pytest.approx(0.008 * 50)


def test_baizhus_a4_on_himself_is_withheld_by_name():
    """His HP moves with every candidate; a reaction bonus from it is not a conversion the
    recipe carries, so it is named rather than frozen at his equipped build."""
    sheet = sheets.sheet_for("10000082")
    assert sheet is not None
    giver = fx.b6._giver("Baizhu", "10000082", 0, {"base_hp": 15000.0, "hp_pct": 0.0,
                                                     "flat_hp": 30000.0})
    kit = sheets.resolve(sheet, giver, giver_is_subject=True, receiver_element="dendro",
                         team_elements=["dendro"])
    assert not [e for e in kit.bonus.effects if e.stat == "reaction_bonus"]
    assert any("All Things Are of the Earth: party" in u.what for u in kit.bonus.unmodelled)
