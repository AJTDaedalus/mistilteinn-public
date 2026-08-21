"""Pin tests for Promeia multi-trigger Abloom (Feature D).

Canonical sources (DB L7 skill text, cited in TASKS_abloom_c8.md §Feature D):
  EX Special Attack: Execution - Merciless Judgment  → Abloom MV 635%  (63 500 bp)
  Chain Attack: Hanging Judgment                     → Abloom MV 100%  (10 000 bp)
  Ultimate: Glaciating Impalement                    → Abloom MV 250%  (25 000 bp)

All three triggers are flat (abloom_ap_scaled=False) and element-uniform — any
active aura element maps to the same MV.

Core passive (corrected, D2):
  AP = +1.5 per AM above 150  (threshold 150, not 140)
  Team Abloom DMG = +0.35% per AM above 150  (was +0.32%; stat key: abloom_dmg_bonus)
  At AM=200: 50 excess → +17.5% Abloom bonus

M1 (DB, corrected D2): DEF Ignore 20% on Abloom (was 15%).
M2 (DB, corrected D2): AP +40 flat (was +60); EX-only Abloom MV x2.2
  (abloom_mv_multiplier_bp=22000, applied via A3, gated MC>=2; Chain/Ult unaffected).
M6: fixed 200% (20 000 bp) second Abloom instance on EX trigger, same aura element,
  gated MC≥6 (once/15 s — rotation assumption).

OQ-D2: Trial-by-Cold resource gate on EX is declarative only (rotation assumption).
OQ-D3: M2 per-move gating mechanism (sub-entry vs. multiplier knob) — see D3 notes.
OQ-D4: M6 second-instance infra (abloom_extra_instance_bp knob vs. sub-trigger).

Design: DESIGN_abloom_c8.md §Feature D.
"""

import pytest

from app.data.loaders.moves import load_agent_moves
from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.buff_resolver import ActiveConditions, resolve_modifiers
from app.services.build_damage_service import BuildSnapshot
from app.services.damage_calculator import calculate_abloom_damage
from app.services.modifier_loader import load_agent_modifiers
from app.services.modifiers import Condition
from app.services.snapshot_builder import _bake_am_excess_modifier

_REAL_MOVES_DB = load_agent_moves()

# ---------------------------------------------------------------------------
# Canonical abloom MV table for Promeia (flat, bp, element-uniform).
# Source: DB skill text L7, cited in TASKS_abloom_c8.md §Feature D.
# ---------------------------------------------------------------------------
_EX_MV_BP = 63_500  # EX: Execution - Merciless Judgment
_CHAIN_MV_BP = 10_000  # Chain: Hanging Judgment
_ULT_MV_BP = 25_000  # Ultimate: Glaciating Impalement

_M6_EXTRA_MV_BP = 20_000  # M6 fixed-200% second instance

_ORIGINAL_ANOMALY_DMG = 10_000

# Core passive corrected values (D2):
_CORE_THRESHOLD = 150
_CORE_AP_PER_AM = 1.5
_CORE_ABLOOM_BONUS_PER_AM = 0.0035  # 0.35% per AM above 150 (in float for formula check)

_PROMEIA_ID = "promeia"
_AURA_ID = "aura_agent"


# ===========================================================================
# Part 1 — Formula pin tests (calculator-level, always GREEN)
# ===========================================================================


