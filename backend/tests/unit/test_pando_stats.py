"""Tests for the stats DAG — parity with stat_calculator.compute_total_stats.

The DAG formulas in :mod:`app.formula.zzz.stats` aggregate base stats +
disc stats + resolved buff contributions into the TotalStats shape. This
test drives them with the same ``StatInputs`` the procedural path uses
and asserts they produce the same numbers.

Structure:
* ``_register_inputs`` populates a registry from a ``StatInputs`` dataclass
* Each test computes the DAG-derived stat and compares to the procedural
  value from :func:`compute_total_stats`.
"""

from __future__ import annotations

from math import floor

from app.formula.zzz.stats import (
    Q_ATK_NODE,
    Q_CRIT_DMG_NODE,
    Q_CRIT_RATE_NODE,
    Q_DEF_NODE,
    Q_HP_NODE,
    elemental_dmg_node,
    register_base_stats,
)
from app.pando.calculator import Calculator, NodeRegistry
from app.services.stat_calculator import StatInputs, compute_total_stats


def _build(inputs: StatInputs) -> Calculator:
    reg = NodeRegistry()
    register_base_stats(reg, inputs)
    return Calculator(reg)


class TestATK:
    def test_base_only(self) -> None:
        inputs = StatInputs(agent_base_atk=600, wengine_base_atk=400)
        expected = compute_total_stats(inputs).atk
        assert floor(_build(inputs).compute(Q_ATK_NODE)) == expected

    def test_with_pct_and_flat(self) -> None:
        inputs = StatInputs(
            agent_base_atk=600,
            wengine_base_atk=400,
            atk_pct=3000,
            flat_atk=200,
        )
        expected = compute_total_stats(inputs).atk
        assert floor(_build(inputs).compute(Q_ATK_NODE)) == expected

    def test_full_formula_with_final_multipliers(self) -> None:
        inputs = StatInputs(
            agent_base_atk=600,
            wengine_base_atk=400,
            atk_pct=3000,
            flat_atk=200,
            final_atk_pct=1000,
            final_flat_atk=50,
        )
        expected = compute_total_stats(inputs).atk
        assert floor(_build(inputs).compute(Q_ATK_NODE)) == expected


class TestHP:
    def test_full_formula(self) -> None:
        inputs = StatInputs(
            agent_base_hp=8000,
            hp_pct=2000,
            flat_hp=500,
            final_hp_pct=500,
            final_flat_hp=100,
        )
        expected = compute_total_stats(inputs).hp
        assert floor(_build(inputs).compute(Q_HP_NODE)) == expected


class TestDEF:
    def test_full_formula(self) -> None:
        inputs = StatInputs(
            agent_base_def=500,
            def_pct=5000,
            flat_def=100,
        )
        expected = compute_total_stats(inputs).defense
        assert floor(_build(inputs).compute(Q_DEF_NODE)) == expected


class TestCritStats:
    def test_crit_rate_passthrough(self) -> None:
        inputs = StatInputs(crit_rate=2400)
        expected = compute_total_stats(inputs).crit_rate
        assert int(_build(inputs).compute(Q_CRIT_RATE_NODE)) == expected

    def test_crit_dmg_passthrough(self) -> None:
        inputs = StatInputs(crit_dmg=12000)
        expected = compute_total_stats(inputs).crit_dmg
        assert int(_build(inputs).compute(Q_CRIT_DMG_NODE)) == expected


class TestElementalDmg:
    def test_per_element(self) -> None:
        inputs = StatInputs(
            fire_dmg=2000,
            ice_dmg=1500,
            electric_dmg=0,
            ether_dmg=500,
            physical_dmg=0,
        )
        calc = _build(inputs)
        for element in ("physical", "fire", "ice", "electric", "ether"):
            expected = compute_total_stats(inputs).elemental_dmg(element)
            actual = int(calc.compute(elemental_dmg_node(element)))
            assert actual == expected, element


class TestParityFullRoundtrip:
    """Sanity: the full StatInputs → TotalStats shape matches on one combined case."""

    def test_all_fields(self) -> None:
        inputs = StatInputs(
            agent_base_hp=8000,
            agent_base_atk=600,
            agent_base_def=500,
            wengine_base_atk=400,
            hp_pct=2000,
            atk_pct=3000,
            def_pct=5000,
            flat_hp=500,
            flat_atk=200,
            flat_def=100,
            final_hp_pct=500,
            final_atk_pct=1000,
            final_def_pct=300,
            final_flat_hp=100,
            final_flat_atk=50,
            final_flat_def=25,
            crit_rate=2400,
            crit_dmg=12000,
            anomaly_mastery=150,
            anomaly_proficiency=300,
            impact=180,
            energy_regen=140,
            pen_flat=30,
            pen_ratio=1500,
            fire_dmg=2000,
            ice_dmg=1500,
            electric_dmg=500,
            ether_dmg=100,
            physical_dmg=400,
        )
        expected = compute_total_stats(inputs)
        calc = _build(inputs)
        assert floor(calc.compute(Q_ATK_NODE)) == expected.atk
        assert floor(calc.compute(Q_HP_NODE)) == expected.hp
        assert floor(calc.compute(Q_DEF_NODE)) == expected.defense
        assert int(calc.compute(Q_CRIT_RATE_NODE)) == expected.crit_rate
        assert int(calc.compute(Q_CRIT_DMG_NODE)) == expected.crit_dmg
        for element in ("physical", "fire", "ice", "electric", "ether"):
            actual = int(calc.compute(elemental_dmg_node(element)))
            assert actual == expected.elemental_dmg(element)
