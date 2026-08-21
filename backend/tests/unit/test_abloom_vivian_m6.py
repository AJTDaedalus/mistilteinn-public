"""Pin tests for Vivian M6 Fluttering Frock - Suspension Abloom.

Canonical text (M6 "Vivian"):
  "Launching Basic Attack: Fluttering Frock - Suspension consumes all Guard Feathers,
  the downward attack's area of effect increases, and upon hit, triggers a special
  instance of Abloom. Each additional Guard Feather consumed will increase the proportion
  of additional Anomaly DMG dealt by that instance of Abloom, consuming a maximum of 5
  Guard Feathers to increase the DMG up to a maximum of 5 times the original."

MV table (same as Featherbloom, per DESIGN_abloom_c8.md §Feature B):
  ether 615 / electric 320 / fire 800 / physical 75 / ice 108 / wind 32  (per 10 AP)

Modelling assumption A5 (OQ-B1): Guard Feathers are not simulated.
  Default abloom_mv_multiplier_bp = 50000 (x5, the M6 best case).
  If feather accrual is ever modelled, replace the constant with a per-step counter.

OQ-B2 (linearity): "up to 5x the original" read as linear N-feathers → xN.
  To verify: 5x single-run == 5x a x1 (1-feather) run.

Design: DESIGN_abloom_c8.md §Feature B.
Infra: B2 (mindscape gate on MoveBuildupSpec + BuildSnapshot.mindscape_level),
       B3 (abloom_mv_multiplier_bp applied in anomaly_simulator.py).
"""

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.damage_calculator import calculate_abloom_damage

# ---------------------------------------------------------------------------
# Vivian per-AP MV table (shared by Featherbloom and Fluttering Frock).
# Source: DESIGN_abloom_v2.md §A1, DESIGN_abloom_c8.md §Feature B.
# ---------------------------------------------------------------------------
_VIVIAN_MV = {
    "ether": 615,
    "electric": 320,
    "fire": 800,
    "physical": 75,
    "ice": 108,
    "wind": 32,
}

_ORIGINAL_ANOMALY_DMG = 10_000  # synthetic original for formula tests
_AP = 120  # reference AP (anomaly_proficiency basis points)


# ===========================================================================
# Part 1 — Formula pin tests (calculator-level, always GREEN)
# These verify the Abloom math in isolation; they do NOT test the sim gate or
# the MV multiplier infra.  They document the expected output at x5 so future
# regressions are caught at the formula level as well as the sim level.
# ===========================================================================


class TestFlutteringFrockFormula:
    """Verify calculate_abloom_damage at x5 MV for each element (OQ-B2: linearity)."""

    @pytest.mark.parametrize(
        ("element", "base_mv_bp"),
        list(_VIVIAN_MV.items()),
    )
    def test_5x_mv_per_element(self, element: str, base_mv_bp: int) -> None:
        """x5 MV produces the correct Abloom damage for each element.

        Formula: total = original * mv_bp * ap // 100_000
        """
        mv_bp_5x = base_mv_bp * 5
        result = calculate_abloom_damage(
            abloom_mv_bp=mv_bp_5x,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=_AP,
            abloom_ap_scaled=True,
        )
        expected = _ORIGINAL_ANOMALY_DMG * mv_bp_5x * _AP // 100_000
        assert result.total == expected, (
            f"{element}: expected {expected} (mv_bp={mv_bp_5x}, ap={_AP}), got {result.total}"
        )

    @pytest.mark.parametrize("element", list(_VIVIAN_MV.keys()))
    def test_5x_equals_5_times_1x(self, element: str) -> None:
        """OQ-B2 linearity: x5 result must equal exactly 5x the x1 result.

        If the in-game formula is base-x1-plus-extra (not linear), this test
        will need updating once confirmed against ZO / in-game footage.
        """
        mv_bp_base = _VIVIAN_MV[element]
        result_1x = calculate_abloom_damage(
            abloom_mv_bp=mv_bp_base,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=_AP,
            abloom_ap_scaled=True,
        )
        result_5x = calculate_abloom_damage(
            abloom_mv_bp=mv_bp_base * 5,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=_AP,
            abloom_ap_scaled=True,
        )
        assert result_5x.total == 5 * result_1x.total, (
            f"{element}: expected 5x{result_1x.total}={5 * result_1x.total}, got {result_5x.total}"
        )


# ===========================================================================
# Part 2 — Exact output pins (formula-derived, for regression detection)
# ===========================================================================

_EXPECTED_5X = {
    "ether": 36_900,  # mv_bp=3075 → 10000*3075*120//100000
    "electric": 19_200,  # mv_bp=1600
    "fire": 48_000,  # mv_bp=4000
    "physical": 4_500,  # mv_bp=375
    "ice": 6_480,  # mv_bp=540
    "wind": 1_920,  # mv_bp=160
}