class TestPromeiaAbloomFormula:
    """Verify calculate_abloom_damage for each of Promeia's three Abloom triggers.

    These are always GREEN — they only test the calculator, not the sim path.
    """

    @pytest.mark.parametrize(
        ("label", "mv_bp"),
        [
            ("EX", _EX_MV_BP),
            ("Chain", _CHAIN_MV_BP),
            ("Ult", _ULT_MV_BP),
        ],
    )
    def test_flat_formula(self, label: str, mv_bp: int) -> None:
        """Flat abloom: total = original * mv_bp // 10_000 regardless of AP."""
        result = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=100,
            abloom_ap_scaled=False,
        )
        expected = _ORIGINAL_ANOMALY_DMG * mv_bp // 10_000
        assert result.total == expected, (
            f"{label}: expected {expected} (mv_bp={mv_bp}), got {result.total}"
        )

    @pytest.mark.parametrize("mv_bp", [_EX_MV_BP, _CHAIN_MV_BP, _ULT_MV_BP])
    def test_ap_independent(self, mv_bp: int) -> None:
        """Flat abloom: result must not change when AP changes."""
        result_low = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=10,
            abloom_ap_scaled=False,
        )
        result_high = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=500,
            abloom_ap_scaled=False,
        )
        assert result_low.total == result_high.total, (
            f"Flat abloom at mv_bp={mv_bp} should be AP-independent; "
            f"ap=10→{result_low.total}, ap=500→{result_high.total}"
        )

    def test_m2_ex_mv_at_2_2x(self) -> None:
        """M2 EX: effective MV = 63500 × 2.2 = 139700 bp (abloom_mv_multiplier_bp=22000)."""
        mv_bp_m2 = _EX_MV_BP * 22_000 // 10_000
        result = calculate_abloom_damage(
            abloom_mv_bp=mv_bp_m2,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=100,
            abloom_ap_scaled=False,
        )
        expected = _ORIGINAL_ANOMALY_DMG * mv_bp_m2 // 10_000
        assert result.total == expected
        assert mv_bp_m2 == 139_700  # 63500 × 2.2

    def test_m6_extra_instance_is_200pct(self) -> None:
        """M6 second instance: fixed 200% = 20000 bp → 2.0× original."""
        result = calculate_abloom_damage(
            abloom_mv_bp=_M6_EXTRA_MV_BP,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=100,
            abloom_ap_scaled=False,
        )
        expected = _ORIGINAL_ANOMALY_DMG * _M6_EXTRA_MV_BP // 10_000
        assert expected == 20_000  # 10000 × 20000 // 10000
        assert result.total == expected


# ===========================================================================
# Part 2 — Exact output pins (regression guard, always GREEN)
# ===========================================================================

_EXACT_FLAT = {
    "EX": 63_500,  # 10000 * 63500 // 10000
    "Chain": 10_000,  # 10000 * 10000 // 10000
    "Ult": 25_000,  # 10000 * 25000 // 10000
}


@pytest.mark.parametrize(
    ("label", "mv_bp", "expected"),
    [
        ("EX", _EX_MV_BP, _EXACT_FLAT["EX"]),
        ("Chain", _CHAIN_MV_BP, _EXACT_FLAT["Chain"]),
        ("Ult", _ULT_MV_BP, _EXACT_FLAT["Ult"]),
    ],
)
def test_exact_flat_pins(label: str, mv_bp: int, expected: int) -> None:
    """Regression guard: exact flat abloom output per trigger."""
    result = calculate_abloom_damage(
        abloom_mv_bp=mv_bp,
        original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
        ap=100,
        abloom_ap_scaled=False,
    )
    assert result.total == expected, f"{label}: expected {expected}, got {result.total}"


# ===========================================================================
# Part 3 — Core passive math (pure formula, always GREEN)
# Documents what the corrected core bonus must produce.
# ===========================================================================


class TestCorePassiveMath:
    """Verify the corrected core passive numbers (threshold 150, 0.35%/AM).

    These are pure arithmetic checks; they do NOT depend on buff_resolver.
    GREEN from the start — they pin the design intent for D2 to implement.
    """

    @pytest.mark.parametrize(
        ("am", "expected_excess"),
        [
            (200, 50),
            (150, 0),
            (149, 0),  # below threshold — no excess
            (100, 0),
        ],
    )
    def test_am_excess_above_150(self, am: int, expected_excess: int) -> None:
        """Excess = max(0, AM - 150)."""
        excess = max(0, am - _CORE_THRESHOLD)
        assert excess == expected_excess

    def test_abloom_bonus_at_am_200(self) -> None:
        """AM=200: 50 excess × 0.35% = 17.5% Abloom DMG bonus."""
        excess = max(0, 200 - _CORE_THRESHOLD)
        bonus_pct = excess * _CORE_ABLOOM_BONUS_PER_AM
        assert abs(bonus_pct - 0.175) < 1e-9, (
            f"Expected 17.5% bonus at AM=200, got {bonus_pct:.4%}"
        )

    def test_abloom_bonus_at_am_150_is_zero(self) -> None:
        """AM=150 (exactly at threshold): 0 excess → 0% bonus."""
        excess = max(0, 150 - _CORE_THRESHOLD)
        bonus_pct = excess * _CORE_ABLOOM_BONUS_PER_AM
        assert bonus_pct == 0.0

    def test_ap_gain_at_am_200(self) -> None:
        """AM=200: 50 excess × 1.5 = +75 flat AP from core passive."""
        excess = max(0, 200 - _CORE_THRESHOLD)
        ap_bonus = excess * _CORE_AP_PER_AM
        assert ap_bonus == 75.0

    def test_abloom_bonus_in_bp(self) -> None:
        """At AM=200: 17.5% → 1750 bp (integer basis points for buff_resolver)."""
        excess = max(0, 200 - _CORE_THRESHOLD)
        bonus_bp = round(excess * _CORE_ABLOOM_BONUS_PER_AM * 10_000)
        assert bonus_bp == 1_750


