"""Task A3 — Pulchra repeat-chain + pulchra.json wiring.

Tests (TDD — written before implementation):
  - test_pulchra_repeat_chain_cap: N qualifying hits → min(N, 6) procs; 7th blocked
  - test_pulchra_finisher_mv: 6th proc uses finisher_mv_bp (not aftershock_mv_bp)
  - test_pulchra_chain_resets_on_new_gait: a fresh Hunter's Gait window resets the chain
  - test_pulchra_heavy_scope_gate: basic-only teammate rotation → 0 procs
"""

from types import SimpleNamespace

from app.data.loaders.moves import AftershockSpec, AgentMovesSpec, MoveBuildupSpec
from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPEAT_MV = 4_630
_FINISHER_MV = 5_350


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


def _build(name: str, element: str = "physical") -> BuildSnapshot:
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


def _pulchra_chain_spec() -> AftershockSpec:
    """Pulchra aftershock spec: state-gated repeat chain (react to Special/EX)."""
    return AftershockSpec(
        react_to=["hit"],
        react_scopes=["special", "ex_special"],
        requires_off_field=True,
        requires_state="hunters_gait",
        repeat_max=5,
        aftershock_mv_bp=_REPEAT_MV,
        finisher_mv_bp=_FINISHER_MV,
        element="physical",
    )


def _special_move() -> MoveBuildupSpec:
    return MoveBuildupSpec(hits=1, duration_s=1.0, scope="special")


def _ex_move_grants_gait() -> MoveBuildupSpec:
    return MoveBuildupSpec(
        hits=1,
        duration_s=1.0,
        scope="ex_special",
        grants_state="hunters_gait",
        state_duration_s=6.0,
    )


def _attack(scope: str = "special", element: str = "physical"):
    return SimpleNamespace(
        element=element,
        skill_key=scope,
        damage_base=10_000,
        damage_growth=0,
        name=f"test_{scope}",
        id="1",
        anomaly_buildup=0,
    )


def _step(agent_id: str, move_name: str, *, scope: str = "special") -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=agent_id,
        move_name=move_name,
        attacks=[_attack(scope=scope)],
        conditions=[],
    )


def _switch(agent_id: str) -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=agent_id,
        move_name="switch",
        attacks=[],
        conditions=[],
    )


def _build_moves_db(pulchra_spec: AftershockSpec, actor_name: str = "actor") -> dict:
    """Moves DB: Pulchra off-field chain emitter + Actor with Special move."""
    actor_key = actor_name.lower().replace(" ", "_")
    return {
        "pulchra": AgentMovesSpec(
            moves={
                "ex_special": _ex_move_grants_gait(),
                "special": MoveBuildupSpec(hits=1, duration_s=1.0, scope="special"),
            },
            aftershock=pulchra_spec,
        ),
        actor_key: AgentMovesSpec(moves={"special": _special_move()}),
    }


# ---------------------------------------------------------------------------
# test_pulchra_repeat_chain_cap
# ---------------------------------------------------------------------------


