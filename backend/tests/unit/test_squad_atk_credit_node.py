"""Squad-ATK credit — the target's share of a teammate's ATK-scaled damage (#160, A4).

The design classified this as needing a teammate-snapshot rebuild and prescribed a
two-pass re-rank. It does not: **damage is linear in ATK**
(`base_damage(stat, mv) = floor(stat * mv / 10000)`, and standard and anomaly
paths both route through it), so a teammate's damage is proportional to their
total ATK and the grant has the same closed form the Refringe uplift does.

The per-row cap makes it piecewise-linear, which was the stated objection. These
pin that the kink is handled and that the node stays a single evaluation.
"""

from __future__ import annotations

import pytest

from app.formula.builder import const
from app.formula.zzz.damage import squad_atk_credit_node
from app.pando.calculator import Calculator, NodeRegistry
from app.services.combo_types import SquadAtkCreditStep

# Remielle's real rows: (cap, atk_scale_ratio).
REMIELLE_ROWS = ((240, 600), (240, 600), (1120, 2800))


def _eval(node, atk: float) -> float:
    """Drive the node with a literal ATK rather than the two-stage stat graph."""
    reg = NodeRegistry()
    return Calculator(reg).compute(node)


def _node(rows=REMIELLE_ROWS, frozen=10000.0, teammate_atk=3000, atk=2000.0):
    """Build with a constant ATK node so the arithmetic is inspectable."""
    return squad_atk_credit_node(const(atk), frozen, teammate_atk, rows)


class TestClosedForm:
    def test_below_every_cap_is_linear(self) -> None:
        """At ATK 2000: each 600-ratio row grants 120, the 2800 row grants 560.

        grant = 120 + 120 + 560 = 800
        credit = 10000 * 800 / 3000
        """
        node = _node(atk=2000.0)
        assert _eval(node, 2000.0) == pytest.approx(10000.0 * 800 / 3000)

    def test_the_cap_bites(self) -> None:
        """At ATK 8000 every row is capped: 240 + 240 + 1120 = 1600.

        That 1600 is the DB's stated shared maximum, which is the arithmetic
        check that the per-row decomposition still sums to the real cap.
        """
        node = _node(atk=8000.0)
        assert _eval(node, 8000.0) == pytest.approx(10000.0 * 1600 / 3000)

    def test_more_atk_never_reduces_the_credit(self) -> None:
        lo = _eval(_node(atk=1000.0), 1000.0)
        mid = _eval(_node(atk=4000.0), 4000.0)
        hi = _eval(_node(atk=9000.0), 9000.0)
        assert lo < mid <= hi

    def test_past_the_cap_more_atk_adds_nothing(self) -> None:
        """The kink: beyond the cap the credit is flat, not still climbing."""
        a = _eval(_node(atk=8000.0), 8000.0)
        b = _eval(_node(atk=99999.0), 99999.0)
        assert a == pytest.approx(b)

    def test_zero_atk_credits_nothing(self) -> None:
        assert _eval(_node(atk=0.0), 0.0) == pytest.approx(0.0)


class TestDividesOutTheStaleGrant:
    def test_two_sims_of_the_same_teammate_agree(self) -> None:
        """`frozen_teammate_damage` already contains the grant the STRIPPED build
        produced. Dividing by that teammate's sim-time ATK removes it, exactly as
        the Refringe credit divides out its stripped-AP multiplier."""
        a = _node(frozen=10000.0 * 3000 / 3000, teammate_atk=3000, atk=2000.0)
        b = _node(frozen=10000.0 * 3600 / 3000, teammate_atk=3600, atk=2000.0)
        assert _eval(a, 2000.0) == pytest.approx(_eval(b, 2000.0))


class TestRowGating:
    def test_only_the_rows_the_caller_passes_contribute(self) -> None:
        """Condition gating (anomaly_count_3_in_team etc.) is the caller's job.

        Keeping it out of the node is what lets this stay a pure function of ATK
        — and therefore a single evaluation per candidate.
        """
        one_row = _node(rows=((240, 600),), atk=2000.0)
        assert _eval(one_row, 2000.0) == pytest.approx(10000.0 * 120 / 3000)

    def test_no_active_rows_credits_nothing(self) -> None:
        assert _eval(_node(rows=(), atk=2000.0), 2000.0) == pytest.approx(0.0)


class TestStepType:
    def test_carries_what_the_node_needs(self) -> None:
        step = SquadAtkCreditStep(
            label="Squad ATK credit",
            attack_id="sac_1.0",
            frozen_teammate_damage=10000.0,
            teammate_atk_at_sim=3000,
            grant_rows=REMIELLE_ROWS,
        )
        node = squad_atk_credit_node(
            const(2000.0),
            step.frozen_teammate_damage,
            step.teammate_atk_at_sim,
            step.grant_rows,
        )
        assert _eval(node, 2000.0) > 0

    def test_grant_rows_is_hashable_for_the_optimizer_signature(self) -> None:
        """`_build_frame_contexts` keys contexts on these; a list would raise."""
        step = SquadAtkCreditStep(
            label="x",
            attack_id="x",
            frozen_teammate_damage=1.0,
            teammate_atk_at_sim=1,
            grant_rows=REMIELLE_ROWS,
        )
        assert hash((step.frozen_teammate_damage, step.teammate_atk_at_sim, step.grant_rows))
