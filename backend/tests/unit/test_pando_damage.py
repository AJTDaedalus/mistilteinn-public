"""Tests for damage-zone DAG nodes.

Each multiplier zone in :mod:`app.formula.zzz.damage` mirrors the matching
pure function in :mod:`app.services.damage_calculator`. The DAG works in
fractional space (1.0 = 100%) while the procedural path works in basis
points (10000 = 100%), so parity checks compare the DAG value against
``procedural_value / 10000`` within a small tolerance.

Exact parity on the final composite damage (with procedural floor-div
after each stage) is out of scope for this phase — the DAG is pure float
for the sake of the upcoming interval arithmetic and monotonicity
analysis. A future "exact mode" using ``custom('floor', ...)`` will match
procedural to the unit, but it will be opt-in.
"""

from __future__ import annotations

import pytest

from app.formula.builder import const
from app.formula.zzz.damage import (
    anomaly_boost_area_node,
    anomaly_damage_node,
    anomaly_level_area_node,
    anomaly_proficiency_area_node,
    boost_area_node,
    buildup_node,
    crit_area_node,
    def_area_node,
    disorder_damage_node,
    register_enemy,
    res_area_node,
    standard_damage_node,
    stun_area_node,
    vortex_damage_node,
    vulnerability_area_node,
)
from app.formula.zzz.stats import Q_ATK_NODE, register_base_stats
from app.formula.zzz.tags import (
    Q_ADDITIONAL_MV,
    Q_ANOMALY_BUILDUP,
    Q_DISORDER_DMG_BONUS,
    Q_ENEMY_RES,
    Q_MAX_DURATION,
    Q_REMAINING_DURATION,
    Q_RES_IGNORE,
    Q_RES_REDUCTION,
    Q_STUN_BONUS,
    Q_VORTEX_DMG_BONUS,
    Q_VULNERABILITY,
    elem_dmg_tag,
    stat_tag,
)
from app.pando.calculator import Calculator, NodeRegistry
from app.services.damage_calculator import (
    ANOMALY_BASE,
    AnomalyType,
    CritMode,
    anomaly_level_multiplier,
    anomaly_proficiency_multiplier,
    calculate_anomaly_damage,
    calculate_standard_damage,
    crit_multiplier,
    def_multiplier,
    dmg_bonus_multiplier,
    dmg_taken_multiplier,
    res_multiplier,
    stun_multiplier,
)
from app.services.stat_calculator import StatInputs


def _calc(registry: NodeRegistry) -> Calculator:
    return Calculator(registry)


class TestBoostArea:
    def test_no_bonuses(self) -> None:
        reg = NodeRegistry()
        result = _calc(reg).compute(boost_area_node("fire"))
        # Procedural: dmg_bonus_multiplier([]) = 10000 = 1.0
        assert result == pytest.approx(dmg_bonus_multiplier([]) / 10000)

    def test_elemental_bonus(self) -> None:
        reg = NodeRegistry()
        reg.register(elem_dmg_tag("fire"), const(2500))  # +25% fire
        result = _calc(reg).compute(boost_area_node("fire"))
        assert result == pytest.approx(dmg_bonus_multiplier([2500]) / 10000)

    def test_wrong_element_skipped(self) -> None:
        reg = NodeRegistry()
        reg.register(elem_dmg_tag("ice"), const(2500))  # +25% ice — irrelevant
        result = _calc(reg).compute(boost_area_node("fire"))
        assert result == pytest.approx(1.0)

    def test_generic_and_elemental(self) -> None:
        reg = NodeRegistry()
        reg.register(elem_dmg_tag("fire"), const(2500))
        # Register a generic dmg_bonus (scope-collapsed by translator)
        from app.formula.tags import Tag
        from app.formula.zzz.tags import Q_DMG_BONUS, Q

        reg.register(Tag.of(**{Q: Q_DMG_BONUS}), const(1000))
        result = _calc(reg).compute(boost_area_node("fire"))
        assert result == pytest.approx(dmg_bonus_multiplier([2500, 1000]) / 10000)