def test_pulchra_repeat_chain_cap():
    """N qualifying teammate hits in one Gait window → min(N, 6) procs; 7th is blocked.

    Rotation:
      Pulchra fires ex_special (grants hunters_gait for 6s); t 0→1
      switch to Actor; t 1→2
      Actor fires 7 Special hits (1s each); hits at t=3,4,5,6,7,8,9
        - t=3..6 inside 6s window (since gait set at t_start=0, until=6)
        - hits at t=3,4,5 → inside window → emit (procs 1,2,3)
        - hit at t=6 → not strictly < 6 → blocked by state gate (t == until_t)

    Wait — gait is set to t_start + state_duration_s = 0 + 6 = 6.
    _state_active checks until_t > t.
    - t=3 → 6>3 ✓ emit (proc 1)
    - t=4 → 6>4 ✓ emit (proc 2)
    - t=5 → 6>5 ✓ emit (proc 3)
    - t=6 → 6>6 ✗ blocked by state gate (window expired)

    So with a 6s window and hits at 1s intervals starting from t=3 (after 2s overhead),
    we get 3 hits inside the window. To get 6 procs we need the window to be longer.

    Use state_duration_s=30 to get all 7 hits inside the window.
    Expected: 6 procs (cap = 1 + repeat_max = 6), 7th blocked.
    """
    spec = AftershockSpec(
        react_to=["hit"],
        react_scopes=["special", "ex_special"],
        requires_off_field=True,
        requires_state="hunters_gait",
        repeat_max=5,
        aftershock_mv_bp=_REPEAT_MV,
        finisher_mv_bp=_FINISHER_MV,
        element="physical",
    )
    gait_move = MoveBuildupSpec(
        hits=1, duration_s=1.0, scope="ex_special",
        grants_state="hunters_gait", state_duration_s=30.0,
    )
    builds = {"pulchra": _build("Pulchra"), "actor": _build("Actor")}
    moves_db = {
        "pulchra": AgentMovesSpec(moves={"ex_special": gait_move}, aftershock=spec),
        "actor": AgentMovesSpec(moves={"special": _special_move()}),
    }
    steps = [
        _step("pulchra", "ex_special", scope="ex_special"),
        _switch("actor"),
        # 7 Special hits; with 30s window all are inside
        _step("actor", "special"),
        _step("actor", "special"),
        _step("actor", "special"),
        _step("actor", "special"),
        _step("actor", "special"),
        _step("actor", "special"),
        _step("actor", "special"),
    ]
    result = simulate(builds, steps, _enemy(), moves_db)
    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 6, (
        f"Expected 6 procs (cap = 1+5); got {len(as_events)}"
    )


# ---------------------------------------------------------------------------
# test_pulchra_finisher_mv
# ---------------------------------------------------------------------------


def test_pulchra_finisher_mv():
    """The 6th proc uses finisher_mv_bp; procs 1-5 use aftershock_mv_bp.

    Use state_duration_s=30 so all 6 hits land inside the window.
    """
    spec = AftershockSpec(
        react_to=["hit"],
        react_scopes=["special", "ex_special"],
        requires_off_field=True,
        requires_state="hunters_gait",
        repeat_max=5,
        aftershock_mv_bp=_REPEAT_MV,
        finisher_mv_bp=_FINISHER_MV,
        element="physical",
    )
    gait_move = MoveBuildupSpec(
        hits=1, duration_s=1.0, scope="ex_special",
        grants_state="hunters_gait", state_duration_s=30.0,
    )
    builds = {"pulchra": _build("Pulchra"), "actor": _build("Actor")}
    moves_db = {
        "pulchra": AgentMovesSpec(moves={"ex_special": gait_move}, aftershock=spec),
        "actor": AgentMovesSpec(moves={"special": _special_move()}),
    }
    steps = [
        _step("pulchra", "ex_special", scope="ex_special"),
        _switch("actor"),
        _step("actor", "special"),  # proc 1
        _step("actor", "special"),  # proc 2
        _step("actor", "special"),  # proc 3
        _step("actor", "special"),  # proc 4
        _step("actor", "special"),  # proc 5
        _step("actor", "special"),  # proc 6 (finisher)
    ]
    result = simulate(builds, steps, _enemy(), moves_db)
    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 6

    # Procs 1-5 use repeat MV; proc 6 uses finisher MV
    for i, ev in enumerate(as_events[:5]):
        assert ev.detail["multiplier"] == _REPEAT_MV, (
            f"Proc {i+1} should use repeat MV {_REPEAT_MV}; got {ev.detail['multiplier']}"
        )
    finisher = as_events[5]
    assert finisher.detail["multiplier"] == _FINISHER_MV, (
        f"Proc 6 (finisher) should use finisher MV {_FINISHER_MV}; "
        f"got {finisher.detail['multiplier']}"
    )
    # Finisher has higher damage than a repeat proc (larger MV)
    assert finisher.damage > as_events[0].damage, "finisher MV should yield higher damage"


# ---------------------------------------------------------------------------
# test_pulchra_chain_resets_on_new_gait
# ---------------------------------------------------------------------------


