"""Task 1 — active_agent state + implicit-switch inference + field_timeline.

Tests are written first (TDD). They must fail before the implementation and
pass after. Parity (damage totals) must be unaffected by the switch machinery.
"""

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockAttack:
    def __init__(
        self,
        *,
        name: str = "hit",
        element: str = "physical",
        damage_base: int = 0,
        damage_growth: int = 0,
        anomaly_buildup: int = 0,
        energy_gain: int = 0,
    ) -> None:
        self.id = None
        self.name = name
        self.element = element
        self.damage_base = damage_base
        self.damage_growth = damage_growth
        self.anomaly_buildup = anomaly_buildup
        self.energy_gain = energy_gain
        self.skill_key = "Basic"


class _MoveSpec:
    def __init__(
        self, *, duration_s: float = 1.0, hits: int = 1, element: str = "physical"
    ) -> None:
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.buildup = 0
        self.scope = "basic"
        self.consolidated = False


class _AgentMoves:
    def __init__(self, moves: dict) -> None:
        self.moves = moves


def _enemy() -> EnemyProfile:
    return EnemyProfile(name="Dummy", level=60, defense=953)


def _build(
    *,
    name: str = "Agent",
    element: str = "physical",
    base_regen: int = 120,
    atk: int = 0,
) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element=element,
        agent_base_atk=atk,
        agent_base_energy_regen=base_regen,
    )


def _step(agent_id: str, move: str = "basic") -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=agent_id,
        move_name=move,
        attacks=[_MockAttack()],
    )


def _moves_db(*agent_ids: str) -> dict:
    return {aid: _AgentMoves({"basic": _MoveSpec(duration_s=1.0, hits=1)}) for aid in agent_ids}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_active_state_inference() -> None:
    """(A,A,B,A) step list → exactly 3 switch events with correct timestamps.

    Switch 1: None→A at t=0 (no 1s charge).
    Switch 2: A→B at t=2.0 (1s charge → clock jumps to 3.0 before B's move).
    Switch 3: B→A at t=4.0 (1s charge → clock jumps to 5.0 before A's move).
    field_timeline records the t when each switch fires (before clock advance).
    """
    a_id, b_id = "agent_a", "agent_b"
    builds = {a_id: _build(name="A"), b_id: _build(name="B")}
    steps = [
        _step(a_id),
        _step(a_id),
        _step(b_id),
        _step(a_id),
    ]
    moves = _moves_db(a_id, b_id)

    result = simulate(builds, steps, _enemy(), moves)

    switch_events = [e for e in result.events if e.kind == "switch"]
    assert len(switch_events) == 3, f"Expected 3 switch events, got {len(switch_events)}"

    # Switch 1: None→A at t=0, no clock advance
    s1 = switch_events[0]
    assert s1.agent_id == a_id
    assert s1.detail["from"] is None
    assert s1.t == pytest.approx(0.0)

    # Switch 2: A→B at t=2.0 (after 2 × 1s steps)
    s2 = switch_events[1]
    assert s2.agent_id == b_id
    assert s2.detail["from"] == a_id
    assert s2.t == pytest.approx(2.0)

    # Switch 3: B→A at t=4.0 (after switch2 1s charge + B's 1s move)
    s3 = switch_events[2]
    assert s3.agent_id == a_id
    assert s3.detail["from"] == b_id
    assert s3.t == pytest.approx(4.0)

    # field_timeline only records real swaps (charge_time=True), not the initial
    # None→agent entry — that would cause phantom OFF_FIELD_OR_5S_AFTER_SWAP injection.
    ft = result.field_timeline
    assert len(ft) == 2
    assert ft[0] == (pytest.approx(2.0), b_id)
    assert ft[1] == (pytest.approx(4.0), a_id)


