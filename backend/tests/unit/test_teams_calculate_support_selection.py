"""`/teams/{id}/calculate` must not hand the primary back as its own support (#133).

The seven sites #133 narrowed all shared one spelling — ``[m for i, m in
enumerate(members) if i != active_index]`` — and the structural guard in
`test_no_index_only_support_selection.py` keys on exactly that shape. `teams.py`'s
`_evaluate_team` reached the same place by a different spelling, ``all_members[1:]``,
which no comprehension-shaped check can see. It is the same defect: on a row with one
build in two slots the primary lands in its own support list, and
`_derive_auto_conditions` then lets it satisfy its own SAME_*/ANOMALY_COUNT_* checks
(a support's ability gate is supposed to depend on its *teammates*).

Left unfixed it would also have split the two team endpoints: `/evaluate-discs` was
narrowed by #133, `/calculate` was not, so the same forged row would have scored
differently through each.
"""

from __future__ import annotations

from unittest.mock import patch

from app.api.v1 import teams as teams_api
from app.schemas.damage import TeamCalculateRequest
from app.services.modifiers import ActiveConditions
from app.services.team_calculator import TeamMember

_PRIMARY = TeamMember(
    build_id="build-primary",
    agent_name="Primary",
    agent_element="ice",
    agent_specialty="anomaly",
    agent_faction_id=1,
)
_SUPPORT = TeamMember(
    build_id="build-support",
    agent_name="Support",
    agent_element="fire",
    agent_specialty="support",
    agent_faction_id=2,
)


def _body(*, with_attribution: bool) -> TeamCalculateRequest:
    return TeamCalculateRequest(
        combo_id="combo",
        enemy_profile_id="enemy",
        with_attribution=with_attribution,
    )


def _captured_support_members(
    all_members: list[TeamMember],
    *,
    with_attribution: bool,
) -> list[str]:
    """Run `_evaluate_team` with the evaluators stubbed; return the support build ids."""
    target = (
        "app.api.v1.teams.evaluate_combo_attributed"
        if with_attribution
        else "app.api.v1.teams.calculate_team_combo"
    )
    with patch(target) as evaluator:
        teams_api._evaluate_team(
            _body(with_attribution=with_attribution),
            all_members=all_members,
            member_snapshots={m.build_id: object() for m in all_members},
            primary_build_id=all_members[0].build_id,
            enemy=object(),
            steps=[],
            conditions=ActiveConditions(),
            crit_mode=teams_api.CritMode.EXPECTED,
        )
    assert evaluator.call_count == 1
    kwargs = evaluator.call_args.kwargs
    assert kwargs["dps_member"] is all_members[0]
    return [m.build_id for m in kwargs["support_members"]]


class TestEvaluateTeamSupportSelection:
    def test_ordinary_team_is_unchanged(self) -> None:
        """The load-bearing claim: distinct builds still yield every other slot, in order."""
        members = [_PRIMARY, _SUPPORT]

        assert _captured_support_members(members, with_attribution=False) == ["build-support"]
        assert _captured_support_members(members, with_attribution=True) == ["build-support"]

    def test_a_build_in_two_slots_is_not_its_own_support(self) -> None:
        members = [_PRIMARY, _PRIMARY, _SUPPORT]

        assert _captured_support_members(members, with_attribution=False) == ["build-support"]
        assert _captured_support_members(members, with_attribution=True) == ["build-support"]

    def test_the_duplicate_does_not_take_the_real_support_with_it(self) -> None:
        """Over-exclusion would drop a genuine teammate — the #121 defect-2 shape."""
        members = [_PRIMARY, _SUPPORT, _PRIMARY]

        assert _captured_support_members(members, with_attribution=False) == ["build-support"]