# ===========================================================================
# Part 4 — Sim-level tests (RED until D2 + D3 land)
#
# D2 delivers: promeia.json moves file with abloom_mv_by_element on EX/Chain/Ult,
#              corrected promeia.json modifier (threshold 150, 0.35%, abloom_dmg_bonus).
# D3 delivers: M2 per-move EX multiplier, M6 second-instance knob.
#
# RED reasons:
#   Before D2: abloom_mv_by_element missing on all three moves → no abloom events.
#   Before D3: M2 EX multiplier not applied; M6 second instance missing.
# ===========================================================================


class _MoveSpec:
    """Minimal move spec stub for sim tests."""

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
        abloom_extra_instance_bp: int = 0,
        abloom_extra_instance_requires_mindscape: int = 0,
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
        self.abloom_extra_instance_bp = abloom_extra_instance_bp
        self.abloom_extra_instance_requires_mindscape = abloom_extra_instance_requires_mindscape


class _AgentMoves:
    def __init__(self, *, agent_id: str, agent_name: str, moves: dict) -> None:
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.moves = moves

    def get_move(self, name: str) -> _MoveSpec | None:
        return self.moves.get(name)


# ---------------------------------------------------------------------------
# Element-uniform Abloom MV dict (same value for all 6 elements).
# ---------------------------------------------------------------------------
_ALL_ELEMENTS = ("ether", "electric", "fire", "physical", "ice", "wind")


def _uniform_mv(mv_bp: int) -> dict:
    return dict.fromkeys(_ALL_ELEMENTS, mv_bp)


# ---------------------------------------------------------------------------
# Move spec factories.
# ---------------------------------------------------------------------------

_FIRE_PRIMER_SPEC = _MoveSpec(
    buildup=100_000,
    duration_s=1.0,
    hits=1,
    element="fire",
    scope="special",
)


def _ex_spec(
    *,
    mc: int = 0,
    m2: bool = False,
    m6: bool = False,
) -> _MoveSpec:
    """EX Merciless Judgment spec.

    At base (mc<2): MV 63500 bp, no multiplier.
    With M2 (mc≥2): MV 63500 bp × 2.2 (abloom_mv_multiplier_bp=22000).
    With M6: second instance at 20000 bp, gated mc≥6.
    """
    multiplier_bp = 22_000 if (m2 and mc >= 2) else 10_000
    return _MoveSpec(
        buildup=5_949,
        duration_s=1.5,
        element="ice",
        scope="special",
        abloom_mv_by_element=_uniform_mv(_EX_MV_BP),
        abloom_ap_scaled=False,
        abloom_requires_mindscape=0,
        abloom_mv_multiplier_bp=multiplier_bp,
        abloom_extra_instance_bp=_M6_EXTRA_MV_BP if m6 else 0,
        abloom_extra_instance_requires_mindscape=6 if m6 else 0,
    )


_CHAIN_SPEC = _MoveSpec(
    buildup=37_360,
    duration_s=1.2,
    element="ice",
    scope="basic",
    abloom_mv_by_element=_uniform_mv(_CHAIN_MV_BP),
    abloom_ap_scaled=False,
    abloom_requires_mindscape=0,
    abloom_mv_multiplier_bp=10_000,
)

_ULT_SPEC = _MoveSpec(
    buildup=60_409,
    duration_s=1.2,
    element="ice",
    scope="basic",
    abloom_mv_by_element=_uniform_mv(_ULT_MV_BP),
    abloom_ap_scaled=False,
    abloom_requires_mindscape=0,
    abloom_mv_multiplier_bp=10_000,
)


# ---------------------------------------------------------------------------
# Build + enemy helpers.
# ---------------------------------------------------------------------------


def _aura_build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Aura Agent",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1_000,
        agent_anomaly_proficiency=120,
        mindscape_level=0,
    )


def _promeia_build(mindscape_level: int = 0) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Promeia",
        agent_element="ice",
        agent_level=60,
        agent_base_atk=1_000,
        agent_anomaly_proficiency=120,
        mindscape_level=mindscape_level,
    )


