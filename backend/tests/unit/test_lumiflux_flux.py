"""Task 6 — `app/services/lumiflux.py`: `LumifluxSpec` + flux resolution.

Covers the acceptance criteria in TASKS_remielle.md's Task 6:

* Attribute Flux resolves to the *next* team slot, cyclic (DESIGN §2 OQ-3's
  worked example, and its 2-agent / solo edge cases).
* Rotating the same three agents through all three slot orders yields three
  different results — proof the resolver reads slot order, not identity.
* `refringe_coefficient` is exactly linear in Anomaly Proficiency (DESIGN
  §9.1 test 1) — no `// 10000` floor-division kink in the AP term.

This module is pure and ORM-free (DESIGN §3), so these are plain unit tests
with no DB, no fixtures, no mocking.
"""

from __future__ import annotations

import pytest

from app.models.enums import Element
from app.services.lumiflux import (
    AgentRef,
    LumifluxSpec,
    refringe_coefficient,
    resolve_fluxed_element,
)

JANE = AgentRef(build_id="jane", element=Element.PHYSICAL)
VELINA = AgentRef(build_id="velina", element=Element.ICE)
SUBJECT = AgentRef(build_id="subject", element=Element.LUMIFLUX)


class TestResolveFluxedElementWorkedExample:
    """DESIGN §2 OQ-3's worked example: `[Jane, Velina, subject]` wraps."""

    def test_three_agent_team_wraps_to_first_slot(self) -> None:
        team = [JANE, VELINA, SUBJECT]

        assert resolve_fluxed_element(team, SUBJECT) == Element.PHYSICAL


class TestResolveFluxedElementEdgeCases:
    def test_two_agent_team_resolves_to_the_other_agent(self) -> None:
        team = [SUBJECT, JANE]

        assert resolve_fluxed_element(team, SUBJECT) == Element.PHYSICAL

    def test_two_agent_team_wraps_both_directions(self) -> None:
        team = [JANE, SUBJECT]

        assert resolve_fluxed_element(team, SUBJECT) == Element.PHYSICAL

    def test_solo_team_returns_none(self) -> None:
        team = [SUBJECT]

        assert resolve_fluxed_element(team, SUBJECT) is None

    def test_empty_team_returns_none(self) -> None:
        assert resolve_fluxed_element([], SUBJECT) is None

    def test_subject_not_in_team_raises(self) -> None:
        team = [JANE, VELINA]

        with pytest.raises(ValueError, match="subject"):
            resolve_fluxed_element(team, SUBJECT)


class TestResolveFluxedElementSlotRotation:
    """"Rotating the same three agents through all three slot orders yields
    the three different expected elements" (TASKS_remielle.md Task 6).

    With only 3 team slots and 3 distinct elements, a *fixed* subject only
    ever has two possible next-slot neighbors (the other two agents), so the
    only way to get three distinct results out of one fixed 3-agent team is
    to walk the "subject" role around all three slots in turn, holding the
    team order fixed — i.e. ask each of the three agents in turn "what is
    *your* flux". Because each agent's next-slot neighbor is a different one
    of the other two (cyclic, no repeats in a 3-cycle), the three answers
    come out pairwise distinct whenever the team's three elements are.
    """

    def test_each_agent_in_the_three_agent_team_fluxes_differently(self) -> None:
        aria = AgentRef(build_id="aria", element=Element.ETHER)
        team = [JANE, VELINA, aria]  # physical, ice, ether

        flux_jane = resolve_fluxed_element(team, JANE)
        flux_velina = resolve_fluxed_element(team, VELINA)
        flux_aria = resolve_fluxed_element(team, aria)

        assert flux_jane == Element.ICE  # Jane's next slot: Velina
        assert flux_velina == Element.ETHER  # Velina's next slot: Aria
        assert flux_aria == Element.PHYSICAL  # Aria's next slot wraps: Jane
        assert {flux_jane, flux_velina, flux_aria} == {
            Element.PHYSICAL,
            Element.ICE,
            Element.ETHER,
        }


def _spec(*, refringe_ap_ratio_bp: int = 2) -> LumifluxSpec:
    """A minimal spec with only the fields `refringe_coefficient` reads."""
    return LumifluxSpec(
        point_cap=4,
        voidflare_cap=3,
        refringe_ap_ratio_bp=refringe_ap_ratio_bp,
        refringe_flat_bonuses={"anomaly_count_3": 1000, "m2": 2000},
        luminize_multipliers={"assist": 32000, "ultimate": 33600},
        luminize_ap_bonus_bp=10,
        phase_flow_tick_s=5.0,
        phase_flow_duration_s=40.0,
        flight_attack_points=(0, 1, 2),
        flight_attack_mv_bp=(8130, 20320, 16250),
        flight_attack_daze_bp=(27500, 37820, 37820),
    )


class TestRefringeCoefficientLinearInAP:
    """DESIGN §9.1 test 1: doubling AP doubles the AP-derived term; the flat
    bonus constants are unaffected."""

    def test_linear_in_ap_holds_at_flat_zero(self) -> None:
        spec = _spec()

        coeff_0 = refringe_coefficient(spec, 0, flat_bonus_bp=0)
        coeff_ap = refringe_coefficient(spec, 400, flat_bonus_bp=0)
        coeff_2ap = refringe_coefficient(spec, 800, flat_bonus_bp=0)

        assert coeff_2ap - coeff_0 == 2 * (coeff_ap - coeff_0)

    def test_linear_in_ap_holds_with_a_nonzero_flat_bonus(self) -> None:
        # The flat bonus is a constant offset -- linearity is about the
        # AP-derived term only, so it must hold regardless of what flat
        # bonus the caller supplies.
        spec = _spec()

        coeff_0 = refringe_coefficient(spec, 0, flat_bonus_bp=3000)
        coeff_ap = refringe_coefficient(spec, 317, flat_bonus_bp=3000)
        coeff_2ap = refringe_coefficient(spec, 634, flat_bonus_bp=3000)

        assert coeff_2ap - coeff_0 == 2 * (coeff_ap - coeff_0)

    def test_ap_term_is_exact_direct_multiplication_no_floor_kink(self) -> None:
        # refringe_ap_ratio_bp is bp *per AP point*, applied by direct
        # multiplication -- not `// 10000` -- so there is no integer
        # truncation to break exact linearity at odd AP values.
        spec = _spec(refringe_ap_ratio_bp=2)

        assert refringe_coefficient(spec, 401, flat_bonus_bp=0) == 802
        assert refringe_coefficient(spec, 999, flat_bonus_bp=0) == 1998

    def test_flat_bonus_is_a_pure_additive_offset(self) -> None:
        spec = _spec()

        without_bonus = refringe_coefficient(spec, 300, flat_bonus_bp=0)
        with_bonus = refringe_coefficient(spec, 300, flat_bonus_bp=1000)

        assert with_bonus - without_bonus == 1000