def test_implicit_switch_costs_1s() -> None:
    """An implicit switch between agents advances the clock by 1s and accrues passive regen.

    Setup: A acts for 1s, then B acts. The A→B switch costs 1s of clock time.
    Passive regen for both agents must accrue during that 1s window.

    Base regen: 120 db = 1.2/s. No ER%. After switch: each agent has 1.2 energy.
    """
    a_id, b_id = "regen_a", "regen_b"
    base_regen = 120  # 1.2/s
    builds = {
        a_id: _build(name="A", base_regen=base_regen),
        b_id: _build(name="B", base_regen=base_regen),
    }
    steps = [_step(a_id), _step(b_id)]
    moves = _moves_db(a_id, b_id)

    result = simulate(builds, steps, _enemy(), moves)

    switch_events = [e for e in result.events if e.kind == "switch"]
    # Switch 1: None→A (no charge). Switch 2: A→B (1s charge).
    assert len(switch_events) == 2
    s2 = switch_events[1]
    assert s2.detail["from"] == a_id
    assert s2.agent_id == b_id

    # Energy after the A→B switch: both agents should have accrued 1.2 energy
    # (passive regen during 1s switch window, ER%=0 so mult=1.0).
    expected_regen = base_regen / 100.0 * 1.0 * 1.0  # 1.2
    final = result.final_energy
    for aid in (a_id, b_id):
        # Each agent gets regen during the 1s switch window.
        # a_id also gets regen during its own 1s step; b_id too.
        # We only assert the switch contributed: final > 0 for both agents.
        assert final[aid] > 0, f"{aid} should have non-zero energy after regen"

    # More precise: the energy_timeline should have an entry at t=2.0 (after switch)
    # reflecting the switch-interval regen before B's move starts.
    # t sequence: step_A starts at 0, ends at 1.0; switch fires at t=1.0,
    # clock advances to 2.0; B's step starts at 2.0, ends at 3.0.
    # energy_timeline entries from the switch: (2.0, a_id, ≈1.2+1.2=2.4), (2.0, b_id, ≈1.2)
    # But we just check both agents got switch-interval regen (energy > step-only baseline).
    # b_id: A-step regen (1.2) + switch regen (1.2) + B-step regen (1.2) = 3.6
    # All agents receive passive regen every interval (authored steps AND switch windows).
    assert final[b_id] == pytest.approx(expected_regen * 3, abs=0.01), (
        f"Expected b_id energy ≈ 3.6, got {final[b_id]:.3f}"
    )


def test_first_step_no_swap_charge() -> None:
    """The opening None→A transition emits a switch event but does NOT charge 1s.

    A single-agent, single-step list: the switch event t should equal 0.0 and
    the step should end at exactly duration_s (no extra 1s from a swap penalty).
    """
    a_id = "solo_a"
    builds = {a_id: _build(name="Solo")}
    steps = [_step(a_id)]
    moves = _moves_db(a_id)

    result = simulate(builds, steps, _enemy(), moves)

    switch_events = [e for e in result.events if e.kind == "switch"]
    assert len(switch_events) == 1, "Exactly one switch event for solo agent (None→A)"

    sw = switch_events[0]
    assert sw.agent_id == a_id
    assert sw.detail["from"] is None
    assert sw.t == pytest.approx(0.0)

    # field_timeline: empty — initial None→agent entry is not recorded (no real swap)
    ft = result.field_timeline
    assert len(ft) == 0

    # All damage events should be at t ≤ 1.0 (no extra 1s from swap penalty).
    hit_events = [e for e in result.events if e.kind == "hit"]
    for ev in hit_events:
        assert ev.t <= 1.0 + 1e-9, (
            f"Hit event at t={ev.t} exceeds expected step end (1.0s) — "
            "first-step switch must not charge 1s"
        )


def test_single_agent_no_extra_switches() -> None:
    """Multi-step single-agent combo → only one switch event (None→A), none after."""
    a_id = "only_a"
    builds = {a_id: _build(name="OnlyA")}
    steps = [_step(a_id), _step(a_id), _step(a_id)]
    moves = _moves_db(a_id)

    result = simulate(builds, steps, _enemy(), moves)

    switch_events = [e for e in result.events if e.kind == "switch"]
    assert len(switch_events) == 1, (
        f"Single-agent multi-step should have exactly one switch (None→A), "
        f"got {len(switch_events)}"
    )
    assert switch_events[0].detail["from"] is None
    assert switch_events[0].agent_id == a_id


