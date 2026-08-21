"""Pin tests for Nangong Yu M6 Vibrato:Modified stun-onset Abloom.

Canonical text (DB, Mindscape M6 "An Angel's Delusion"):
  "When the enemy becomes Stunned, all Vibrato: Modified stacks are cleared.
  When Vibrato: Modified is cleared, if the enemy is under an Ether, Electric,
  Fire, Physical, Ice, or Wind Anomaly, Nangong Yu triggers an instance of
  Abloom DMG on the target, dealing an additional instance of Attribute Anomaly
  DMG equal to 800%/400%/1,000%/70%/100%/40% of the original Attribute Anomaly
  DMG. Each stack of Vibrato: Modified on the enemy increases this Abloom DMG
  ratio by an additional 25%."

M2 canonical text (DB, Mindscape M2 "Painless Tears"):
  "Each stack of Vibrato's additional Abloom DMG ratio increase from Core
  Passive: Prodigious Idol increases by an additional 10%."

Base MV table (bp) — ether/electric/fire/physical/ice/wind:
  80000 / 40000 / 100000 / 7000 / 10000 / 4000

Per-stack multiplier at M6 (TASKS_abloom_c8.md §C3):
  abloom_mv_multiplier_bp = 10000 + N * 3500
  (M2 +10%/stack assumed to apply to Vibrato:Modified; OQ-C2: unconfirmed — verify
  vs. in-game or ZO. If M2 applies only to core Vibrato, ratio reverts to 2500.)
  OQ-C1: Default 4-stack assumption (N=4); accumulator not simulated.
  At N=4: 10000 + 4*3500 = 24000 (×2.4).

Flat (non-AP-scaled) abloom — same class as Grace/Burnice.
Trigger: stun-onset (fires exactly once when enemy enters Stunned state).

Design: DESIGN_abloom_c8.md §Feature C.
Infra: C2 (stun-onset Abloom hook in anomaly_simulator.py),
       C3 (nangong_yu.json with stun_onset_abloom move + abloom_mv_multiplier_bp).
"""

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.damage_calculator import calculate_abloom_damage

# ---------------------------------------------------------------------------
# Nangong Yu M6 Vibrato:Modified base MV table (bp)
# Source: DB Mindscape M6, cited above.
# ---------------------------------------------------------------------------
_NANGONG_MV = {
    "ether": 80000,
    "electric": 40000,
    "fire": 100000,
    "physical": 7000,
    "ice": 10000,
    "wind": 4000,
}

_N_STACKS = 4  # OQ-C1: default assumption
_RATIO_M6 = 3500  # M2 always present at M6: +35%/stack
_MULTIPLIER_BP = 10000 + _N_STACKS * _RATIO_M6  # = 24000

_ORIGINAL_ANOMALY_DMG = 10_000
_NANGONG_AP = 200


# ---------------------------------------------------------------------------
# Lightweight mock helpers for sim tests
# ---------------------------------------------------------------------------


class _MockSpec:
    """Minimal move spec stub — uses defaults for fields not listed."""

    def __init__(
        self,
        *,
        buildup: int | None = None,
        duration_s: float = 1.0,
        hits: int = 1,
        element: str | None = None,
        scope: str | None = None,
        abloom_mv_by_element: dict | None = None,
        abloom_ap_scaled: bool = False,
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


class _MockAgentMoves:
    def __init__(self, moves: dict) -> None:
        self.moves = moves


_AURA_ID = "aura-agent-id"
_NANGONG_ID = "nangong-test-id"

_NANGONG_STUN_SPEC = _MockSpec(
    abloom_mv_by_element=dict(_NANGONG_MV),
    abloom_ap_scaled=False,
    abloom_requires_mindscape=6,
    abloom_mv_multiplier_bp=_MULTIPLIER_BP,
)


def _primer_spec(element: str) -> _MockSpec:
    return _MockSpec(buildup=50_000, element=element)


def _nangong_build(mindscape_level: int = 6) -> BuildSnapshot:
    """Nangong Yu BuildSnapshot at the given mindscape level."""
    return BuildSnapshot(
        agent_name="Nangong Yu",
        agent_element="ether",
        agent_level=60,
        agent_base_atk=1_000,
        agent_anomaly_proficiency=_NANGONG_AP,
        mindscape_level=mindscape_level,
    )


def _aura_build(element: str) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Aura Agent",
        agent_element=element,
        agent_level=60,
        agent_base_atk=1_000,
        agent_anomaly_proficiency=120,
    )


