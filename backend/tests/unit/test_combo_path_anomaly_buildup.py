"""Task 37 — the team-combo path derives anomalies instead of reporting zero.

`/api/v1/teams/calculate` used to report `anomaly_total = 0` for **every** anomaly
agent, because `simulate_combo_steps` synthesised each step with no gauge:
`_SyntheticAttack.anomaly_buildup` was hardcoded to 0, and `_StepMoveSpec.buildup`
defaulted to `0` — which the step loop reads as an *authored* zero, the value that
deliberately suppresses a move's gauge, rather than as "not specified", which falls
back to summing the step's own DB rows. Both halves had to change: fixing either
alone still yields zero.

That was a known v1 scoping decision (`anomaly_total: int  # always 0 in v1`), and
it is being broken on purpose. These tests pin the new behaviour, the guard that
keeps it sound, and the paths that must NOT change.
"""

from __future__ import annotations

import pytest

from app.services.anomaly_simulator import simulate_combo_steps
from app.services.build_damage_service import BuildSnapshot
from app.services.combo_types import (
    AnomalyStep,
    AnomalyStepResult,
    ComboStep,
    sim_result_to_combo_evaluation,
)
from app.services.modifiers import ActiveConditions, AttackScope


class _Enemy:
    name = "Combo Anomaly Dummy"
    level = 60
    defense = 50
    fire_res = 0
    anomaly_capacity_fire = 100
    anomaly_res_fire = 0
    anomaly_duration_default = 10.0
    stun_buildup_multiplier = 10000
    stun_dmg_taken_ratio = 5000


def _build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_specialty="anomaly",
        agent_level=60,
        agent_base_atk=2000,
        agent_anomaly_proficiency=115,
        agent_anomaly_mastery=100,
    )


def _fire_combo(buildup: int, n: int = 6) -> list[ComboStep]:
    return [
        ComboStep(
            label=f"Basic {i + 1}",
            attack_id=f"atk{i}",
            attack_name=f"Basic Attack {i + 1}",
            scope=AttackScope.BASIC,
            multiplier=3000,
            element="fire",
            anomaly_buildup=buildup,
        )
        for i in range(n)
    ]


def _evaluate(steps: list[ComboStep]):
    build = _build()
    sim = simulate_combo_steps(build, steps, _Enemy())
    return sim, sim_result_to_combo_evaluation(sim, steps, build, ActiveConditions())


class TestAnomaliesNowReachTheComboPath:
    """The acceptance bar: a 6-step fire combo produces a real Burn."""

    def test_emits_anomaly_and_anomaly_tick_events(self) -> None:
        sim, _ = _evaluate(_fire_combo(3000))
        kinds = {e.kind for e in sim.events}
        assert "anomaly" in kinds, (
            "no `anomaly` event — the gauge never filled, so either the step's "
            "anomaly_buildup is not reaching _SyntheticAttack or _StepMoveSpec.buildup "
            "is still an authored zero"
        )
        assert "anomaly_tick" in kinds, "the anomaly applied but dealt no damage"

    def test_anomaly_total_is_nonzero(self) -> None:
        _, ev = _evaluate(_fire_combo(3000))
        assert ev.anomaly_total > 0, "anomaly_total is still hardcoded to 0"
        assert ev.total_damage == ev.standard_total + ev.anomaly_total

    def test_anomaly_step_results_are_emitted_and_aggregated(self) -> None:
        _, ev = _evaluate(_fire_combo(3000))
        anom_results = [s for s in ev.steps if isinstance(s, AnomalyStepResult)]
        assert anom_results
        assert sum(s.total for s in anom_results) == ev.anomaly_total
        # The breakdowns must see them too — a total that does not appear in
        # by_category/by_element renders as a missing slice in the UI.
        assert sum(c.total for c in ev.by_category) == ev.total_damage
        assert sum(c.total for c in ev.by_element) == ev.total_damage

    def test_the_gauge_threshold_is_respected(self) -> None:
        """Buildup accrues against the enemy's anomaly capacity — it does not
        simply switch anomalies on.

        Below the threshold the rotation still reports zero, which is the honest
        answer and not the old hardcoded one. Above it, exactly one aura applies:
        further buildup refreshes that aura rather than re-triggering it, so the
        damage plateaus. (Pinned because a naive "any buildup ⇒ anomaly"
        implementation would pass every other test in this class.)
        """
        _, below = _evaluate(_fire_combo(1500))
        _, above = _evaluate(_fire_combo(2000))
        assert below.anomaly_total == 0
        assert above.anomaly_total > 0

        sim_far_above, far_above = _evaluate(_fire_combo(15000))
        assert sum(1 for e in sim_far_above.events if e.kind == "anomaly") == 1
        assert far_above.anomaly_total == above.anomaly_total


