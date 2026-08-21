"""`aftershock` and `kit_formula` are standard damage and must be scored (#163).

Both were falling into the warn-only tail of the event→step mapper, which logs
once per process and contributes **zero**. Any agent whose damage flows through
them was being optimized against a fraction of its own output, and the only
symptom was a server-log line nobody reads.

They are ordinary standard damage: each carries a motion value and an attack
scope, is computed by `calculate_build_damage`, and crits. So they map onto
`ComboStep` exactly as `hit` does and differ only in provenance.
"""

from __future__ import annotations

import pytest

from app.services.optimizer_pipeline import (
    _DELIBERATELY_UNSCORED_EVENT_KINDS,
    _STANDARD_DAMAGE_EVENT_KINDS,
    _owns,
)


class TestTheKindSet:
    def test_covers_hit_and_the_three_that_were_unscored(self) -> None:
        assert {
            "hit",
            "aftershock",
            "kit_formula",
            # Remielle's auto-triggered Assist on gaining 3 Voidflares. Ordinary
            # ASSIST_FOLLOWUP standard damage, and it was scored as zero twice
            # over: absent from every branch, AND its detail carried no
            # `multiplier`/`scope`, so even the generic mapping would have
            # produced 0.
            "phase_flow_unlock_assist",
        } == _STANDARD_DAMAGE_EVENT_KINDS

    @pytest.mark.parametrize("kind", ["abloom", "anomaly_tick", "disorder", "vortex", "luminize"])
    def test_excludes_every_anomaly_family_kind(self, kind: str) -> None:
        """Routing an anomaly kind here would make it crit.

        `ComboStep` goes through `calculate_build_damage`, which has a CritArea.
        Anomaly damage does not crit (absent a kit grant), so a mis-route here is
        not an under-count but a silent inflation.
        """
        assert kind not in _STANDARD_DAMAGE_EVENT_KINDS

    def test_abloom_is_not_quietly_marked_deliberately_unscored(self) -> None:
        """Abloom remains genuinely unhandled, and must keep announcing itself.

        It is anomaly-derived — it scales off the original anomaly's per-proc
        damage and AP, with its own optional crit path — so it needs a dedicated
        step type rather than a `ComboStep`. Listing it as *deliberately*
        unscored would silence the warning while the damage stays lost, which is
        the #163 failure mode wearing a different hat.
        """
        assert "abloom" not in _DELIBERATELY_UNSCORED_EVENT_KINDS
        assert "abloom" not in _STANDARD_DAMAGE_EVENT_KINDS


class TestOwnershipStillApplies:
    """Scoring these must not resurrect the #112 cross-agent credit bug."""

    @staticmethod
    def _event(kind: str, agent_id: str):
        from types import SimpleNamespace

        return SimpleNamespace(
            kind=kind,
            agent_id=agent_id,
            applier_agent_id=agent_id,
            element="physical",
            t=1.0,
            damage=1234.0,
            detail={"multiplier": 5000, "scope": "all"},
        )

    @pytest.mark.parametrize("kind", ["aftershock", "kit_formula"])
    def test_the_scored_builds_own_event_is_kept(self, kind: str) -> None:
        assert _owns(self._event(kind, "dps"), "dps") is True

    @pytest.mark.parametrize("kind", ["aftershock", "kit_formula"])
    def test_a_teammates_event_is_dropped(self, kind: str) -> None:
        """`_owns` falls through to `event.agent_id`, which is the emitter.

        Without this, scoring these kinds would credit the target's stats for a
        teammate's aftershock — exactly what Task 26 fixed for the other kinds.
        """
        assert _owns(self._event(kind, "support1"), "dps") is False
