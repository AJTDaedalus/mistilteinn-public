"""F-11/F-23a: Frostbite + Flinch enemy secondary-anomaly states.

References: RESEARCH_math_review.md F-11/F-23; DESIGN_math_review_sim.md
"F-11 / F-23". Both are sim-only enemy-state modifiers (no calc-chain change):

- Frostbite (post-Shatter, ice): +10% Crit DMG taken for 10s (20s Frost
  variant) — additive into the crit-DMG input of standard hits.
- Flinch (post-Assault, physical): +7.5% Daze/Stun taken for 10s — fed into
  the existing `stun_buildup_multiplier` path already used by
  `calculate_buildup` (F-09's previously-unsourced parameter; manifests while
  the enemy is Stunned, same as the enemy's own base value).
"""

from dataclasses import replace

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget


class _MoveSpec:
    def __init__(self, buildup, duration_s, hits, element, scope="basic"):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope


class _AgentMovesSpec:
    def __init__(self, moves):
        self.moves = moves


class MockAttack:
    def __init__(self, name: str, damage_base: int, element: str):
        self.name = name
        self.damage_base = damage_base
        self.element = element


def _ice_enemy() -> EnemyProfile:
    return EnemyProfile(
        name="F-11 Frostbite Target",
        level=60,
        defense=50,
        ice_res=0,
        anomaly_capacity_ice=100,  # threshold = 100 * 100 = 10000
        anomaly_duration_default=10.0,
    )


def _physical_enemy() -> EnemyProfile:
    return EnemyProfile(
        name="F-23 Flinch Target",
        level=60,
        defense=50,
        physical_res=0,
        fire_res=0,
        anomaly_capacity_physical=100,  # threshold = 100 * 100 = 10000
        anomaly_capacity_fire=105,  # threshold = 105 * 100 = 10500
        anomaly_duration_default=10.0,
    )


def _build(element: str) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="a",
        agent_element=element,
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=10000,  # 100% -> CritArea = 1 + crit_dmg exactly
        agent_crit_dmg=5000,  # 50%
        agent_anomaly_proficiency=100,
    )


def _hit_events(result):
    return [e for e in result.events if e.kind == "hit"]