def _fire_enemy() -> EnemyProfile:
    """Fire-weak enemy; fire anomaly triggers instantly (capacity=1)."""
    return EnemyProfile(
        name="Test Dummy",
        level=60,
        defense=50,
        fire_res=0,
        anomaly_capacity_fire=1,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10_000,
    )


# ---------------------------------------------------------------------------
# moves_db factories.
# ---------------------------------------------------------------------------


def _moves_db(
    *,
    mc: int = 0,
    m2: bool = False,
    m6: bool = False,
) -> dict:
    return {
        _AURA_ID: _AgentMoves(
            agent_id=_AURA_ID,
            agent_name="AuraAgent",
            moves={"fire_primer": _FIRE_PRIMER_SPEC},
        ),
        _PROMEIA_ID: _AgentMoves(
            agent_id=_PROMEIA_ID,
            agent_name="Promeia",
            moves={
                "EX Special Attack: Execution - Merciless Judgment": _ex_spec(mc=mc, m2=m2, m6=m6),
                "Chain Attack: Hanging Judgment": _CHAIN_SPEC,
                "Ultimate: Glaciating Impalement": _ULT_SPEC,
            },
        ),
    }


def _primer_step() -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=_AURA_ID,
        move_name="fire_primer",
        attacks=[],
        conditions=[],
    )


def _promeia_step(move_name: str) -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=_PROMEIA_ID,
        move_name=move_name,
        attacks=[],
        conditions=[],
    )


# ===========================================================================
# Part 4a — Base move Abloom fires (RED until D2 adds moves/agents/promeia.json)
# ===========================================================================


class TestPromeiaBaseAblooms:
    """Each of Promeia's three abloom moves fires exactly one abloom event.

    RED until D2 creates moves/agents/promeia.json with abloom_mv_by_element
    on EX, Chain, and Ult entries.
    """

    def _run(self, move_name: str, mc: int = 0) -> list:
        builds = {
            _AURA_ID: _aura_build(),
            _PROMEIA_ID: _promeia_build(mindscape_level=mc),
        }
        steps = [_primer_step(), _promeia_step(move_name)]
        result = simulate(
            builds=builds,
            steps=steps,
            enemy=_fire_enemy(),
            moves_db=_moves_db(mc=mc),
        )
        return [e for e in result.events if e.kind == "abloom"]

    def test_ex_fires_one_abloom(self) -> None:
        """EX at base (MC=0) fires exactly one abloom event at 635% MV.

        RED until D2 (abloom_mv_by_element missing on EX move in moves file).
        """
        events = self._run("EX Special Attack: Execution - Merciless Judgment")
        assert len(events) == 1, f"EX: expected 1 abloom event, got {len(events)}"
        ev = events[0]
        assert ev.element == "fire"  # fire aura → fire abloom
        assert ev.agent_id == _PROMEIA_ID

    def test_chain_fires_one_abloom(self) -> None:
        """Chain fires exactly one abloom event at 100% MV.

        RED until D2.
        """
        events = self._run("Chain Attack: Hanging Judgment")
        assert len(events) == 1, f"Chain: expected 1 abloom event, got {len(events)}"
        ev = events[0]
        assert ev.element == "fire"
        assert ev.agent_id == _PROMEIA_ID

    def test_ult_fires_one_abloom(self) -> None:
        """Ult fires exactly one abloom event at 250% MV.

        RED until D2.
        """
        events = self._run("Ultimate: Glaciating Impalement")
        assert len(events) == 1, f"Ult: expected 1 abloom event, got {len(events)}"
        ev = events[0]
        assert ev.element == "fire"
        assert ev.agent_id == _PROMEIA_ID

    def test_ex_abloom_damage_matches_flat_formula(self) -> None:
        """EX abloom damage = original * 63500 // 10000 (flat, AP-independent).

        RED until D2.
        """
        events = self._run("EX Special Attack: Execution - Merciless Judgment")
        assert len(events) == 1
        ev = events[0]
        assert ev.damage is not None
        original = ev.detail.get("original_anomaly_dmg", 0)
        expected = original * _EX_MV_BP // 10_000
        assert ev.damage == expected, (
            f"EX: expected {expected} (original={original}), got {ev.damage}"
        )

    def test_chain_abloom_damage_matches_flat_formula(self) -> None:
        """Chain abloom damage = original * 10000 // 10000 (= original).

        RED until D2.
        """
        events = self._run("Chain Attack: Hanging Judgment")
        assert len(events) == 1
        ev = events[0]
        original = ev.detail.get("original_anomaly_dmg", 0)
        expected = original * _CHAIN_MV_BP // 10_000
        assert ev.damage == expected

    def test_ult_abloom_damage_matches_flat_formula(self) -> None:
        """Ult abloom damage = original * 25000 // 10000 (2.5× original).

        RED until D2.
        """
        events = self._run("Ultimate: Glaciating Impalement")
        assert len(events) == 1
        ev = events[0]
        original = ev.detail.get("original_anomaly_dmg", 0)
        expected = original * _ULT_MV_BP // 10_000
        assert ev.damage == expected


