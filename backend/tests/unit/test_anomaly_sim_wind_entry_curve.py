"""F-17b: wind entry-curve — n=1 entry #1, n=2 entry #2 (Leifa-cited constants),
n>=3 rejoins the generic non-physical (ether) curve at the same index.

Reference: DESIGN_math_review_sim.md "Brain resolution — 2026-07-05" +
"Brain resolution — pure-power tail confirmed". The n>=3 tail is the
*continuous* S-3 escalation (`capacity * 1.02^(min(n,10)-1)`, no per-step
floor) — Brain confirmed the printed Leifa table rows (…699, 712, …) are a
display-rounded rendering of this same curve, not a distinct threshold
sequence. Tests below assert the pure-power values.

Buildup passes through `calculate_buildup` unscaled for these builds (default
anomaly_mastery=100, no buildup bonus, 0 enemy anomaly RES, not stunned), so
raw `buildup` values map 1:1 onto gauge points — letting these tests pin the
exact threshold values the sim computes (same convention as
test_anomaly_sim_threshold_escalation.py, S-3).
"""

import math

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import (
    WIND_ENTRY2_BY_TIER,
    SimulatedAttackStep,
    simulate,
)
from app.services.build_damage_service import BuildSnapshot

# (tier, wind entry #1, generic/ether capacity)
_TIERS = [
    ("normal", 300, 600),
    ("elite", 1150, 2250),
    ("boss", 1500, 3000),
]


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


def _enemy(wind_cap: int, ether_cap: int) -> EnemyProfile:
    return EnemyProfile(
        name="F-17b Wind Entry Target",
        level=60,
        defense=50,
        wind_res=0,
        ether_res=0,
        anomaly_capacity_wind=wind_cap,
        anomaly_capacity_ether=ether_cap,
        anomaly_duration_default=10.0,
    )


def _build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="agent",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1200,
        agent_anomaly_proficiency=150,
    )


def _events(result, element):
    """A gate-pass shows up as either a brand-new 'anomaly' aura or a 'refresh'
    of the still-active same-element aura — both prove the threshold+CD gate
    let the crossing through."""
    return [e for e in result.events if e.kind in ("anomaly", "refresh") and e.element == element]


def _threshold_n_ge3(ether_cap: int, n: int) -> float:
    exp = min(n, 10) - 1
    return ether_cap * 100 * (1.02**exp)


def _overwhelming_triggers(count: int, element: str, duration: float = 3.1):
    """`count` steps, each with buildup far above any n<=10 threshold, spaced
    far enough apart (> 3s F-18 per-attribute CD) to each land its own trigger.
    Returns (moves, steps, elapsed_time)."""
    moves = {}
    steps = []
    for i in range(count):
        key = f"big_{element}_{i}"
        moves[key] = _MoveSpec(10_000_000, duration, 1, element)
        steps.append(SimulatedAttackStep("agent", key, []))
    return moves, steps, count * duration


def _bracket_moves(
    threshold: float,
    prefix: str,
    element: str,
    gap_duration: float = 3.1,
    cross_duration: float = 0.1,
):
    """A 'near miss' step whose buildup lands just under `threshold` (must NOT
    trigger), followed by a 'cross' step that pushes the held gauge just over
    it (must trigger). Returns (moves, steps, elapsed_time)."""
    near = math.floor(threshold)
    if near >= threshold:
        near -= 1
    cross_amount = math.ceil(threshold - near) + 1
    moves = {
        f"{prefix}_near": _MoveSpec(near, gap_duration, 1, element),
        f"{prefix}_cross": _MoveSpec(cross_amount, cross_duration, 1, element),
    }
    steps = [
        SimulatedAttackStep("agent", f"{prefix}_near", []),
        SimulatedAttackStep("agent", f"{prefix}_cross", []),
    ]
    return moves, steps, gap_duration + cross_duration


# --- n=1: entry #1 (exact, unchanged from today) ---------------------------


@pytest.mark.parametrize(("tier", "wind_cap", "ether_cap"), _TIERS)
def test_n1_entry1_exact(tier, wind_cap, ether_cap):
    enemy = _enemy(wind_cap, ether_cap)
    builds = {"agent": _build()}

    moves_hit = {"agent": _AgentMovesSpec({"hit": _MoveSpec(wind_cap * 100, 1.0, 1, "wind")})}
    result = simulate(builds, [SimulatedAttackStep("agent", "hit", [])], enemy, moves_hit)
    assert len(_events(result, "wind")) == 1

    moves_low = {"agent": _AgentMovesSpec({"hit": _MoveSpec(wind_cap * 100 - 1, 1.0, 1, "wind")})}
    result_low = simulate(builds, [SimulatedAttackStep("agent", "hit", [])], enemy, moves_low)
    assert len(_events(result_low, "wind")) == 0


# --- n=2: entry #2 (exact, Leifa-cited constant) ----------------------------


@pytest.mark.parametrize(("tier", "wind_cap", "ether_cap"), _TIERS)
def test_n2_entry2_exact(tier, wind_cap, ether_cap):
    enemy = _enemy(wind_cap, ether_cap)
    builds = {"agent": _build()}
    entry2 = WIND_ENTRY2_BY_TIER[tier]

    pre_moves, pre_steps, elapsed = _overwhelming_triggers(1, "wind")
    bracket_moves, bracket_steps, bracket_elapsed = _bracket_moves(entry2 * 100, "n2", "wind")

    moves_db = {"agent": _AgentMovesSpec({**pre_moves, **bracket_moves})}
    result = simulate(builds, pre_steps + bracket_steps, enemy, moves_db)

    triggers = _events(result, "wind")
    assert len(triggers) == 2
    assert triggers[-1].t == pytest.approx(elapsed + bracket_elapsed)


