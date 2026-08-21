"""Task 9 — per-enemy Lumiflux Buildup Point pool (P2).

Covers the acceptance criteria in TASKS_remielle.md's Task 9:

* Points cap at `spec.point_cap` (read from the spec, never hardcoded) and
  never go negative.
* A second Lumiflux agent in the squad shares the *same* per-enemy pool —
  the pool is keyed by enemy only, never by (enemy, agent); `owner_agent_id`
  is attribution, not partitioning.
* The state serialises into the simulator's timeline for explainability.

`lumiflux.py`'s `apply_lumiflux_points`/`consume_lumiflux_points` are pure
and ORM-free (DESIGN §3), so the first two groups below are plain unit
tests. The timeline-serialization group exercises
`anomaly_simulator._record_lumiflux_points`, the plumbing that a future
move-resolution call site (Task 18/20) will invoke — there is no live call
site inside `simulate()` yet (Task 9 is infra only), so these tests call
the helper directly rather than driving a full `simulate()` run.
"""

from __future__ import annotations

import pytest

from app.services.anomaly_simulator import TimelineEvent, _record_lumiflux_points
from app.services.lumiflux import (
    LumifluxEnemyState,
    LumifluxSpec,
    apply_lumiflux_points,
    consume_lumiflux_points,
)


def _spec(*, point_cap: int = 4) -> LumifluxSpec:
    """A minimal spec with only the fields the pool functions read."""
    return LumifluxSpec(
        point_cap=point_cap,
        voidflare_cap=3,
        refringe_ap_ratio_bp=2,
        refringe_flat_bonuses={},
        luminize_multipliers={},
        luminize_ap_bonus_bp=10,
        phase_flow_tick_s=5.0,
        phase_flow_duration_s=40.0,
        flight_attack_points=(0, 1, 2),
        flight_attack_mv_bp=(8130, 20320, 16250),
        flight_attack_daze_bp=(27500, 37820, 37820),
    )


class TestLumifluxEnemyStateEmpty:
    def test_empty_has_zero_points_and_no_history(self) -> None:
        state = LumifluxEnemyState.empty()

        assert state.points == 0
        assert state.owner_agent_id is None
        assert state.last_point_at is None


class TestApplyLumifluxPointsCapping:
    """"Points cap at spec.point_cap (4 for Remielle, but the cap must come
    from spec, not a hardcoded 4)" (Task 9 acceptance)."""

    def test_apply_from_none_state_starts_the_pool(self) -> None:
        state = apply_lumiflux_points(None, _spec(), 2, agent_id="remielle", at=1.0)

        assert state.points == 2
        assert state.owner_agent_id == "remielle"
        assert state.last_point_at == 1.0

    def test_apply_accumulates(self) -> None:
        state = apply_lumiflux_points(None, _spec(), 2, agent_id="remielle", at=1.0)
        state = apply_lumiflux_points(state, _spec(), 1, agent_id="remielle", at=2.0)

        assert state.points == 3

    def test_apply_caps_at_spec_point_cap(self) -> None:
        state = apply_lumiflux_points(None, _spec(point_cap=4), 3, agent_id="remielle", at=1.0)
        state = apply_lumiflux_points(state, _spec(point_cap=4), 5, agent_id="remielle", at=2.0)

        assert state.points == 4

    def test_cap_is_read_from_spec_not_hardcoded(self) -> None:
        """A different agent's spec with a non-4 cap must be honored exactly."""
        state = apply_lumiflux_points(None, _spec(point_cap=2), 10, agent_id="other", at=1.0)

        assert state.points == 2

    def test_apply_at_cap_still_refreshes_owner_and_last_point_at(self) -> None:
        # DESIGN §7.1: the linger clock tracks "when a point was applied,"
        # not "when the total actually changed" -- applying while already
        # at cap still counts as an application for that purpose.
        state = apply_lumiflux_points(None, _spec(point_cap=4), 4, agent_id="a", at=1.0)

        state = apply_lumiflux_points(state, _spec(point_cap=4), 1, agent_id="b", at=5.0)

        assert state.points == 4
        assert state.owner_agent_id == "b"
        assert state.last_point_at == 5.0

    def test_zero_count_is_a_no_op(self) -> None:
        state = apply_lumiflux_points(None, _spec(), 2, agent_id="a", at=1.0)

        same = apply_lumiflux_points(state, _spec(), 0, agent_id="b", at=99.0)

        assert same.points == 2
        assert same.owner_agent_id == "a"
        assert same.last_point_at == 1.0

    def test_negative_count_raises(self) -> None:
        with pytest.raises(ValueError, match="apply_lumiflux_points"):
            apply_lumiflux_points(None, _spec(), -1, agent_id="a", at=1.0)