def test_post_shatter_hit_within_window_gets_plus_10pct_crit_dmg():
    enemy = _ice_enemy()
    builds = {"a": _build("ice")}
    moves_db = {
        "a": _AgentMovesSpec(
            {
                # t=0.1: crosses the ice threshold -> Shatter, opens
                # frostbite_until = 0.1 + 10.0 = 10.1.
                "shatter_trigger": _MoveSpec(15000, 0.1, 1, "ice"),
                # t=0.2: well within the frostbite window.
                "hit_in_window": _MoveSpec(0, 0.1, 1, "ice"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("a", "shatter_trigger", []),
        SimulatedAttackStep("a", "hit_in_window", [MockAttack("Basic", 1000, "ice")]),
    ]

    baseline_steps = [
        SimulatedAttackStep("a", "hit_in_window", [MockAttack("Basic", 1000, "ice")]),
    ]

    result = simulate(builds, steps, enemy, moves_db)
    baseline = simulate(builds, baseline_steps, enemy, moves_db)

    frostbite_dmg = _hit_events(result)[0].damage
    baseline_dmg = _hit_events(baseline)[0].damage

    # CritArea = 1 + crit_rate*crit_dmg (crit_rate=100% here). Base: 1 + 0.50
    # = 1.5; with +10% Crit DMG taken: 1 + 0.60 = 1.6. Ratio = 1.6/1.5.
    expected = baseline_dmg * 16 // 15
    assert frostbite_dmg > baseline_dmg
    assert abs(frostbite_dmg - expected) <= 1


def test_post_shatter_hit_outside_window_unaffected():
    enemy = _ice_enemy()
    builds = {"a": _build("ice")}
    moves_db = {
        "a": _AgentMovesSpec(
            {
                "shatter_trigger": _MoveSpec(15000, 0.1, 1, "ice"),
                # Advance the clock well past frostbite_until (10.1).
                "filler": _MoveSpec(0, 10.5, 1, "ice"),
                "hit_out_of_window": _MoveSpec(0, 0.1, 1, "ice"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("a", "shatter_trigger", []),
        SimulatedAttackStep("a", "filler", []),
        SimulatedAttackStep("a", "hit_out_of_window", [MockAttack("Basic", 1000, "ice")]),
    ]
    baseline_steps = [
        SimulatedAttackStep("a", "hit_out_of_window", [MockAttack("Basic", 1000, "ice")]),
    ]

    result = simulate(builds, steps, enemy, moves_db)
    baseline = simulate(builds, baseline_steps, enemy, moves_db)

    assert _hit_events(result)[0].damage == _hit_events(baseline)[0].damage


def test_frost_variant_window_is_20s():
    enemy = _ice_enemy()
    builds = {"a": _build("ice")}
    moves_db = {
        "a": _AgentMovesSpec(
            {
                "shatter_trigger": _MoveSpec(15000, 0.1, 1, "ice"),
                # Advance the clock past the 10s default window but still
                # inside the 20s Frost-variant window (t_hit ~= 15.2).
                "filler": _MoveSpec(0, 15.0, 1, "ice"),
                "hit_still_in_window": _MoveSpec(0, 0.1, 1, "ice"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("a", "shatter_trigger", []),
        SimulatedAttackStep("a", "filler", []),
        SimulatedAttackStep("a", "hit_still_in_window", [MockAttack("Basic", 1000, "ice")]),
    ]

    frost_build = replace(
        _build("ice"),
        modifiers=[
            Modifier(
                stat="frostbite_frost_variant",
                value=1,
                source=ModifierSource.CORE_SKILL,
                target=ModifierTarget.SELF,
                conditions=(Condition.ALWAYS,),
            )
        ],
    )

    frost_result = simulate({"a": frost_build}, steps, enemy, moves_db)
    normal_result = simulate(builds, steps, enemy, moves_db)

    baseline = simulate(
        builds,
        [SimulatedAttackStep("a", "hit_still_in_window", [MockAttack("Basic", 1000, "ice")])],
        enemy,
        moves_db,
    )

    assert _hit_events(normal_result)[0].damage == _hit_events(baseline)[0].damage
    assert _hit_events(frost_result)[0].damage > _hit_events(baseline)[0].damage


def test_flinch_active_boosts_buildup_enough_to_trigger():
    enemy = _physical_enemy()
    builds = {"a": _build("physical")}
    moves_db = {
        "a": _AgentMovesSpec(
            {
                # t=0.1: crosses the physical threshold -> Assault, opens
                # flinch_until = 0.1 + 10.0 = 10.1.
                "assault_trigger": _MoveSpec(15000, 0.1, 1, "physical"),
                "measure": _MoveSpec(10000, 0.1, 1, "fire"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("a", "assault_trigger", []),
        SimulatedAttackStep("a", "stun_trigger", []),
        # t=0.2: within the flinch window; is_stunned=True so the buildup
        # path's stun_buildup_multiplier (base 10000 + flinch 750) applies.
        # buildup = 10000 * 10750 / 10000 = 10750 >= threshold 10500.
        SimulatedAttackStep("a", "measure", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    fire_triggers = [e for e in result.events if e.kind == "anomaly" and e.element == "fire"]
    assert len(fire_triggers) == 1


def test_flinch_expired_out_of_window_buildup_insufficient():
    enemy = _physical_enemy()
    builds = {"a": _build("physical")}
    moves_db = {
        "a": _AgentMovesSpec(
            {
                "assault_trigger": _MoveSpec(15000, 0.1, 1, "physical"),
                "filler": _MoveSpec(0, 10.5, 1, "fire"),
                "measure": _MoveSpec(10000, 0.1, 1, "fire"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("a", "assault_trigger", []),
        SimulatedAttackStep("a", "stun_trigger", []),
        SimulatedAttackStep("a", "filler", []),
        # t ~= 10.8: past flinch_until (10.1) -> no bonus. buildup = 10000 <
        # threshold 10500 -> no trigger.
        SimulatedAttackStep("a", "measure", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    fire_triggers = [e for e in result.events if e.kind == "anomaly" and e.element == "fire"]
    assert len(fire_triggers) == 0