class TestUnchangedWhereItMustBe:
    """The fix must be inert for every rotation that genuinely accrues no gauge —
    otherwise it is not a fix, it is a rewrite of every combo's number.
    """

    def test_zero_buildup_steps_still_produce_no_anomaly(self) -> None:
        sim, ev = _evaluate(_fire_combo(0))
        assert {e.kind for e in sim.events}.isdisjoint({"anomaly", "anomaly_tick"})
        assert ev.anomaly_total == 0
        assert ev.total_damage == ev.standard_total

    def test_standard_total_is_untouched_by_the_change(self) -> None:
        """Buildup must add anomaly damage without perturbing the standard half."""
        _, without = _evaluate(_fire_combo(0))
        _, with_gauge = _evaluate(_fire_combo(3000))
        assert with_gauge.standard_total == without.standard_total

    def test_a_hand_built_combostep_defaults_to_no_gauge(self) -> None:
        """`anomaly_buildup` defaults to 0, so every existing caller that builds a
        ComboStep positionally or by keyword is unaffected."""
        step = ComboStep(
            label="x",
            attack_id="x",
            attack_name="x",
            scope=AttackScope.BASIC,
            multiplier=1000,
        )
        assert step.anomaly_buildup == 0


class TestStepResultsSurviveSerialization:
    """The route must be able to serialise what the evaluation now emits.

    `_build_step_schemas` only knew marker steps and `ComboStepResult`; an
    `AnomalyStepResult` fell into the ComboStepResult branch and crashed on
    `s.attack_name` — a 500 on `/api/v1/teams/calculate` for exactly the
    rotations this fix exists for (any that actually proc an anomaly).
    """

    def test_anomaly_step_results_serialize_to_schemas(self) -> None:
        from app.api.v1.teams import _build_step_schemas

        _, ev = _evaluate(_fire_combo(3000))
        assert any(isinstance(s, AnomalyStepResult) for s in ev.steps)

        schemas = _build_step_schemas(ev.steps)
        assert len(schemas) == len(ev.steps)
        anom_schemas = [s for s in schemas if getattr(s, "is_anomaly", False)]
        assert anom_schemas
        assert sum(s.total for s in anom_schemas) == ev.anomaly_total
        for s in anom_schemas:
            # scope doubles as the by_category key for anomaly rows.
            assert s.scope == "burn"
            assert s.element == "fire"


class TestDoubleCountGuard:
    """Deriving anomalies from buildup is only sound while the input list has not
    already materialised them. A list carrying both would count each anomaly
    twice — a plausible wrong number, not a crash, which is why it is asserted.
    """

    def test_rejects_a_step_list_containing_an_anomaly_step(self) -> None:
        steps = [
            *_fire_combo(3000, n=2),
            AnomalyStep(
                label="Burn",
                attack_id="burn",
                anomaly_type="burn",
                element="fire",
            ),
        ]
        with pytest.raises(ValueError, match="counted twice"):
            simulate_combo_steps(_build(), steps, _Enemy())

    def test_the_guard_names_how_many_it_found(self) -> None:
        steps = [
            *_fire_combo(3000, n=1),
            AnomalyStep(label="a", attack_id="a", anomaly_type="burn", element="fire"),
            AnomalyStep(label="b", attack_id="b", anomaly_type="burn", element="fire"),
        ]
        with pytest.raises(ValueError, match="2 AnomalyStep"):
            simulate_combo_steps(_build(), steps, _Enemy())

    def test_a_clean_list_passes_the_guard(self) -> None:
        simulate_combo_steps(_build(), _fire_combo(3000), _Enemy())
