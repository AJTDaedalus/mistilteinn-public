"""Unit tests for the build damage service (orchestration layer).

The service takes value objects (BuildSnapshot, EnemySnapshot), not DB models.
This makes it callable from either a snapshot UI or a future rotation tick.
"""

from __future__ import annotations

from app.services.build_damage_service import (
    BuildSnapshot,
    EnemySnapshot,
    calculate_build_anomaly,
    calculate_build_damage,
    out_of_combat_stats,
)
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


def _snap(
    *,
    agent_base_atk: int = 900,
    wengine_base_atk: int = 600,
    agent_base_hp: int = 8000,
    agent_base_def: int = 600,
    crit_rate: int = 500,
    crit_dmg: int = 5000,
    anomaly_proficiency: int = 0,
    pen_ratio: int = 0,
    pen_flat: int = 0,
    element: str = "ice",
    disc_stats: list[dict] | None = None,
    modifiers: list[Modifier] | None = None,
    level: int = 60,
) -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_hp=agent_base_hp,
        agent_base_atk=agent_base_atk,
        agent_base_def=agent_base_def,
        wengine_base_atk=wengine_base_atk,
        agent_crit_rate=crit_rate,
        agent_crit_dmg=crit_dmg,
        agent_anomaly_proficiency=anomaly_proficiency,
        agent_pen_ratio=pen_ratio,
        agent_pen_flat=pen_flat,
        agent_element=element,
        agent_level=level,
        disc_stats=disc_stats or [],
        modifiers=modifiers or [],
    )


def _enemy(
    *,
    level: int = 60,
    base_def: int = 50,
    element_res: int = 0,
) -> EnemySnapshot:
    return EnemySnapshot(level=level, base_def=base_def, element_res=element_res)


def _mod(
    stat: str = "atk_pct",
    value: int = 1000,
    source: ModifierSource = ModifierSource.CORE_SKILL,
    conditions: tuple[Condition, ...] = (Condition.ALWAYS,),
    scopes: tuple[AttackScope, ...] = (AttackScope.ALL,),
    target: ModifierTarget = ModifierTarget.SELF,
    max_stacks: int = 1,
    source_label: str = "test",
) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=source,
        source_label=source_label,
        target=target,
        conditions=conditions,
        scopes=scopes,
        max_stacks=max_stacks,
    )


