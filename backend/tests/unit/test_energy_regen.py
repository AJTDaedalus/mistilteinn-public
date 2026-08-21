"""Energy regen / accounting keystone tests — Gap G-A.

Task 1: pin scale factors and write a failing closed-form test.

Scale factors verified from DB + snapshot_builder.py:
  base_energy_regen  : DB int (e.g. 120) ÷ 100     → energy/s   (120 → 1.20/s)
  energy_gain        : DB int (e.g. 24150) ÷ 10000  → energy/hit (24150 → 2.415)
  ER% stat           : BP ÷ 10000                   → multiplier (6000 → 0.60 = 60%)

Cross-references:
  - snapshot_builder.py:90 ("enerRegen","energy_regen",10000) confirms ÷10000 for ER%.
  - Nanoka sp_recovery values (Anby Basic: 51260) match community per-hit energy values
    when divided by 10000 (5.126 per hit), consistent with standard ZZZ regen rates.
  - base_energy_regen=120 for all standard agents → 1.20/s passive matches ZZZ wiki base rate.
  - ER% scales passive regen only (not per-hit gain) — OQ-1 resolved to community consensus
    (passive-only); documented here pending a hard cross-reference.
"""

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import (
    SimulatedAttackStep,
    simulate,
)
from app.services.build_damage_service import BuildSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockAttack:
    """Minimal duck-type of a DB Attack model."""

    def __init__(
        self,
        *,
        name: str = "test_hit",
        element: str = "physical",
        damage_base: int = 0,
        energy_gain: int = 0,
        anomaly_buildup: int = 0,
    ) -> None:
        self.name = name
        self.element = element
        self.damage_base = damage_base
        self.energy_gain = energy_gain
        self.anomaly_buildup = anomaly_buildup


class _MoveSpec:
    """Minimal duck-type of an ORM MoveSpec."""

    def __init__(
        self, *, duration_s: float, hits: int, element: str = "physical", scope: str = "basic"
    ) -> None:
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.buildup = 0


class _AgentMovesSpec:
    def __init__(self, moves: dict) -> None:
        self.moves = moves


def _base_enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Training Dummy",
        level=60,
        defense=953,
    )


# ---------------------------------------------------------------------------
# Scale-factor constants (pinned by this test)
# ---------------------------------------------------------------------------
_BASE_REGEN_SCALE = 100  # DB int ÷ 100 → energy/s
_ENERGY_GAIN_SCALE = 10_000  # DB int ÷ 10000 → energy/hit
_ER_SCALE = 10_000  # ER% stat BP ÷ 10000 → decimal multiplier


# ---------------------------------------------------------------------------
# Closed-form hand-computed expectation
# ---------------------------------------------------------------------------
# Agent: anby (1 agent, single acting agent across both steps)
#   base_energy_regen = 120 (DB)  →  1.20 energy/s
#   ER%               = 6000 (BP) →  +60%
#
# Step 1: duration_s=2.0, one hit with energy_gain=24150
#   passive  = (120/100) × (1 + 6000/10000) × 2.0 = 1.20 × 1.60 × 2.0 = 3.840
#   on-hit   = 24150 / 10000                                             = 2.415
#   bank     = 0.0 + 3.840 + 2.415                                       = 6.255
#
# Step 2: duration_s=1.5, one hit with energy_gain=51260
#   passive  = (120/100) × (1 + 6000/10000) × 1.5 = 1.20 × 1.60 × 1.5 = 2.880
#   on-hit   = 51260 / 10000                                             = 5.126
#   bank     = 6.255 + 2.880 + 5.126                                     = 14.261

_BASE_ENERGY_REGEN_DB = 120
_ER_PCT_DB = 6000
_STEP1_DURATION = 2.0
_STEP1_ENERGY_GAIN_DB = 24_150  # Anby Basic hit (DB value, confirmed)
_STEP2_DURATION = 1.5
_STEP2_ENERGY_GAIN_DB = 51_260  # Anby Basic final hit (DB value, confirmed)

