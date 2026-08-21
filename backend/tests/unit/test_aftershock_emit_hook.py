"""Task 4 — AftershockSpec schema + _resolve_aftershock emit hook tests.

Three scenarios:
  1. Off-field agent B emits a proc when on-field A lands a hit.
  2. No proc fires when the emitter is the actor (on-field).
  3. Cooldown correctly blocks the second hit in a two-step rotation.
"""

from types import SimpleNamespace

from app.data.loaders.moves import AftershockSpec, AgentMovesSpec
from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot


def _enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Test Target",
        level=60,
        defense=50,
        fire_res=0,
        anomaly_capacity_fire=10000,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )


def _build(name: str) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=[],
    )


def _fake_attack():
    """Minimal attack object sufficient for the standard-hit path."""
    return SimpleNamespace(
        element="electric",
        skill_key="Basic",
        damage_base=10_000,  # 100% ATK in basis points
        damage_growth=0,
        name="test_basic",
        id="1",
        anomaly_buildup=0,
    )


def _spec(cooldown_s: float = 0.0, procs: int = 1) -> AftershockSpec:
    return AftershockSpec(
        react_to=["hit"],
        react_scopes=None,
        requires_off_field=True,
        resource=None,
        cost=0.0,
        cooldown_s=cooldown_s,
        procs_per_trigger=procs,
        aftershock_mv_bp=5_000,
    )


def _moves_db(agent_name: str, spec: AftershockSpec) -> dict:
    key = agent_name.lower().replace(" ", "_")
    return {key: AgentMovesSpec(moves={}, aftershock=spec)}


# ---------------------------------------------------------------------------
# test_offfield_aftershock_emits_on_onfield_hit
# ---------------------------------------------------------------------------


def test_offfield_aftershock_emits_on_onfield_hit():
    """Off-field B emits exactly one aftershock event when on-field A lands a hit."""
    builds = {
        "agent_a": _build("Agent_A"),
        "agent_b": _build("Agent_B"),
    }
    steps = [
        SimulatedAttackStep(
            agent_id="agent_a",
            move_name="basic",
            attacks=[_fake_attack()],
            conditions=[],
        )
    ]
    result = simulate(builds, steps, _enemy(), _moves_db("Agent_B", _spec()))

    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 1
    ev = as_events[0]
    assert ev.agent_id == "agent_b"
    assert ev.damage is not None
    assert ev.damage > 0
    assert ev.detail.get("on_field") is False
    assert ev.detail.get("aftershock") is True
    assert result.totals["aftershock"] == ev.damage
    assert result.per_agent_attribution["agent_b"] >= ev.damage


# ---------------------------------------------------------------------------
# test_no_aftershock_when_emitter_is_actor
# ---------------------------------------------------------------------------


def test_no_aftershock_when_emitter_is_actor():
    """B has an aftershock spec but is on-field — no proc should fire."""
    builds = {"agent_b": _build("Agent_B")}
    steps = [
        SimulatedAttackStep(
            agent_id="agent_b",
            move_name="basic",
            attacks=[_fake_attack()],
            conditions=[],
        )
    ]
    result = simulate(builds, steps, _enemy(), _moves_db("Agent_B", _spec()))

    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 0
    assert result.totals["aftershock"] == 0


# ---------------------------------------------------------------------------
# test_aftershock_respects_cooldown_in_rotation
# ---------------------------------------------------------------------------


def test_aftershock_respects_cooldown_in_rotation():
    """With a 3s cooldown, two A hits 1s apart produce only the first proc.

    Step durations are 1s each with 1 attack → hits at t=1.0 and t=2.0.
    Proc fires at t=1.0, cd_until=4.0. Second hit at t=2.0 is blocked.
    """
    builds = {
        "agent_a": _build("Agent_A"),
        "agent_b": _build("Agent_B"),
    }
    steps = [
        SimulatedAttackStep(
            agent_id="agent_a",
            move_name="basic",
            attacks=[_fake_attack()],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="agent_a",
            move_name="basic",
            attacks=[_fake_attack()],
            conditions=[],
        ),
    ]
    result = simulate(builds, steps, _enemy(), _moves_db("Agent_B", _spec(cooldown_s=3.0)))

    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 1, (
        f"Expected 1 proc (3s cooldown blocks the second hit at t=2), got {len(as_events)}"
    )