def test_field_timeline_tracks_agent_identity() -> None:
    """field_timeline entries carry the correct agent_id strings."""
    a_id, b_id = "fa", "fb"
    builds = {a_id: _build(name="FA"), b_id: _build(name="FB")}
    steps = [_step(a_id), _step(b_id)]
    moves = _moves_db(a_id, b_id)

    result = simulate(builds, steps, _enemy(), moves)

    ft = result.field_timeline
    # Only the real A→B swap is recorded; the initial None→A entry is excluded.
    assert len(ft) == 1
    assert ft[0][1] == b_id
    # Real swap fires at t=1.0 (after A's 1s step)
    assert ft[0][0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Task 2 tests — authorable explicit switch combo step
# ---------------------------------------------------------------------------


def _switch_step(agent_id: str) -> SimulatedAttackStep:
    """An explicit switch marker step (no attacks)."""
    return SimulatedAttackStep(agent_id=agent_id, move_name="switch", attacks=[])


def test_explicit_switch_step() -> None:
    """Authorable {agent_id: B, move_name: 'switch'} between A-steps.

    Expectations:
    - active_agent changes to B
    - exactly one switch event emitted (A→B)
    - clock advances 1s (with passive regen)
    - zero damage from the switch step itself
    - subsequent B step runs at t = t_switch + 1s (swap cost)
    """
    a_id, b_id = "exp_a", "exp_b"
    builds = {a_id: _build(name="EA"), b_id: _build(name="EB", base_regen=120)}
    moves = _moves_db(a_id, b_id)

    steps = [
        _step(a_id),  # t=0..1 on A
        _switch_step(b_id),  # explicit switch A→B at t=1 (+1s charge)
        _step(b_id),  # t=2..3 on B
    ]

    result = simulate(builds, steps, _enemy(), moves)

    switch_events = [e for e in result.events if e.kind == "switch"]
    # None→A (implicit) + A→B (explicit)
    assert len(switch_events) == 2

    explicit_sw = switch_events[1]
    assert explicit_sw.agent_id == b_id
    assert explicit_sw.detail["from"] == a_id
    assert explicit_sw.t == pytest.approx(1.0)

    # B's hit lands at end of B's step: t_switch(1.0) + swap_cost(1.0) + step_duration(1.0) = 3.0
    b_hits = [e for e in result.events if e.kind == "hit" and e.agent_id == b_id]
    assert b_hits, "Expected at least one hit from B"
    assert b_hits[0].t == pytest.approx(3.0)

    # field_timeline: only real swaps; None→A is excluded, A→B(explicit) is recorded
    ft = result.field_timeline
    assert len(ft) == 1
    assert ft[0] == (pytest.approx(1.0), b_id)


def test_redundant_switch_warning() -> None:
    """Switch to already-active agent: emits a warning, no event, no clock advance."""
    a_id = "red_a"
    builds = {a_id: _build(name="RedA")}
    moves = _moves_db(a_id)

    steps = [
        _step(a_id),  # t=0..1 on A
        _switch_step(a_id),  # redundant: A is already active
        _step(a_id),  # t=1..2 (no extra 1s)
    ]

    result = simulate(builds, steps, _enemy(), moves)

    switch_events = [e for e in result.events if e.kind == "switch"]
    # Only None→A; the redundant switch must NOT emit an event
    assert len(switch_events) == 1

    # A warning must mention the redundant switch
    assert any("redundant" in w.lower() or "already" in w.lower() for w in result.warnings), (
        f"Expected redundant-switch warning, got: {result.warnings}"
    )

    # Clock must not advance an extra 1s from redundant switch.
    # Step 1 hit at t=1.0 (end of 1s move), step 3 hit at t=2.0 (no gap from redundant switch).
    # If the switch incorrectly charged 1s, step 3 would hit at t=3.0.
    a_hits = [e for e in result.events if e.kind == "hit" and e.agent_id == a_id]
    assert len(a_hits) == 2
    assert a_hits[0].t == pytest.approx(1.0)
    assert a_hits[1].t == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Task 3 tests — on_field annotation on damage events
# ---------------------------------------------------------------------------


class _MockAttackWithBuildup(_MockAttack):
    def __init__(self, *, anomaly_buildup: int = 10000, **kwargs) -> None:  # type: ignore[override]
        super().__init__(**kwargs)
        self.anomaly_buildup = anomaly_buildup


def test_on_field_flag() -> None:
    """Every hit/anomaly event for the acting agent carries detail['on_field'] is True.

    Engine-emitted derived events (disorder, vortex, anomaly_tick) must NOT get on_field.
    """
    a_id = "onf_a"
    # Use enough buildup to trigger a physical anomaly (Assault) on the first hit.
    # Threshold = capacity(100) * 100 = 10000 buildup units.
    builds = {a_id: _build(name="A", element="physical", atk=1000)}
    moves = {
        a_id: _AgentMoves(
            {
                "buildup": _MoveSpec(duration_s=1.0, hits=1, element="physical"),
            }
        )
    }
    step = SimulatedAttackStep(
        agent_id=a_id,
        move_name="buildup",
        attacks=[_MockAttackWithBuildup(element="physical", anomaly_buildup=10000)],
    )

    result = simulate(builds, [step], _enemy(), moves)

    hit_events = [e for e in result.events if e.kind == "hit"]
    anomaly_events = [e for e in result.events if e.kind == "anomaly"]

    assert hit_events, "Expected at least one hit event"
    for e in hit_events:
        assert e.detail.get("on_field") is True, (
            f"hit event at t={e.t} missing on_field=True (detail={e.detail})"
        )

    assert anomaly_events, "Expected at least one anomaly event (Assault trigger)"
    for e in anomaly_events:
        assert e.detail.get("on_field") is True, (
            f"anomaly event at t={e.t} missing on_field=True (detail={e.detail})"
        )

    # Derived events must NOT have on_field
    for e in result.events:
        if e.kind in ("disorder", "vortex", "anomaly_tick"):
            assert "on_field" not in e.detail, (
                f"{e.kind} event at t={e.t} should not have on_field"
            )


# ---------------------------------------------------------------------------
# Task 5 tests — validation & edge cases
# ---------------------------------------------------------------------------


def test_leading_switch() -> None:
    """Explicit switch step as the very first step: from=None, active_agent set to target.

    An explicit leading switch calls _apply_switch(charge_time=True), so the clock
    advances 1s before the first damage step — unlike an implicit leading switch (None→A
    via damage step) which does not charge.
    """
    a_id, b_id = "lead_a", "lead_b"
    builds = {a_id: _build(name="LA"), b_id: _build(name="LB", base_regen=120)}
    moves = _moves_db(a_id, b_id)

    steps = [
        _switch_step(b_id),  # explicit leading switch — active_agent was None
        _step(b_id),  # B acts after the switch
    ]

    result = simulate(builds, steps, _enemy(), moves)

    switch_events = [e for e in result.events if e.kind == "switch"]
    # Only one switch: the explicit leading switch (None→B). No implicit switch for B's damage
    # step since B is already active_agent.
    assert len(switch_events) == 1

    sw = switch_events[0]
    assert sw.agent_id == b_id
    assert sw.detail["from"] is None, "Leading switch must carry from=None"
    assert sw.t == pytest.approx(0.0)

    # field_timeline: one entry (the leading switch)
    ft = result.field_timeline
    assert len(ft) == 1
    assert ft[0] == (pytest.approx(0.0), b_id)

    # Explicit switch always charges 1s, so B's hit lands at t=2.0 (1s switch + 1s move)
    b_hits = [e for e in result.events if e.kind == "hit" and e.agent_id == b_id]
    assert b_hits, "Expected at least one hit from B"
    assert b_hits[0].t == pytest.approx(2.0), (
        "Explicit leading switch charges 1s — B's hit should land at t=2.0"
    )


def test_back_to_back_switches() -> None:
    """Two consecutive explicit switch steps each emit a switch event and each advance clock 1s."""
    a_id, b_id, c_id = "bbs_a", "bbs_b", "bbs_c"
    builds = {
        a_id: _build(name="A"),
        b_id: _build(name="B"),
        c_id: _build(name="C", base_regen=120),
    }
    moves = _moves_db(a_id, b_id, c_id)

    steps = [
        _step(a_id),  # t=0..1, implicit None→A (no charge)
        _switch_step(b_id),  # t=1: explicit A→B (+1s → t=2)
        _switch_step(c_id),  # t=2: explicit B→C (+1s → t=3)
        _step(c_id),  # t=3..4
    ]

    result = simulate(builds, steps, _enemy(), moves)

    switch_events = [e for e in result.events if e.kind == "switch"]
    # Three switch events: implicit None→A, explicit A→B, explicit B→C
    assert len(switch_events) == 3

    s_none_a, s_a_b, s_b_c = switch_events

    assert s_none_a.agent_id == a_id
    assert s_none_a.detail["from"] is None
    assert s_none_a.t == pytest.approx(0.0)

    assert s_a_b.agent_id == b_id
    assert s_a_b.detail["from"] == a_id
    assert s_a_b.t == pytest.approx(1.0)

    assert s_b_c.agent_id == c_id
    assert s_b_c.detail["from"] == b_id
    assert s_b_c.t == pytest.approx(2.0)

    # C's hit lands at t=4.0 (A 1s + A→B switch 1s + B→C switch 1s + C step 1s)
    c_hits = [e for e in result.events if e.kind == "hit" and e.agent_id == c_id]
    assert c_hits, "Expected at least one hit from C"
    assert c_hits[0].t == pytest.approx(4.0)

    # field_timeline: two real swaps only (implicit None→A is excluded)
    ft = result.field_timeline
    assert len(ft) == 2
    assert ft[0] == (pytest.approx(1.0), b_id)
    assert ft[1] == (pytest.approx(2.0), c_id)
