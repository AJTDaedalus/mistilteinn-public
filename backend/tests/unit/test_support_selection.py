"""Unit tests for `select_support_members` (issue #133).

Seven call sites built the support list independently as
``[m for i, m in enumerate(members) if i != active_index]``, and each carried the same
latent defect: a build occupying two slots came back as its own support, so
`build_snapshot_from_db` folded that build's own ``target=team`` modifiers into its own
scoring snapshot twice.

The integration counterpart (`tests/integration/test_self_support_exclusion.py`) proves
the helper is actually wired into each pipeline. These pin the rule itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.support_selection import build_identity, select_support_members


@dataclass
class _Build:
    """Stands in for an ORM ``Build`` — identity on ``.id``."""

    id: str
    name: str = ""


@dataclass
class _Member:
    """Stands in for a ``TeamMember`` value object — identity on ``.build_id``."""

    build_id: str
    agent_name: str = ""


class TestBuildIdentity:
    def test_reads_build_id_for_a_team_member(self) -> None:
        assert build_identity(_Member(build_id="b1")) == "b1"

    def test_reads_id_for_an_orm_build(self) -> None:
        assert build_identity(_Build(id="b1")) == "b1"

    def test_build_id_wins_when_both_are_present(self) -> None:
        """A dataclass carrying both means the build it refers to, not its own row."""

        @dataclass
        class Both:
            id: str
            build_id: str

        assert build_identity(Both(id="row", build_id="b1")) == "b1"

    def test_coerces_to_str_so_uuid_and_str_compare_equal(self) -> None:
        import uuid

        u = uuid.uuid4()
        assert build_identity(_Build(id=u)) == str(u)  # type: ignore[arg-type]

    def test_returns_none_when_there_is_no_identity(self) -> None:
        assert build_identity(object()) is None


class TestSelectSupportMembers:
    def test_ordinary_team_returns_the_other_two_in_slot_order(self) -> None:
        a, b, c = _Build("b1"), _Build("b2"), _Build("b3")

        assert select_support_members([a, b, c], 0) == [b, c]
        assert select_support_members([a, b, c], 1) == [a, c]
        assert select_support_members([a, b, c], 2) == [a, b]

    def test_drops_empty_slots(self) -> None:
        a = _Build("b1")
        assert select_support_members([a, None, None], 0) == []

    def test_excludes_a_second_slot_holding_the_same_build(self) -> None:
        """The point of the helper. Index alone would return the primary as its own support."""
        a, other = _Build("b1"), _Build("b2")

        assert select_support_members([a, a, other], 0) == [other]
        # ...from whichever of the duplicated slots is the active one.
        assert select_support_members([a, a, other], 1) == [other]

    def test_a_team_that_is_entirely_one_build_has_no_supports(self) -> None:
        a = _Build("b1")
        assert select_support_members([a, a, a], 0) == []

    def test_distinct_builds_of_the_same_agent_are_kept(self) -> None:
        """Identity is the build, not the agent.

        `assert_slots_distinct` forbids the same *build* twice, not two builds of one
        agent, so excluding by agent name would silently drop a legitimate support.
        """
        a = _Build("b1", name="Miyabi A")
        b = _Build("b2", name="Miyabi B")

        assert select_support_members([a, b, None], 0) == [b]

    def test_works_on_team_member_objects_too(self) -> None:
        """`teams.py` passes TeamMember, not Build — the other shape in this codebase."""
        a, b = _Member(build_id="b1"), _Member(build_id="b2")

        assert select_support_members([a, b], 0) == [b]
        assert select_support_members([a, a], 0) == []

    def test_an_out_of_range_active_index_drops_no_one_but_still_excludes_nothing(self) -> None:
        """Defensive: callers validate the index, so this must not raise."""
        a, b = _Build("b1"), _Build("b2")

        assert select_support_members([a, b], 5) == [a, b]

    def test_an_empty_target_slot_leaves_the_others_intact(self) -> None:
        b, c = _Build("b2"), _Build("b3")

        assert select_support_members([None, b, c], 0) == [b, c]