# ===========================================================================
# Part 4b — M2 EX-only multiplier (RED until D3)
# ===========================================================================


class TestM2ExMultiplier:
    """M2 doubles the EX abloom MV (×2.2); Chain/Ult are unaffected.

    RED until D3 implements per-move MC-gated multiplier.
    OQ-D3: exact mechanism (sub-entry vs. A3 knob) resolved in D3.
    """

    def _abloom_total(self, move_name: str, mc: int, m2: bool) -> int:
        builds = {
            _AURA_ID: _aura_build(),
            _PROMEIA_ID: _promeia_build(mindscape_level=mc),
        }
        steps = [_primer_step(), _promeia_step(move_name)]
        result = simulate(
            builds=builds,
            steps=steps,
            enemy=_fire_enemy(),
            moves_db=_moves_db(mc=mc, m2=m2),
        )
        return sum(e.damage for e in result.events if e.kind == "abloom")

    def test_ex_m2_abloom_is_2_2x_base(self) -> None:
        """At MC≥2, EX abloom total must be 2.2× the base (MC=0) result.

        RED until D3 applies abloom_mv_multiplier_bp=22000 on the EX entry.
        """
        base_total = self._abloom_total(
            "EX Special Attack: Execution - Merciless Judgment", mc=0, m2=False
        )
        m2_total = self._abloom_total(
            "EX Special Attack: Execution - Merciless Judgment", mc=2, m2=True
        )
        assert base_total > 0, "Base EX abloom must fire (check D2 first)"
        assert m2_total == base_total * 22_000 // 10_000, (
            f"EX M2: expected {base_total * 22000 // 10000} (x2.2), got {m2_total}"
        )

    def test_chain_unaffected_by_m2(self) -> None:
        """Chain abloom MV is unchanged whether MC=0 or MC=2.

        Chain must not carry abloom_mv_multiplier_bp from EX.
        RED until D2 (chain abloom fires); must stay GREEN after D3 (M2 EX-only).
        """
        base_total = self._abloom_total("Chain Attack: Hanging Judgment", mc=0, m2=False)
        mc2_total = self._abloom_total("Chain Attack: Hanging Judgment", mc=2, m2=True)
        assert base_total > 0, "Chain abloom must fire (check D2)"
        assert mc2_total == base_total, (
            f"Chain should be unaffected by M2; base={base_total}, mc2={mc2_total}"
        )

    def test_ult_unaffected_by_m2(self) -> None:
        """Ult abloom MV is unchanged whether MC=0 or MC=2 (M2 is EX-only).

        RED until D2; must stay GREEN after D3.
        """
        base_total = self._abloom_total("Ultimate: Glaciating Impalement", mc=0, m2=False)
        mc2_total = self._abloom_total("Ultimate: Glaciating Impalement", mc=2, m2=True)
        assert base_total > 0, "Ult abloom must fire (check D2)"
        assert mc2_total == base_total, (
            f"Ult should be unaffected by M2; base={base_total}, mc2={mc2_total}"
        )


# ===========================================================================
# Part 4c — M6 second instance on EX (RED until D3 + abloom_extra_instance_bp)
# ===========================================================================