class TestConsumeLumifluxPointsNeverNegative:
    """"[Points] never go negative" (Task 9 acceptance)."""

    def test_consume_decrements(self) -> None:
        state = apply_lumiflux_points(None, _spec(), 3, agent_id="a", at=1.0)

        state = consume_lumiflux_points(state, 1)

        assert state.points == 2

    def test_consume_floors_at_zero(self) -> None:
        state = apply_lumiflux_points(None, _spec(), 1, agent_id="a", at=1.0)

        state = consume_lumiflux_points(state, 5)

        assert state.points == 0

    def test_consume_from_none_state_stays_at_zero(self) -> None:
        state = consume_lumiflux_points(None, 1)

        assert state.points == 0

    def test_consume_does_not_touch_owner_or_last_point_at(self) -> None:
        state = apply_lumiflux_points(None, _spec(), 2, agent_id="a", at=1.0)

        state = consume_lumiflux_points(state, 1)

        assert state.owner_agent_id == "a"
        assert state.last_point_at == 1.0

    def test_negative_count_raises(self) -> None:
        state = apply_lumiflux_points(None, _spec(), 2, agent_id="a", at=1.0)

        with pytest.raises(ValueError, match="consume_lumiflux_points"):
            consume_lumiflux_points(state, -1)


class TestSecondLumifluxAgentSharesThePool:
    """"A second Lumiflux agent in the squad shares the same per-enemy pool
    (i.e. the pool is keyed by enemy only, not by (enemy, lumiflux_agent)
    pair -- owner_agent_id just records who most recently contributed
    points, for attribution, not for partitioning the pool)" (Task 9
    acceptance)."""

    def test_two_agents_contribute_to_one_shared_total(self) -> None:
        spec = _spec(point_cap=4)

        state = apply_lumiflux_points(None, spec, 1, agent_id="remielle", at=1.0)
        state = apply_lumiflux_points(state, spec, 1, agent_id="second_lumiflux_agent", at=2.0)
        state = apply_lumiflux_points(state, spec, 1, agent_id="remielle", at=3.0)

        # Not 1 (per-agent) or a per-agent split -- one pool, three
        # contributions summed.
        assert state.points == 3

    def test_owner_agent_id_reflects_only_the_most_recent_contributor(self) -> None:
        spec = _spec(point_cap=4)

        state = apply_lumiflux_points(None, spec, 1, agent_id="remielle", at=1.0)
        state = apply_lumiflux_points(state, spec, 1, agent_id="second_lumiflux_agent", at=2.0)

        assert state.owner_agent_id == "second_lumiflux_agent"
        # But the shared total still includes remielle's earlier point --
        # owner_agent_id is attribution, not a partition key.
        assert state.points == 2

    def test_shared_cap_binds_across_both_agents_combined(self) -> None:
        spec = _spec(point_cap=4)

        state = apply_lumiflux_points(None, spec, 3, agent_id="remielle", at=1.0)
        state = apply_lumiflux_points(state, spec, 3, agent_id="second_lumiflux_agent", at=2.0)

        # 3 + 3 = 6 would overflow a 4-point cap if the pool were shared;
        # confirms the cap applies to the combined total, not per agent.
        assert state.points == 4


class TestRecordLumifluxPointsTimelineSerialization:
    """"The state serialises into the timeline for explainability" (Task 9
    acceptance) -- exercised via `anomaly_simulator._record_lumiflux_points`,
    the plumbing a future move-resolution call site will invoke."""

    def test_emits_a_lumiflux_point_event_with_the_new_state(self) -> None:
        events: list[TimelineEvent] = []

        new_state = _record_lumiflux_points(
            None, _spec(point_cap=4), 2, agent_id="remielle", t=3.5, events=events
        )

        assert new_state.points == 2
        assert len(events) == 1
        event = events[0]
        assert event.kind == "lumiflux_point"
        assert event.t == 3.5
        assert event.agent_id == "remielle"
        assert event.applier_agent_id == "remielle"
        assert event.detail == {
            "points_added": 2,
            "points": 2,
            "point_cap": 4,
            "owner_agent_id": "remielle",
            "last_point_at": 3.5,
        }

    def test_returns_the_same_state_apply_lumiflux_points_would(self) -> None:
        events: list[TimelineEvent] = []
        direct = apply_lumiflux_points(None, _spec(), 2, agent_id="remielle", at=1.0)

        via_helper = _record_lumiflux_points(
            None, _spec(), 2, agent_id="remielle", t=1.0, events=events
        )

        assert via_helper == direct

    def test_second_agent_call_shares_the_same_state_slot(self) -> None:
        events: list[TimelineEvent] = []
        spec = _spec(point_cap=4)

        state = _record_lumiflux_points(None, spec, 1, agent_id="remielle", t=1.0, events=events)
        state = _record_lumiflux_points(
            state, spec, 1, agent_id="second_lumiflux_agent", t=2.0, events=events
        )

        assert state.points == 2
        assert len(events) == 2
        assert [e.agent_id for e in events] == ["remielle", "second_lumiflux_agent"]