class TestCritArea:
    def test_expected_mode(self) -> None:
        reg = NodeRegistry()
        register_base_stats(reg, StatInputs(crit_rate=5000, crit_dmg=15000))
        result = _calc(reg).compute(crit_area_node(CritMode.EXPECTED))
        # Procedural: 1 + 5000/10000 * 15000/10000 = 1 + 0.5 * 1.5 = 1.75
        assert result == pytest.approx(crit_multiplier(5000, 15000, CritMode.EXPECTED) / 10000)

    def test_always_crit(self) -> None:
        reg = NodeRegistry()
        register_base_stats(reg, StatInputs(crit_rate=5000, crit_dmg=15000))
        result = _calc(reg).compute(crit_area_node(CritMode.CRIT))
        # 1 + 15000/10000 = 2.5
        assert result == pytest.approx(crit_multiplier(5000, 15000, CritMode.CRIT) / 10000)

    def test_no_crit(self) -> None:
        reg = NodeRegistry()
        register_base_stats(reg, StatInputs(crit_rate=5000, crit_dmg=15000))
        result = _calc(reg).compute(crit_area_node(CritMode.NO_CRIT))
        assert result == pytest.approx(1.0)

    def test_rate_clamped_to_100(self) -> None:
        reg = NodeRegistry()
        # Crit rate over 100% — procedural clamps to 10000 basis points
        register_base_stats(reg, StatInputs(crit_rate=15000, crit_dmg=20000))
        result = _calc(reg).compute(crit_area_node(CritMode.EXPECTED))
        assert result == pytest.approx(crit_multiplier(15000, 20000, CritMode.EXPECTED) / 10000)


class TestResArea:
    def test_neutral(self) -> None:
        reg = NodeRegistry()
        result = _calc(reg).compute(res_area_node())
        assert result == pytest.approx(res_multiplier(0) / 10000)

    def test_weakness(self) -> None:
        reg = NodeRegistry()
        reg.register(stat_tag(Q_ENEMY_RES), const(-2000))  # -20% weakness
        result = _calc(reg).compute(res_area_node())
        assert result == pytest.approx(res_multiplier(-2000) / 10000)

    def test_with_reduction_and_ignore(self) -> None:
        reg = NodeRegistry()
        reg.register(stat_tag(Q_ENEMY_RES), const(2000))  # 20% resist
        reg.register(stat_tag(Q_RES_REDUCTION), const(1000))
        reg.register(stat_tag(Q_RES_IGNORE), const(500))
        result = _calc(reg).compute(res_area_node())
        assert result == pytest.approx(
            res_multiplier(2000, res_reduction=1000, res_ignore=500) / 10000
        )

    def test_clamped_at_zero(self) -> None:
        reg = NodeRegistry()
        reg.register(stat_tag(Q_ENEMY_RES), const(15000))  # 150% resist
        result = _calc(reg).compute(res_area_node())
        assert result == pytest.approx(res_multiplier(15000) / 10000)
        assert result == pytest.approx(0.0)

    def test_clamped_at_two(self) -> None:
        reg = NodeRegistry()
        reg.register(stat_tag(Q_ENEMY_RES), const(-20000))  # -200% "weakness"
        result = _calc(reg).compute(res_area_node())
        # Procedural clamps to 20000 bp = 2.0
        assert result == pytest.approx(res_multiplier(-20000) / 10000)
        assert result == pytest.approx(2.0)


class TestVulnerabilityArea:
    def test_empty(self) -> None:
        reg = NodeRegistry()
        result = _calc(reg).compute(vulnerability_area_node())
        assert result == pytest.approx(dmg_taken_multiplier([]) / 10000)

    def test_single(self) -> None:
        reg = NodeRegistry()
        reg.register(stat_tag(Q_VULNERABILITY), const(2000))  # +20% vuln
        result = _calc(reg).compute(vulnerability_area_node())
        assert result == pytest.approx(dmg_taken_multiplier([2000]) / 10000)

    def test_multiple(self) -> None:
        reg = NodeRegistry()
        reg.register(stat_tag(Q_VULNERABILITY), const(2000))
        reg.register(stat_tag(Q_VULNERABILITY), const(1500))
        result = _calc(reg).compute(vulnerability_area_node())
        assert result == pytest.approx(dmg_taken_multiplier([2000, 1500]) / 10000)