class TestM6SecondInstance:
    """M6 adds a fixed-200% second Abloom instance on EX trigger only.

    RED until D3 + abloom_extra_instance_bp knob (or sub-trigger mechanism; OQ-D4).
    """

    def _ex_abloom_events(self, mc: int) -> list:
        builds = {
            _AURA_ID: _aura_build(),
            _PROMEIA_ID: _promeia_build(mindscape_level=mc),
        }
        steps = [
            _primer_step(),
            _promeia_step("EX Special Attack: Execution - Merciless Judgment"),
        ]
        result = simulate(
            builds=builds,
            steps=steps,
            enemy=_fire_enemy(),
            moves_db=_moves_db(mc=mc, m2=mc >= 2, m6=mc >= 6),
        )
        return [e for e in result.events if e.kind == "abloom"]

    def test_mc5_ex_fires_one_abloom(self) -> None:
        """MC=5 (no M6): EX fires exactly 1 abloom event.

        RED until D2 (EX abloom fires).  Must stay 1 event after D3.
        """
        events = self._ex_abloom_events(mc=5)
        assert len(events) == 1, f"MC=5 EX should fire 1 abloom, got {len(events)}"

    def test_mc6_ex_fires_two_abloom(self) -> None:
        """MC=6: EX fires 2 abloom events — base + M6 fixed-200% second instance.

        RED until D3 + abloom_extra_instance_bp infra.
        OQ-D4: the exact knob/mechanism is decided in D3.
        """
        events = self._ex_abloom_events(mc=6)
        assert len(events) == 2, (
            f"MC=6 EX should fire 2 abloom events (base + M6 instance), got {len(events)}"
        )

    def test_mc6_second_instance_is_200pct(self) -> None:
        """M6 second instance damage = original × 200% = original × 20000/10000.

        RED until D3.
        """
        events = self._ex_abloom_events(mc=6)
        assert len(events) == 2, "Requires D3 to pass"
        abloom_damages = sorted(e.damage for e in events)
        # Smaller one is the 200% instance; larger is the base EX at 635% (or 635% × 2.2 at M6)
        smaller = abloom_damages[0]
        original = events[0].detail.get("original_anomaly_dmg", 0)
        expected_200pct = original * _M6_EXTRA_MV_BP // 10_000
        assert smaller == expected_200pct, (
            f"M6 second instance: expected {expected_200pct} (200% flat), got {smaller}"
        )

    def test_chain_m6_no_second_instance(self) -> None:
        """Chain is NOT affected by M6 second instance (EX-only).

        RED until D2 (chain abloom fires).  Must remain 1 event at MC=6.
        """
        builds = {
            _AURA_ID: _aura_build(),
            _PROMEIA_ID: _promeia_build(mindscape_level=6),
        }
        steps = [_primer_step(), _promeia_step("Chain Attack: Hanging Judgment")]
        result = simulate(
            builds=builds,
            steps=steps,
            enemy=_fire_enemy(),
            moves_db=_moves_db(mc=6, m2=True, m6=True),
        )
        abloom_events = [e for e in result.events if e.kind == "abloom"]
        assert len(abloom_events) == 1, (
            f"Chain at MC=6 must fire exactly 1 abloom (M6 is EX-only); got {len(abloom_events)}"
        )

    def test_ult_m6_no_second_instance(self) -> None:
        """Ult is NOT affected by M6 second instance (EX-only).

        RED until D2; must remain 1 event at MC=6.
        """
        builds = {
            _AURA_ID: _aura_build(),
            _PROMEIA_ID: _promeia_build(mindscape_level=6),
        }
        steps = [_primer_step(), _promeia_step("Ultimate: Glaciating Impalement")]
        result = simulate(
            builds=builds,
            steps=steps,
            enemy=_fire_enemy(),
            moves_db=_moves_db(mc=6, m2=True, m6=True),
        )
        abloom_events = [e for e in result.events if e.kind == "abloom"]
        assert len(abloom_events) == 1, (
            f"Ult at MC=6 must fire exactly 1 abloom (M6 is EX-only); got {len(abloom_events)}"
        )


# ===========================================================================
# Part 5 — Pipeline tests: M2 EX gate using real moves JSON
# ===========================================================================

_REAL_AURA_ID = "aura_agent_pipeline"
_REAL_PROMEIA_ID = "promeia"

_PIPELINE_FIRE_PRIMER = _MoveSpec(
    buildup=100_000,
    duration_s=1.0,
    hits=1,
    element="fire",
    scope="special",
)


def _pipeline_real_moves_db(aura_agent_name: str = "Aura Agent Pipeline") -> dict:
    """moves_db mixing the real Promeia JSON with a stub fire-primer agent."""
    return {
        _REAL_AURA_ID: _AgentMoves(
            agent_id=_REAL_AURA_ID,
            agent_name=aura_agent_name,
            moves={"fire_primer": _PIPELINE_FIRE_PRIMER},
        ),
        **_REAL_MOVES_DB,
    }