_base_regen_per_s = _BASE_ENERGY_REGEN_DB / _BASE_REGEN_SCALE  # 1.20
_er_mult = 1 + _ER_PCT_DB / _ER_SCALE  # 1.60

_expected_after_step1 = (
    _base_regen_per_s * _er_mult * _STEP1_DURATION  # 3.840
    + _STEP1_ENERGY_GAIN_DB / _ENERGY_GAIN_SCALE  # 2.415
)  # 6.255

_expected_after_step2 = _expected_after_step1 + (
    _base_regen_per_s * _er_mult * _STEP2_DURATION  # 2.880
    + _STEP2_ENERGY_GAIN_DB / _ENERGY_GAIN_SCALE  # 5.126
)  # 14.261


def test_energy_closed_form_two_step_rotation() -> None:
    """Verify energy bank against a hand-computed 2-step rotation.

    Pins all three scale factors: ÷100 (base regen), ÷10000 (per-hit gain),
    ÷10000 (ER% stat).  ER% must scale passive regen only (not on-hit gain).

    Should go green when Tasks 2, 3, and 4 are complete.
    """
    anby_id = "anby"

    build = BuildSnapshot(
        agent_name="Anby",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=0,  # damage doesn't matter for energy tracking
        agent_base_energy_regen=_BASE_ENERGY_REGEN_DB,  # Task 2 adds this field
        agent_energy_regen=_ER_PCT_DB,  # Task 2 also wires this
    )

    moves_db = {
        anby_id: _AgentMovesSpec(
            {
                "basic_s1": _MoveSpec(duration_s=_STEP1_DURATION, hits=1),
                "basic_s2": _MoveSpec(duration_s=_STEP2_DURATION, hits=1),
            }
        )
    }

    steps = [
        SimulatedAttackStep(
            agent_id=anby_id,
            move_name="basic_s1",
            attacks=[_MockAttack(energy_gain=_STEP1_ENERGY_GAIN_DB)],
        ),
        SimulatedAttackStep(
            agent_id=anby_id,
            move_name="basic_s2",
            attacks=[_MockAttack(energy_gain=_STEP2_ENERGY_GAIN_DB)],
        ),
    ]

    result = simulate({anby_id: build}, steps, _base_enemy(), moves_db)

    # Task 6 adds final_energy to SimulationResult
    final = result.final_energy  # type: ignore[attr-defined]

    assert final[anby_id] == pytest.approx(_expected_after_step2, abs=0.01), (
        f"Expected energy ≈ {_expected_after_step2:.3f}, got {final[anby_id]:.3f}. "
        "Check scale factors: base_regen ÷100, energy_gain ÷10000, ER% ÷10000."
    )


def test_er_pct_scales_passive_only() -> None:
    """ER% must scale passive regen, not per-hit energy_gain.

    Two identical rotations differing only in ER% (0 vs 60%).
    The delta must equal the passive regen contribution only:
      delta = base_regen_per_s * er_pct_decimal * total_duration
    """
    anby_id = "anby"
    duration = 3.0
    er_pct_0 = 0
    er_pct_60 = 6_000  # BP → 60%
    energy_gain_db = 30_000  # 3.0 per hit

    def _run(er_pct_db: int) -> float:
        build = BuildSnapshot(
            agent_name="Anby",
            agent_element="electric",
            agent_level=60,
            agent_base_atk=0,
            agent_base_energy_regen=_BASE_ENERGY_REGEN_DB,
            agent_energy_regen=er_pct_db,
        )
        moves_db = {anby_id: _AgentMovesSpec({"m": _MoveSpec(duration_s=duration, hits=1)})}
        steps = [
            SimulatedAttackStep(
                agent_id=anby_id,
                move_name="m",
                attacks=[_MockAttack(energy_gain=energy_gain_db)],
            )
        ]
        r = simulate({anby_id: build}, steps, _base_enemy(), moves_db)
        return r.final_energy[anby_id]  # type: ignore[attr-defined]

    energy_0 = _run(er_pct_0)
    energy_60 = _run(er_pct_60)

    # on-hit gain is the same for both; only passive differs
    expected_passive_delta = (
        _BASE_ENERGY_REGEN_DB
        / _BASE_REGEN_SCALE  # 1.20/s
        * (er_pct_60 / _ER_SCALE)  # × 0.60
        * duration  # × 3.0
    )  # = 2.16

    actual_delta = energy_60 - energy_0
    assert actual_delta == pytest.approx(expected_passive_delta, abs=0.01), (
        f"ER% delta: expected {expected_passive_delta:.3f}, got {actual_delta:.3f}. "
        "If delta includes on-hit, ER% is incorrectly scaling energy_gain."
    )


