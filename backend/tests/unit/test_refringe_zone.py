"""Unit tests for the Refringe Coefficient zone (Task 10, DESIGN_remielle.md §7.1).

Refringe is its own multiplicative zone in the anomaly chain — separate from
anomaly_dmg_bonus — because it must be frozen onto ``active_aura`` at trigger
time so Disorder/Abloom/Vortex can inherit it (Task 11). This suite only
covers the zone itself: the default no-op, the scaling math, and that it
surfaces in the formula-card serialization. Wiring a real Lumiflux-consumption
value into a live sim run is Task 11's job.
"""

from __future__ import annotations

from app.services.build_damage_service import (
    BuildSnapshot,
    EnemySnapshot,
    calculate_build_anomaly,
    calculate_build_damage,
)
from app.services.damage_calculator import AnomalyResult, AnomalyType, calculate_anomaly_damage
from app.services.modifiers import ActiveConditions, AttackScope


def _snap(**overrides) -> BuildSnapshot:
    defaults = {
        "agent_base_atk": 900,
        "wengine_base_atk": 600,
        "agent_base_hp": 8000,
        "agent_crit_rate": 500,
        "agent_crit_dmg": 5000,
        "agent_anomaly_proficiency": 120,
        "agent_element": "ice",
        "agent_level": 60,
        "agent_specialty": "anomaly",
    }
    defaults.update(overrides)
    return BuildSnapshot(**defaults)


def _enemy(**overrides) -> EnemySnapshot:
    defaults = {"level": 60, "base_def": 50, "element_res": 0}
    defaults.update(overrides)
    return EnemySnapshot(**defaults)


class TestRefringeDefault:
    def test_default_is_neutral(self):
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.BURN,
            atk=2000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
        )
        assert result.refringe_mult == 10000

    def test_default_byte_identical_to_explicit_neutral(self):
        kwargs = {
            "anomaly_type": AnomalyType.SHOCK,
            "atk": 1500,
            "anomaly_proficiency": 150,
            "attacker_level": 60,
            "dmg_bonuses": [1200],
            "anomaly_dmg_bonus": 2000,
            "enemy_base_def": 50,
            "enemy_level": 60,
            "pen_ratio": 500,
            "enemy_res": 1000,
        }
        without = calculate_anomaly_damage(**kwargs)
        with_neutral = calculate_anomaly_damage(**kwargs, refringe_mult=10000)
        assert without == with_neutral


class TestRefringeScaling:
    def test_refringe_scales_total_by_exact_factor(self):
        # All other zones held neutral (10000) or exactly divisible (level_mult
        # at 60 = 2.0*) so the only truncating division in the chain is
        # refringe's own — isolates "exactly 1.2*" from unrelated floor-division
        # compounding elsewhere in the chain (a general property of sequential
        # integer division, not specific to this zone's slot).
        kwargs = {
            "anomaly_type": AnomalyType.BURN,
            "atk": 1000,
            "anomaly_proficiency": 100,
            "attacker_level": 60,
            "enemy_base_def": 0,
            "enemy_level": 60,
        }
        baseline = calculate_anomaly_damage(**kwargs)
        boosted = calculate_anomaly_damage(**kwargs, refringe_mult=12000)
        assert boosted.per_proc == baseline.per_proc * 12000 // 10000
        assert boosted.total == boosted.per_proc * boosted.procs

    def test_refringe_is_isolated_from_anomaly_dmg_bonus(self):
        """Refringe must not be folded into AnomalyBoostArea — it's a separate zone."""
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.BURN,
            atk=1000,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            anomaly_dmg_bonus=2000,
            refringe_mult=12000,
        )
        assert result.anomaly_boost_mult == 12000  # unaffected by refringe_mult
        assert result.refringe_mult == 12000


class TestRefringeBuildDamageServicePassthrough:
    def test_default_matches_calculator_default(self):
        build = _snap()
        result = calculate_build_anomaly(
            build=build,
            enemy=_enemy(),
            anomaly_type="shock",
            conditions=ActiveConditions(),
        )
        assert result.damage.refringe_mult == 10000

    def test_passthrough_scales_damage(self):
        # Proves the kwarg reaches calculate_anomaly_damage unmodified; the
        # exact-1.2x math itself is proven at the calculator level above with
        # a config free of other zones' floor-division compounding — this
        # build's resolved stats aren't chosen for that, so only monotonicity
        # and the passed-through field are asserted here.
        build = _snap()
        enemy = _enemy()
        baseline = calculate_build_anomaly(
            build=build,
            enemy=enemy,
            anomaly_type="shock",
            conditions=ActiveConditions(),
        )
        boosted = calculate_build_anomaly(
            build=build,
            enemy=enemy,
            anomaly_type="shock",
            conditions=ActiveConditions(),
            refringe_mult=12000,
        )
        assert boosted.damage.refringe_mult == 12000
        assert boosted.damage.per_proc > baseline.damage.per_proc


class TestRefringeZoneFormulaSerialization:
    def test_zone_absent_when_neutral(self):
        build = _snap()
        result = calculate_build_anomaly(
            build=build,
            enemy=_enemy(),
            anomaly_type="shock",
            conditions=ActiveConditions(),
            with_attribution=True,
        )
        assert "refringe" not in result.attribution.zone_formulas

    def test_zone_present_and_matches_result_bp_when_active(self):
        build = _snap()
        result = calculate_build_anomaly(
            build=build,
            enemy=_enemy(),
            anomaly_type="shock",
            conditions=ActiveConditions(),
            with_attribution=True,
            refringe_mult=12000,
        )
        formulas = result.attribution.zone_formulas
        assert "refringe" in formulas
        assert formulas["refringe"].result_bp == 12000
        assert formulas["refringe"].result_bp == result.damage.refringe_mult
        assert formulas["refringe"].terms["refringe_coefficient_bp"] == 2000

    def test_zone_never_present_on_standard_damage(self):
        """Refringe is anomaly-only — build_step_attribution must never emit it
        for a standard-damage AnomalyResult-less call."""
        build = _snap(agent_specialty="attack")
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        assert "refringe" not in result.attribution.zone_formulas


def test_anomaly_result_isinstance_check():
    result = calculate_anomaly_damage(
        anomaly_type=AnomalyType.BURN,
        atk=2000,
        attacker_level=60,
        enemy_base_def=0,
        enemy_level=60,
    )
    assert isinstance(result, AnomalyResult)
    assert hasattr(result, "refringe_mult")
