"""F-19: Shock/Corruption ticks must be on-hit-gated, not uniformly scheduled.

Burn (and Shatter/Assault/Windswept) keep the old unconditional/instant schedule;
only Shock (electric) and Corruption (ether) are gated on actual timeline hit
events within the aura's window, throttled by an internal cooldown (Shock 1.0s,
Corruption 0.5s). See docs/RESEARCH_math_review.md F-19 / F-02 and
docs/DESIGN_math_review_sim.md "F-19 — On-hit gating for Shock/Corruption ticks".
"""

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot


class _MoveSpec:
    def __init__(self, buildup, duration_s, hits, element):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = "basic"


class _AgentMovesSpec:
    def __init__(self, moves):
        self.moves = moves


def _electric_enemy() -> EnemyProfile:
    return EnemyProfile(
        name="F-19 Gating Target",
        level=60,
        defense=50,
        electric_res=0,
        anomaly_capacity_electric=100,
        anomaly_duration_default=10.0,
    )


def _electric_build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Grace",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1200,
        agent_anomaly_proficiency=150,
    )


def _shock_ticks(result):
    return [e for e in result.events if e.kind == "anomaly_tick" and e.element == "electric"]


def test_idle_window_credits_fewer_shock_ticks_than_uniform_schedule():
    """A rotation with long idle gaps must credit fewer than the old uniform
    10-tick (1/s over 10s) schedule."""
    enemy = _electric_enemy()
    builds = {"grace": _electric_build()}
    moves_db = {
        "grace": _AgentMovesSpec(
            {
                "trigger": _MoveSpec(15000, 1.0, 1, "electric"),
                # Two idle hits, well over 1s apart, inside the 10s aura window.
                "idle_a": _MoveSpec(0, 5.0, 1, "electric"),
                "idle_b": _MoveSpec(0, 4.9, 1, "electric"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("grace", "trigger", []),
        SimulatedAttackStep("grace", "idle_a", []),
        SimulatedAttackStep("grace", "idle_b", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    ticks = _shock_ticks(result)
    # Old uniform schedule would have credited all 10 procs regardless of hits.
    assert len(ticks) < 10
    assert len(ticks) == 3  # trigger hit (t=1.0) + idle_a (t=6.0) + idle_b (t=10.9)


def test_fully_active_rotation_credits_same_total_as_uniform_schedule():
    """A rotation that hits the enemy in every 1s bucket credits the same total
    (10 ticks, same per-tick damage) as the old uniform schedule."""
    enemy = _electric_enemy()
    builds = {"grace": _electric_build()}
    moves = {"trigger": _MoveSpec(15000, 1.0, 1, "electric")}
    # 9 filler hits, each landing exactly 1.0s after the previous one (t=2..10),
    # filling every remaining bucket of the aura's [1.0, 11.0) window.
    for i in range(9):
        moves[f"filler_{i}"] = _MoveSpec(0, 1.0, 1, "electric")
    moves_db = {"grace": _AgentMovesSpec(moves)}

    steps = [SimulatedAttackStep("grace", "trigger", [])]
    steps += [SimulatedAttackStep("grace", f"filler_{i}", []) for i in range(9)]

    result = simulate(builds, steps, enemy, moves_db)

    ticks = _shock_ticks(result)
    assert len(ticks) == 10  # SHOCK proc cap (ANOMALY_PROC_COUNTS)
    assert result.totals["anomaly"] == sum(t.damage for t in ticks)
    # Same per-tick damage as the (unchanged) trigger-time calculation.
    assert len({t.damage for t in ticks}) == 1


def test_burn_total_unchanged_regression():
    """Burn must keep its unconditional 20-tick/10s schedule even with zero
    hits after the trigger — F-19 only gates Shock/Corruption."""
    enemy = EnemyProfile(
        name="F-19 Burn Regression Target",
        level=60,
        defense=50,
        fire_res=0,
        anomaly_capacity_fire=100,
        anomaly_duration_default=10.0,
    )
    build = BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=115,
    )
    builds = {"burnice": build}
    moves_db = {
        "burnice": _AgentMovesSpec({"trigger": _MoveSpec(15000, 1.0, 1, "fire")})
    }
    steps = [SimulatedAttackStep("burnice", "trigger", [])]

    result = simulate(builds, steps, enemy, moves_db)

    fire_ticks = [e for e in result.events if e.kind == "anomaly_tick" and e.element == "fire"]
    assert len(fire_ticks) == 20  # BURN proc cap, unconditional timer, unaffected by gating


def test_two_hits_in_one_bucket_credit_a_single_shock_tick():
    """Two hits within the same 1.0s cooldown bucket must credit only one tick."""
    enemy = _electric_enemy()
    builds = {"grace": _electric_build()}
    moves_db = {
        "grace": _AgentMovesSpec(
            {
                "trigger": _MoveSpec(15000, 1.0, 1, "electric"),
                # Second hit at t=1.3 — same 1.0s bucket as the trigger hit (t=1.0).
                "close_hit": _MoveSpec(0, 0.3, 1, "electric"),
            }
        )
    }
    steps = [
        SimulatedAttackStep("grace", "trigger", []),
        SimulatedAttackStep("grace", "close_hit", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    ticks = _shock_ticks(result)
    assert len(ticks) == 1
    assert ticks[0].t == 1.0