# ---------------------------------------------------------------------------
# Task 3 — passive regen (no on-hit energy yet)
# ---------------------------------------------------------------------------


def _make_build(agent_name: str, base_regen: int, er_pct_db: int = 0) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=agent_name,
        agent_element="physical",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=base_regen,
        agent_energy_regen=er_pct_db,
    )


def test_passive_regen_multi_agent() -> None:
    """Both agents in a team accrue passive energy independently each step."""
    a_id, b_id = "agent_a", "agent_b"
    duration = 2.0

    build_a = _make_build("Agent A", base_regen=120)  # 1.20/s, no ER%
    build_b = _make_build("Agent B", base_regen=100)  # 1.00/s, no ER%

    moves_db = {
        "agent_a": _AgentMovesSpec({"move": _MoveSpec(duration_s=duration, hits=1)}),
        "agent_b": _AgentMovesSpec({"move": _MoveSpec(duration_s=duration, hits=1)}),
    }
    steps = [
        SimulatedAttackStep(agent_id=a_id, move_name="move", attacks=[]),
        SimulatedAttackStep(agent_id=b_id, move_name="move", attacks=[]),
    ]

    result = simulate({a_id: build_a, b_id: build_b}, steps, _base_enemy(), moves_db)

    # Total clock time: step_a (2s) + agent_a→agent_b switch (1s) + step_b (2s) = 5s.
    # Both agents accrue passive regen during ALL intervals (steps and switch window).
    expected_a = (120 / 100) * 1.0 * 5.0  # 6.00
    expected_b = (100 / 100) * 1.0 * 5.0  # 5.00

    assert result.final_energy[a_id] == pytest.approx(expected_a, abs=0.01)
    assert result.final_energy[b_id] == pytest.approx(expected_b, abs=0.01)


def test_passive_regen_does_not_affect_damage_output() -> None:
    """events / totals / per_agent_attribution must be byte-identical to pre-Task-3 behaviour.

    A zero-base-regen agent is used so energy tracking makes no observable change
    beyond the final_energy field itself.
    """
    agent_id = "anby"
    build = BuildSnapshot(
        agent_name="Anby",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=0,  # no passive regen → energy stays 0
    )
    moves_db = {"anby": _AgentMovesSpec({"m": _MoveSpec(duration_s=1.0, hits=1)})}
    steps = [SimulatedAttackStep(agent_id=agent_id, move_name="m", attacks=[])]

    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)

    # Damage output fields unchanged
    assert result.totals == {
        "standard": 0,
        "anomaly": 0,
        "disorder": 0,
        "vortex": 0,
        "abloom": 0,
        "aftershock": 0,
        "kit_formula": 0,  # Task 21 (C3) — kit `formulas[]` damage instances
        "luminize": 0,  # Task 14 (Remielle DESIGN §7.2) — Luminize instances
        "phase_flow": 0,  # Task 15 (Remielle DESIGN §7.3) — Phase Flow EV ticks
        "total": 0,
    }
    assert result.per_agent_attribution == {agent_id: 0}
    # Energy field exists and is zero (no base regen)
    assert result.final_energy == {agent_id: pytest.approx(0.0)}


# ---------------------------------------------------------------------------
# Task 5 — EX spend + cost table
# ---------------------------------------------------------------------------
# Scale: default EX cost = 60 energy (EX_COST_DEFAULT from anomaly_simulator.py).
# ex_energy_cost is now set directly on BuildSnapshot — no name-based lookup.
_EX_COST_DEFAULT = 60  # must match anomaly_simulator.EX_COST_DEFAULT
# Dimbreath-verified; energy_costs.py had 40, which was wrong.
_ANBY_EX_COST = 60  # matches EX_COST_DEFAULT


