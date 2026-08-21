"""Unit tests for calculate_build_sheer routing and DEF-bypass verification.

Confirms:
1. Yixuan build (specialty=rupture) dispatched via calculate_build_sheer returns
   a BuildSheerDamageResult with the expected SheerForce calculation.
2. Ellen build (specialty=attack) dispatched via calculate_build_damage returns
   a standard BuildDamageResult.
3. DEF end-to-end: Yixuan against high-DEF enemy and zero-DEF enemy produce
   IDENTICAL totals (DEF zone is absent from the Sheer path).
4. An external flat Sheer Force contribution (mock Lucia) reaches the total
   via buffs.sheer_force_flat.
"""

from __future__ import annotations

from app.services.build_damage_service import (
    BuildDamageResult,
    BuildSheerDamageResult,
    BuildSnapshot,
    EnemySnapshot,
    calculate_build_damage,
    calculate_build_sheer,
)
from app.services.damage_calculator import CritMode
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


def _yixuan_snap(extra_mods: list[Modifier] | None = None) -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_hp=0,
        agent_base_atk=2000,
        agent_base_def=0,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        wengine_base_atk=0,
        agent_name="Yixuan",
        agent_specialty="rupture",
        agent_sheer_force_hp_ratio=1000,
        agent_element="ether",
        agent_level=60,
        disc_stats=[
            {"main_stat_type": "hp_flat", "main_stat_value": 30000, "substats": []},
        ],
        modifiers=extra_mods or [],
    )


def _ellen_snap() -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_atk=2000,
        agent_name="Ellen",
        agent_specialty="attack",
        agent_element="ice",
    )


def _enemy(base_def: int = 50) -> EnemySnapshot:
    return EnemySnapshot(level=60, base_def=base_def, element_res=0)


_CONDITIONS = ActiveConditions()
_SCOPE = AttackScope.ALL
_MV = 10000  # 100%


class TestCalculateBuildSheerRouting:
    def test_yixuan_returns_sheer_result(self):
        snap = _yixuan_snap()
        result = calculate_build_sheer(
            build=snap,
            enemy=_enemy(),
            multiplier=_MV,
            conditions=_CONDITIONS,
            attack_scope=_SCOPE,
            crit_mode=CritMode.NO_CRIT,
        )
        assert isinstance(result, BuildSheerDamageResult)
        assert result.damage.sheer_force > 0

    def test_ellen_returns_standard_result(self):
        snap = _ellen_snap()
        result = calculate_build_damage(
            build=snap,
            enemy=_enemy(),
            multiplier=_MV,
            conditions=_CONDITIONS,
            attack_scope=_SCOPE,
            crit_mode=CritMode.NO_CRIT,
        )
        assert isinstance(result, BuildDamageResult)

    def test_def_is_bypassed_in_sheer_path(self):
        # High-DEF enemy vs zero-DEF enemy — Sheer totals must be identical.
        snap = _yixuan_snap()
        r_high_def = calculate_build_sheer(
            build=snap,
            enemy=_enemy(base_def=9999),
            multiplier=_MV,
            conditions=_CONDITIONS,
            attack_scope=_SCOPE,
            crit_mode=CritMode.NO_CRIT,
        )
        r_zero_def = calculate_build_sheer(
            build=snap,
            enemy=_enemy(base_def=0),
            multiplier=_MV,
            conditions=_CONDITIONS,
            attack_scope=_SCOPE,
            crit_mode=CritMode.NO_CRIT,
        )
        assert r_high_def.damage.total == r_zero_def.damage.total

    def test_flat_sheer_force_from_support_reaches_total(self):
        flat_sf_mod = Modifier(
            stat="sheer_force_flat",
            value=1000,
            source=ModifierSource.TEAM_BUFF,
            source_label="Mock Lucia: Sheer Force",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        )
        snap_with = _yixuan_snap(extra_mods=[flat_sf_mod])
        snap_without = _yixuan_snap()

        r_with = calculate_build_sheer(
            build=snap_with,
            enemy=_enemy(),
            multiplier=_MV,
            conditions=_CONDITIONS,
            attack_scope=_SCOPE,
            crit_mode=CritMode.NO_CRIT,
        )
        r_without = calculate_build_sheer(
            build=snap_without,
            enemy=_enemy(),
            multiplier=_MV,
            conditions=_CONDITIONS,
            attack_scope=_SCOPE,
            crit_mode=CritMode.NO_CRIT,
        )
        assert r_with.damage.sheer_force == r_without.damage.sheer_force + 1000
        assert r_with.damage.total > r_without.damage.total

    def test_sheer_dmg_bonus_applies_as_separate_zone(self):
        m6_mod = Modifier(
            stat="sheer_dmg_bonus",
            value=2000,
            source=ModifierSource.MINDSCAPE,
            source_label="M6: Sheer Force DMG",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        )
        snap_m6 = _yixuan_snap(extra_mods=[m6_mod])
        snap_base = _yixuan_snap()

        r_m6 = calculate_build_sheer(
            build=snap_m6,
            enemy=_enemy(),
            multiplier=_MV,
            conditions=_CONDITIONS,
            attack_scope=_SCOPE,
            crit_mode=CritMode.NO_CRIT,
        )
        r_base = calculate_build_sheer(
            build=snap_base,
            enemy=_enemy(),
            multiplier=_MV,
            conditions=_CONDITIONS,
            attack_scope=_SCOPE,
            crit_mode=CritMode.NO_CRIT,
        )
        # M6 +20% sheer boost → total should be base * 12000 // 10000
        expected_m6 = r_base.damage.total * 12000 // 10000
        assert r_m6.damage.total == expected_m6