class TestStunArea:
    def test_not_stunned(self) -> None:
        reg = NodeRegistry()
        result = _calc(reg).compute(stun_area_node())
        assert result == pytest.approx(stun_multiplier(is_stunned=False) / 10000)

    def test_stunned_default(self) -> None:
        reg = NodeRegistry()
        # Stun bonus = stun_mult - 10000 (default 15000 -> +5000)
        reg.register(stat_tag(Q_STUN_BONUS), const(5000))
        result = _calc(reg).compute(stun_area_node())
        assert result == pytest.approx(
            stun_multiplier(is_stunned=True, stun_dmg_mult=15000) / 10000
        )

    def test_stunned_2x(self) -> None:
        reg = NodeRegistry()
        reg.register(stat_tag(Q_STUN_BONUS), const(10000))  # 2.0x
        result = _calc(reg).compute(stun_area_node())
        assert result == pytest.approx(
            stun_multiplier(is_stunned=True, stun_dmg_mult=20000) / 10000
        )


class TestDefArea:
    def test_neutral_levels(self) -> None:
        reg = NodeRegistry()
        register_enemy(
            reg,
            enemy_base_def=60,
            enemy_level=60,
            enemy_res=0,
            attacker_level=60,
        )
        result = _calc(reg).compute(def_area_node())
        expected = def_multiplier(60, 60, 60) / 10000
        # Float DAG drifts from int floor-div procedural by up to ~0.5%
        # on enemy_def rounding — sufficient for optimizer ranking.
        assert result == pytest.approx(expected, rel=1e-2)

    def test_with_pen_ratio(self) -> None:
        reg = NodeRegistry()
        register_enemy(
            reg,
            enemy_base_def=60,
            enemy_level=60,
            enemy_res=0,
            attacker_level=60,
        )
        register_base_stats(reg, StatInputs(pen_ratio=2500))
        result = _calc(reg).compute(def_area_node())
        expected = def_multiplier(60, 60, 60, pen_ratio=2500) / 10000
        # Float DAG drifts from int floor-div procedural by up to ~0.5%
        # on enemy_def rounding — sufficient for optimizer ranking.
        assert result == pytest.approx(expected, rel=1e-2)

    def test_with_pen_flat(self) -> None:
        reg = NodeRegistry()
        register_enemy(
            reg,
            enemy_base_def=60,
            enemy_level=60,
            enemy_res=0,
            attacker_level=60,
        )
        register_base_stats(reg, StatInputs(pen_flat=100))
        result = _calc(reg).compute(def_area_node())
        expected = def_multiplier(60, 60, 60, pen_flat=100) / 10000
        # Float DAG drifts from int floor-div procedural by up to ~0.5%
        # on enemy_def rounding — sufficient for optimizer ranking.
        assert result == pytest.approx(expected, rel=1e-2)

    def test_pen_flat_over_enemy_def_floors_at_zero(self) -> None:
        """Huge pen_flat should drive effective_def to 0 → def_mult == 1.0."""
        reg = NodeRegistry()
        register_enemy(
            reg,
            enemy_base_def=50,
            enemy_level=1,
            enemy_res=0,
            attacker_level=60,
        )
        register_base_stats(reg, StatInputs(pen_flat=100_000))
        result = _calc(reg).compute(def_area_node())
        assert result == pytest.approx(1.0, rel=1e-4)

    def test_combined_pen_and_ignore(self) -> None:
        reg = NodeRegistry()
        register_enemy(
            reg,
            enemy_base_def=80,
            enemy_level=70,
            enemy_res=0,
            attacker_level=60,
        )
        from app.formula.zzz.tags import Q_DEF_IGNORE

        reg.register(stat_tag(Q_DEF_IGNORE), const(1500))
        register_base_stats(reg, StatInputs(pen_ratio=2000, pen_flat=50))
        result = _calc(reg).compute(def_area_node())
        expected = (
            def_multiplier(
                60,
                80,
                70,
                pen_ratio=2000,
                pen_flat=50,
                def_ignore=1500,
            )
            / 10000
        )
        # Float DAG drifts from int floor-div procedural by up to ~0.5%
        # on enemy_def rounding — sufficient for optimizer ranking.
        assert result == pytest.approx(expected, rel=1e-2)