def test_ex_special_deducts_cost() -> None:
    """EX Special step deducts the DB cost from the acting agent's bank.

    Rotation: fill step (scope=basic) → EX step (scope=ex_special).
    base_regen=6000 (60/s).  Each step 1 second → each adds 60 energy.

    Fill:  0 → 60 (passive regen only)
    EX:    60 − 60 (EX cost) = 0, then passive +60 → 60 final.
    """
    # agent_id must equal agent_name.lower().replace(" ","_") for moves_db lookup
    agent_id = "test_agent"
    build = BuildSnapshot(
        agent_name="Test Agent",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=6_000,  # 6000/100 = 60 energy/s
        ex_energy_cost=60,
    )
    moves_db = {
        agent_id: _AgentMovesSpec(
            {
                "fill": _MoveSpec(duration_s=1.0, hits=1, scope="basic"),
                "ex": _MoveSpec(duration_s=1.0, hits=1, scope="ex_special"),
            }
        )
    }
    steps = [
        SimulatedAttackStep(agent_id=agent_id, move_name="fill", attacks=[]),
        SimulatedAttackStep(agent_id=agent_id, move_name="ex", attacks=[]),
    ]
    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)
    # Fill: +60 → 60; EX: −60 +60 → 60
    assert result.final_energy[agent_id] == pytest.approx(60.0, abs=0.05)


def test_ex_curated_agent_uses_table_cost() -> None:
    """Anby's Dimbreath-verified EX cost (60) is used via BuildSnapshot.ex_energy_cost.

    Rotation: fill 1s (60/s) → EX step 1s.
    base_regen=6000 → 60/s.  Fill gives 60.  EX: −60 +60 → 60.
    """
    agent_id = "anby"
    build = BuildSnapshot(
        agent_name="Anby",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=6_000,  # 6000/100 = 60 energy/s
        ex_energy_cost=_ANBY_EX_COST,  # 60 — Dimbreath-verified
    )
    moves_db = {
        agent_id: _AgentMovesSpec(
            {
                "fill": _MoveSpec(duration_s=1.0, hits=1, scope="basic"),
                "ex": _MoveSpec(duration_s=1.0, hits=1, scope="ex_special"),
            }
        )
    }
    steps = [
        SimulatedAttackStep(agent_id=agent_id, move_name="fill", attacks=[]),
        SimulatedAttackStep(agent_id=agent_id, move_name="ex", attacks=[]),
    ]
    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)
    # Fill: +60 → 60; EX: −60 +60 → 60
    assert result.final_energy[agent_id] == pytest.approx(float(_ANBY_EX_COST), abs=0.05)


def test_ex_db_cost_reflected_in_event_detail() -> None:
    """energy_spend event detail.cost equals the BuildSnapshot.ex_energy_cost value.

    Uses a custom cost (45) to verify the DB value flows end-to-end into the
    TimelineEvent, not the EX_COST_DEFAULT.
    """
    agent_id = "velina"
    build = BuildSnapshot(
        agent_name="Velina",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=4_500,  # 45/s so fill → exactly 45
        ex_energy_cost=45,
    )
    moves_db = {
        agent_id: _AgentMovesSpec(
            {
                "fill": _MoveSpec(duration_s=1.0, hits=1, scope="basic"),
                "ex": _MoveSpec(duration_s=1.0, hits=1, scope="ex_special"),
            }
        )
    }
    steps = [
        SimulatedAttackStep(agent_id=agent_id, move_name="fill", attacks=[]),
        SimulatedAttackStep(agent_id=agent_id, move_name="ex", attacks=[]),
    ]
    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)

    spend_events = [e for e in result.events if e.kind == "energy_spend"]
    assert len(spend_events) == 1
    ev = spend_events[0]
    assert ev.detail["cost"] == 45, f"Expected cost=45 in event, got {ev.detail['cost']!r}"
    # Bank: 0 +45 (fill) −45 (EX) +45 (EX regen) = 45
    assert result.final_energy[agent_id] == pytest.approx(45.0, abs=0.05)


