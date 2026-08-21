"""F-18: anomaly/disorder cooldowns + ultimate reset.

Arkkus rules: a 3s cooldown per enemy blocks re-triggering the *same* attribute
anomaly; triggering a Disorder applies a *global* 3s cooldown blocking triggers
of ANY attribute; using an Ultimate resets both cooldowns. If the gauge reaches
threshold while a cooldown is active, the gauge is held at/above threshold
(not reset, buildup not dropped) and the trigger fires once the cooldown lapses.

Default: hold-at-threshold (not accumulate-past) per DESIGN_math_review_sim.md
"F-18" open question — see docs/RESEARCH_math_review.md F-18.
"""

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
        name="F-18 CD Target",
        level=60,
        defense=50,
        fire_res=0,
        electric_res=0,
        ether_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_capacity_ether=100,
        anomaly_duration_default=10.0,
    )


def _build(element: str) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Grace",
        agent_element=element,
        agent_level=60,
        agent_base_atk=1200,
        agent_anomaly_proficiency=150,
    )


def _anomaly_events(result, element=None):
    """Events proving a gate-pass: a brand new aura ('anomaly') or a refresh of
    the still-active same-element aura ('refresh'). Both mean the CD gate let
    the crossing through; a blocked crossing produces neither."""
    return [
        e
        for e in result.events
        if e.kind in ("anomaly", "refresh") and (element is None or e.element == element)
    ]


def test_two_same_element_crossings_within_3s_credit_one_trigger():
    enemy = _enemy()
    builds = {"grace": _build("electric")}
    moves_db = {
        "grace": _AgentMovesSpec(
            {
                "trigger": _MoveSpec(15000, 1.0, 1, "electric"),
                # Second crossing at t=2.0 — within the 3s CD from t=1.0.
                "retrigger": _MoveSpec(15000, 1.0, 1, "electric"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("grace", "trigger", []),
        SimulatedAttackStep("grace", "retrigger", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    assert len(_anomaly_events(result, "electric")) == 1


def test_disorder_blocks_all_attribute_triggers_for_3s():
    enemy = _enemy()
    builds = {"grace": _build("fire")}
    moves_db = {
        "grace": _AgentMovesSpec(
            {
                # t=1.0: Fire (Burn) aura established.
                "fire_trigger": _MoveSpec(15000, 1.0, 1, "fire"),
                # t=2.0: Electric crosses threshold while a Fire aura is active
                # -> Disorder. Sets a global disorder_cd_until = 5.0.
                "electric_disorder": _MoveSpec(15000, 1.0, 1, "electric"),
                # t=3.0: Ether crosses threshold too, but disorder_cd_until (5.0)
                # blocks it even though ether has no per-attribute CD of its own.
                "ether_attempt": _MoveSpec(15000, 1.0, 1, "ether"),
                # t=5.5: past disorder_cd_until (5.0) -- held ether gauge (15000
                # from ether_attempt, never dropped) plus this hit's buildup (100)
                # crosses threshold again and fires.
                "ether_followup": _MoveSpec(100, 2.5, 1, "ether"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("grace", "fire_trigger", []),
        SimulatedAttackStep("grace", "electric_disorder", []),
        SimulatedAttackStep("grace", "ether_attempt", []),
        SimulatedAttackStep("grace", "ether_followup", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    ether_triggers = _anomaly_events(result, "ether")
    assert len(ether_triggers) == 1
    assert ether_triggers[0].t == 5.5


def test_ultimate_resets_both_cooldowns():
    enemy = _enemy()
    builds = {"grace": _build("electric")}
    moves_db = {
        "grace": _AgentMovesSpec(
            {
                # t=1.0: first electric trigger, sets anomaly_cd_until[electric]=4.0.
                "trigger": _MoveSpec(15000, 1.0, 1, "electric"),
                # t=1.5: Ultimate resets anomaly_cd_until and disorder_cd_until.
                "ult": _MoveSpec(0, 0.5, 1, "electric", scope="ultimate"),
                # t=2.0: would still be inside the original 3s CD (until 4.0) if
                # the Ultimate hadn't reset it -- must fire immediately.
                "retrigger": _MoveSpec(15000, 0.5, 1, "electric"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("grace", "trigger", []),
        SimulatedAttackStep("grace", "ult", []),
        SimulatedAttackStep("grace", "retrigger", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    triggers = _anomaly_events(result, "electric")
    assert len(triggers) == 2
    assert triggers[1].t == 2.0


def test_held_gauge_does_not_lose_buildup_fires_on_cd_expiry():
    enemy = _enemy()
    builds = {"grace": _build("electric")}
    moves_db = {
        "grace": _AgentMovesSpec(
            {
                # t=1.0: first trigger, CD until 4.0.
                "trigger": _MoveSpec(15000, 1.0, 1, "electric"),
                # t=2.0: crosses threshold again but blocked by CD -- gauge held
                # at 15000, not reset to 0.
                "blocked_attempt": _MoveSpec(15000, 1.0, 1, "electric"),
                # t=4.0: CD just expired. Only +100 buildup this step -- if the
                # held gauge had been dropped, 100 alone could never cross the
                # 10000 threshold. It fires, proving the buildup was preserved.
                "small_followup": _MoveSpec(100, 2.0, 1, "electric"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("grace", "trigger", []),
        SimulatedAttackStep("grace", "blocked_attempt", []),
        SimulatedAttackStep("grace", "small_followup", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    triggers = _anomaly_events(result, "electric")
    assert len(triggers) == 2
    assert [t.t for t in triggers] == [1.0, 4.0]