def _pipeline_simulate_ex(mc: int) -> list:
    """Run EX step with real Promeia moves, fire aura, return abloom events."""
    builds = {
        _REAL_AURA_ID: BuildSnapshot(
            agent_name="Aura Agent Pipeline",
            agent_element="fire",
            agent_level=60,
            agent_base_atk=1_000,
            agent_anomaly_proficiency=120,
            mindscape_level=0,
        ),
        _REAL_PROMEIA_ID: BuildSnapshot(
            agent_name="Promeia",
            agent_element="ice",
            agent_level=60,
            agent_base_atk=1_000,
            agent_anomaly_proficiency=120,
            mindscape_level=mc,
        ),
    }
    steps = [
        SimulatedAttackStep(
            agent_id=_REAL_AURA_ID, move_name="fire_primer", attacks=[], conditions=[]
        ),
        SimulatedAttackStep(
            agent_id=_REAL_PROMEIA_ID,
            move_name="EX Special Attack: Execution - Merciless Judgment",
            attacks=[],
            conditions=[],
        ),
    ]
    result = simulate(
        builds=builds,
        steps=steps,
        enemy=_fire_enemy(),
        moves_db=_pipeline_real_moves_db(),
    )
    return [e for e in result.events if e.kind == "abloom" and e.agent_id == _REAL_PROMEIA_ID]


class TestM2ExMultiplierPipeline:
    """Pipeline tests: real Promeia JSON, abloom_mv_multiplier_requires_mindscape gate.

    These validate that the simulator correctly reads the gate from the JSON
    (not from a baked stub) and that MC<2 does NOT get the ×2.2 multiplier.
    """

    def test_mc0_ex_abloom_fires_at_base_mv(self) -> None:
        """MC=0: EX abloom fires at 635% (63500 bp), no multiplier."""
        events = _pipeline_simulate_ex(mc=0)
        assert len(events) >= 1, "EX abloom must fire"
        ev = events[0]
        original = ev.detail.get("original_anomaly_dmg", 0)
        expected = original * _EX_MV_BP // 10_000
        assert ev.damage == expected, f"MC=0 EX: expected {expected} (base 635%), got {ev.damage}"

    def test_mc1_ex_abloom_fires_at_base_mv(self) -> None:
        """MC=1 (gate not met): EX abloom must NOT apply ×2.2 multiplier."""
        events = _pipeline_simulate_ex(mc=1)
        assert len(events) >= 1, "EX abloom must fire at MC=1"
        ev = events[0]
        original = ev.detail.get("original_anomaly_dmg", 0)
        expected_base = original * _EX_MV_BP // 10_000
        assert ev.damage == expected_base, (
            f"MC=1 EX: gate not met, expected base {expected_base}, got {ev.damage}"
        )

    def test_mc2_ex_abloom_is_2_2x_base(self) -> None:
        """MC=2 (gate met): EX abloom must apply ×2.2 multiplier → 139700 bp."""
        mc0_events = _pipeline_simulate_ex(mc=0)
        mc2_events = _pipeline_simulate_ex(mc=2)
        assert mc0_events, "Base EX abloom must fire"
        assert mc2_events, "MC=2 EX abloom must fire"
        base_dmg = mc0_events[0].damage
        mc2_dmg = mc2_events[0].damage
        expected_mc2 = base_dmg * 22_000 // 10_000
        assert mc2_dmg == expected_mc2, f"MC=2 EX: expected {expected_mc2} (x2.2), got {mc2_dmg}"


# ===========================================================================
# Part 6 — Core passive AM-excess pipeline tests (RED until Task 3 lands)
#
# Verifies that Promeia's core passive AM-excess scaling actually reaches
# the damage calc pipeline — not just that the formula math is correct.
#
# After Task 3: snapshot_builder bakes scaling_stat="anomaly_mastery_excess"
# modifiers at build time, so resolve_modifiers sees a concrete value.
# ===========================================================================

_PROMEIA_HAKUSHIN_ID = "1541"  # from promeia.json source_id

# At AM=200: excess=50, abloom_dmg_bonus = floor(50 * 35) = 1750 bp
# At AM=200: excess=50, AP flat = floor(50 * 1.5) = 75
_AM_TEST = 200
_EXCESS_AT_200 = 50
_EXPECTED_ABLOOM_DMG_BONUS_BP = 1_750  # 50 * 35 bp/AM
_EXPECTED_CORE_AP_FLAT = 75  # floor(50 * 1.5)


def _promeia_core_mods_only() -> list:
    """Load only Promeia's core-skill modifiers (exclude mindscape M1/M2/M6)."""
    from app.services.modifiers import ModifierSource

    return [
        m
        for m in load_agent_modifiers(_PROMEIA_HAKUSHIN_ID)
        if m.source != ModifierSource.MINDSCAPE
    ]