def test_ex_null_cost_warns_and_falls_back() -> None:
    """NULL ex_energy_cost emits a named warning and falls back to EX_COST_DEFAULT (60)."""
    agent_id = "no_energy_agent"
    build = BuildSnapshot(
        agent_name="No Energy Agent",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=6_000,  # 60/s
        ex_energy_cost=None,  # simulates a non-Energy primary or missing DB row
    )
    moves_db = {
        agent_id: _AgentMovesSpec(
            {
                "fill": _MoveSpec(duration_s=1.0, hits=1, scope="basic"),
                "ex": _MoveSpec(duration_s=1.0, hits=1, scope="ex_special"),
            }
        )
    }
    steps = [
        SimulatedAttackStep(agent_id=agent_id, move_name="fill", attacks=[]),
        SimulatedAttackStep(agent_id=agent_id, move_name="ex", attacks=[]),
    ]
    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)

    # Must warn — not a silent deduction
    assert any("ex_energy_cost" in w and "NULL" in w for w in result.warnings), (
        "Expected a NULL ex_energy_cost warning; got: " + str(result.warnings)
    )
    # Falls back to EX_COST_DEFAULT=60: fill +60 → 60; EX −60 +60 → 60
    assert result.final_energy[agent_id] == pytest.approx(60.0, abs=0.05)


def test_ex_spend_clamps_to_zero() -> None:
    """EX Special with insufficient energy clamps bank to 0 and issues a warning."""
    agent_id = "test_agent"
    build = BuildSnapshot(
        agent_name="Test Agent",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=0,  # no passive → stays at 0
        ex_energy_cost=60,
    )
    moves_db = {
        agent_id: _AgentMovesSpec(
            {
                "ex": _MoveSpec(duration_s=0.001, hits=1, scope="ex_special"),
            }
        )
    }
    steps = [SimulatedAttackStep(agent_id=agent_id, move_name="ex", attacks=[])]
    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)

    assert result.final_energy[agent_id] >= 0.0
    assert result.final_energy[agent_id] == pytest.approx(0.0, abs=0.01)
    assert any("energy" in w.lower() for w in result.warnings), (
        "Expected a warning for insufficient EX energy; got: " + str(result.warnings)
    )


def test_basic_step_no_energy_spend() -> None:
    """Basic step (scope=basic) must not deduct energy."""
    agent_id = "test_agent"
    build = BuildSnapshot(
        agent_name="Test Agent",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=6_000,
    )
    moves_db = {agent_id: _AgentMovesSpec({"m": _MoveSpec(duration_s=1.0, hits=1, scope="basic")})}
    steps = [SimulatedAttackStep(agent_id=agent_id, move_name="m", attacks=[])]
    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)
    # Only passive regen — no EX deduction
    assert result.final_energy[agent_id] == pytest.approx(60.0, abs=0.05)


# ---------------------------------------------------------------------------
# Task 6 — energy_timeline surface tests
# ---------------------------------------------------------------------------


def test_energy_timeline_populated_after_step() -> None:
    """energy_timeline must contain at least one entry per step."""
    agent_id = "test_agent"
    build = BuildSnapshot(
        agent_name="Test Agent",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=120,
    )
    moves_db = {agent_id: _AgentMovesSpec({"m": _MoveSpec(duration_s=1.0, hits=1, scope="basic")})}
    steps = [SimulatedAttackStep(agent_id=agent_id, move_name="m", attacks=[])]
    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)

    assert hasattr(result, "energy_timeline"), "SimulationResult must expose energy_timeline"
    assert len(result.energy_timeline) > 0
    # Each entry: (t: float, agent_id: str, energy: float)
    t, aid, e = result.energy_timeline[0]
    assert isinstance(t, float)
    assert aid == agent_id
    assert isinstance(e, float)


