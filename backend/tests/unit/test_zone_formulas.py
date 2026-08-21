"""Unit tests for zone_formulas — per-zone derivation metadata on attribution.

Covers DESIGN_explainability.md §2.1 (Task A1): each template's operands are
surfaced with the correct result_bp (matching the calculator's own *_mult),
and pre_clamp_bp is populated only when a clamp/floor actually bit.
"""

from __future__ import annotations

from app.services.build_damage_service import (
    BuildSnapshot,
    EnemySnapshot,
    calculate_build_anomaly,
    calculate_build_damage,
    calculate_build_sheer,
)
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
        "agent_specialty": "attack",
    }
    defaults.update(overrides)
    return BuildSnapshot(**defaults)


def _enemy(**overrides) -> EnemySnapshot:
    defaults = {"level": 60, "base_def": 50, "element_res": 0}
    defaults.update(overrides)
    return EnemySnapshot(**defaults)


class TestStandardZoneFormulas:
    def test_expected_templates_present(self):
        build = _snap()
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        formulas = result.attribution.zone_formulas
        assert set(formulas) == {"base", "boost", "crit", "def", "res", "vulnerability", "stun"}

    def test_result_bp_matches_damage_mults(self):
        build = _snap()
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        f = result.attribution.zone_formulas
        d = result.damage
        assert f["base"].result_bp == d.base_dmg
        assert f["boost"].result_bp == d.boost_mult
        assert f["crit"].result_bp == d.crit_mult
        assert f["def"].result_bp == d.def_mult
        assert f["res"].result_bp == d.res_mult
        assert f["vulnerability"].result_bp == d.vulnerability_mult
        assert f["stun"].result_bp == d.stun_mult

    def test_no_pre_clamp_in_normal_case(self):
        build = _snap()
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        f = result.attribution.zone_formulas
        assert f["crit"].pre_clamp_bp is None
        assert f["def"].pre_clamp_bp is None
        assert f["res"].pre_clamp_bp is None
        assert f["stun"].pre_clamp_bp is None

    def test_def_floor_exposes_pre_clamp(self):
        # A huge PEN Flat drives effective enemy DEF to floor at 0 —
        # the pre-floor value would have gone negative.
        build = _snap(agent_pen_flat=100_000_000)
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        f = result.attribution.zone_formulas["def"]
        assert f.result_bp == result.damage.def_mult
        assert f.pre_clamp_bp is not None
        assert f.pre_clamp_bp != f.result_bp

    def test_stun_clamp_exposes_pre_clamp(self):
        build = _snap()
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            is_stunned=True,
            stun_dmg_mult=999_000,  # far above the [2000, 50000] clamp
            with_attribution=True,
        )
        f = result.attribution.zone_formulas["stun"]
        assert f.result_bp == result.damage.stun_mult
        assert f.pre_clamp_bp == 999_000

    def test_res_clamp_exposes_pre_clamp(self):
        build = _snap()
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(element_res=-50000),  # deep weakness, pushes RES area above 2.0x
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        f = result.attribution.zone_formulas["res"]
        assert f.result_bp == result.damage.res_mult
        assert f.pre_clamp_bp is not None
        assert f.pre_clamp_bp > f.result_bp

    def test_no_attribution_when_not_requested(self):
        build = _snap()
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=False,
        )
        assert result.attribution is None


class TestAnomalyZoneFormulas:
    def test_expected_templates_present(self):
        build = _snap(agent_specialty="anomaly")
        result = calculate_build_anomaly(
            build=build,
            enemy=_enemy(),
            anomaly_type="shock",
            conditions=ActiveConditions(),
            with_attribution=True,
        )
        formulas = result.attribution.zone_formulas
        assert set(formulas) == {
            "base",
            "boost",
            "def",
            "res",
            "vulnerability",
            "stun",
            "anomaly_prof",
            "anomaly_level",
            "anomaly_boost",
        }
        assert "crit" not in formulas

    def test_result_bp_matches_damage_mults(self):
        build = _snap(agent_specialty="anomaly")
        result = calculate_build_anomaly(
            build=build,
            enemy=_enemy(),
            anomaly_type="shock",
            conditions=ActiveConditions(),
            with_attribution=True,
        )
        f = result.attribution.zone_formulas
        d = result.damage
        assert f["anomaly_prof"].result_bp == d.anomaly_prof_mult
        assert f["anomaly_level"].result_bp == d.level_mult
        assert f["anomaly_boost"].result_bp == d.anomaly_boost_mult
        assert f["def"].result_bp == d.def_mult
        assert f["res"].result_bp == d.res_mult


class TestSheerZoneFormulas:
    def test_expected_templates_present(self):
        build = _snap(agent_specialty="rupture", agent_sheer_force_hp_ratio=1000)
        result = calculate_build_sheer(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        formulas = result.attribution.zone_formulas
        assert set(formulas) == {
            "base",
            "boost",
            "crit",
            "res",
            "vulnerability",
            "stun",
            "sheer_force",
            "sheer_boost",
        }
        assert "def" not in formulas
        assert "anomaly_prof" not in formulas

    def test_result_bp_matches_damage_mults(self):
        build = _snap(agent_specialty="rupture", agent_sheer_force_hp_ratio=1000)
        result = calculate_build_sheer(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        f = result.attribution.zone_formulas
        d = result.damage
        assert f["base"].result_bp == d.base_dmg
        assert f["sheer_force"].result_bp == d.sheer_force
        assert f["sheer_boost"].result_bp == d.sheer_boost_mult
        assert f["crit"].result_bp == d.crit_mult
        assert f["res"].result_bp == d.res_mult
        assert f["stun"].result_bp == d.stun_mult

    def test_dispatches_from_calculate_build_damage(self):
        """Rupture specialty auto-dispatches through calculate_build_damage too."""
        build = _snap(agent_specialty="rupture", agent_sheer_force_hp_ratio=1000)
        result = calculate_build_damage(
            build=build,
            enemy=_enemy(),
            multiplier=3120,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
            with_attribution=True,
        )
        formulas = result.attribution.zone_formulas
        assert "sheer_force" in formulas
        assert "def" not in formulas
