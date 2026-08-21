"""Unit tests for the support_builds kwarg added in Task 2 of team-decoupling.

Tests inject_derived_conditions with explicit support_builds (no DB needed).
For build_snapshot_from_db parity (requires DB data), see the integration
tests in test_snapshot_builder_supports.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models.enums import Element, Specialty
from app.services.modifiers import ActiveConditions, Condition
from app.services.snapshot_builder import inject_derived_conditions


def _agent(element: Element = Element.FIRE, specialty: Specialty = Specialty.ATTACK):
    a = MagicMock()
    a.element = element
    a.specialty = specialty
    return a


def _support(element: Element = Element.FIRE):
    s = MagicMock()
    s.agent = MagicMock()
    s.agent.element = element
    return s


class TestInjectDerivedConditionsSupportBuilds:
    def test_same_element_set_when_support_builds_match(self) -> None:
        active = ActiveConditions()
        agent = _agent(Element.FIRE)
        supports = [_support(Element.FIRE)]

        inject_derived_conditions(active, agent, support_builds=supports)

        assert Condition.SAME_ELEMENT_IN_TEAM in active.active

    def test_same_element_not_set_when_no_match(self) -> None:
        active = ActiveConditions()
        agent = _agent(Element.FIRE)
        supports = [_support(Element.ICE), _support(Element.ELECTRIC)]

        inject_derived_conditions(active, agent, support_builds=supports)

        assert Condition.SAME_ELEMENT_IN_TEAM not in active.active

    def test_empty_support_builds_no_same_element(self) -> None:
        active = ActiveConditions()
        agent = _agent(Element.FIRE)

        inject_derived_conditions(active, agent, support_builds=[])

        assert Condition.SAME_ELEMENT_IN_TEAM not in active.active

    def test_empty_support_builds_no_same_element_via_build(self) -> None:
        """Empty support_builds does not trigger SAME_ELEMENT."""
        active = ActiveConditions()
        agent = _agent(Element.FIRE)

        inject_derived_conditions(active, agent, support_builds=[])

        assert Condition.SAME_ELEMENT_IN_TEAM not in active.active

    def test_specialty_and_element_conditions_set_regardless(self) -> None:
        active = ActiveConditions()
        agent = _agent(Element.ELECTRIC, Specialty.STUN)

        inject_derived_conditions(active, agent, support_builds=[])

        assert Condition.EQUIPPER_IS_ELECTRIC in active.active
        assert Condition.EQUIPPER_IS_STUN in active.active


class TestBuildSnapshotFromDbSupportBuildsKwarg:
    """Verify §1c routing in build_snapshot_from_db via patched _support_modifiers."""

    def test_explicit_support_builds_called_for_each_support(self) -> None:
        """§1c iterates support_builds and calls _support_modifiers for each."""
        from app.services.snapshot_builder import build_snapshot_from_db

        calls: list = []

        def fake_support_modifiers(b, disabled_buffs=None):
            calls.append(b)
            return []

        explicit_support = MagicMock()
        explicit_support.agent = MagicMock()

        build = MagicMock()
        build.disabled_buffs = []
        build.mindscape_level = 0
        build.core_skill_level = 5
        build.w_engine_refinement = 1
        build.w_engine = None
        build.discs = []
        build.agent_level = 60

        agent = MagicMock()
        agent.hakushin_id = 99999
        agent.name = "TestAgent"
        agent.specialty = Specialty.ATTACK
        agent.element = Element.FIRE
        agent.base_hp = 800
        agent.base_atk = 150
        agent.base_def = 60
        agent.hp_growth = 500000
        agent.atk_growth = 40000
        agent.def_growth = 50000
        agent.base_crit_rate = 500
        agent.base_crit_dmg = 5000
        agent.core_stats = None
        agent.promotion_stats = None

        with (
            patch("app.services.snapshot_builder.load_agent_modifiers", return_value=[]),
            patch("app.services.snapshot_builder._core_modifiers", return_value=[]),
            patch("app.services.snapshot_builder._core_base_deltas", return_value={}),
            patch(
                "app.services.snapshot_builder._support_modifiers",
                side_effect=fake_support_modifiers,
            ),
        ):
            build_snapshot_from_db(build, agent, support_builds=[explicit_support])

        assert calls == [explicit_support]

    def test_support_builds_none_means_no_supports(self) -> None:
        """When support_builds=None, no support modifiers are folded in."""
        from app.services.snapshot_builder import build_snapshot_from_db

        calls: list = []

        def fake_support_modifiers(b, disabled_buffs=None):
            calls.append(b)
            return []

        build = MagicMock()
        build.disabled_buffs = []
        build.mindscape_level = 0
        build.core_skill_level = 5
        build.w_engine_refinement = 1
        build.w_engine = None
        build.discs = []
        build.agent_level = 60

        agent = MagicMock()
        agent.hakushin_id = 99998
        agent.name = "TestAgentSolo"
        agent.specialty = Specialty.ATTACK
        agent.element = Element.FIRE
        agent.base_hp = 800
        agent.base_atk = 150
        agent.base_def = 60
        agent.hp_growth = 500000
        agent.atk_growth = 40000
        agent.def_growth = 50000
        agent.base_crit_rate = 500
        agent.base_crit_dmg = 5000
        agent.core_stats = None
        agent.promotion_stats = None

        with (
            patch("app.services.snapshot_builder.load_agent_modifiers", return_value=[]),
            patch("app.services.snapshot_builder._core_modifiers", return_value=[]),
            patch("app.services.snapshot_builder._core_base_deltas", return_value={}),
            patch(
                "app.services.snapshot_builder._support_modifiers",
                side_effect=fake_support_modifiers,
            ),
        ):
            build_snapshot_from_db(build, agent, support_builds=None)

        assert calls == []
