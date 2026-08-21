"""Refringe credit — the scored build's share of a teammate's anomaly tick (#160).

`_owns` drops a teammate's `anomaly_tick` because the scored build's *buildup*
share of it is 0.0. That is right for the teammate's own damage and wrong for the
Refringe uplift riding on it, which exists only because of the Lumiflux agent and
scales with **her** AP. Dropping both is what lets the optimizer sell AP to buy
CRIT on an agent whose kit barely crits.

These pin the node's arithmetic. The wiring that emits the step is A2; until then
nothing constructs this node in production, which is exactly why the linearity and
divide-out properties need pinning here rather than being inferred from a
end-to-end number later.
"""

from __future__ import annotations

import pytest

from app.formula.builder import const
from app.formula.zzz.damage import refringe_credit_node
from app.formula.zzz.tags import Q_ANOMALY_PROF, stat_tag
from app.pando.calculator import Calculator, NodeRegistry
from app.services.combo_types import RefringeCreditStep


def _eval_at_ap(node, ap: int) -> float:
    """Evaluate a credit node with the registry holding one AP value."""
    reg = NodeRegistry()
    reg.register(stat_tag(Q_ANOMALY_PROF), const(float(ap)))
    return Calculator(reg).compute(node)


class TestCreditsTheUpliftOnly:
    def test_matches_the_closed_form(self) -> None:
        """neutral = 1000 * 10000/11224 ; credit = neutral * (2000 + 2*600)/10000.

        Using Remielle's real shape: `refringe_ap_ratio_bp` 2 (0.02%/AP) and a
        2000 bp flat (M2's +20%). At the simulation's AP the multiplier was
        11224, i.e. coefficient 1224 = 612 AP * 2.
        """
        node = refringe_credit_node(
            frozen_tick_damage=1000.0,
            refringe_mult_at_stripped_ap=11224,
            refringe_ap_ratio_bp=2,
            refringe_flat_bonus_bp=2000,
        )
        neutral = 1000.0 * 10000 / 11224
        expected = neutral * (2000 + 2 * 600) / 10000
        assert _eval_at_ap(node, 600) == pytest.approx(expected)

    def test_never_credits_the_whole_tick(self) -> None:
        """The teammate's own damage stays the teammate's.

        At the very AP the simulation used, the credit must equal the tick's
        uplift — `frozen - neutral` — not `frozen`.
        """
        frozen, mult, ratio = 5000.0, 11224.0, 2
        # Flat term deliberately 0 so the whole coefficient is the AP term and
        # `sim_ap` below reproduces the simulation's multiplier exactly.
        node = refringe_credit_node(
            frozen_tick_damage=frozen,
            refringe_mult_at_stripped_ap=int(mult),
            refringe_ap_ratio_bp=ratio,
            refringe_flat_bonus_bp=0,
        )
        sim_ap = (11224 - 10000) // ratio  # 612
        neutral = frozen * 10000 / mult
        credit = _eval_at_ap(node, sim_ap)
        assert credit == pytest.approx(frozen - neutral)
        assert credit < frozen

    def test_zero_coefficient_credits_nothing(self) -> None:
        """No AP and no flat term means no uplift to attribute."""
        node = refringe_credit_node(
            frozen_tick_damage=9999.0,
            refringe_mult_at_stripped_ap=11224,
            refringe_ap_ratio_bp=2,
            refringe_flat_bonus_bp=0,
        )
        assert _eval_at_ap(node, 0) == pytest.approx(0.0)


class TestLinearInAP:
    """The property that keeps this inside the optimizer's per-candidate budget."""

    def test_exactly_linear(self) -> None:
        node = refringe_credit_node(
            frozen_tick_damage=1000.0,
            refringe_mult_at_stripped_ap=11224,
            refringe_ap_ratio_bp=2,
            refringe_flat_bonus_bp=2000,
        )
        lo, mid, hi = (_eval_at_ap(node, ap) for ap in (0, 500, 1000))
        assert mid - lo == pytest.approx(hi - mid)

    def test_more_ap_is_strictly_more_credit(self) -> None:
        """The whole point: her AP must move this number, or #160 is not fixed."""
        node = refringe_credit_node(
            frozen_tick_damage=1000.0,
            refringe_mult_at_stripped_ap=11224,
            refringe_ap_ratio_bp=2,
            refringe_flat_bonus_bp=2000,
        )
        assert _eval_at_ap(node, 612) > _eval_at_ap(node, 576)

    def test_the_flat_term_shifts_without_changing_slope(self) -> None:
        common = {
            "frozen_tick_damage": 1000.0,
            "refringe_mult_at_stripped_ap": 11224,
            "refringe_ap_ratio_bp": 2,
        }
        no_flat = refringe_credit_node(**common, refringe_flat_bonus_bp=0)
        with_flat = refringe_credit_node(**common, refringe_flat_bonus_bp=2000)
        slope_a = _eval_at_ap(no_flat, 1000) - _eval_at_ap(no_flat, 0)
        slope_b = _eval_at_ap(with_flat, 1000) - _eval_at_ap(with_flat, 0)
        assert slope_a == pytest.approx(slope_b)
        assert _eval_at_ap(with_flat, 0) > _eval_at_ap(no_flat, 0)


class TestDividesOutTheStaleMultiplier:
    def test_the_simulations_multiplier_does_not_survive(self) -> None:
        """Two sims of the same teammate tick at different stripped APs agree.

        `frozen_tick_damage` carries whatever Refringe multiplier the simulation
        happened to use. If that were not divided back out, the credit would
        depend on the disc-stripped build — the exact staleness
        `luminize_owner_scaled_node` exists to remove.
        """
        # Same underlying neutral tick (1000.0), baked at two different sim APs.
        a = refringe_credit_node(
            frozen_tick_damage=1000.0 * 11000 / 10000,
            refringe_mult_at_stripped_ap=11000,
            refringe_ap_ratio_bp=2,
            refringe_flat_bonus_bp=2000,
        )
        b = refringe_credit_node(
            frozen_tick_damage=1000.0 * 12000 / 10000,
            refringe_mult_at_stripped_ap=12000,
            refringe_ap_ratio_bp=2,
            refringe_flat_bonus_bp=2000,
        )
        assert _eval_at_ap(a, 600) == pytest.approx(_eval_at_ap(b, 600))


class TestStepType:
    def test_is_a_damage_step_and_a_step(self) -> None:
        """Must be in both unions or the mappers/scorers will not dispatch it.

        The unions are declared with forward references, so compare by name
        rather than by identity.
        """
        from app.services import combo_types

        for union_name in ("DamageStep", "Step"):
            members = {
                a.__forward_arg__ if hasattr(a, "__forward_arg__") else a.__name__
                for a in getattr(combo_types, union_name).__args__
            }
            assert "RefringeCreditStep" in members, union_name

    def test_carries_what_the_node_needs(self) -> None:
        step = RefringeCreditStep(
            label="Refringe credit (physical)",
            attack_id="refringe_credit_physical_1.0",
            frozen_tick_damage=1000.0,
            refringe_mult_at_stripped_ap=11224,
            refringe_ap_ratio_bp=2,
            refringe_flat_bonus_bp=2000,
        )
        node = refringe_credit_node(
            frozen_tick_damage=step.frozen_tick_damage,
            refringe_mult_at_stripped_ap=step.refringe_mult_at_stripped_ap,
            refringe_ap_ratio_bp=step.refringe_ap_ratio_bp,
            refringe_flat_bonus_bp=step.refringe_flat_bonus_bp,
        )
        assert _eval_at_ap(node, 612) > 0
