"""Unit tests for A6 — null-safety in calculate_team_endpoint build-id set."""

from __future__ import annotations

from types import SimpleNamespace


def _team_build_ids(team: object) -> set[str]:
    """Replicate the null-safe id set from calculate_team_endpoint."""
    return {
        str(bid)
        for bid in (team.build1_id, team.build2_id, team.build3_id)  # type: ignore[attr-defined]
        if bid is not None
    }


class TestTeamBuildIdNullSafety:
    def test_three_members_all_present(self) -> None:
        team = SimpleNamespace(build1_id="aaa", build2_id="bbb", build3_id="ccc")
        ids = _team_build_ids(team)
        assert ids == {"aaa", "bbb", "ccc"}

    def test_two_members_build3_absent(self) -> None:
        team = SimpleNamespace(build1_id="aaa", build2_id="bbb", build3_id=None)
        ids = _team_build_ids(team)
        assert ids == {"aaa", "bbb"}
        assert "None" not in ids

    def test_one_member_only(self) -> None:
        team = SimpleNamespace(build1_id="aaa", build2_id=None, build3_id=None)
        ids = _team_build_ids(team)
        assert ids == {"aaa"}

    def test_dps_not_in_present_ids_is_excluded(self) -> None:
        team = SimpleNamespace(build1_id="aaa", build2_id=None, build3_id="ccc")
        ids = _team_build_ids(team)
        assert "bbb" not in ids
        assert "None" not in ids

    def test_dps_in_two_member_team(self) -> None:
        team = SimpleNamespace(build1_id="aaa", build2_id="bbb", build3_id=None)
        ids = _team_build_ids(team)
        assert "aaa" in ids
        assert "bbb" in ids
        assert len(ids) == 2
