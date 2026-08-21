"""Abloom is scored, rescaled to the scored build's live AP (#163).

The last damage-carrying event kind that fell into the mapper's warn-only tail
and contributed zero. It is not a ComboStep — it fractions an already-resolved
anomaly, so it carries no DEF/RES/level areas of its own and must not gain a
CritArea (Aria M1's grant is a separate bucket, per C2).

Two agents own its inputs, as they do for Luminize (E-8): `original_anomaly_dmg`
belongs to the aura's applier, `ap` to the acting agent. Only the second is the
scored build's, and the expression is linear in it.
"""

from __future__ import annotations

import pytest

from app.formula.builder import const
from app.formula.zzz.damage import abloom_rescaled_node
from app.formula.zzz.tags import Q_ANOMALY_PROF, stat_tag
from app.pando.calculator import Calculator, NodeRegistry
from app.services.combo_types import AbloomStep
from app.services.optimizer_pipeline import _DELIBERATELY_UNSCORED_EVENT_KINDS


def _eval(node, ap: int) -> float:
    reg = NodeRegistry()
    reg.register(stat_tag(Q_ANOMALY_PROF), const(float(ap)))
    return Calculator(reg).compute(node)


class TestApScaled:
    def test_rescales_linearly_from_the_frozen_ap(self) -> None:
        """At the simulation's own AP the value is unchanged — the identity case."""
        node = abloom_rescaled_node(9000.0, frozen_ap=300, ap_scaled=True)
        assert _eval(node, 300) == pytest.approx(9000.0)
        assert _eval(node, 600) == pytest.approx(18000.0)

    def test_more_ap_is_strictly_more_damage(self) -> None:
        node = abloom_rescaled_node(9000.0, frozen_ap=300, ap_scaled=True)
        assert _eval(node, 400) > _eval(node, 300)

    def test_exactly_linear(self) -> None:
        node = abloom_rescaled_node(9000.0, frozen_ap=300, ap_scaled=True)
        lo, mid, hi = (_eval(node, ap) for ap in (100, 200, 300))
        assert mid - lo == pytest.approx(hi - mid)


class TestNotApScaled:
    """Grace and Burnice — kits whose text quotes a fixed percentage."""

    def test_is_a_constant(self) -> None:
        node = abloom_rescaled_node(9000.0, frozen_ap=300, ap_scaled=False)
        assert _eval(node, 0) == pytest.approx(9000.0)
        assert _eval(node, 9999) == pytest.approx(9000.0)

    def test_a_zero_frozen_ap_cannot_divide(self) -> None:
        """Guards the division rather than trusting callers to never pass 0."""
        node = abloom_rescaled_node(9000.0, frozen_ap=0, ap_scaled=True)
        assert _eval(node, 500) == pytest.approx(9000.0)


class TestTheUnderCreditIsDeliberate:
    def test_the_applier_half_stays_frozen(self) -> None:
        """`original_anomaly_dmg` is inside `frozen_abloom_damage` and does not move.

        Exact when a teammate applied the aura — the optimizer never strips a
        support. An under-credit when the scored build applied it, since its own
        anomaly would also grow with its discs. Rebuilding that half needs the
        aura's full anomaly context, which the event does not carry; an
        under-credit is the safe direction and strictly better than the 100%
        under-credit of scoring abloom as zero.
        """
        node = abloom_rescaled_node(9000.0, frozen_ap=300, ap_scaled=True)
        # Doubling AP doubles the result — no term beyond AP responds.
        assert _eval(node, 600) == pytest.approx(2 * _eval(node, 300))


class TestStillClassifiedAsScored:
    def test_abloom_is_not_marked_deliberately_unscored(self) -> None:
        """It used to be tracked as known-unhandled-and-noisy. Now it is handled,
        and it must not drift into the "intentionally silent" set either way."""
        assert "abloom" not in _DELIBERATELY_UNSCORED_EVENT_KINDS

    def test_the_step_carries_what_the_node_needs(self) -> None:
        step = AbloomStep(
            label="Abloom (fire)",
            attack_id="abloom_fire_1.0",
            frozen_abloom_damage=9000.0,
            frozen_ap=300,
        )
        assert step.ap_scaled is True
        node = abloom_rescaled_node(
            step.frozen_abloom_damage, step.frozen_ap, step.ap_scaled
        )
        assert _eval(node, 600) == pytest.approx(18000.0)
