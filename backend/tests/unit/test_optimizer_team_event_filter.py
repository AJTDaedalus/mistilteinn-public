"""Task 26 / issue #112 — the optimizer simulates the full team, then filters
events by ownership.

The pre-simulation step cut it replaces (team-builder B10) deleted every
cross-agent mechanic before the simulator could run it: Refringe needs Remielle's
move to bank a Lumiflux point AND a teammate's anomaly trigger to consume it, so
a target-only rotation could never produce one. These are the unit-level pins on
the three pieces that replaced it -- role normalization, per-kind ownership, and
the fractional buildup share.
"""

import pytest
from fastapi import HTTPException

from app.services.anomaly_simulator import TimelineEvent
from app.services.optimizer_pipeline import (
    _anomaly_owner_share,
    _owns,
    normalize_team_sequence,
)


class _Build:
    """Minimal stand-in for a Build row — only `.id` is read."""

    def __init__(self, uid: str) -> None:
        self.id = uid


def _event(kind, *, agent_id="dps", applier_agent_id=None, detail=None):
    return TimelineEvent(
        t=0.0,
        kind=kind,
        agent_id=agent_id,
        element="fire",
        damage=100,
        aura_type=None,
        applier_agent_id=applier_agent_id if applier_agent_id is not None else agent_id,
        detail=detail or {},
    )


class TestOwnership:
    """`_owns` answers "would swapping the scored build's discs move this number?",
    which is not the same as who the timeline credits or who pressed the button."""

    def test_a_teammates_hit_is_not_owned(self):
        assert _owns(_event("hit", agent_id="dps"), "dps") is True
        assert _owns(_event("hit", agent_id="support1"), "dps") is False

    def test_disorder_follows_the_applier_not_the_actor(self):
        """Disorder is emitted against the agent who TRIGGERED it but computed
        from the overridden aura's applier context (`old_ctx`) and credited to
        that applier. So a Disorder the scored build triggers on a teammate's
        aura is teammate-scaled damage and must not be re-scored.

        Filtering it on `agent_id` instead would credit the scored build a
        Disorder whose every stat term belongs to someone else.
        """
        triggered_by_target_on_teammate_aura = _event(
            "disorder", agent_id="dps", applier_agent_id="support1"
        )
        assert _owns(triggered_by_target_on_teammate_aura, "dps") is False

        triggered_by_teammate_on_target_aura = _event(
            "disorder", agent_id="support1", applier_agent_id="dps"
        )
        assert _owns(triggered_by_teammate_on_target_aura, "dps") is True

    def test_vortex_uses_the_triggerer(self):
        assert _owns(_event("vortex", agent_id="dps"), "dps") is True
        assert _owns(_event("vortex", agent_id="support2"), "dps") is False

    def test_stun_markers_belong_to_nobody(self):
        """A stun window opened by a teammate's hit is still a window the scored
        build attacks into — dropping the marker would silently un-stun the
        rest of the rotation."""
        for kind in ("stun_trigger", "stun_end"):
            assert _owns(_event(kind, agent_id="support1"), "dps") is True

    def test_luminize_captured_from_the_scored_build_is_kept(self):
        """She is a support; the Voidflare she fractions is a snapshot of the
        scored build's ATK/AP/DMG%/PEN, so its discs move this number. This is
        the live branch (`frozen_damage is None`) and the reason
        `anomaly_proficiency` joins the union keep-set."""
        e = _event(
            "luminize",
            agent_id="support1",
            detail={
                "voidflare_captured_from": "dps",
                "luminize_owner_agent_id": "support1",
            },
        )
        assert _owns(e, "dps") is True

    def test_luminize_fired_by_the_scored_build_is_kept(self):
        """She IS the optimized build. She can never capture from herself, so
        `voidflare_captured_from` always names a teammate here — filtering on
        provenance alone would delete her own signature damage (Task 15's
        owner-scaled shape)."""
        e = _event(
            "luminize",
            agent_id="dps",
            detail={
                "voidflare_captured_from": "support1",
                "luminize_owner_agent_id": "dps",
            },
        )
        assert _owns(e, "dps") is True

    def test_luminize_between_two_teammates_is_not_kept(self):
        """Captured from one teammate, fired by another. Frozen at a build the
        optimizer never strips and never varies, so no candidate disc can move it
        by a single point — it rode along as a pure constant inflating
        `total_damage` with a teammate's move. The same call `phase_flow_tick`
        already makes for the same reason."""
        e = _event(
            "luminize",
            agent_id="support1",
            detail={
                "voidflare_captured_from": "support2",
                "luminize_owner_agent_id": "support1",
            },
        )
        assert _owns(e, "dps") is False