def _promeia_snapshot_with_am(am: int) -> BuildSnapshot:
    """BuildSnapshot for Promeia with given AM and core-only modifiers.

    Mindscape mods are excluded so M2's unconditional AP+40 doesn't
    confound the core-passive AP test.  AM-excess modifiers are baked
    at construction time (simulating what build_snapshot_from_db does).
    """
    raw_mods = _promeia_core_mods_only()
    baked_mods = [
        _bake_am_excess_modifier(m, am) if m.scaling_stat == "anomaly_mastery_excess" else m
        for m in raw_mods
    ]
    return BuildSnapshot(
        agent_name="Promeia",
        agent_element="ice",
        agent_level=60,
        agent_base_atk=1_000,
        agent_anomaly_mastery=am,
        agent_anomaly_proficiency=120,
        mindscape_level=0,
        modifiers=baked_mods,
    )


class TestCorePassiveAmExcessPipeline:
    """Verify that AM-excess modifiers are baked and reach the calc.

    Source: Promeia core passive (threshold 150, AP +1.5/AM, Abloom DMG +35 bp/AM).
    These tests are RED until snapshot_builder bakes anomaly_mastery_excess mods.
    """

    def test_abloom_dmg_bonus_at_am200(self) -> None:
        """AM=200 → abloom_dmg_bonus = 1750 bp (50 excess × 35 bp/AM)."""
        snap = _promeia_snapshot_with_am(_AM_TEST)
        conditions = ActiveConditions(active={Condition.ALWAYS}, stack_counts={})
        buffs = resolve_modifiers(snap.modifiers, conditions)
        assert buffs.abloom_dmg_bonus == _EXPECTED_ABLOOM_DMG_BONUS_BP, (
            f"Expected abloom_dmg_bonus={_EXPECTED_ABLOOM_DMG_BONUS_BP} at AM={_AM_TEST}, "
            f"got {buffs.abloom_dmg_bonus}"
        )

    def test_abloom_dmg_bonus_zero_at_am150(self) -> None:
        """AM=150 (at threshold): excess=0 → abloom_dmg_bonus=0."""
        snap = _promeia_snapshot_with_am(150)
        conditions = ActiveConditions(active={Condition.ALWAYS}, stack_counts={})
        buffs = resolve_modifiers(snap.modifiers, conditions)
        assert buffs.abloom_dmg_bonus == 0, (
            f"AM=150 must produce 0 abloom_dmg_bonus; got {buffs.abloom_dmg_bonus}"
        )

    def test_abloom_dmg_bonus_zero_below_threshold(self) -> None:
        """AM=100 (below threshold): abloom_dmg_bonus=0."""
        snap = _promeia_snapshot_with_am(100)
        conditions = ActiveConditions(active={Condition.ALWAYS}, stack_counts={})
        buffs = resolve_modifiers(snap.modifiers, conditions)
        assert buffs.abloom_dmg_bonus == 0, (
            f"AM=100 (below threshold) must give 0 abloom_dmg_bonus; got {buffs.abloom_dmg_bonus}"
        )

    def test_ap_flat_from_core_at_am200(self) -> None:
        """AM=200 → core AP flat = 75 (floor(50 * 1.5)).

        Uses core-only modifiers (mindscape excluded) so M2's unconditional
        +40 AP doesn't inflate the result. Checks stat_bonuses path.
        """
        snap = _promeia_snapshot_with_am(_AM_TEST)
        conditions = ActiveConditions(active={Condition.ALWAYS}, stack_counts={})
        buffs = resolve_modifiers(snap.modifiers, conditions)
        ap_flat = buffs.stat_bonuses.get("anomaly_proficiency", 0)
        assert ap_flat == _EXPECTED_CORE_AP_FLAT, (
            f"Expected core AP flat={_EXPECTED_CORE_AP_FLAT} at AM={_AM_TEST}, got {ap_flat}"
        )

    def test_ap_flat_zero_below_threshold(self) -> None:
        """AM=100 → core AP flat = 0 (core-only modifiers; M2 excluded)."""
        snap = _promeia_snapshot_with_am(100)
        conditions = ActiveConditions(active={Condition.ALWAYS}, stack_counts={})
        buffs = resolve_modifiers(snap.modifiers, conditions)
        ap_flat = buffs.stat_bonuses.get("anomaly_proficiency", 0)
        assert ap_flat == 0, f"AM=100 (below threshold) must give 0 core AP flat; got {ap_flat}"
