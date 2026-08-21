"""Pin tests for Velina Abloom (Feature E).

Canonical source: DB core_skills level 7 "Core Passive: Breeze in Bloom" /
  "Additional Ability: Tea Party Etiquette" (agent: Avatar_Female_Size03_Velina,
  id: 019e4c7e-797e-7402-aae4-fbb3a2011af2), retrieved 2026-07-19 (Task 29 — supersedes
  the 160%/280%/755% figures retrieved 2026-05-31; Velina's kit changed during active
  development).

Cyclone dissipation explosion:
  "... it triggers one instance of Abloom DMG against the target: resolves an additional
  instance of Attribute Anomaly DMG, dealing a fixed 145% and 255% multiplier Wind
  Anomaly DMG respectively."

  Model: Micro Cyclone dissipation → 145% (14 500 bp), Wide-Area → 255% (25 500 bp).
  UNCONFIRMED PAIRING — the DB text does not explicitly assign 145/255 per cyclone type.
  Review at kit-final; update if in-game testing confirms otherwise.

Ultimate heavy attack Abloom:
  "When another character in your squad is an Anomaly character or shares the same
  attribute: … When the heavy attack from an Ultimate hits an enemy suffering a Wind
  Attribute Anomaly, it triggers an instance of Abloom DMG against the target: resolves
  one additional instance of Attribute Anomaly DMG, fixed at 680% of Wind Attribute
  Anomaly DMG."

  Squad condition (Anomaly char or Wind char) treated as declarative rotation assumption —
  not simulated. Review at kit-final.

All three triggers are flat (abloom_ap_scaled=False) and Wind-only — non-Wind auras
produce zero MV and no Abloom event.

NOTE: Velina is under active development. These pins reflect DB L7 at 2026-07-19;
  re-verify against final kit release.

Design: DESIGN_abloom_c8.md §Feature E.
"""

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.damage_calculator import calculate_abloom_damage

# ---------------------------------------------------------------------------
# Canonical MV constants — DB L7 core passive, all flat Wind-only.
# ---------------------------------------------------------------------------
_MICRO_MV_BP = 14_500  # Micro Cyclone dissipation: 145%  (unconfirmed pairing)
_WIDE_MV_BP = 25_500  # Wide-Area Cyclone dissipation: 255% (unconfirmed pairing)
_ULT_MV_BP = 68_000  # Ultimate heavy: 680%

_ORIGINAL_ANOMALY_DMG = 10_000
_AP = 120

_AURA_ID = "wind-aura-agent"
_FIRE_AURA_ID = "fire-aura-agent"
_VELINA_ID = "velina-test-id"


# ---------------------------------------------------------------------------
# Lightweight mock helpers (same pattern as other Abloom tests)
# ---------------------------------------------------------------------------


class _MockSpec:
    def __init__(
        self,
        *,
        buildup: int = 0,
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


# Move specs — Wind-only MV dicts confirm no Abloom fires for non-Wind aura.
_MICRO_SPEC = _MockSpec(
    abloom_mv_by_element={"wind": _MICRO_MV_BP},
    abloom_ap_scaled=False,
)

_WIDE_SPEC = _MockSpec(
    abloom_mv_by_element={"wind": _WIDE_MV_BP},
    abloom_ap_scaled=False,
)

_ULT_SPEC = _MockSpec(
    buildup=30_000,
    element="wind",
    scope="basic",
    abloom_mv_by_element={"wind": _ULT_MV_BP},
    abloom_ap_scaled=False,
)

_WIND_PRIMER_SPEC = _MockSpec(buildup=50_000, element="wind")
_FIRE_PRIMER_SPEC = _MockSpec(buildup=50_000, element="fire")


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------


def _wind_aura_build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Wind Aura Agent",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1_000,
        agent_anomaly_proficiency=_AP,
        mindscape_level=0,
    )


def _fire_aura_build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Fire Aura Agent",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1_000,
        agent_anomaly_proficiency=_AP,
        mindscape_level=0,
    )


def _velina_build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Velina",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1_000,
        agent_anomaly_proficiency=_AP,
        mindscape_level=0,
    )


def _wind_enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Test Dummy",
        level=60,
        defense=50,
        wind_res=0,
        anomaly_capacity_wind=1,
        anomaly_res_wind=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10_000,
    )


def _fire_enemy() -> EnemyProfile:
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
# moves_db factories
# ---------------------------------------------------------------------------