class TestStandardDamageComposite:
    """Parity against :func:`calculate_standard_damage` — within small rel tol.

    The procedural path floor-divs basis points at each zone boundary,
    whereas the DAG stays float throughout. On reasonable inputs the
    drift is under 0.5%; we allow 1% to cover worst-case chained
    rounding.
    """

    def test_minimal(self) -> None:
        reg = NodeRegistry()
        register_base_stats(
            reg,
            StatInputs(
                agent_base_atk=600,
                wengine_base_atk=400,
                crit_rate=500,
                crit_dmg=5000,
            ),
        )
        register_enemy(
            reg,
            enemy_base_def=60,
            enemy_level=60,
            enemy_res=0,
            attacker_level=60,
        )
        dag_total = _calc(reg).compute(
            standard_damage_node(Q_ATK_NODE, multiplier_bp=10000, element="fire"),
        )

        proc = calculate_standard_damage(
            scaling_stat=1000,  # 600 + 400 base
            multiplier=10000,
            crit_rate=500,
            crit_dmg=5000,
            enemy_base_def=60,
            enemy_level=60,
        )
        assert dag_total == pytest.approx(proc.total, rel=0.01)

    def test_full_build_vs_elite(self) -> None:
        """Full kit: base + %, crits, element, pen, enemy with weakness + stun."""
        inputs = StatInputs(
            agent_base_atk=700,
            wengine_base_atk=600,
            atk_pct=6000,
            flat_atk=400,
            crit_rate=7000,
            crit_dmg=25000,
            pen_ratio=2000,
            pen_flat=50,
            fire_dmg=4000,
        )
        reg = NodeRegistry()
        register_base_stats(reg, inputs)
        register_enemy(
            reg,
            enemy_base_def=80,
            enemy_level=70,
            enemy_res=-2000,  # fire weakness
            attacker_level=60,
            is_stunned=True,
            stun_dmg_mult=20000,
        )

        dag_total = _calc(reg).compute(
            standard_damage_node(Q_ATK_NODE, multiplier_bp=12500, element="fire"),
        )

        from app.services.stat_calculator import compute_total_stats

        total_stats = compute_total_stats(inputs)
        proc = calculate_standard_damage(
            scaling_stat=total_stats.atk,
            multiplier=12500,
            dmg_bonuses=[inputs.fire_dmg],
            crit_rate=inputs.crit_rate,
            crit_dmg=inputs.crit_dmg,
            enemy_base_def=80,
            enemy_level=70,
            enemy_res=-2000,
            pen_ratio=inputs.pen_ratio,
            pen_flat=inputs.pen_flat,
            is_stunned=True,
            stun_dmg_mult=20000,
        )
        # DAG uses unfloored ATK, procedural uses floored — allow 1% drift.
        assert dag_total == pytest.approx(proc.total, rel=0.01)


