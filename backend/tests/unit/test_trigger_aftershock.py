"""Task 5 — Trigger (1361) aftershock JSON + engine integration tests.

Two scenarios:
  1. test_trigger_aftershock_window  — 4 EX-heavy hits with Trigger off-field yield
     the proc count the 3s/2-per-20s gates allow (≤2 procs).
  2. test_trigger_heavy_scope_gate   — basic/light attack rotation → 0 Trigger procs.
"""

from types import SimpleNamespace

from app.data.loaders.moves import AftershockSpec, AgentMovesSpec, MoveBuildupSpec
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


def _build(name: str, element: str = "electric") -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element=element,
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=[],
    )


def _fake_attack(element: str = "electric"):
    return SimpleNamespace(
        element=element,
        skill_key="EXSpecial",
        damage_base=10_000,
        damage_growth=0,
        name="ex_special_test",
        id="1",
        anomaly_buildup=0,
    )


def _fake_basic_attack():
    return SimpleNamespace(
        element="electric",
        skill_key="Basic",
        damage_base=5_000,
        damage_growth=0,
        name="basic_test",
        id="2",
        anomaly_buildup=0,
    )


def _trigger_spec() -> AftershockSpec:
    """Trigger's aftershock spec: heavy-hit react, 3s CD, 2/20s window."""
    return AftershockSpec(
        react_to=["hit"],
        react_scopes=["ex_special", "chain", "ultimate", "assist_followup"],
        requires_off_field=True,
        resource=None,
        cost=0.0,
        cooldown_s=3.0,
        max_per_window=2,
        window_s=20.0,
        procs_per_trigger=1,
        aftershock_mv_bp=6780,
        element="electric",
        damage_path="standard",
    )


def _moves_db_with_trigger(on_field_name: str, move_scope: str) -> dict:
    """moves_db containing the on-field agent's scoped move + Trigger's aftershock."""
    on_key = on_field_name.lower().replace(" ", "_")
    return {
        on_key: AgentMovesSpec(
            moves={
                "scoped_move": MoveBuildupSpec(
                    scope=move_scope,
                    duration_s=4.0,
                    hits=1,
                )
            }
        ),
        "trigger": AgentMovesSpec(moves={}, aftershock=_trigger_spec()),
    }


# ---------------------------------------------------------------------------
# test_trigger_aftershock_window
# ---------------------------------------------------------------------------


def test_trigger_aftershock_window():
    """4 EX-heavy hits with Trigger off-field → exactly 2 procs (2/20s gate).

    Steps of duration_s=4 produce hits at t=4, 8, 12, 16.
    Proc 1 fires at t=4 (cd_until=7, window=[4]).
    Proc 2 fires at t=8 (cd_until=11, window=[4,8] — now at cap).
    t=12 and t=16: 2 procs already in 20s window → blocked.
    """
    builds = {
        "yanagi": _build("Yanagi"),
        "trigger": _build("Trigger"),
    }
    steps = [
        SimulatedAttackStep(
            agent_id="yanagi",
            move_name="scoped_move",
            attacks=[_fake_attack()],
            conditions=[],
        )
        for _ in range(4)
    ]
    result = simulate(builds, steps, _enemy(), _moves_db_with_trigger("Yanagi", "ex_special"))

    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 2, (
        f"Expected 2 procs (2/20s window cap), got {len(as_events)}"
    )
    for ev in as_events:
        assert ev.agent_id == "trigger"
        assert ev.detail.get("on_field") is False
        assert ev.detail.get("aftershock") is True
        assert ev.damage is not None
        assert ev.damage > 0

    assert result.totals["aftershock"] == sum(e.damage for e in as_events if e.damage)


# ---------------------------------------------------------------------------
# test_trigger_heavy_scope_gate
# ---------------------------------------------------------------------------


def test_trigger_heavy_scope_gate():
    """Basic/light attacks do not trigger Trigger's aftershock (scope gate).

    Trigger reacts only to ex_special/chain/ultimate/assist_followup.
    A basic-scope rotation should yield 0 aftershock procs.
    """
    builds = {
        "yanagi": _build("Yanagi"),
        "trigger": _build("Trigger"),
    }
    steps = [
        SimulatedAttackStep(
            agent_id="yanagi",
            move_name="scoped_move",
            attacks=[_fake_basic_attack()],
            conditions=[],
        )
        for _ in range(4)
    ]
    # moves_db: Yanagi's "scoped_move" uses scope="basic"
    result = simulate(builds, steps, _enemy(), _moves_db_with_trigger("Yanagi", "basic"))

    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 0, (
        f"Expected 0 procs for basic-scope attacks, got {len(as_events)}"
    )
    assert result.totals["aftershock"] == 0