def test_energy_timeline_monotone_t() -> None:
    """energy_timeline entries must be in non-decreasing time order."""
    agent_id = "test_agent"
    build = BuildSnapshot(
        agent_name="Test Agent",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=120,
    )
    moves_db = {
        agent_id: _AgentMovesSpec(
            {
                "a": _MoveSpec(duration_s=1.0, hits=1, scope="basic"),
                "b": _MoveSpec(duration_s=1.0, hits=1, scope="basic"),
                "c": _MoveSpec(duration_s=1.0, hits=1, scope="basic"),
            }
        )
    }
    steps = [
        SimulatedAttackStep(agent_id=agent_id, move_name="a", attacks=[]),
        SimulatedAttackStep(agent_id=agent_id, move_name="b", attacks=[]),
        SimulatedAttackStep(agent_id=agent_id, move_name="c", attacks=[]),
    ]
    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)

    ts = [entry[0] for entry in result.energy_timeline]
    assert ts == sorted(ts), "energy_timeline t values must be non-decreasing"


def test_energy_timeline_ex_spend_event() -> None:
    """An EX step must emit a kind='energy_spend' TimelineEvent."""
    agent_id = "anby"
    build = BuildSnapshot(
        agent_name="Anby",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=120,
        ex_energy_cost=40,
    )
    moves_db = {
        agent_id: _AgentMovesSpec(
            {
                "ex": _MoveSpec(duration_s=0.5, hits=1, scope="ex_special"),
            }
        )
    }
    steps = [SimulatedAttackStep(agent_id=agent_id, move_name="ex", attacks=[])]
    result = simulate({agent_id: build}, steps, _base_enemy(), moves_db)

    spend_events = [e for e in result.events if e.kind == "energy_spend"]
    assert len(spend_events) == 1, (
        f"Expected 1 energy_spend event for EX step, got {len(spend_events)}"
    )
    ev = spend_events[0]
    assert ev.agent_id == agent_id
    # detail carries the cost that was deducted
    assert "cost" in ev.detail


def test_energy_timeline_default_empty_for_no_steps() -> None:
    """energy_timeline defaults to empty list when no steps are run."""
    agent_id = "test_agent"
    build = BuildSnapshot(
        agent_name="Test Agent",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=120,
    )
    result = simulate({agent_id: build}, [], _base_enemy(), {})

    assert result.energy_timeline == []


# ---------------------------------------------------------------------------
# Task 7 — Orphie ≥60 validation + ER% ranking sanity
# ---------------------------------------------------------------------------
# DB-verified energy_gain values for Orphie & Magus (fairy DB as of 2026-06-13):
#   Basic Attack: High-Pressure Flamethrower — 6 hits with energy_gain:
#     hit 0: 3830, hit 1: 10580, hit 2: 8290, hit 3: 17540, hit 4: 38670, hit 5: 33900
#   Sum = 112810  →  11.281 energy per full basic chain (÷10000 scale)
#
# Skill duration: ~4.0 s per basic chain (community estimate; no duration column in DB).
# base_energy_regen = 120 (DB) → 1.20 energy/s passive.
#
# 4-chain rotation (16 s total):
#   on-hit total = 4 × 11.281 = 45.124
#   passive      = 1.20/s × 16 s = 19.20  (ER%=0)
#   bank         ≈ 64.32  ≥ 60  (core threshold)
#
# ER%=60% (6000 BP) extra passive = 1.20 × 0.60 × 16 = 11.52
#   bank_60er ≈ 75.84 vs bank_0er ≈ 64.32  → diff = 11.52

# Orphie DB energy_gain values per hit (verified against fairy DB 2026-06-13)
_ORPHIE_BASIC_ENERGY_GAINS = [3830, 10580, 8290, 17540, 38670, 33900]
_ORPHIE_BASIC_DURATION_S = 4.0  # community estimate; ~4s per full chain
_ORPHIE_BASE_REGEN_DB = 120  # DB value
_ORPHIE_AGENT_ID = "orphie_magus"  # matches _agent_key("Orphie & Magus") → re.sub(\W+,"_",name)