class TestAnomalyZones:
    def test_prof_zero(self) -> None:
        reg = NodeRegistry()
        result = _calc(reg).compute(anomaly_proficiency_area_node())
        assert result == pytest.approx(anomaly_proficiency_multiplier(0) / 10000)

    def test_prof_typical(self) -> None:
        reg = NodeRegistry()
        register_base_stats(reg, StatInputs(anomaly_proficiency=300))
        result = _calc(reg).compute(anomaly_proficiency_area_node())
        # 300 / 100 = 3.0; procedural returns 300*100 = 30000 bp = 3.0
        assert result == pytest.approx(anomaly_proficiency_multiplier(300) / 10000)

    def test_prof_clamped_at_10(self) -> None:
        reg = NodeRegistry()
        register_base_stats(reg, StatInputs(anomaly_proficiency=5000))
        result = _calc(reg).compute(anomaly_proficiency_area_node())
        assert result == pytest.approx(10.0)

    def test_level_at_1(self) -> None:
        reg = NodeRegistry()
        register_enemy(
            reg,
            enemy_base_def=50,
            enemy_level=1,
            enemy_res=0,
            attacker_level=1,
        )
        result = _calc(reg).compute(anomaly_level_area_node())
        assert result == pytest.approx(anomaly_level_multiplier(1) / 10000)

    def test_level_at_60(self) -> None:
        reg = NodeRegistry()
        register_enemy(
            reg,
            enemy_base_def=50,
            enemy_level=60,
            enemy_res=0,
            attacker_level=60,
        )
        result = _calc(reg).compute(anomaly_level_area_node())
        # Level 60 -> (60-1)/59 = 1.0; total = 2.0
        assert result == pytest.approx(2.0)
        assert result == pytest.approx(anomaly_level_multiplier(60) / 10000)

    def test_anomaly_boost_empty(self) -> None:
        reg = NodeRegistry()
        result = _calc(reg).compute(anomaly_boost_area_node())
        assert result == pytest.approx(1.0)

    def test_anomaly_boost_with_bonus(self) -> None:
        from app.formula.zzz.tags import Q_ANOMALY_DMG_BONUS

        reg = NodeRegistry()
        reg.register(stat_tag(Q_ANOMALY_DMG_BONUS), const(2500))  # +25%
        result = _calc(reg).compute(anomaly_boost_area_node())
        assert result == pytest.approx(1.25)


class TestAnomalyDamageComposite:
    """Parity against :func:`calculate_anomaly_damage` (per_proc value)."""

    def test_shatter(self) -> None:
        inputs = StatInputs(
            agent_base_atk=700,
            wengine_base_atk=500,
            atk_pct=5000,
            anomaly_proficiency=250,
        )
        reg = NodeRegistry()
        register_base_stats(reg, inputs)
        register_enemy(
            reg,
            enemy_base_def=60,
            enemy_level=60,
            enemy_res=-2000,
            attacker_level=60,
        )
        base_mult_bp, _procs = ANOMALY_BASE[AnomalyType.SHATTER]
        dag_per_proc = _calc(reg).compute(
            anomaly_damage_node(Q_ATK_NODE, base_mult_bp, element="ice"),
        )

        from app.services.stat_calculator import compute_total_stats

        total_stats = compute_total_stats(inputs)
        proc = calculate_anomaly_damage(
            anomaly_type=AnomalyType.SHATTER,
            atk=total_stats.atk,
            anomaly_proficiency=250,
            enemy_base_def=60,
            enemy_level=60,
            enemy_res=-2000,
        )
        assert dag_per_proc == pytest.approx(proc.per_proc, rel=0.01)

    def test_burn_with_boost(self) -> None:
        inputs = StatInputs(
            agent_base_atk=650,
            wengine_base_atk=550,
            anomaly_proficiency=400,
            fire_dmg=3000,
        )
        reg = NodeRegistry()
        register_base_stats(reg, inputs)
        # Also add an anomaly-specific damage bonus
        from app.formula.zzz.tags import Q_ANOMALY_DMG_BONUS

        reg.register(stat_tag(Q_ANOMALY_DMG_BONUS), const(2000))  # +20%
        register_enemy(
            reg,
            enemy_base_def=50,
            enemy_level=60,
            enemy_res=0,
            attacker_level=60,
        )
        base_mult_bp, _procs = ANOMALY_BASE[AnomalyType.BURN]
        dag_per_proc = _calc(reg).compute(
            anomaly_damage_node(Q_ATK_NODE, base_mult_bp, element="fire"),
        )

        from app.services.stat_calculator import compute_total_stats

        total_stats = compute_total_stats(inputs)
        proc = calculate_anomaly_damage(
            anomaly_type=AnomalyType.BURN,
            atk=total_stats.atk,
            anomaly_proficiency=400,
            dmg_bonuses=[inputs.fire_dmg],
            anomaly_dmg_bonus=2000,
        )
        assert dag_per_proc == pytest.approx(proc.per_proc, rel=0.01)


