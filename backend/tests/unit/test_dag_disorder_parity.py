"""F-24: DAG disorder_mv_node/disorder_damage_node parity with the procedural path.

disorder_mv_node had the Frost-Freeze base (600%) wrongly paired with
Ice-Freeze's slope (t*7.5%) for SHATTER, and was missing the
base_dmg_bonus_pct/flat_base_dmg (Yanagi) hooks. Both nodes are currently
unconsumed by damage_dag_service (latent) — this test only proves the node
itself matches the procedural formula, not that it's wired into a live path.

All builds set anomaly_proficiency > 0 — at AP=0 the AnomalyProfArea zeroes
the whole chain, which would make DAG/procedural comparisons pass trivially
(0 == 0) without actually exercising the MV term being tested.
"""

from __future__ import annotations

import pytest

from app.formula.builder import const
from app.formula.zzz.damage import disorder_damage_node, register_enemy
from app.formula.zzz.stats import Q_ATK_NODE, register_base_stats
from app.formula.zzz.tags import (
    Q_ADDITIONAL_MV,
    Q_BASE_DMG_BONUS_PCT,
    Q_FLAT_BASE_DMG,
    Q_MAX_DURATION,
    Q_REMAINING_DURATION,
    stat_tag,
)
from app.pando.calculator import Calculator, NodeRegistry
from app.services.damage_calculator import AnomalyType, calculate_disorder_damage
from app.services.stat_calculator import StatInputs, compute_total_stats


def _calc(registry: NodeRegistry) -> Calculator:
    return Calculator(registry)


def _dag_disorder(
    anomaly_type: AnomalyType,
    inputs: StatInputs,
    *,
    remaining_duration: float,
    max_duration: float = 10.0,
    base_dmg_bonus_pct: int = 0,
    flat_base_dmg: int = 0,
) -> float:
    reg = NodeRegistry()
    register_base_stats(reg, inputs)
    register_enemy(reg, enemy_base_def=0, enemy_level=60, enemy_res=0)
    reg.register(stat_tag(Q_REMAINING_DURATION), const(remaining_duration))
    reg.register(stat_tag(Q_MAX_DURATION), const(max_duration))
    reg.register(stat_tag(Q_ADDITIONAL_MV), const(0))
    reg.register(stat_tag(Q_BASE_DMG_BONUS_PCT), const(base_dmg_bonus_pct))
    reg.register(stat_tag(Q_FLAT_BASE_DMG), const(flat_base_dmg))
    node = disorder_damage_node(Q_ATK_NODE, anomaly_type, "ice")
    return _calc(reg).compute(node)


def _procedural_disorder(
    anomaly_type: AnomalyType,
    atk: int,
    anomaly_proficiency: int,
    *,
    remaining_duration: float,
    max_duration: float = 10.0,
    base_dmg_bonus_pct: int = 0,
    flat_base_dmg: int = 0,
) -> int:
    return calculate_disorder_damage(
        anomaly_type=anomaly_type,
        atk=atk,
        anomaly_proficiency=anomaly_proficiency,
        attacker_level=60,
        enemy_base_def=0,
        enemy_level=60,
        remaining_duration=remaining_duration,
        max_duration=max_duration,
        base_dmg_bonus_pct=base_dmg_bonus_pct,
        flat_base_dmg=flat_base_dmg,
    ).total


class TestDagDisorderShatterParity:
    def test_ice_freeze_matches_procedural(self) -> None:
        inputs = StatInputs(agent_base_atk=700, wengine_base_atk=300, anomaly_proficiency=180)
        total_stats = compute_total_stats(inputs)

        dag_total = _dag_disorder(AnomalyType.SHATTER, inputs, remaining_duration=6.0)
        proc_total = _procedural_disorder(
            AnomalyType.SHATTER,
            total_stats.atk,
            inputs.anomaly_proficiency,
            remaining_duration=6.0,
        )

        assert dag_total == pytest.approx(proc_total, rel=0.01)

    def test_ice_freeze_base_is_450_not_600(self) -> None:
        # At t=0, MV = 450% only (Frost-Freeze's 600% must not leak in).
        inputs = StatInputs(agent_base_atk=1000, wengine_base_atk=0, anomaly_proficiency=100)
        dag_total = _dag_disorder(AnomalyType.SHATTER, inputs, remaining_duration=0.0)
        # mv = 45000bp = 4.5x; base = atk(1000) * 4.5 = 4500
        # AP=100 -> prof area 1.0; level_mult(60) = 2.0 -> total = 4500 * 1.0 * 2.0 = 9000
        assert dag_total == pytest.approx(9000.0)


class TestDagDisorderQuantizationParity:
    @pytest.mark.parametrize("anomaly_type", [AnomalyType.BURN, AnomalyType.CORRUPTION])
    def test_boundary_tick_matches_procedural(self, anomaly_type: AnomalyType) -> None:
        inputs = StatInputs(agent_base_atk=800, wengine_base_atk=200, anomaly_proficiency=150)
        total_stats = compute_total_stats(inputs)

        dag_total = _dag_disorder(anomaly_type, inputs, remaining_duration=0.9)
        proc_total = _procedural_disorder(
            anomaly_type, total_stats.atk, inputs.anomaly_proficiency, remaining_duration=0.9
        )

        assert dag_total == pytest.approx(proc_total, rel=0.01)

    def test_shock_stays_continuous_matches_procedural(self) -> None:
        inputs = StatInputs(agent_base_atk=800, wengine_base_atk=200, anomaly_proficiency=150)
        total_stats = compute_total_stats(inputs)

        dag_total = _dag_disorder(AnomalyType.SHOCK, inputs, remaining_duration=0.9)
        proc_total = _procedural_disorder(
            AnomalyType.SHOCK, total_stats.atk, inputs.anomaly_proficiency, remaining_duration=0.9
        )

        assert dag_total == pytest.approx(proc_total, rel=0.01)


class TestDagDisorderYanagiHooks:
    def test_base_dmg_bonus_pct_and_flat_base_dmg_match_procedural(self) -> None:
        inputs = StatInputs(agent_base_atk=900, wengine_base_atk=100, anomaly_proficiency=200)
        total_stats = compute_total_stats(inputs)

        dag_total = _dag_disorder(
            AnomalyType.WINDSWEPT,
            inputs,
            remaining_duration=0.0,
            base_dmg_bonus_pct=-8500,
            flat_base_dmg=500,
        )
        proc_total = _procedural_disorder(
            AnomalyType.WINDSWEPT,
            total_stats.atk,
            inputs.anomaly_proficiency,
            remaining_duration=0.0,
            base_dmg_bonus_pct=-8500,
            flat_base_dmg=500,
        )

        assert dag_total == pytest.approx(proc_total, rel=0.01)
