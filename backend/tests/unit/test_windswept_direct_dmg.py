"""F-11/F-23b: Windswept Direct-DMG zone.

References: RESEARCH_math_review.md F-11/F-23; DESIGN_math_review_sim.md
"F-11 / F-23"; docs/DECISIONS.md (Windswept new-zone decision).

Windswept infusion grants +10% Direct DMG Bonus on wind hits while its
window is open. Unlike Frostbite/Flinch (S-6), this is a genuinely new
multiplicative zone in the standard-damage chain (`DirectDmgArea`,
`calculate_standard_damage`'s `direct_dmg_bonus` param) rather than an
override of an existing input — it is a separate zone from generic DMG%
(does not combine additively with it) and must never reach anomaly damage.
"""

from dataclasses import replace

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.damage_calculator import AnomalyResult, calculate_standard_damage
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


def _wind_enemy() -> EnemyProfile:
    return EnemyProfile(
        name="F-11 Windswept Target",
        level=60,
        defense=50,
        wind_res=0,
        anomaly_capacity_wind=100,  # threshold (n=1) = 100 * 100 = 10000
        anomaly_duration_default=10.0,
    )


def _build(element: str) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="a",
        agent_element=element,
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=10000,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=100,
    )


def _hit_events(result):
    return [e for e in result.events if e.kind == "hit"]


# ---------------------------------------------------------------------------
# Pure calc-chain zone tests (fast, no simulator).
# ---------------------------------------------------------------------------


def test_calculate_standard_damage_direct_dmg_bonus_defaults_neutral():
    result = calculate_standard_damage(scaling_stat=1000, multiplier=10000)
    assert result.direct_mult == 10000


def test_calculate_standard_damage_direct_dmg_bonus_is_multiplicative():
    base = calculate_standard_damage(scaling_stat=1000, multiplier=10000, dmg_bonuses=[5000])
    boosted = calculate_standard_damage(
        scaling_stat=1000, multiplier=10000, dmg_bonuses=[5000], direct_dmg_bonus=1000
    )

    assert boosted.direct_mult == 11000
    assert boosted.total == base.total * 11000 // 10000


def test_anomaly_result_has_no_direct_dmg_zone():
    # Windswept Direct-DMG must never reach anomaly damage — AnomalyResult
    # (and calculate_anomaly_damage) carry no direct_dmg_bonus concept at all.
    assert "direct_mult" not in AnomalyResult.__dataclass_fields__


# ---------------------------------------------------------------------------
# Simulator-level tests.
# ---------------------------------------------------------------------------


