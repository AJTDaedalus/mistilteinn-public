"""F-17a: anomaly-threshold escalation Base × 1.02^(n−1), capped at n=10.

Reference: Leifa buildup curves — each repeat trigger of the same attribute on
an enemy raises the next threshold by 2%, compounding, capped at the 10th
trigger's multiplier. Wind's special low first/second entry values are a data
layer follow-up (S-4) and are not modeled here — wind uses this same curve as
a placeholder until then, per DESIGN_math_review_sim.md "F-17".

Buildup passes through `calculate_buildup` unscaled for these builds (default
anomaly_mastery=100, no buildup bonus, 0 enemy anomaly RES, not stunned), so
raw `buildup` values below map 1:1 onto gauge points — letting these tests
pin the exact threshold values the sim computes.
"""

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot


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


def _enemy() -> EnemyProfile:
    return EnemyProfile(
        name="F-17 Escalation Target",
        level=60,
        defense=50,
        electric_res=0,
        anomaly_capacity_electric=100,
        anomaly_duration_default=10.0,
    )


def _build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Grace",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1200,
        agent_anomaly_proficiency=150,
    )


def _anomaly_events(result, element="electric"):
    """A gate-pass shows up as either a brand-new 'anomaly' aura or a 'refresh'
    of the still-active same-element aura — both prove the threshold+CD gate
    let the crossing through."""
    return [e for e in result.events if e.kind in ("anomaly", "refresh") and e.element == element]


# n=10's threshold: capacity*100 * 1.02^9, floored/ceiled to bracket it exactly.
_THRESHOLD_N10 = 10000 * (1.02**9)  # ~11950.9257


def test_first_trigger_uses_base_threshold_not_escalated():
    enemy = _enemy()
    builds = {"grace": _build()}

    # Exactly at base threshold (10000) -- must trigger. If n=1 were mistakenly
    # escalated (e.g. exponent 1 instead of 0), threshold would be 10200 and
    # this would NOT trigger.
    moves_db = {"grace": _AgentMovesSpec({"hit": _MoveSpec(10000, 1.0, 1, "electric")})}
    steps = [SimulatedAttackStep("grace", "hit", [])]
    result = simulate(builds, steps, enemy, moves_db)
    assert len(_anomaly_events(result)) == 1

    # One below base threshold -- must NOT trigger.
    moves_db_low = {"grace": _AgentMovesSpec({"hit": _MoveSpec(9999, 1.0, 1, "electric")})}
    steps_low = [SimulatedAttackStep("grace", "hit", [])]
    result_low = simulate(builds, steps_low, enemy, moves_db_low)
    assert len(_anomaly_events(result_low)) == 0


def test_tenth_trigger_threshold_matches_1_02_pow_9():
    enemy = _enemy()
    builds = {"grace": _build()}

    moves = {}
    steps = []
    # 9 overwhelming triggers (buildup far above any n<=10 threshold, ~11951
    # max), spaced 3.1s apart to clear the 3s per-attribute CD (F-18) each time.
    for i in range(9):
        key = f"big_{i}"
        moves[key] = _MoveSpec(50000, 3.1, 1, "electric")
        steps.append(SimulatedAttackStep("grace", key, []))

    # Boundary probe for the 10th trigger's threshold (~11950.9257): one below
    # (must NOT trigger), one more that crosses it (must trigger).
    moves["near_miss"] = _MoveSpec(11950, 3.1, 1, "electric")
    steps.append(SimulatedAttackStep("grace", "near_miss", []))
    moves["cross"] = _MoveSpec(1, 0.1, 1, "electric")
    steps.append(SimulatedAttackStep("grace", "cross", []))

    moves_db = {"grace": _AgentMovesSpec(moves)}
    result = simulate(builds, steps, enemy, moves_db)

    triggers = _anomaly_events(result)
    assert len(triggers) == 10
    # The near_miss step (t=31.0) must not have triggered; the cross step (t=31.1) did.
    assert triggers[-1].t == pytest.approx(31.1)
    assert _THRESHOLD_N10 - 11951 < 1.0  # sanity: our probe brackets the real threshold


def test_escalation_caps_at_n_10():
    enemy = _enemy()
    builds = {"grace": _build()}

    moves = {}
    steps = []
    # 10 overwhelming triggers to reach trigger_count=10 (the 11th attempt uses
    # exponent min(11,10)-1=9 -- same as the 10th's, if capping is correct).
    for i in range(10):
        key = f"big_{i}"
        moves[key] = _MoveSpec(50000, 3.1, 1, "electric")
        steps.append(SimulatedAttackStep("grace", key, []))

    # 11th trigger: buildup pinned just above the CAPPED threshold (~11950.9257)
    # but well below the uncapped n=11 threshold (~12189.94, i.e. 1.02^10). If
    # escalation incorrectly continued past n=10, this would NOT trigger.
    moves["capped_probe"] = _MoveSpec(11951, 3.1, 1, "electric")
    steps.append(SimulatedAttackStep("grace", "capped_probe", []))

    moves_db = {"grace": _AgentMovesSpec(moves)}
    result = simulate(builds, steps, enemy, moves_db)

    triggers = _anomaly_events(result)
    assert len(triggers) == 11
