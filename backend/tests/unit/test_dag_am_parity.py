"""F-25: DAG buildup_node's Anomaly Mastery term matches the procedural formula.

Before this fix, ``buildup_node`` read only the flat ``anomaly_mastery``
accumulator (``StatInputs.anomaly_mastery``), silently dropping the
``agent_base_am * (1 + am_pct)`` term that
``stat_calculator.compute_total_stats`` bakes in for every other consumer.
Builds relying on %-AM sources (Vivian M2, Chained disc 4pc) saw the DAG
buildup path use an AM near 0-100 instead of the true total.

``buildup_node`` is imported by ``damage_dag_service`` — the module doesn't
have its own AM-composition step, so this fix is live wherever the DAG
overlay path computes anomaly buildup, not merely latent.
"""

from __future__ import annotations

import pytest

from app.formula.zzz.damage import buildup_node, register_enemy
from app.formula.zzz.stats import register_base_stats
from app.pando.calculator import Calculator, NodeRegistry
from app.services.stat_calculator import StatInputs, compute_total_stats


def _calc(registry: NodeRegistry) -> Calculator:
    return Calculator(registry)


def _dag_buildup(
    inputs: StatInputs, *, move_buildup: float = 100.0, element: str = "fire"
) -> float:
    reg = NodeRegistry()
    register_base_stats(reg, inputs)
    register_enemy(reg, enemy_base_def=0, enemy_level=60, enemy_res=0)
    return _calc(reg).compute(buildup_node(move_buildup, element))


class TestBuildupNodeAnomalyMasteryParity:
    def test_flat_only_matches_procedural(self) -> None:
        # Regression guard: flat-only AM (the pre-fix behavior) must be unchanged.
        inputs = StatInputs(anomaly_mastery=115)
        total_stats = compute_total_stats(inputs)

        dag_total = _dag_buildup(inputs, move_buildup=100.0)
        assert dag_total == pytest.approx(100.0 * total_stats.anomaly_mastery / 100.0)

    def test_base_am_and_pct_and_flat_all_combine(self) -> None:
        # base_am=200, am_pct=10% -> 220, + flat 50 -> 270. Was ~50 pre-fix
        # (base_am/am_pct silently dropped).
        inputs = StatInputs(agent_base_am=200, am_pct=1000, anomaly_mastery=50)
        total_stats = compute_total_stats(inputs)
        assert total_stats.anomaly_mastery == 270

        dag_total = _dag_buildup(inputs, move_buildup=100.0)
        assert dag_total == pytest.approx(100.0 * total_stats.anomaly_mastery / 100.0)

    def test_matches_procedural_for_nonzero_base_am_and_pct(self) -> None:
        inputs = StatInputs(agent_base_am=180, am_pct=2500, anomaly_mastery=30)
        total_stats = compute_total_stats(inputs)

        dag_total = _dag_buildup(inputs, move_buildup=60.0, element="electric")
        assert dag_total == pytest.approx(60.0 * total_stats.anomaly_mastery / 100.0)