class TestAnomalyBuildupShare:
    """F-20 made a triggered anomaly's per-proc damage the buildup-share-weighted
    sum of each contributor's OWN calc, so an aura two agents fed is only partly
    the scored build's."""

    def test_absent_field_means_sole_ownership(self):
        """Hand-built events and anything predating this field: a single
        contributor is share 1.0, which is what the pre-F-20 world always was."""
        assert _anomaly_owner_share({}, "dps") == 1.0

    def test_solo_contributor_is_one(self):
        assert _anomaly_owner_share({"per_agent_buildup_shares": {"dps": 1.0}}, "dps") == 1.0

    def test_a_teammate_only_aura_is_zero_and_not_owned(self):
        detail = {"per_agent_buildup_shares": {"support1": 1.0}}
        assert _anomaly_owner_share(detail, "dps") == 0.0
        assert _owns(_event("anomaly_tick", detail=detail), "dps") is False

    def test_shared_aura_is_fractional_and_still_owned(self):
        detail = {"per_agent_buildup_shares": {"dps": 0.25, "support1": 0.75}}
        assert _anomaly_owner_share(detail, "dps") == 0.25
        assert _owns(_event("anomaly_tick", detail=detail), "dps") is True

    def test_buildup_shares_are_not_the_damage_shares(self):
        """`per_agent_shares` is renormalized by each contributor's own per-proc
        damage. The optimizer re-scores the whole anomaly against the candidate
        and wants `buildup_share * per_proc(candidate)`, so dividing by a
        per_proc the rescore is about to recompute would be wrong twice over.
        Pinned because the two fields sit adjacent in the same detail dict.
        """
        detail = {
            "per_agent_buildup_shares": {"dps": 0.5, "support1": 0.5},
            "per_agent_shares": {"dps": 0.9, "support1": 0.1},
        }
        assert _anomaly_owner_share(detail, "dps") == 0.5


class TestNormalizeTeamSequence:
    """The simulator always seats the optimized build as `"dps"`. A stored step
    can name its agent by UUID, by legacy role string, or not at all."""

    def test_uuids_map_to_simulator_roles(self):
        sup_a, sup_b = _Build("a"), _Build("b")
        out = normalize_team_sequence(
            [
                {"move_name": "m1", "agent_id": "t"},
                {"move_name": "m2", "agent_id": "a"},
                {"move_name": "m3", "agent_id": "b"},
            ],
            target_build_id="t",
            support_builds=[sup_a, sup_b],
        )
        assert [s["agent_id"] for s in out] == ["dps", "support1", "support2"]

    def test_teammate_steps_survive(self):
        """The whole point of Task 26: they used to be deleted here, which is
        what switched Refringe off."""
        out = normalize_team_sequence(
            [{"move_name": "m1", "agent_id": "t"}, {"move_name": "m2", "agent_id": "a"}],
            target_build_id="t",
            support_builds=[_Build("a")],
        )
        assert len(out) == 2

    def test_legacy_role_strings_follow_the_active_index(self):
        """Legacy strings index by TEAM slot, so with `active_index=1` the
        stored `"support1"` IS the target and the stored `"dps"` is a support.
        Passing them through unmapped resolved the target's own moves against
        another member's attack table — a pre-existing mis-mapping that only
        stayed invisible while every non-target step was thrown away.
        """
        members = [_Build("m0"), _Build("m1"), _Build("m2")]
        out = normalize_team_sequence(
            [
                {"move_name": "m1", "agent_id": "dps"},
                {"move_name": "m2", "agent_id": "support1"},
                {"move_name": "m3", "agent_id": "support2"},
            ],
            target_build_id="m1",
            support_builds=[members[0], members[2]],
            active_index=1,
            team_members=members,
        )
        assert [s["agent_id"] for s in out] == ["support1", "dps", "support2"]

    def test_missing_agent_id_defaults_to_the_target(self):
        out = normalize_team_sequence(
            [{"move_name": "m1"}],
            target_build_id="t",
            support_builds=[],
        )
        assert out[0]["agent_id"] == "dps"

    def test_other_step_fields_are_preserved(self):
        out = normalize_team_sequence(
            [{"move_name": "m1", "agent_id": "t", "variant_label": "v", "cycle_position": 2}],
            target_build_id="t",
            support_builds=[],
        )
        assert out[0]["variant_label"] == "v"
        assert out[0]["cycle_position"] == 2

    def test_no_target_step_is_still_a_422(self):
        """The contract team-builder B10 introduced alongside the filter. The
        filter is gone; the contract is not."""
        with pytest.raises(HTTPException) as exc:
            normalize_team_sequence(
                [{"move_name": "m1", "agent_id": "a"}],
                target_build_id="t",
                support_builds=[_Build("a")],
            )
        assert exc.value.status_code == 422

    def test_empty_sequence_is_a_422(self):
        with pytest.raises(HTTPException) as exc:
            normalize_team_sequence(None, target_build_id="t", support_builds=[])
        assert exc.value.status_code == 422