class TestCalculateBuildDamage:
    """Tests for the stateless calculate_build_damage function."""

    def test_base_atk_aggregation(self):
        """Base ATK = agent + wengine, no % bonuses."""
        result = calculate_build_damage(
            build=_snap(),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        # ATK = (900 + 600) * 1.0 = 1500
        assert result.damage.base_dmg == 1500

    def test_atk_pct_modifier_increases_base_dmg(self):
        result = calculate_build_damage(
            build=_snap(modifiers=[_mod("atk_pct", 3000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        # ATK = 1500 * 1.30 = 1950
        assert result.damage.base_dmg == 1950

    def test_flat_atk_from_discs(self):
        discs = [{"main_stat_type": "atk", "main_stat_value": 100, "substats": []}]
        result = calculate_build_damage(
            build=_snap(disc_stats=discs),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        # ATK = 1500 * 1.0 + 100 = 1600
        assert result.damage.base_dmg == 1600

    def test_atk_pct_from_discs(self):
        discs = [{"main_stat_type": "atk_pct", "main_stat_value": 3000, "substats": []}]
        result = calculate_build_damage(
            build=_snap(disc_stats=discs),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        # ATK = 1500 * 1.30 = 1950
        assert result.damage.base_dmg == 1950

    def test_crit_rate_from_disc_substats(self):
        discs = [
            {
                "main_stat_type": "hp",
                "main_stat_value": 0,
                "substats": [{"stat": "crit_rate", "value": 2400}],
            },
        ]
        result = calculate_build_damage(
            build=_snap(disc_stats=discs),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        # CR = 500 (base) + 2400 (disc) = 2900 = 29%
        # Crit mult = 1 + 0.29 * 0.50 = 1.145 → 11450 bp
        assert result.damage.crit_mult == 11450

    def test_dmg_bonus_feeds_boost_zone(self):
        result = calculate_build_damage(
            build=_snap(modifiers=[_mod("dmg_bonus", 2500)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert result.damage.boost_mult == 12500

    def test_elemental_dmg_feeds_boost_zone(self):
        """Element-matching DMG bonus enters the boost zone."""
        result = calculate_build_damage(
            build=_snap(element="ice", modifiers=[_mod("ice_dmg", 3000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert result.damage.boost_mult == 13000

    def test_non_matching_element_dmg_excluded(self):
        """Fire DMG bonus doesn't boost an ice agent's damage."""
        result = calculate_build_damage(
            build=_snap(element="ice", modifiers=[_mod("fire_dmg", 3000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert result.damage.boost_mult == 10000

    def test_res_reduction_in_res_zone(self):
        result = calculate_build_damage(
            build=_snap(modifiers=[_mod("res_reduction", 2000)]),
            enemy=_enemy(element_res=2000),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        # RES = 1 - 0.20 + 0.20 = 1.0
        assert result.damage.res_mult == 10000

    def test_res_ignore_in_res_zone(self):
        result = calculate_build_damage(
            build=_snap(modifiers=[_mod("res_ignore", 1500)]),
            enemy=_enemy(element_res=2000),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        # RES = 1 - 0.20 + 0.15 = 0.95 → 9500 bp
        assert result.damage.res_mult == 9500

    def test_def_ignore_increases_def_mult(self):
        r_with = calculate_build_damage(
            build=_snap(modifiers=[_mod("def_ignore", 5000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        r_without = calculate_build_damage(
            build=_snap(),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert r_with.damage.def_mult > r_without.damage.def_mult

    def test_pen_ratio_from_modifier(self):
        r_with = calculate_build_damage(
            build=_snap(modifiers=[_mod("pen_ratio", 2400)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        r_without = calculate_build_damage(
            build=_snap(),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert r_with.damage.def_mult > r_without.damage.def_mult

    def test_vulnerability_feeds_vuln_zone(self):
        result = calculate_build_damage(
            build=_snap(modifiers=[_mod("vulnerability", 2000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert result.damage.vulnerability_mult == 12000

    def test_conditional_modifier_inactive(self):
        mods = [_mod("crit_dmg", 10000, conditions=(Condition.ENEMY_STUNNED,))]
        r_off = calculate_build_damage(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        r_on = calculate_build_damage(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(active={Condition.ALWAYS, Condition.ENEMY_STUNNED}),
            attack_scope=AttackScope.BASIC,
        )
        assert r_on.damage.crit_mult > r_off.damage.crit_mult

    def test_scope_filtering(self):
        """Dash-scoped modifier only applies to dash attacks."""
        mods = [_mod("dmg_bonus", 5000, scopes=(AttackScope.DASH,))]
        r_dash = calculate_build_damage(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.DASH,
        )
        r_basic = calculate_build_damage(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert r_dash.damage.boost_mult == 15000
        assert r_basic.damage.boost_mult == 10000

    def test_stun_applied_via_kwargs(self):
        result = calculate_build_damage(
            build=_snap(),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            is_stunned=True,
            stun_dmg_mult=15000,
        )
        assert result.damage.stun_mult == 15000

    def test_multiple_modifiers_stack(self):
        mods = [
            _mod("atk_pct", 2000),
            _mod("atk_pct", 1000),
            _mod("crit_rate", 1500),
            _mod("dmg_bonus", 3000),
        ]
        result = calculate_build_damage(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        # ATK = 1500 * 1.30 = 1950
        assert result.damage.base_dmg == 1950
        # CR = 500 + 1500 = 2000 = 20%, CD = 50%
        assert result.damage.crit_mult == 11000
        assert result.damage.boost_mult == 13000

    def test_enemy_weakness(self):
        result = calculate_build_damage(
            build=_snap(),
            enemy=_enemy(element_res=-2000),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        # RES = 1 - (-0.20) = 1.20
        assert result.damage.res_mult == 12000

    def test_zero_multiplier_gives_zero_damage(self):
        result = calculate_build_damage(
            build=_snap(),
            enemy=_enemy(),
            multiplier=0,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )
        assert result.damage.total == 0

    def test_mv_crit_scaling_scales_multiplier(self):
        """YSG-style core passive: effective_MV = base_MV × (1 + crit_dmg × factor).

        factor=2500 (0.25 in bp), crit_dmg=20000 (200%).
        mv_scale = 10000 + 20000 × 2500 // 10000 = 10000 + 5000 = 15000 (1.5×).
        effective_multiplier = 10000 × 15000 // 10000 = 15000.
        Base damage should be 1.5× compared to no scaling.
        """
        base_result = calculate_build_damage(
            build=_snap(crit_dmg=20000),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
        )
        scaled_result = calculate_build_damage(
            build=_snap(crit_dmg=20000, modifiers=[_mod("mv_crit_scaling", 2500)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
        )
        # effective multiplier = 15000, base = 1.5× of base_result.base_dmg
        assert scaled_result.damage.base_dmg == base_result.damage.base_dmg * 15000 // 10000
        assert scaled_result.damage.total > base_result.damage.total

    def test_mv_crit_scaling_zero_when_no_modifier(self):
        """No mv_crit_scaling modifier → no effect on damage."""
        r1 = calculate_build_damage(
            build=_snap(crit_dmg=20000),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
        )
        r2 = calculate_build_damage(
            build=_snap(crit_dmg=20000, modifiers=[_mod("mv_crit_scaling", 0)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.ALL,
        )
        assert r1.damage.total == r2.damage.total


class TestCalculateBuildAnomaly:
    def test_burn_basic(self):
        result = calculate_build_anomaly(
            build=_snap(anomaly_proficiency=300),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
        )
        assert result.damage.total > 0
        assert result.damage.procs == 20

    def test_shock(self):
        result = calculate_build_anomaly(
            build=_snap(anomaly_proficiency=300),
            enemy=_enemy(),
            anomaly_type="shock",
            conditions=ActiveConditions(),
        )
        assert result.damage.procs == 10

    def test_anomaly_dmg_bonus_modifier(self):
        r_without = calculate_build_anomaly(
            build=_snap(anomaly_proficiency=300),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
        )
        r_with = calculate_build_anomaly(
            build=_snap(
                anomaly_proficiency=300,
                modifiers=[_mod("anomaly_dmg_bonus", 2500)],
            ),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
        )
        assert r_with.damage.total > r_without.damage.total
        assert r_with.damage.anomaly_boost_mult == 12500

    def test_custom_procs(self):
        result = calculate_build_anomaly(
            build=_snap(anomaly_proficiency=300),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
            procs=5,
        )
        assert result.damage.procs == 5


class TestBaseAnomalyMastery:
    """Task 1 — agent_anomaly_mastery must reach resolved stats."""

    def test_base_am_propagates_with_no_disc_am(self):
        # Agent with base_anomaly_mastery=114, zero AM discs
        snap = BuildSnapshot(
            agent_base_atk=900,
            agent_base_hp=8000,
            agent_base_def=600,
            wengine_base_atk=600,
            agent_crit_rate=500,
            agent_crit_dmg=5000,
            agent_anomaly_proficiency=0,
            agent_anomaly_mastery=114,
            agent_element="electric",
            agent_level=60,
            disc_stats=[],
            modifiers=[],
        )
        stats = out_of_combat_stats(snap)
        assert stats.anomaly_mastery == 114

    def test_base_am_stacks_with_disc_am(self):
        snap = BuildSnapshot(
            agent_base_atk=900,
            agent_base_hp=8000,
            agent_base_def=600,
            wengine_base_atk=600,
            agent_crit_rate=500,
            agent_crit_dmg=5000,
            agent_anomaly_proficiency=0,
            agent_anomaly_mastery=114,
            agent_element="electric",
            agent_level=60,
            disc_stats=[
                {
                    "main_stat_type": "hp",
                    "main_stat_value": 0,
                    "substats": [{"stat": "anomaly_mastery", "value": 36}],
                }
            ],
            modifiers=[],
        )
        stats = out_of_combat_stats(snap)
        assert stats.anomaly_mastery == 150