@pytest.mark.parametrize(("element", "expected"), list(_EXPECTED_5X.items()))
def test_5x_exact_pins(element: str, expected: int) -> None:
    """Regression guard: exact output at x5 per element, ap=120, original=10000."""
    mv_bp_5x = _VIVIAN_MV[element] * 5
    result = calculate_abloom_damage(
        abloom_mv_bp=mv_bp_5x,
        original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
        ap=_AP,
        abloom_ap_scaled=True,
    )
    assert result.total == expected


# ===========================================================================
# Part 3 — Sim-level tests (RED until B2 + B3 land)
#
# These tests use the full anomaly_simulator.simulate() path and verify:
#   - mindscape gate: M5 build → no Abloom on Fluttering Frock - Suspension
#   - mindscape gate: M6 build → Abloom fires on Fluttering Frock - Suspension
#   - MV multiplier: M6 Fluttering Frock Abloom == 5x a x1-multiplier run
#   - C5 Featherbloom is unchanged (still fires regardless of M6 infra)
#
# RED reason before B2: BuildSnapshot(mindscape_level=...) raises TypeError
#   (field does not exist on the frozen dataclass).
# RED reason after B2 (gate added), before B3 (multiplier):
#   the M6 x5 multiplier test fails (result == 1x instead of 5x).
# ===========================================================================

# --- Shared helpers --------------------------------------------------------


class _MoveSpec:
    """Minimal mock of data/loaders/moves.py MoveBuildupSpec."""

    def __init__(
        self,
        buildup: int,
        duration_s: float = 1.0,
        hits: int = 1,
        element: str | None = None,
        scope: str = "basic",
        abloom_mv_by_element: dict | None = None,
        abloom_ap_scaled: bool = True,
        abloom_requires_mindscape: int = 0,
        abloom_mv_multiplier_bp: int = 10_000,
    ) -> None:
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.abloom_mv_by_element = abloom_mv_by_element
        self.abloom_ap_scaled = abloom_ap_scaled
        self.abloom_requires_mindscape = abloom_requires_mindscape
        self.abloom_mv_multiplier_bp = abloom_mv_multiplier_bp


class _AgentMoves:
    def __init__(self, agent_id: str, agent_name: str, moves: dict) -> None:
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.moves = moves


_VIVIAN_ID = "vivian-test-id"

# Primer move: triggers the ether anomaly so active_aura is set for the
# Fluttering Frock step.  No abloom_mv_by_element → no Abloom on this move.
_PRIMER_SPEC = _MoveSpec(buildup=50_000, element="ether")

_FEATHERBLOOM_SPEC = _MoveSpec(
    buildup=12_600,
    element="ether",
    abloom_mv_by_element=dict(_VIVIAN_MV),
    abloom_ap_scaled=True,
    abloom_requires_mindscape=0,
    abloom_mv_multiplier_bp=10_000,
)


def _fluttering_frock_spec(multiplier_bp: int = 50_000) -> _MoveSpec:
    return _MoveSpec(
        buildup=5_665,
        element="ether",
        abloom_mv_by_element=dict(_VIVIAN_MV),
        abloom_ap_scaled=True,
        abloom_requires_mindscape=6,
        abloom_mv_multiplier_bp=multiplier_bp,
    )


def _enemy() -> EnemyProfile:
    """Ether-weak enemy with capacity=1 so the primer instantly triggers."""
    return EnemyProfile(
        name="Test Dummy",
        level=60,
        defense=50,
        ether_res=0,
        anomaly_capacity_ether=1,
        anomaly_res_ether=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10_000,
    )


def _vivian_build(mindscape_level: int = 6) -> BuildSnapshot:
    """Vivian BuildSnapshot at the given mindscape level.

    RED before B2: BuildSnapshot does not accept mindscape_level keyword.
    """
    return BuildSnapshot(
        agent_name="Vivian",
        agent_element="ether",
        agent_level=60,
        agent_base_atk=1_000,
        agent_anomaly_proficiency=_AP,
        mindscape_level=mindscape_level,  # <-- RED until B2 adds this field
    )


def _moves_db(frock_multiplier_bp: int = 50_000) -> dict:
    return {
        "vivian": _AgentMoves(
            agent_id=_VIVIAN_ID,
            agent_name="Vivian",
            moves={
                "Primer: Ether Buildup": _PRIMER_SPEC,
                "Basic Attack: Featherbloom": _FEATHERBLOOM_SPEC,
                "Basic Attack: Fluttering Frock - Suspension": _fluttering_frock_spec(
                    frock_multiplier_bp
                ),
            },
        )
    }


def _steps_primer_then_frock() -> list[SimulatedAttackStep]:
    """Sequence: trigger anomaly → then fire Fluttering Frock."""
    return [
        SimulatedAttackStep(
            agent_id=_VIVIAN_ID,
            move_name="Primer: Ether Buildup",
            attacks=[],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id=_VIVIAN_ID,
            move_name="Basic Attack: Fluttering Frock - Suspension",
            attacks=[],
            conditions=[],
        ),
    ]