def _orphie_rotation_steps(
    n_chains: int = 4,
) -> tuple[
    dict[str, "BuildSnapshot"],
    list["SimulatedAttackStep"],
    dict,
]:
    """Build a minimal Orphie rotation of n_chains basic attack chains."""
    attacks = [
        _MockAttack(name=f"basic_h{i}", element="fire", energy_gain=g)
        for i, g in enumerate(_ORPHIE_BASIC_ENERGY_GAINS)
    ]
    moves: dict[str, _MoveSpec] = {}
    steps: list[SimulatedAttackStep] = []
    for i in range(n_chains):
        key = f"basic_{i}"
        moves[key] = _MoveSpec(
            duration_s=_ORPHIE_BASIC_DURATION_S,
            hits=len(_ORPHIE_BASIC_ENERGY_GAINS),
            element="fire",
            scope="basic",
        )
        steps.append(
            SimulatedAttackStep(
                agent_id=_ORPHIE_AGENT_ID,
                move_name=key,
                attacks=attacks,
            )
        )
    build = BuildSnapshot(
        agent_name="Orphie & Magus",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=0,
        agent_base_energy_regen=_ORPHIE_BASE_REGEN_DB,
    )
    moves_db = {_ORPHIE_AGENT_ID: _AgentMovesSpec(moves)}
    return {_ORPHIE_AGENT_ID: build}, steps, moves_db


def test_orphie_4chain_rotation_reaches_threshold() -> None:
    """4 full basic chains must push Orphie's energy bank to ≥60.

    This is the threshold that Orphie's core passive gates on.
    Energy sources: passive regen (1.20/s) + on-hit gain from each hit.
    DB-verified energy_gain values used (see module header above).

    Expected bank ≈ 64.32:
      on-hit  = 4 × 11.281 = 45.124
      passive = 1.20/s × 16 s = 19.200
    """
    builds, steps, moves_db = _orphie_rotation_steps(n_chains=4)
    result = simulate(builds, steps, _base_enemy(), moves_db)

    bank = result.final_energy[_ORPHIE_AGENT_ID]
    assert bank >= 60.0, (
        f"Orphie energy after 4 basic chains = {bank:.2f}; expected ≥ 60. "
        "Core passive threshold not reached — check energy_gain scale or passive regen."
    )


def test_er_pct_ranking_sanity() -> None:
    """Builds differing ONLY in ER% must produce different end-of-rotation energy.

    This proves ER% is no longer a no-op (was a known modelling gap — see
    project_energy_regen memory).  Uses Orphie's rotation for a realistic scenario.

    ER%=0 vs ER%=60 (6000 BP) over 16 s:
      expected extra passive = 1.20/s × 0.60 × 16 s = 11.52 energy
    """
    _er_60_db = 6_000  # 60% ER stat in BP

    def _run_er(er_pct_db: int) -> float:
        _, steps, moves_db = _orphie_rotation_steps(n_chains=4)
        # override the build to inject ER%
        build = BuildSnapshot(
            agent_name="Orphie & Magus",
            agent_element="fire",
            agent_level=60,
            agent_base_atk=0,
            agent_base_energy_regen=_ORPHIE_BASE_REGEN_DB,
            agent_energy_regen=er_pct_db,
        )
        result = simulate({_ORPHIE_AGENT_ID: build}, steps, _base_enemy(), moves_db)
        return result.final_energy[_ORPHIE_AGENT_ID]

    energy_0 = _run_er(0)
    energy_60 = _run_er(_er_60_db)

    expected_er_delta = (
        _ORPHIE_BASE_REGEN_DB
        / _BASE_REGEN_SCALE  # 1.20/s
        * (_er_60_db / _ER_SCALE)  # × 0.60
        * (4 * _ORPHIE_BASIC_DURATION_S)  # × 16 s
    )  # = 11.52

    actual_delta = energy_60 - energy_0
    assert actual_delta > 0, (
        f"ER%=60 build produced no more energy than ER%=0 ({energy_60:.2f} vs {energy_0:.2f}). "
        "ER% stat is still a no-op — check agent_energy_regen wiring in simulate()."
    )
    assert actual_delta == pytest.approx(expected_er_delta, abs=0.05), (
        f"ER% delta: expected {expected_er_delta:.2f}, got {actual_delta:.2f}."
    )