def _enemy(element: str) -> EnemyProfile:
    """Enemy with capacity=1 for the given element so the primer triggers it immediately."""
    kwargs: dict = {
        "name": "Test Dummy",
        "level": 60,
        "defense": 50,
        "anomaly_duration_default": 10.0,
        "stun_buildup_multiplier": 10_000,
    }
    for elem in ("physical", "fire", "ice", "electric", "ether", "wind"):
        kwargs[f"anomaly_capacity_{elem}"] = 1 if elem == element else 10_000
        kwargs[f"anomaly_res_{elem}"] = 0
    if element == "wind":
        # F-17b: wind's entry #1 discount only applies when anomaly_capacity_ether
        # resolves to a known tier (600/2250/3000) — else the sim falls back to
        # the generic curve for all n (by design, never guesses a tier). Use the
        # "normal" tier so this fixture's capacity=1 primer still triggers wind
        # immediately, same as every other tested element.
        kwargs["anomaly_capacity_ether"] = 600
    return EnemyProfile(**kwargs)


def _moves_db(aura_element: str, nangong_mc: int = 6) -> dict:
    """Builds a mock moves_db: aura_agent primer + nangong_yu stun_onset_abloom."""
    nangong_spec = _MockSpec(
        abloom_mv_by_element=dict(_NANGONG_MV),
        abloom_ap_scaled=False,
        abloom_requires_mindscape=6,
        abloom_mv_multiplier_bp=_MULTIPLIER_BP,
    )
    return {
        "aura_agent": _MockAgentMoves({"primer": _primer_spec(aura_element)}),
        "nangong_yu": _MockAgentMoves({"stun_onset_abloom": nangong_spec}),
    }


def _steps_primer_then_stun(element: str) -> list[SimulatedAttackStep]:
    return [
        SimulatedAttackStep(agent_id=_AURA_ID, move_name="primer", attacks=[], conditions=[]),
        SimulatedAttackStep(
            agent_id=_AURA_ID, move_name="stun_trigger", attacks=[], conditions=[]
        ),
    ]


# ===========================================================================
# Part 1 — Formula pin tests (calculator-level, always GREEN)
# These test calculate_abloom_damage directly with flat (non-AP-scaled) formula.
# They serve as a regression anchor independent of the sim gate.
# ===========================================================================


class TestVibratoModifiedFormula:
    """Verify calculate_abloom_damage at ×2.4 MV for each element (N=4, M6+M2)."""

    @pytest.mark.parametrize(
        ("element", "base_mv_bp"),
        list(_NANGONG_MV.items()),
    )
    def test_flat_mv_per_element_4_stacks(self, element: str, base_mv_bp: int) -> None:
        """Flat abloom formula: total = original * mv_effective // 10_000.

        mv_effective = base_mv_bp * abloom_mv_multiplier_bp // 10_000
                     = base_mv_bp * 24000 // 10_000 (at N=4 M6 with M2).
        """
        mv_effective = base_mv_bp * _MULTIPLIER_BP // 10_000
        result = calculate_abloom_damage(
            abloom_mv_bp=mv_effective,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=_NANGONG_AP,
            abloom_ap_scaled=False,
        )
        expected = _ORIGINAL_ANOMALY_DMG * mv_effective // 10_000
        assert result.total == expected, (
            f"{element}: expected {expected} (mv_effective={mv_effective}), got {result.total}"
        )

    def test_fire_highest_mv(self) -> None:
        """Fire is the highest MV element at 1000% = 100000 bp (×2.4 → 240000)."""
        mv_effective = _NANGONG_MV["fire"] * _MULTIPLIER_BP // 10_000
        assert mv_effective == 240_000, f"Expected 240000, got {mv_effective}"

    def test_wind_lowest_mv(self) -> None:
        """Wind is the lowest MV element at 40% = 4000 bp (×2.4 → 9600)."""
        mv_effective = _NANGONG_MV["wind"] * _MULTIPLIER_BP // 10_000
        assert mv_effective == 9_600, f"Expected 9600, got {mv_effective}"

    def test_no_ap_scaling(self) -> None:
        """Flat and AP-scaled formulas diverge at AP != 10 (AP=200 in these tests)."""
        mv_bp = _NANGONG_MV["ether"] * _MULTIPLIER_BP // 10_000
        flat = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=_NANGONG_AP,
            abloom_ap_scaled=False,
        )
        ap_scaled = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=_NANGONG_AP,
            abloom_ap_scaled=True,
        )
        assert flat.total != ap_scaled.total, (
            "Flat and AP-scaled should produce different results when AP != 10"
        )

    @pytest.mark.parametrize(
        ("n_stacks", "expected_mult_bp"),
        [
            (0, 10_000),
            (1, 13_500),
            (2, 17_000),
            (3, 20_500),
            (4, 24_000),
        ],
    )
    def test_per_stack_multiplier_formula(self, n_stacks: int, expected_mult_bp: int) -> None:
        """abloom_mv_multiplier_bp = 10000 + N * 3500 at M6 with M2."""
        computed = 10_000 + n_stacks * _RATIO_M6
        assert computed == expected_mult_bp, (
            f"At N={n_stacks}: expected {expected_mult_bp}, got {computed}"
        )