def test_windswept_hit_within_window_gets_direct_dmg_bonus():
    enemy = _wind_enemy()
    builds = {"a": _build("wind")}
    moves_db = {
        "a": _AgentMovesSpec(
            {
                # t=0.1: crosses the wind threshold -> Windswept, opens
                # windswept_until = 0.1 + 20.0 = 20.1.
                "windswept_trigger": _MoveSpec(15000, 0.1, 1, "wind"),
                # t=0.2: well within the windswept window.
                "hit_in_window": _MoveSpec(0, 0.1, 1, "wind"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("a", "windswept_trigger", []),
        SimulatedAttackStep("a", "hit_in_window", [MockAttack("Basic", 1000, "wind")]),
    ]
    baseline_steps = [
        SimulatedAttackStep("a", "hit_in_window", [MockAttack("Basic", 1000, "wind")]),
    ]

    result = simulate(builds, steps, enemy, moves_db)
    baseline = simulate(builds, baseline_steps, enemy, moves_db)

    windswept_dmg = _hit_events(result)[0].damage
    baseline_dmg = _hit_events(baseline)[0].damage

    # DirectDmgArea = 1 + 10% = 1.10.
    expected = baseline_dmg * 11 // 10
    assert windswept_dmg > baseline_dmg
    assert abs(windswept_dmg - expected) <= 1


def test_windswept_hit_outside_window_unaffected():
    enemy = _wind_enemy()
    builds = {"a": _build("wind")}
    moves_db = {
        "a": _AgentMovesSpec(
            {
                "windswept_trigger": _MoveSpec(15000, 0.1, 1, "wind"),
                # Advance the clock well past windswept_until (20.1).
                "filler": _MoveSpec(0, 20.5, 1, "wind"),
                "hit_out_of_window": _MoveSpec(0, 0.1, 1, "wind"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("a", "windswept_trigger", []),
        SimulatedAttackStep("a", "filler", []),
        SimulatedAttackStep("a", "hit_out_of_window", [MockAttack("Basic", 1000, "wind")]),
    ]
    baseline_steps = [
        SimulatedAttackStep("a", "hit_out_of_window", [MockAttack("Basic", 1000, "wind")]),
    ]

    result = simulate(builds, steps, enemy, moves_db)
    baseline = simulate(builds, baseline_steps, enemy, moves_db)

    assert _hit_events(result)[0].damage == _hit_events(baseline)[0].damage


def test_windswept_direct_dmg_not_additive_with_generic_dmg_pct():
    enemy = _wind_enemy()
    build_with_dmg_bonus = replace(
        _build("wind"),
        modifiers=[
            Modifier(
                stat="dmg_bonus",
                value=5000,  # +50% generic DMG%
                source=ModifierSource.CORE_SKILL,
                target=ModifierTarget.SELF,
                conditions=(Condition.ALWAYS,),
            )
        ],
    )
    builds = {"a": build_with_dmg_bonus}
    moves_db = {
        "a": _AgentMovesSpec(
            {
                "windswept_trigger": _MoveSpec(15000, 0.1, 1, "wind"),
                "hit_in_window": _MoveSpec(0, 0.1, 1, "wind"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("a", "windswept_trigger", []),
        SimulatedAttackStep("a", "hit_in_window", [MockAttack("Basic", 1000, "wind")]),
    ]
    baseline_steps = [
        SimulatedAttackStep("a", "hit_in_window", [MockAttack("Basic", 1000, "wind")]),
    ]

    result = simulate(builds, steps, enemy, moves_db)
    # Same +50% dmg_bonus build, no Windswept trigger -> DMG%-only baseline.
    baseline = simulate(builds, baseline_steps, enemy, moves_db)

    windswept_dmg = _hit_events(result)[0].damage
    dmg_bonus_only = _hit_events(baseline)[0].damage

    # Multiplicative (correct): the two zones multiply independently, so the
    # ratio is exactly 1.10 regardless of the generic DMG% bonus already applied.
    expected_multiplicative = dmg_bonus_only * 11 // 10
    assert abs(windswept_dmg - expected_multiplicative) <= 1

    # If it were wrongly folded additively into the same BoostArea pool
    # (1 + 0.50 + 0.10) / (1 + 0.50) != 1.10 -- assert we do NOT match that.
    additive_wrong = dmg_bonus_only * (10000 + 5000 + 1000) // (10000 + 5000)
    assert windswept_dmg != additive_wrong


def test_windswept_trigger_anomaly_damage_unaffected_by_direct_dmg_zone():
    # The Windswept anomaly proc itself (calculate_anomaly_damage) never
    # receives direct_dmg_bonus -- its damage is identical whether or not a
    # subsequent wind standard hit exercises the Direct-DMG window.
    enemy = _wind_enemy()
    builds = {"a": _build("wind")}
    moves_db = {
        "a": _AgentMovesSpec(
            {
                "windswept_trigger": _MoveSpec(15000, 0.1, 1, "wind"),
                "hit_in_window": _MoveSpec(0, 0.1, 1, "wind"),
            }
        )
    }
    trigger_only_steps = [SimulatedAttackStep("a", "windswept_trigger", [])]
    with_followup_steps = [
        SimulatedAttackStep("a", "windswept_trigger", []),
        SimulatedAttackStep("a", "hit_in_window", [MockAttack("Basic", 1000, "wind")]),
    ]

    trigger_only = simulate(builds, trigger_only_steps, enemy, moves_db)
    with_followup = simulate(builds, with_followup_steps, enemy, moves_db)

    anomaly_dmg_1 = next(e.damage for e in trigger_only.events if e.kind == "anomaly")
    anomaly_dmg_2 = next(e.damage for e in with_followup.events if e.kind == "anomaly")

    assert anomaly_dmg_1 == anomaly_dmg_2
