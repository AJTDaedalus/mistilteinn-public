"""Parity tests for the disc-overlay fast path on damage_dag_service.

``compute_damage_with_disc_overlay`` must produce the same number as
``calculate_build_damage_dag`` would with the disc baked into the
build snapshot — that's the contract the scorer relies on. These tests
lock that invariant across a range of inputs (plain build, with set
modifiers, with stunned multiplier, multiple substats per disc).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.damage_calculator import CritMode
from app.services.damage_dag_service import (
    build_anomaly_step_context,
    build_damage_step_context,
    calculate_build_anomaly_dag,
    calculate_build_damage_dag,
    compute_anomaly_with_disc_overlay,
    compute_damage_with_disc_overlay,
)
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


def _build(modifiers: list[Modifier] | None = None) -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_atk=900,
        agent_base_hp=8000,
        agent_base_def=600,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        wengine_base_atk=46,
        agent_element="fire",
        agent_level=60,
        modifiers=modifiers or [],
    )


def _enemy() -> EnemySnapshot:
    return EnemySnapshot(level=60, base_def=60, element_res=0)


def _disc_layout() -> list[dict]:
    return [
        {
            "main_stat_type": "atk_pct",
            "main_stat_value": 3000,
            "substats": [
                {"stat": "crit_rate", "value": 720},
                {"stat": "crit_dmg", "value": 1440},
                {"stat": "atk_pct", "value": 600},
                {"stat": "pen_flat", "value": 27},
            ],
        },
    ]


def _bake_into_build(build: BuildSnapshot, disc_stats: list[dict]) -> BuildSnapshot:
    return replace(build, disc_stats=disc_stats)


@pytest.mark.parametrize("crit_mode", [CritMode.EXPECTED, CritMode.NO_CRIT, CritMode.CRIT])
def test_overlay_matches_full_dag_no_modifiers(crit_mode):
    build, enemy = _build(), _enemy()
    discs = _disc_layout()

    ctx = build_damage_step_context(
        build=build,
        enemy=enemy,
        multiplier=12000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
        crit_mode=crit_mode,
    )
    overlay = compute_damage_with_disc_overlay(ctx, discs)

    full = calculate_build_damage_dag(
        build=_bake_into_build(build, discs),
        enemy=enemy,
        multiplier=12000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
        crit_mode=crit_mode,
    )
    assert overlay == pytest.approx(full.total)


def test_overlay_matches_full_dag_with_modifiers():
    mods = [
        Modifier(
            stat="atk_pct",
            value=2000,
            source=ModifierSource.CORE_SKILL,
            source_label="core",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        ),
        Modifier(
            stat="dmg_bonus",
            value=1500,
            source=ModifierSource.WENGINE_PASSIVE,
            source_label="wengine",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        ),
        Modifier(
            stat="vulnerability",
            value=2500,
            source=ModifierSource.DISC_SET_4PC,
            source_label="set4",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        ),
    ]
    build, enemy = _build(mods), _enemy()
    discs = _disc_layout()

    ctx = build_damage_step_context(
        build=build,
        enemy=enemy,
        multiplier=10000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
    )
    overlay = compute_damage_with_disc_overlay(ctx, discs)

    full = calculate_build_damage_dag(
        build=_bake_into_build(build, discs),
        enemy=enemy,
        multiplier=10000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
    )
    assert overlay == pytest.approx(full.total)


def test_overlay_matches_with_stun_state():
    build, enemy = _build(), _enemy()
    discs = _disc_layout()
    ctx = build_damage_step_context(
        build=build,
        enemy=enemy,
        multiplier=10000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
        is_stunned=True,
        stun_dmg_mult=20000,
    )
    overlay = compute_damage_with_disc_overlay(ctx, discs)

    full = calculate_build_damage_dag(
        build=_bake_into_build(build, discs),
        enemy=enemy,
        multiplier=10000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
        is_stunned=True,
        stun_dmg_mult=20000,
    )
    assert overlay == pytest.approx(full.total)


def test_context_is_reusable_across_disc_layouts():
    """Same context, two different discs → matches two independent full calls."""
    build, enemy = _build(), _enemy()
    ctx = build_damage_step_context(
        build=build,
        enemy=enemy,
        multiplier=12000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
    )

    disc_a = [
        {
            "main_stat_type": "atk_pct",
            "main_stat_value": 3000,
            "substats": [{"stat": "crit_dmg", "value": 1920}],
        }
    ]
    disc_b = [
        {
            "main_stat_type": "crit_rate",
            "main_stat_value": 2400,
            "substats": [{"stat": "atk_pct", "value": 1500}],
        }
    ]

    overlay_a = compute_damage_with_disc_overlay(ctx, disc_a)
    overlay_b = compute_damage_with_disc_overlay(ctx, disc_b)

    full_a = calculate_build_damage_dag(
        build=_bake_into_build(build, disc_a),
        enemy=enemy,
        multiplier=12000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
    ).total
    full_b = calculate_build_damage_dag(
        build=_bake_into_build(build, disc_b),
        enemy=enemy,
        multiplier=12000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
    ).total

    assert overlay_a == pytest.approx(full_a)
    assert overlay_b == pytest.approx(full_b)
    # Reuse must not leak: a third call with disc_a recovers the same number.
    assert compute_damage_with_disc_overlay(ctx, disc_a) == pytest.approx(full_a)


def test_empty_disc_stats_matches_empty_baked_build():
    build, enemy = _build(), _enemy()
    ctx = build_damage_step_context(
        build=build,
        enemy=enemy,
        multiplier=10000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
    )
    overlay = compute_damage_with_disc_overlay(ctx, [])

    full = calculate_build_damage_dag(
        build=_bake_into_build(build, []),
        enemy=enemy,
        multiplier=10000,
        conditions=ActiveConditions(),
        attack_scope=AttackScope.BASIC,
    )
    assert overlay == pytest.approx(full.total)


# ---------------------------------------------------------------------------
# Anomaly overlay parity tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anomaly_type", ["burn", "shock"])
def test_anomaly_overlay_matches_full_dag_no_modifiers(anomaly_type: str) -> None:
    """Anomaly overlay equals full DAG for two anomaly types, two disc layouts."""
    build = BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="fire",
        agent_level=60,
        modifiers=[],
    )
    enemy = _enemy()

    disc_layouts = [
        # Layout A — atk% + AP
        [
            {
                "main_stat_type": "atk_pct",
                "main_stat_value": 3000,
                "substats": [
                    {"stat": "anomaly_proficiency", "value": 27},
                    {"stat": "atk_pct", "value": 600},
                ],
            }
        ],
        # Layout B — pen_ratio heavy
        [
            {
                "main_stat_type": "crit_rate",
                "main_stat_value": 2400,
                "substats": [
                    {"stat": "pen_ratio", "value": 960},
                    {"stat": "atk_pct", "value": 300},
                ],
            }
        ],
    ]

    ctx = build_anomaly_step_context(
        build=build,
        enemy=enemy,
        anomaly_type=anomaly_type,
        conditions=ActiveConditions(),
    )

    for discs in disc_layouts:
        overlay = compute_anomaly_with_disc_overlay(ctx, discs)
        full = calculate_build_anomaly_dag(
            build=_bake_into_build(build, discs),
            enemy=enemy,
            anomaly_type=anomaly_type,
            conditions=ActiveConditions(),
        )
        assert overlay == pytest.approx(full.total, rel=1e-6), (
            f"{anomaly_type}: overlay={overlay}, full.total={full.total}"
        )


def test_anomaly_overlay_with_modifiers() -> None:
    """Anomaly overlay is stable with agent kit modifiers active."""
    mods = [
        Modifier(
            stat="atk_pct",
            value=2000,
            source=ModifierSource.CORE_SKILL,
            source_label="core",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        ),
        Modifier(
            stat="anomaly_proficiency",
            value=90,
            source=ModifierSource.WENGINE_PASSIVE,
            source_label="wengine",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        ),
    ]
    build = BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="electric",
        agent_level=60,
        modifiers=mods,
    )
    enemy = _enemy()
    discs = _disc_layout()
    anomaly_type = "shock"

    ctx = build_anomaly_step_context(
        build=build,
        enemy=enemy,
        anomaly_type=anomaly_type,
        conditions=ActiveConditions(),
    )
    overlay = compute_anomaly_with_disc_overlay(ctx, discs)
    full = calculate_build_anomaly_dag(
        build=_bake_into_build(build, discs),
        enemy=enemy,
        anomaly_type=anomaly_type,
        conditions=ActiveConditions(),
    )
    assert overlay == pytest.approx(full.total, rel=1e-6)


def test_anomaly_overlay_reusable_across_disc_layouts() -> None:
    """Same anomaly context, two disc layouts → matches two independent full calls."""
    build = BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="fire",
        agent_level=60,
        modifiers=[],
    )
    enemy = _enemy()
    anomaly_type = "burn"

    disc_a = [
        {
            "main_stat_type": "atk_pct",
            "main_stat_value": 3000,
            "substats": [{"stat": "anomaly_proficiency", "value": 36}],
        }
    ]
    disc_b = [
        {
            "main_stat_type": "atk_pct",
            "main_stat_value": 3000,
            "substats": [{"stat": "atk_pct", "value": 900}],
        }
    ]

    ctx = build_anomaly_step_context(
        build=build,
        enemy=enemy,
        anomaly_type=anomaly_type,
        conditions=ActiveConditions(),
    )

    overlay_a = compute_anomaly_with_disc_overlay(ctx, disc_a)
    overlay_b = compute_anomaly_with_disc_overlay(ctx, disc_b)

    full_a = calculate_build_anomaly_dag(
        build=_bake_into_build(build, disc_a),
        enemy=enemy,
        anomaly_type=anomaly_type,
        conditions=ActiveConditions(),
    ).total
    full_b = calculate_build_anomaly_dag(
        build=_bake_into_build(build, disc_b),
        enemy=enemy,
        anomaly_type=anomaly_type,
        conditions=ActiveConditions(),
    ).total

    assert overlay_a == pytest.approx(full_a, rel=1e-6)
    assert overlay_b == pytest.approx(full_b, rel=1e-6)
    # Reuse must not leak state — third call with disc_a recovers same number.
    assert compute_anomaly_with_disc_overlay(ctx, disc_a) == pytest.approx(full_a, rel=1e-6)


def test_anomaly_overlay_custom_proc_count() -> None:
    """Custom proc count is honoured (e.g. Disorder scenario)."""
    build = BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="ice",
        agent_level=60,
        modifiers=[],
    )
    enemy = _enemy()
    discs = _disc_layout()
    anomaly_type = "shatter"

    custom_procs = 3
    ctx = build_anomaly_step_context(
        build=build,
        enemy=enemy,
        anomaly_type=anomaly_type,
        conditions=ActiveConditions(),
        procs=custom_procs,
    )
    overlay = compute_anomaly_with_disc_overlay(ctx, discs)
    full = calculate_build_anomaly_dag(
        build=_bake_into_build(build, discs),
        enemy=enemy,
        anomaly_type=anomaly_type,
        conditions=ActiveConditions(),
        procs=custom_procs,
    )
    assert overlay == pytest.approx(full.total, rel=1e-6)