# --- n>=3: rejoins the generic (ether) curve at the same index -------------


@pytest.mark.parametrize("n", [3, 10])
@pytest.mark.parametrize(("tier", "wind_cap", "ether_cap"), _TIERS)
def test_wind_n_ge3_matches_ether_generic_curve(tier, wind_cap, ether_cap, n):
    enemy = _enemy(wind_cap, ether_cap)
    builds = {"agent": _build()}
    threshold = _threshold_n_ge3(ether_cap, n)

    # Ether path: the untouched S-3 branch (element != "wind") computes this
    # threshold directly off anomaly_capacity_ether. Confirms the formula
    # value is really what S-3 produces before asserting wind matches it.
    ether_pre_moves, ether_pre_steps, ether_elapsed = _overwhelming_triggers(n - 1, "ether")
    ether_bracket_moves, ether_bracket_steps, ether_bracket_elapsed = _bracket_moves(
        threshold, "ether_probe", "ether"
    )
    ether_result = simulate(
        builds,
        ether_pre_steps + ether_bracket_steps,
        enemy,
        {"agent": _AgentMovesSpec({**ether_pre_moves, **ether_bracket_moves})},
    )
    ether_triggers = _events(ether_result, "ether")
    assert len(ether_triggers) == n
    assert ether_triggers[-1].t == pytest.approx(ether_elapsed + ether_bracket_elapsed)

    # Wind path: same n, same formula-derived threshold, new S-4 branch.
    wind_pre_moves, wind_pre_steps, wind_elapsed = _overwhelming_triggers(n - 1, "wind")
    wind_bracket_moves, wind_bracket_steps, wind_bracket_elapsed = _bracket_moves(
        threshold, "wind_probe", "wind"
    )
    wind_result = simulate(
        builds,
        wind_pre_steps + wind_bracket_steps,
        enemy,
        {"agent": _AgentMovesSpec({**wind_pre_moves, **wind_bracket_moves})},
    )
    wind_triggers = _events(wind_result, "wind")
    assert len(wind_triggers) == n
    assert wind_triggers[-1].t == pytest.approx(wind_elapsed + wind_bracket_elapsed)


# --- cap at n=10: 11th trigger reuses the 10th's multiplier -----------------


@pytest.mark.parametrize(("tier", "wind_cap", "ether_cap"), _TIERS)
def test_cap_at_n_10(tier, wind_cap, ether_cap):
    enemy = _enemy(wind_cap, ether_cap)
    builds = {"agent": _build()}
    # Capped: the 11th trigger's threshold equals the 10th's (min(n,10)).
    threshold_n11 = _threshold_n_ge3(ether_cap, 11)
    assert threshold_n11 == _threshold_n_ge3(ether_cap, 10)

    pre_moves, pre_steps, elapsed = _overwhelming_triggers(10, "wind")
    bracket_moves, bracket_steps, bracket_elapsed = _bracket_moves(threshold_n11, "n11", "wind")

    moves_db = {"agent": _AgentMovesSpec({**pre_moves, **bracket_moves})}
    result = simulate(builds, pre_steps + bracket_steps, enemy, moves_db)

    triggers = _events(result, "wind")
    assert len(triggers) == 11
    assert triggers[-1].t == pytest.approx(elapsed + bracket_elapsed)


# --- unknown tier: fall back to the standard generic curve for all n -------


def test_unknown_tier_fallback_no_entry_discount():
    wind_cap, ether_cap = 300, 999  # 999 matches no tier
    enemy = _enemy(wind_cap, ether_cap)
    builds = {"agent": _build()}

    # n=1: must NOT trigger off wind_cap*100 (entry #1) -- unknown tier means
    # no discount, so the real threshold is ether_cap*100.
    moves_at_entry1 = {
        "agent": _AgentMovesSpec({"hit": _MoveSpec(wind_cap * 100, 1.0, 1, "wind")})
    }
    result = simulate(builds, [SimulatedAttackStep("agent", "hit", [])], enemy, moves_at_entry1)
    assert len(_events(result, "wind")) == 0

    threshold_n1 = ether_cap * 100
    moves_at_generic = {"agent": _AgentMovesSpec({"hit": _MoveSpec(threshold_n1, 1.0, 1, "wind")})}
    result2 = simulate(builds, [SimulatedAttackStep("agent", "hit", [])], enemy, moves_at_generic)
    assert len(_events(result2, "wind")) == 1

    # n=2: must NOT use WIND_ENTRY2_BY_TIER (undefined for this tier anyway) --
    # threshold is ether_cap*100*1.02, continuing the generic curve.
    threshold_n2 = ether_cap * 100 * 1.02
    pre_moves, pre_steps, elapsed = _overwhelming_triggers(1, "wind")
    bracket_moves, bracket_steps, bracket_elapsed = _bracket_moves(threshold_n2, "n2fb", "wind")
    moves_db = {"agent": _AgentMovesSpec({**pre_moves, **bracket_moves})}
    result3 = simulate(builds, pre_steps + bracket_steps, enemy, moves_db)

    triggers = _events(result3, "wind")
    assert len(triggers) == 2
    assert triggers[-1].t == pytest.approx(elapsed + bracket_elapsed)
