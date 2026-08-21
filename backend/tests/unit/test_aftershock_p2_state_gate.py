"""Task A2 — Hunter's Gait state machine + state-gate predicate.

Tests:
  - test_state_gate_blocks_when_inactive: no proc without state active
  - test_state_window_expiry: hit inside window emits; hit past expiry does not
  - test_state_persists_off_field: state set on Pulchra before switch stays active off-field
"""

from types import SimpleNamespace

from app.data.loaders.moves import AftershockSpec, AgentMovesSpec, MoveBuildupSpec
from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _hit(element: str = "electric", scope: str = "special"):
    """Return a minimal attack object for a Special-scope hit."""
    return SimpleNamespace(
        element=element,
        skill_key="Special",
        damage_base=10_000,
        damage_growth=0,
        name="test_special",
        id="1",
        anomaly_buildup=0,
    )


def _state_gated_spec(state: str = "hunters_gait") -> AftershockSpec:
    """Aftershock spec gated on a named state; only reacts to Special-scope hits."""
    return AftershockSpec(
        react_to=["hit"],
        react_scopes=["special", "ex_special"],
        requires_off_field=True,
        requires_state=state,
        aftershock_mv_bp=4_630,
    )


_ACTOR_SPECIAL_MOVE = MoveBuildupSpec(hits=1, duration_s=1.0, scope="special")


def _moves_db_for_emitter(
    emitter_name: str,
    spec: AftershockSpec,
    actor_name: str = "Actor",
    gait_move: str | None = None,
    state_name: str = "hunters_gait",
    state_dur: float = 6.0,
) -> dict:
    """Build a moves_db with spec on emitter and Special-scope move on actor."""
    emitter_key = emitter_name.lower().replace(" ", "_")
    actor_key = actor_name.lower().replace(" ", "_")
    moves: dict[str, MoveBuildupSpec] = {}
    if gait_move:
        moves[gait_move] = MoveBuildupSpec(
            hits=1,
            duration_s=1.0,
            grants_state=state_name,
            state_duration_s=state_dur,
        )
    db: dict = {emitter_key: AgentMovesSpec(moves=moves, aftershock=spec)}
    # actor needs a move spec so hit_scope is "special" (not the "all" fallback)
    db[actor_key] = AgentMovesSpec(moves={"special": _ACTOR_SPECIAL_MOVE})
    return db


def _step(agent_id: str, move_name: str, *, element: str = "electric") -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=agent_id,
        move_name=move_name,
        attacks=[_hit(element=element)],
        conditions=[],
    )


def _switch_step(agent_id: str) -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=agent_id,
        move_name="switch",
        attacks=[],
        conditions=[],
    )


# ---------------------------------------------------------------------------
# test_state_gate_blocks_when_inactive
# ---------------------------------------------------------------------------


def test_state_gate_blocks_when_inactive():
    """Off-field emitter has requires_state but state was never activated → 0 procs."""
    builds = {
        "actor": _build("Actor"),
        "emitter": _build("Emitter"),
    }
    steps = [
        # actor fires a Special-scope hit but emitter's hunters_gait is never set
        _step("actor", "special"),
    ]
    moves_db = _moves_db_for_emitter("Emitter", _state_gated_spec(), gait_move=None)
    result = simulate(builds, steps, _enemy(), moves_db)

    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 0, "state gate should block all procs when inactive"
    assert result.totals["aftershock"] == 0


# ---------------------------------------------------------------------------
# test_state_window_expiry
# ---------------------------------------------------------------------------


def test_state_window_expiry():
    """Emitter sets hunters_gait for 6s.

    Hit inside the window emits; a hit timed past the 6s window does not.

    Step timing (each step uses duration_s=1.0 from the move spec, hit at t_start+1):
      t=0..1 : emitter performs "ex_special" → grants hunters_gait until t=7
                  (step starts at t=0, hit at t=1, but state set at step start t=0 → until=6)
      Wait: the state is set at step processing. Let's trace:
        * step 0: emitter "ex_special" (duration 1s) → t goes 0→1; state set to until=6
        * step 1: switch to actor
        * step 2: actor "special" at t=2 → hit at t=3 → inside window (3 < 6) → emits
        * step 3: actor 5× "special" (1s each) → hits at t=4..8; last hit at t≈8 > 6 → blocked

    More precisely with 2 actor steps after switch:
      step 0: emitter ex_special, t 0→1, state until=6
      step 1: switch actor, t += 1s
      step 2: actor special, t 2→3, hit at t=3: 3 < 6 → emits  ✓
      step 3: actor special×4 duration so hits spread; use 4 single steps at t=3→7 each 1s
              hits at 4,5,6,7:
                t=4 <6 → emits ✓
                t=5 <6 → emits ✓
                t=6: not strictly < 6 → blocked ✗
                t=7: 7>6 → blocked ✗

    So 3 hits inside window, 2 outside.
    """
    state_dur = 6.0
    builds = {
        "emitter": _build("Emitter"),
        "actor": _build("Actor"),
    }

    steps = [
        # emitter fires its gait-granting move (grants hunters_gait for 6s)
        _step("emitter", "ex_special"),
        # switch to actor
        _switch_step("actor"),
        # actor lands 5 Special hits 1s apart; hits at t=3,4,5,6,7
        _step("actor", "special"),  # hit at t=3 → inside
        _step("actor", "special"),  # hit at t=4 → inside
        _step("actor", "special"),  # hit at t=5 → inside
        _step("actor", "special"),  # hit at t=6 → exactly at boundary (not strictly <6)
        _step("actor", "special"),  # hit at t=7 → outside
    ]

    moves_db = _moves_db_for_emitter(
        "Emitter",
        _state_gated_spec(),
        gait_move="ex_special",
        state_dur=state_dur,
    )
    result = simulate(builds, steps, _enemy(), moves_db)

    as_events = [e for e in result.events if e.kind == "aftershock"]
    # hits at t=3,4,5 are inside (3 procs); t=6 is boundary; t=7 is outside
    # The exact boundary depends on _state_active using until_t > t (strictly greater)
    # So t=6 is blocked (until_t == t == 6 → 6 > 6 is False → blocked).
    assert len(as_events) == 3, (
        f"Expected 3 procs inside 6s window; got {len(as_events)}. "
        f"Hit times: {[e.t for e in result.events if e.kind == 'aftershock']}"
    )
    assert result.totals["aftershock"] > 0


# ---------------------------------------------------------------------------
# test_state_persists_off_field
# ---------------------------------------------------------------------------


def test_state_persists_off_field():
    """State set on emitter persists while emitter is off-field (wall-clock window).

    Sequence:
      t=0..1  emitter fires gait move (state until=6)
      t=1..2  switch to actor
      t=2..3  actor fires Special → hit at t=3 → emitter is off-field, state still active → emits
    """
    builds = {
        "emitter": _build("Emitter"),
        "actor": _build("Actor"),
    }
    steps = [
        _step("emitter", "ex_special"),  # grants hunters_gait until t=6
        _switch_step("actor"),
        _step("actor", "special"),        # hit at t=3 → emitter off-field, state active → emits
    ]
    moves_db = _moves_db_for_emitter(
        "Emitter",
        _state_gated_spec(),
        gait_move="ex_special",
        state_dur=6.0,
    )
    result = simulate(builds, steps, _enemy(), moves_db)

    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 1, "emitter's state should persist while off-field"
    assert as_events[0].agent_id == "emitter"
    assert result.totals["aftershock"] > 0