def _steps_primer_then_featherbloom() -> list[SimulatedAttackStep]:
    """Sequence: trigger anomaly → then fire Featherbloom."""
    return [
        SimulatedAttackStep(
            agent_id=_VIVIAN_ID,
            move_name="Primer: Ether Buildup",
            attacks=[],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id=_VIVIAN_ID,
            move_name="Basic Attack: Featherbloom",
            attacks=[],
            conditions=[],
        ),
    ]


# --- Gate tests (RED until B2) ---------------------------------------------


class TestMindscapeGate:
    """Verify abloom_requires_mindscape gates Fluttering Frock Abloom."""

    def test_m5_build_no_frock_abloom(self) -> None:
        """M5 Vivian: Fluttering Frock - Suspension must NOT trigger Abloom.

        abloom_requires_mindscape=6 and mindscape_level=5 → gate blocks it.
        RED before B2 (TypeError: mindscape_level unknown to BuildSnapshot).
        After B2: RED until gate check is wired in anomaly_simulator.py.
        """
        build = _vivian_build(mindscape_level=5)
        builds = {_VIVIAN_ID: build}
        result = simulate(builds, _steps_primer_then_frock(), _enemy(), _moves_db())
        abloom_events = [e for e in result.events if e.kind == "abloom"]
        assert len(abloom_events) == 0, (
            f"M5 Vivian should produce no Fluttering Frock Abloom; "
            f"got {len(abloom_events)} abloom event(s)"
        )

    def test_m6_build_frock_abloom_fires(self) -> None:
        """M6 Vivian: Fluttering Frock - Suspension MUST trigger Abloom.

        RED before B2 (TypeError).  After B2: passes (gate allows M6).
        """
        build = _vivian_build(mindscape_level=6)
        builds = {_VIVIAN_ID: build}
        result = simulate(builds, _steps_primer_then_frock(), _enemy(), _moves_db())
        abloom_events = [e for e in result.events if e.kind == "abloom"]
        assert len(abloom_events) >= 1, "M6 Vivian should produce ≥1 Fluttering Frock Abloom event"

    def test_featherbloom_unaffected_by_mindscape_gate(self) -> None:
        """C5 Featherbloom Abloom fires regardless of mindscape level (gate=0).

        RED before B2 (TypeError on _vivian_build).  After B2: must pass
        (gate check: abloom_requires_mindscape=0 → always allowed).
        """
        build = _vivian_build(mindscape_level=5)  # M5 — Featherbloom is C5
        builds = {_VIVIAN_ID: build}
        result = simulate(builds, _steps_primer_then_featherbloom(), _enemy(), _moves_db())
        abloom_events = [e for e in result.events if e.kind == "abloom"]
        assert len(abloom_events) >= 1, (
            "C5 Featherbloom Abloom must fire even on M5 build (gate=0)"
        )


# --- Multiplier tests (RED until B3) ----------------------------------------


class TestMvMultiplier:
    """Verify abloom_mv_multiplier_bp scales Abloom output correctly."""

    def test_5x_multiplier_equals_5_times_1x(self) -> None:
        """M6 Fluttering Frock x5 == 5x a x1-multiplier run (OQ-B2 linearity).

        RED before B2 (TypeError).
        After B2 gate passes: RED because multiplier not applied → result == 1x.
        After B3: GREEN.
        """
        build = _vivian_build(mindscape_level=6)
        builds = {_VIVIAN_ID: build}

        result_1x = simulate(
            builds, _steps_primer_then_frock(), _enemy(), _moves_db(frock_multiplier_bp=10_000)
        )
        result_5x = simulate(
            builds, _steps_primer_then_frock(), _enemy(), _moves_db(frock_multiplier_bp=50_000)
        )

        abloom_1x = sum(e.damage for e in result_1x.events if e.kind == "abloom")
        abloom_5x = sum(e.damage for e in result_5x.events if e.kind == "abloom")

        assert abloom_1x > 0, "x1 run produced no abloom damage"
        assert abloom_5x == 5 * abloom_1x, (
            f"x5 abloom={abloom_5x} should be 5x{abloom_1x}={5 * abloom_1x}"
        )

    def test_m6_default_multiplier_matches_formula(self) -> None:
        """M6 at x5 produces ether abloom > x1 abloom (sanity check).

        Complementary to test_5x_multiplier_equals_5_times_1x; confirms the
        x5 result is strictly greater than the unscaled (x1) result.
        RED until B3 applies the multiplier.
        """
        build = _vivian_build(mindscape_level=6)
        builds = {_VIVIAN_ID: build}

        result_1x = simulate(
            builds, _steps_primer_then_frock(), _enemy(), _moves_db(frock_multiplier_bp=10_000)
        )
        result_5x = simulate(
            builds, _steps_primer_then_frock(), _enemy(), _moves_db(frock_multiplier_bp=50_000)
        )

        abloom_1x = sum(e.damage for e in result_1x.events if e.kind == "abloom")
        abloom_5x = sum(e.damage for e in result_5x.events if e.kind == "abloom")

        assert abloom_5x > abloom_1x, (
            f"x5 abloom ({abloom_5x}) should exceed x1 abloom ({abloom_1x})"
        )