def test_pulchra_chain_resets_on_new_gait():
    """A fresh Hunter's Gait window resets the repeat chain.

    Rotation:
      Pulchra ex_special → gait1 (state_duration_s=5)
      switch to Actor
      Actor: 6 Specials (fill chain1: 6 procs total)
      Pulchra ex_special → gait2 (new window_until → chain resets)
      switch to Actor
      Actor: 2 Specials (chain2: 2 procs)

    Total: 6 + 2 = 8 procs.
    """
    spec = AftershockSpec(
        react_to=["hit"],
        react_scopes=["special", "ex_special"],
        requires_off_field=True,
        requires_state="hunters_gait",
        repeat_max=5,
        aftershock_mv_bp=_REPEAT_MV,
        finisher_mv_bp=_FINISHER_MV,
        element="physical",
    )
    # Two gait moves with different state_duration_s to get different window_until values
    gait_move_long = MoveBuildupSpec(
        hits=1, duration_s=1.0, scope="ex_special",
        grants_state="hunters_gait", state_duration_s=60.0,
    )
    builds = {"pulchra": _build("Pulchra"), "actor": _build("Actor")}
    moves_db = {
        "pulchra": AgentMovesSpec(moves={"ex_special": gait_move_long}, aftershock=spec),
        "actor": AgentMovesSpec(moves={"special": _special_move()}),
    }
    steps = [
        # Window 1: Pulchra ex_special at t=0 → gait until t=60
        _step("pulchra", "ex_special", scope="ex_special"),
        _switch("actor"),
        # 6 Specials → exhaust chain (procs 1–6)
        _step("actor", "special"),
        _step("actor", "special"),
        _step("actor", "special"),
        _step("actor", "special"),
        _step("actor", "special"),
        _step("actor", "special"),
        # Window 2: Pulchra ex_special at t=8 → gait until t=68 (different window_until)
        _switch("pulchra"),
        _step("pulchra", "ex_special", scope="ex_special"),
        _switch("actor"),
        # 2 Specials → chain2 procs (proc 1 and 2 of chain2)
        _step("actor", "special"),
        _step("actor", "special"),
    ]
    result = simulate(builds, steps, _enemy(), moves_db)
    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 8, (
        f"Expected 8 procs (6 from chain1 + 2 from chain2); got {len(as_events)}"
    )


# ---------------------------------------------------------------------------
# test_pulchra_heavy_scope_gate
# ---------------------------------------------------------------------------


def test_pulchra_heavy_scope_gate():
    """With react_scopes=['special','ex_special'], a basic-only actor rotation → 0 procs.

    Even with Hunter's Gait active, basic-scope hits don't qualify.
    """
    spec = AftershockSpec(
        react_to=["hit"],
        react_scopes=["special", "ex_special"],
        requires_off_field=True,
        requires_state="hunters_gait",
        repeat_max=5,
        aftershock_mv_bp=_REPEAT_MV,
        finisher_mv_bp=_FINISHER_MV,
        element="physical",
    )
    gait_move = MoveBuildupSpec(
        hits=1, duration_s=1.0, scope="ex_special",
        grants_state="hunters_gait", state_duration_s=30.0,
    )
    builds = {"pulchra": _build("Pulchra"), "actor": _build("Actor")}
    moves_db = {
        "pulchra": AgentMovesSpec(moves={"ex_special": gait_move}, aftershock=spec),
        "actor": AgentMovesSpec(
            moves={"basic": MoveBuildupSpec(hits=1, duration_s=1.0, scope="basic")}
        ),
    }
    steps = [
        _step("pulchra", "ex_special", scope="ex_special"),
        _switch("actor"),
        # Basic-scope hits (not Special/EX) — should not trigger the chain
        SimulatedAttackStep(
            agent_id="actor",
            move_name="basic",
            attacks=[_attack(scope="basic")],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="actor",
            move_name="basic",
            attacks=[_attack(scope="basic")],
            conditions=[],
        ),
    ]
    result = simulate(builds, steps, _enemy(), moves_db)
    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 0, (
        f"basic-scope hits should not trigger Pulchra's chain; got {len(as_events)} procs"
    )
