"""Parity tests for the DAG-backed damage service.

For each :class:`BuildSnapshot` / :class:`EnemySnapshot` pair exercised by
``test_build_damage_service.py``, the DAG total must land within 1% of
the procedural total. That drift is the per-zone floor-div the
procedural path applies versus the continuous float the DAG preserves
— on reasonable inputs it stays well under 0.5%; 1% covers worst-case
chained rounding.

This is the parity gate before the optimizer switches to the DAG. Exact
parity would require an opt-in ``custom('floor', ...)`` path at each
zone boundary, which the JIT work (Phase 6.5) can revisit.
"""

from __future__ import annotations

import pytest

from app.services.build_damage_service import (
    BuildSnapshot,
    EnemySnapshot,
    calculate_build_anomaly,
    calculate_build_damage,
)
from app.services.damage_calculator import CritMode
from app.services.damage_dag_service import (
    calculate_build_anomaly_dag,
    calculate_build_damage_dag,
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


def _assert_parity(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    multiplier: int,
    conditions: ActiveConditions,
    attack_scope: AttackScope,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    rel: float = 0.01,
) -> None:
    proc = calculate_build_damage(
        build=build,
        enemy=enemy,
        multiplier=multiplier,
        conditions=conditions,
        attack_scope=attack_scope,
        crit_mode=crit_mode,
        is_stunned=is_stunned,
        stun_dmg_mult=stun_dmg_mult,
    )
    dag = calculate_build_damage_dag(
        build=build,
        enemy=enemy,
        multiplier=multiplier,
        conditions=conditions,
        attack_scope=attack_scope,
        crit_mode=crit_mode,
        is_stunned=is_stunned,
        stun_dmg_mult=stun_dmg_mult,
    )
    if proc.damage.total == 0:
        assert dag.total == pytest.approx(0, abs=1e-6)
    else:
        assert dag.total == pytest.approx(proc.damage.total, rel=rel)
    # Stats should match exactly — same procedural path under the hood.
    assert dag.stats.atk == proc.stats.atk
    assert dag.stats.crit_rate == proc.stats.crit_rate
    assert dag.stats.crit_dmg == proc.stats.crit_dmg


class TestStandardDamageParity:
    def test_baseline(self) -> None:
        _assert_parity(
            build=_snap(),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_atk_pct_modifier(self) -> None:
        _assert_parity(
            build=_snap(modifiers=[_mod("atk_pct", 3000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_disc_atk_main_stat(self) -> None:
        discs = [{"main_stat_type": "atk", "main_stat_value": 100, "substats": []}]
        _assert_parity(
            build=_snap(disc_stats=discs),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_disc_atk_pct_main_stat(self) -> None:
        discs = [{"main_stat_type": "atk_pct", "main_stat_value": 3000, "substats": []}]
        _assert_parity(
            build=_snap(disc_stats=discs),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_disc_crit_rate_substat(self) -> None:
        discs = [
            {
                "main_stat_type": "hp",
                "main_stat_value": 0,
                "substats": [{"stat": "crit_rate", "value": 2400}],
            },
        ]
        _assert_parity(
            build=_snap(disc_stats=discs),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_generic_dmg_bonus(self) -> None:
        _assert_parity(
            build=_snap(modifiers=[_mod("dmg_bonus", 2500)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_elemental_dmg_matching_element(self) -> None:
        _assert_parity(
            build=_snap(element="ice", modifiers=[_mod("ice_dmg", 3000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_elemental_dmg_non_matching(self) -> None:
        """Fire DMG bonus doesn't boost an ice agent's hit."""
        _assert_parity(
            build=_snap(element="ice", modifiers=[_mod("fire_dmg", 3000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_res_reduction(self) -> None:
        _assert_parity(
            build=_snap(modifiers=[_mod("res_reduction", 2000)]),
            enemy=_enemy(element_res=2000),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_res_ignore(self) -> None:
        _assert_parity(
            build=_snap(modifiers=[_mod("res_ignore", 1500)]),
            enemy=_enemy(element_res=2000),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_def_ignore(self) -> None:
        _assert_parity(
            build=_snap(modifiers=[_mod("def_ignore", 5000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_pen_ratio_modifier(self) -> None:
        _assert_parity(
            build=_snap(modifiers=[_mod("pen_ratio", 2400)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_vulnerability(self) -> None:
        _assert_parity(
            build=_snap(modifiers=[_mod("vulnerability", 2000)]),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_conditional_modifier_off(self) -> None:
        mods = [_mod("crit_dmg", 10000, conditions=(Condition.ENEMY_STUNNED,))]
        _assert_parity(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_conditional_modifier_on(self) -> None:
        mods = [_mod("crit_dmg", 10000, conditions=(Condition.ENEMY_STUNNED,))]
        _assert_parity(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(
                active={Condition.ALWAYS, Condition.ENEMY_STUNNED},
            ),
            attack_scope=AttackScope.BASIC,
        )

    def test_scope_filtered_dash_only(self) -> None:
        mods = [_mod("dmg_bonus", 5000, scopes=(AttackScope.DASH,))]
        # Dash hit — dmg_bonus applies
        _assert_parity(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.DASH,
        )
        # Basic hit — dmg_bonus filtered out
        _assert_parity(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_stunned(self) -> None:
        _assert_parity(
            build=_snap(),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            is_stunned=True,
            stun_dmg_mult=15000,
        )

    def test_always_crit_mode(self) -> None:
        _assert_parity(
            build=_snap(crit_rate=5000, crit_dmg=20000),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            crit_mode=CritMode.CRIT,
        )

    def test_no_crit_mode(self) -> None:
        _assert_parity(
            build=_snap(crit_rate=5000, crit_dmg=20000),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            crit_mode=CritMode.NO_CRIT,
        )

    def test_stacked_modifiers(self) -> None:
        mods = [
            _mod("atk_pct", 2000),
            _mod("atk_pct", 1000),
            _mod("crit_rate", 1500),
            _mod("dmg_bonus", 3000),
        ]
        _assert_parity(
            build=_snap(modifiers=mods),
            enemy=_enemy(),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_enemy_weakness(self) -> None:
        _assert_parity(
            build=_snap(),
            enemy=_enemy(element_res=-2000),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_zero_multiplier(self) -> None:
        _assert_parity(
            build=_snap(),
            enemy=_enemy(),
            multiplier=0,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
        )

    def test_full_build_vs_elite(self) -> None:
        """High-complexity parity: many modifiers + elite enemy + stun."""
        mods = [
            _mod("atk_pct", 3500),
            _mod("flat_atk", 400),
            _mod("crit_rate", 2500),
            _mod("crit_dmg", 5000),
            _mod("ice_dmg", 2500),
            _mod("dmg_bonus", 1500),
            _mod("pen_ratio", 2000),
            _mod("vulnerability", 1500),
            _mod("res_reduction", 2000),
        ]
        _assert_parity(
            build=_snap(element="ice", modifiers=mods),
            enemy=_enemy(level=70, base_def=80, element_res=-2000),
            multiplier=12500,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            is_stunned=True,
            stun_dmg_mult=18000,
        )


class TestAnomalyDamageParity:
    def _assert_anom_parity(
        self,
        *,
        build: BuildSnapshot,
        enemy: EnemySnapshot,
        anomaly_type: str,
        conditions: ActiveConditions,
        procs: int | None = None,
        is_stunned: bool = False,
        rel: float = 0.01,
    ) -> None:
        proc = calculate_build_anomaly(
            build=build,
            enemy=enemy,
            anomaly_type=anomaly_type,
            conditions=conditions,
            procs=procs,
            is_stunned=is_stunned,
        )
        dag = calculate_build_anomaly_dag(
            build=build,
            enemy=enemy,
            anomaly_type=anomaly_type,
            conditions=conditions,
            procs=procs,
            is_stunned=is_stunned,
        )
        assert dag.procs == proc.damage.procs
        assert dag.total == pytest.approx(proc.damage.total, rel=rel)

    def test_burn_basic(self) -> None:
        self._assert_anom_parity(
            build=_snap(element="fire", anomaly_proficiency=300),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
        )

    def test_shock(self) -> None:
        self._assert_anom_parity(
            build=_snap(element="electric", anomaly_proficiency=300),
            enemy=_enemy(),
            anomaly_type="shock",
            conditions=ActiveConditions(),
        )

    def test_shatter(self) -> None:
        self._assert_anom_parity(
            build=_snap(element="ice", anomaly_proficiency=250),
            enemy=_enemy(element_res=-2000),
            anomaly_type="shatter",
            conditions=ActiveConditions(),
        )

    def test_anomaly_dmg_bonus_modifier(self) -> None:
        self._assert_anom_parity(
            build=_snap(
                element="fire",
                anomaly_proficiency=300,
                modifiers=[_mod("anomaly_dmg_bonus", 2500)],
            ),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
        )

    def test_custom_procs(self) -> None:
        self._assert_anom_parity(
            build=_snap(element="fire", anomaly_proficiency=300),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
            procs=5,
        )

    def test_with_elemental_dmg_bonus(self) -> None:
        self._assert_anom_parity(
            build=_snap(
                element="fire",
                anomaly_proficiency=400,
                modifiers=[_mod("fire_dmg", 3000)],
            ),
            enemy=_enemy(),
            anomaly_type="burn",
            conditions=ActiveConditions(),
        )

    def test_full_anom_build(self) -> None:
        mods = [
            _mod("atk_pct", 3000),
            _mod("anomaly_proficiency", 200),
            _mod("fire_dmg", 2500),
            _mod("anomaly_dmg_bonus", 2000),
            _mod("res_reduction", 1500),
        ]
        self._assert_anom_parity(
            build=_snap(
                element="fire",
                anomaly_proficiency=200,
                modifiers=mods,
            ),
            enemy=_enemy(element_res=-2000, level=70, base_def=80),
            anomaly_type="burn",
            conditions=ActiveConditions(),
        )

    def test_agent_anomaly_mastery_propagates(self) -> None:
        """DAG _snapshot_inputs must include agent_anomaly_mastery, not disc-only."""
        build = BuildSnapshot(
            agent_base_hp=8000,
            agent_base_atk=900,
            agent_base_def=600,
            wengine_base_atk=600,
            agent_crit_rate=500,
            agent_crit_dmg=5000,
            agent_anomaly_proficiency=0,
            agent_anomaly_mastery=114,
            agent_pen_ratio=0,
            agent_pen_flat=0,
            agent_element="electric",
            agent_level=60,
            disc_stats=[],
            modifiers=[],
        )
        from app.services.damage_dag_service import _snapshot_inputs
        from app.services.stat_calculator import compute_total_stats

        inputs = _snapshot_inputs(build)
        stats = compute_total_stats(inputs)
        assert stats.anomaly_mastery == 114