def _wind_moves_db() -> dict:
    # Keys are agent_name.lower().replace(" ", "_") — matches simulator lookup.
    return {
        "wind_aura_agent": _MockAgentMoves({"wind_primer": _WIND_PRIMER_SPEC}),
        "velina": _MockAgentMoves(
            {
                "Micro Cyclone - Dissipation Explosion": _MICRO_SPEC,
                "Wide-Area Cyclone - Dissipation Explosion": _WIDE_SPEC,
                "Ultimate: Heed the Howl": _ULT_SPEC,
            }
        ),
    }


def _fire_moves_db() -> dict:
    return {
        "fire_aura_agent": _MockAgentMoves({"fire_primer": _FIRE_PRIMER_SPEC}),
        "velina": _MockAgentMoves(
            {
                "Micro Cyclone - Dissipation Explosion": _MICRO_SPEC,
                "Wide-Area Cyclone - Dissipation Explosion": _WIDE_SPEC,
                "Ultimate: Heed the Howl": _ULT_SPEC,
            }
        ),
    }


def _wind_primer_step() -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=_AURA_ID,
        move_name="wind_primer",
        attacks=[],
        conditions=[],
    )


def _fire_primer_step() -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=_FIRE_AURA_ID,
        move_name="fire_primer",
        attacks=[],
        conditions=[],
    )


def _velina_step(move_name: str) -> SimulatedAttackStep:
    return SimulatedAttackStep(
        agent_id=_VELINA_ID,
        move_name=move_name,
        attacks=[],
        conditions=[],
    )


# ===========================================================================
# Part 1 — Formula pin tests (calculator-level, always GREEN)
# ===========================================================================


class TestVelinaAbloomFormula:
    """Verify calculate_abloom_damage for each of Velina's three Abloom triggers.

    Source: DB L7 core passive "Wind and Grace", 2026-05-31.
    ACTIVE-DEV CAVEAT: re-verify MVs at Velina kit-final.
    """

    @pytest.mark.parametrize(
        ("label", "mv_bp"),
        [
            ("Micro Cyclone dissipation", _MICRO_MV_BP),
            ("Wide-Area Cyclone dissipation", _WIDE_MV_BP),
            ("Ultimate heavy", _ULT_MV_BP),
        ],
    )
    def test_flat_formula(self, label: str, mv_bp: int) -> None:
        """Flat abloom: total = original * mv_bp // 10_000 regardless of AP."""
        result = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=_AP,
            abloom_ap_scaled=False,
        )
        expected = _ORIGINAL_ANOMALY_DMG * mv_bp // 10_000
        assert result.total == expected, (
            f"{label}: expected {expected} (mv_bp={mv_bp}), got {result.total}"
        )

    @pytest.mark.parametrize("mv_bp", [_MICRO_MV_BP, _WIDE_MV_BP, _ULT_MV_BP])
    def test_ap_independent(self, mv_bp: int) -> None:
        """Flat abloom: result must not change when AP changes."""
        r_low = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=10,
            abloom_ap_scaled=False,
        )
        r_high = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=500,
            abloom_ap_scaled=False,
        )
        assert r_low.total == r_high.total, (
            f"mv_bp={mv_bp}: AP should not affect flat abloom ({r_low.total} vs {r_high.total})"
        )


