"""Scored-step diagnostics on the optimize response (#161).

A run whose target never fired its signature mechanic is indistinguishable from
a healthy one, and its stat recommendations are confidently wrong. That is not
hypothetical: a Remielle run put her only Luminize trigger at step 1, before any
Voidflare could exist, so Luminize damage was exactly zero, 100% of her scored
output was crit-bearing, and the optimizer recommended selling Anomaly
Proficiency to buy CRIT. Diagnosing it took a direct `optimization_jobs` query
against production.

These pin the two numbers that would have made it a five-minute answer.
"""

from __future__ import annotations

from app.schemas.optimizer import SearchTransparencySchema
from app.services.combo_types import (
    AnomalyStep,
    ComboStep,
    LuminizeStep,
    RefringeCreditStep,
    StunEndStep,
    StunTriggerStep,
)
from app.services.modifiers import AttackScope
from app.services.optimizer_pipeline import _STEP_KIND_LABELS, _scored_event_kind_counts


class _Payload:
    """Minimal stand-in for ResolvedPayload's two step-carrying fields."""

    def __init__(self, all_step_lists, event_log_by_am=None):
        self.all_step_lists = all_step_lists
        self.event_log_by_am = event_log_by_am


def _combo(label="Hit"):
    return ComboStep(
        label=label, attack_id=label, attack_name=label, scope=AttackScope.ALL, multiplier=1000
    )


def _anomaly():
    return AnomalyStep(
        label="Burn", attack_id="burn", anomaly_type="burn", element="fire", procs_override=1.0
    )


def _luminize():
    return LuminizeStep(
        label="Luminize",
        attack_id="lum",
        voidflare_element="physical",
        effective_mult_bp=32000,
        def_ignore=0,
        constant_factor=1.0,
        frozen_damage=100.0,
    )


def _credit():
    return RefringeCreditStep(
        label="Refringe credit",
        attack_id="rc",
        frozen_tick_damage=100.0,
        refringe_mult_at_stripped_ap=11224,
        refringe_ap_ratio_bp=2,
        refringe_flat_bonus_bp=2000,
    )


class TestCounts:
    def test_counts_each_step_class_under_its_label(self) -> None:
        steps = [_combo(), _combo(), _anomaly(), _luminize(), _credit()]
        assert _scored_event_kind_counts(_Payload([steps])) == {
            "standard": 2,
            "anomaly": 1,
            "luminize": 1,
            "refringe_credit": 1,
        }

    def test_markers_collapse_to_one_label(self) -> None:
        counts = _scored_event_kind_counts(_Payload([[StunTriggerStep(), StunEndStep()]]))
        assert counts == {"stun_marker": 2}

    def test_prefers_the_am_multiplexed_map_when_present(self) -> None:
        """`event_log_by_am` is the sentinel for AM multiplexing.

        Reading `all_step_lists` there would report a stale or partial view.
        """
        payload = _Payload(
            all_step_lists=[[_combo()]],
            event_log_by_am={100: [_combo(), _anomaly()], 200: [_combo()]},
        )
        assert _scored_event_kind_counts(payload) == {"standard": 2, "anomaly": 1}

    def test_a_mechanic_that_never_fired_is_visibly_absent(self) -> None:
        """The motivating case. Luminize scoring zero must be READABLE.

        Absence, not a zero entry — the caller checks membership, and a run with
        no Luminize step at all is exactly the state that produced a confidently
        wrong AP-vs-CRIT recommendation.
        """
        counts = _scored_event_kind_counts(_Payload([[_combo(), _combo(), _anomaly()]]))
        assert "luminize" not in counts
        assert "refringe_credit" not in counts
        assert counts["standard"] == 2

    def test_empty_is_empty_not_an_error(self) -> None:
        assert _scored_event_kind_counts(_Payload([])) == {}
        assert _scored_event_kind_counts(_Payload([[]])) == {}


class TestLabelCoverage:
    def test_every_step_class_has_a_label(self) -> None:
        """An unlabelled step type would report as its raw class name.

        Harmless but ugly, and it means a new step type silently changes the
        diagnostic's vocabulary rather than being named deliberately.
        """
        from app.services import combo_types

        union = combo_types.Step
        names = {
            a.__forward_arg__ if hasattr(a, "__forward_arg__") else a.__name__
            for a in union.__args__
        }
        labelled = {cls.__name__ for cls in _STEP_KIND_LABELS}
        assert names == labelled, f"unlabelled step types: {sorted(names - labelled)}"


class TestSchema:
    def test_both_diagnostics_default_so_old_payloads_still_validate(self) -> None:
        schema = SearchTransparencySchema(
            total_space=10,
            evaluated=5,
            pruned_sets=0,
            pruned_stats=0,
            prefiltered=0,
            is_exact=True,
        )
        assert schema.pareto_removed == 0
        assert schema.scored_event_kinds == {}

    def test_pareto_removed_is_reportable(self) -> None:
        """It was tracked internally and never surfaced, which made a
        53-billion-to-6,592 reduction look like it came from nowhere."""
        schema = SearchTransparencySchema(
            total_space=53_035_661_250,
            evaluated=6592,
            pruned_sets=0,
            pruned_stats=0,
            prefiltered=0,
            is_exact=True,
            pareto_removed=412,
            scored_event_kinds={"standard": 12, "luminize": 0},
        )
        assert schema.pareto_removed == 412