class TestBuildupNode:
    def test_basic_buildup(self) -> None:
        reg = NodeRegistry()
        register_base_stats(reg, StatInputs(anomaly_mastery=100))
        register_enemy(reg, enemy_base_def=50, enemy_level=60, enemy_res=0)
        result = _calc(reg).compute(buildup_node(60, "fire"))
        assert result == pytest.approx(60.0)

    def test_full_buildup_formula(self) -> None:
        reg = NodeRegistry()
        register_base_stats(reg, StatInputs(anomaly_mastery=115))
        reg.register(stat_tag(Q_ANOMALY_BUILDUP), const(3000))
        # register enemy anomaly resistance and stun buildup
        register_enemy(
            reg,
            enemy_base_def=50,
            enemy_level=60,
            enemy_res=0,
            is_stunned=True,
            stun_buildup_multiplier=15000,
            enemy_anomaly_res={"fire": -2000},
        )
        result = _calc(reg).compute(buildup_node(60, "fire"))
        # expected_float = 60 * 1.3 (buildup bonus) * 1.15 (mastery)
        #                  * 1.2 (enemy res weakness) * 1.5 (stun) = 161.46
        assert result == pytest.approx(161.46)


class TestDisorderDamageNode:
    def test_disorder_damage(self) -> None:
        inputs = StatInputs(
            agent_base_atk=1000,
            wengine_base_atk=1000,
            anomaly_proficiency=100,
        )
        reg = NodeRegistry()
        register_base_stats(reg, inputs)
        register_enemy(reg, enemy_base_def=0, enemy_level=60, enemy_res=0)

        # Register remaining duration, max duration, disorder dmg bonus
        reg.register(stat_tag(Q_REMAINING_DURATION), const(5.0))
        reg.register(stat_tag(Q_MAX_DURATION), const(10.0))
        reg.register(stat_tag(Q_ADDITIONAL_MV), const(0))
        reg.register(stat_tag(Q_DISORDER_DMG_BONUS), const(1000))  # 10%

        node = disorder_damage_node(Q_ATK_NODE, AnomalyType.BURN, "fire")
        total = _calc(reg).compute(node)

        # expected value calculation:
        # base (2000 * 9.5 = 19000) multiplied by level factor (2.0)
        # and disorder boost factor (1.1) to yield 41800.
        assert total == pytest.approx(41800)


class TestVortexDamageNode:
    def test_vortex_damage(self) -> None:
        inputs = StatInputs(
            agent_base_atk=500,
            wengine_base_atk=500,
            anomaly_proficiency=100,
        )
        reg = NodeRegistry()
        register_base_stats(reg, inputs)
        register_enemy(reg, enemy_base_def=0, enemy_level=60, enemy_res=0)

        # Register remaining duration, max duration, vortex dmg bonus
        reg.register(stat_tag(Q_REMAINING_DURATION), const(5.0))
        reg.register(stat_tag(Q_MAX_DURATION), const(10.0))
        reg.register(stat_tag(Q_ADDITIONAL_MV), const(0))
        reg.register(stat_tag(Q_VORTEX_DMG_BONUS), const(2000))  # 20%

        total = _calc(reg).compute(vortex_damage_node(Q_ATK_NODE, "burn", "fire"))

        # expected = base(1000 * 14 = 14000) * 2.0 (level) * 1.2 (vortex_boost) = 33600
        assert total == pytest.approx(33600)