class TestVelinaExactOutputPins:
    """Exact integer output pins at _ORIGINAL_ANOMALY_DMG=10_000."""

    @pytest.mark.parametrize(
        ("label", "mv_bp", "expected"),
        [
            ("Micro: 145%", _MICRO_MV_BP, _ORIGINAL_ANOMALY_DMG * _MICRO_MV_BP // 10_000),
            ("Wide: 255%", _WIDE_MV_BP, _ORIGINAL_ANOMALY_DMG * _WIDE_MV_BP // 10_000),
            ("Ult: 680%", _ULT_MV_BP, _ORIGINAL_ANOMALY_DMG * _ULT_MV_BP // 10_000),
        ],
    )
    def test_exact_pin(self, label: str, mv_bp: int, expected: int) -> None:
        result = calculate_abloom_damage(
            abloom_mv_bp=mv_bp,
            original_anomaly_dmg=_ORIGINAL_ANOMALY_DMG,
            ap=_AP,
            abloom_ap_scaled=False,
        )
        assert result.total == expected, f"{label}: got {result.total}, want {expected}"


# ===========================================================================
# Part 2 — Wind aura triggers Abloom (sim-level)
# ===========================================================================


def _run_wind(move_name: str) -> list:
    builds = {
        _AURA_ID: _wind_aura_build(),
        _VELINA_ID: _velina_build(),
    }
    steps = [_wind_primer_step(), _velina_step(move_name)]
    result = simulate(
        builds=builds,
        steps=steps,
        enemy=_wind_enemy(),
        moves_db=_wind_moves_db(),
    )
    return [e for e in result.events if e.kind == "abloom"]


def _run_fire(move_name: str) -> list:
    """Fire aura — Velina's Wind-only MV dict yields mv_bp=0 → no Abloom."""
    builds = {
        _FIRE_AURA_ID: _fire_aura_build(),
        _VELINA_ID: _velina_build(),
    }
    steps = [_fire_primer_step(), _velina_step(move_name)]
    result = simulate(
        builds=builds,
        steps=steps,
        enemy=_fire_enemy(),
        moves_db=_fire_moves_db(),
    )
    return [e for e in result.events if e.kind == "abloom"]


class TestVelinaWindAbloom:
    """Wind aura fires Abloom at the correct MV for each trigger.

    Source: DB L7 core passive; 145%/255% pairing UNCONFIRMED — see module docstring.
    ACTIVE-DEV CAVEAT: review at kit-final.
    """

    def test_micro_cyclone_fires_one_abloom(self) -> None:
        events = _run_wind("Micro Cyclone - Dissipation Explosion")
        assert len(events) == 1, (
            f"Micro Cyclone dissipation should fire exactly one Abloom; got {len(events)}"
        )

    def test_micro_cyclone_abloom_mv_is_145pct(self) -> None:
        """Abloom from Micro dissipation: 145% flat Wind (14 500 bp).

        UNCONFIRMED PAIRING: 145% tentatively assigned to Micro; verify at kit-final.
        """
        events = _run_wind("Micro Cyclone - Dissipation Explosion")
        assert len(events) == 1
        ev = events[0]
        original = ev.detail.get("original_anomaly_dmg", 0)
        expected = original * _MICRO_MV_BP // 10_000
        assert ev.damage == expected, (
            f"Micro Abloom: expected {expected} (mv=145%, original={original}), got {ev.damage}"
        )

    def test_wide_cyclone_fires_one_abloom(self) -> None:
        events = _run_wind("Wide-Area Cyclone - Dissipation Explosion")
        assert len(events) == 1, (
            f"Wide-Area Cyclone dissipation should fire exactly one Abloom; got {len(events)}"
        )

    def test_wide_cyclone_abloom_mv_is_255pct(self) -> None:
        """Abloom from Wide-Area dissipation: 255% flat Wind (25 500 bp).

        UNCONFIRMED PAIRING: 255% tentatively assigned to Wide-Area; verify at kit-final.
        """
        events = _run_wind("Wide-Area Cyclone - Dissipation Explosion")
        assert len(events) == 1
        ev = events[0]
        original = ev.detail.get("original_anomaly_dmg", 0)
        expected = original * _WIDE_MV_BP // 10_000
        assert ev.damage == expected, (
            f"Wide Abloom: expected {expected} (mv=255%, original={original}), got {ev.damage}"
        )

    def test_ult_heavy_fires_one_abloom(self) -> None:
        """Ult-heavy fires Abloom when Wind aura is active.

        Squad condition (Anomaly/Wind char in squad) is a rotation assumption —
        not simulated. ACTIVE-DEV CAVEAT.
        """
        events = _run_wind("Ultimate: Heed the Howl")
        assert len(events) == 1, f"Ult-heavy should fire exactly one Abloom; got {len(events)}"

    def test_ult_heavy_abloom_mv_is_680pct(self) -> None:
        events = _run_wind("Ultimate: Heed the Howl")
        assert len(events) == 1
        ev = events[0]
        original = ev.detail.get("original_anomaly_dmg", 0)
        expected = original * _ULT_MV_BP // 10_000
        assert ev.damage == expected, (
            f"Ult Abloom: expected {expected} (mv=680%, original={original}), got {ev.damage}"
        )


# ===========================================================================
# Part 3 — Non-Wind aura: no Abloom
# ===========================================================================


class TestVelinaNoAbloomOnNonWindAura:
    """Wind-only MV dict → any non-Wind active aura yields mv_bp=0 → no Abloom.

    Test uses a Fire aura so the anomaly fires (capacity 1). If the MV dict
    accidentally included fire, these tests would catch it.
    """

    @pytest.mark.parametrize(
        "move_name",
        [
            "Micro Cyclone - Dissipation Explosion",
            "Wide-Area Cyclone - Dissipation Explosion",
            "Ultimate: Heed the Howl",
        ],
    )
    def test_no_abloom_on_fire_aura(self, move_name: str) -> None:
        events = _run_fire(move_name)
        assert events == [], (
            f"{move_name}: Abloom should not fire on non-Wind aura; got {len(events)} events"
        )