# ===========================================================================
# Part 2 — Sim gate tests  (RED until C2 stun-onset hook + C3 nangong_yu.json)
# These drive the full anomaly_simulator.simulate() pipeline.
# ===========================================================================


class TestStunOnsetAbbloomSim:
    """Integration-level sim tests for Nangong M6 stun-onset Abloom."""

    def _abloom_events(
        self,
        element: str,
        nangong_mc: int = 6,
        include_nangong: bool = True,
        with_aura: bool = True,
    ) -> list:
        builds: dict = {}
        if with_aura:
            builds[_AURA_ID] = _aura_build(element)
        else:
            # Still need a valid agent for the stun_trigger step
            builds[_AURA_ID] = _aura_build("ether")
        if include_nangong:
            builds[_NANGONG_ID] = _nangong_build(mindscape_level=nangong_mc)

        steps: list[SimulatedAttackStep] = []
        if with_aura:
            steps.append(
                SimulatedAttackStep(
                    agent_id=_AURA_ID,
                    move_name="primer",
                    attacks=[],
                    conditions=[],
                )
            )
        steps.append(
            SimulatedAttackStep(
                agent_id=_AURA_ID,
                move_name="stun_trigger",
                attacks=[],
                conditions=[],
            )
        )

        result = simulate(
            builds=builds,
            steps=steps,
            enemy=_enemy(element if with_aura else "ether"),
            moves_db=_moves_db(element, nangong_mc),
        )
        return [e for e in result.events if e.kind == "abloom"]

    @pytest.mark.parametrize("element", list(_NANGONG_MV.keys()))
    def test_stun_onset_abloom_fires_per_element(self, element: str) -> None:
        """Vibrato:Modified fires for all 6 aura elements with M6 build.

        RED until C2 (stun-onset hook) + C3 (nangong_yu.json with stun_onset_abloom).
        """
        events = self._abloom_events(element)
        assert len(events) == 1, (
            f"Expected exactly 1 stun-onset abloom event for {element} aura, got {len(events)}"
        )
        ev = events[0]
        assert ev.element == element
        assert ev.agent_id == _NANGONG_ID

    @pytest.mark.parametrize("element", list(_NANGONG_MV.keys()))
    def test_stun_onset_abloom_damage_formula(self, element: str) -> None:
        """Abloom damage matches flat formula: original * mv_effective // 10_000.

        RED until C2 + C3.
        """
        events = self._abloom_events(element)
        assert len(events) == 1
        ev = events[0]
        assert ev.damage is not None
        assert ev.damage > 0

        mv_effective = _NANGONG_MV[element] * _MULTIPLIER_BP // 10_000
        original_dmg = ev.detail.get("original_anomaly_dmg", 0)
        expected = original_dmg * mv_effective // 10_000
        assert ev.damage == expected, (
            f"{element}: expected {expected} (mv_eff={mv_effective}, "
            f"original={original_dmg}), got {ev.damage}"
        )

    def test_m5_build_no_stun_onset_abloom(self) -> None:
        """Mindscape level 5 → mindscape gate blocks stun-onset Abloom.

        RED until C2 + C3.
        """
        events = self._abloom_events("ether", nangong_mc=5)
        nangong_ablooms = [e for e in events if e.agent_id == _NANGONG_ID]
        assert len(nangong_ablooms) == 0, (
            f"M5 build should produce no Nangong abloom, got {nangong_ablooms}"
        )

    def test_no_nangong_no_stun_onset_abloom(self) -> None:
        """Without Nangong in builds, stun_trigger emits no abloom.

        RED until C2 (hook silently skips when no matching build).
        """
        events = self._abloom_events("ether", include_nangong=False)
        assert len(events) == 0, (
            f"No Nangong build should produce no abloom, got {len(events)} events"
        )

    def test_no_aura_no_stun_onset_abloom(self) -> None:
        """Without an active aura, stun_trigger emits no Nangong abloom.

        RED until C2 (hook checks active_aura before firing).
        """
        events = self._abloom_events("ether", with_aura=False)
        nangong_ablooms = [e for e in events if e.agent_id == _NANGONG_ID]
        assert len(nangong_ablooms) == 0, (
            f"No active aura should produce no Nangong abloom, got {nangong_ablooms}"
        )

    def test_stun_onset_abloom_attributed_to_nangong(self) -> None:
        """Abloom event agent_id must be Nangong's build key, not the aura applier.

        RED until C2 + C3.
        """
        events = self._abloom_events("fire")
        assert len(events) == 1
        assert events[0].agent_id == _NANGONG_ID
        assert events[0].applier_agent_id == _AURA_ID, (
            "Applier (aura owner) should be the aura agent, not Nangong"
        )

    def test_c5_crossval_unaffected_by_nangong(self) -> None:
        """Nangong M6 hook must not change per-step (C5) Abloom on other agents.

        Ensures the stun-onset path is isolated from the per-step Abloom path.
        RED until C2 (isolation requirement).
        """
        # Aura agent with abloom move fires per-step → should fire normally
        aura_mv = {"ether": 615}  # Vivian-style per-AP spec for comparison
        per_step_spec = _MockSpec(
            buildup=12_600,
            element="ether",
            abloom_mv_by_element=aura_mv,
            abloom_ap_scaled=True,
            abloom_requires_mindscape=0,
            abloom_mv_multiplier_bp=10_000,
        )
        moves_db_with_perstep: dict = {
            "aura_agent": _MockAgentMoves(
                {
                    "primer": _primer_spec("ether"),
                    "per_step_abloom_move": per_step_spec,
                }
            ),
            "nangong_yu": _MockAgentMoves({"stun_onset_abloom": _NANGONG_STUN_SPEC}),
        }
        builds: dict = {
            _AURA_ID: _aura_build("ether"),
            _NANGONG_ID: _nangong_build(mindscape_level=6),
        }
        steps = [
            SimulatedAttackStep(_AURA_ID, "primer", [], []),
            SimulatedAttackStep(_AURA_ID, "stun_trigger", [], []),
            SimulatedAttackStep(_AURA_ID, "per_step_abloom_move", [], []),
        ]
        result = simulate(
            builds=builds,
            steps=steps,
            enemy=_enemy("ether"),
            moves_db=moves_db_with_perstep,
        )
        abloom_events = [e for e in result.events if e.kind == "abloom"]
        # Expect exactly 2 abloom: 1 stun-onset (Nangong), 1 per-step (aura agent)
        assert len(abloom_events) == 2, (
            f"Expected 2 abloom events (1 stun-onset + 1 per-step), got {len(abloom_events)}"
        )
        agent_ids = {e.agent_id for e in abloom_events}
        assert _NANGONG_ID in agent_ids, "Nangong stun-onset abloom missing"
        assert _AURA_ID in agent_ids, "Per-step abloom from aura agent missing"
