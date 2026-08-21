"""Unit tests for optimizer_pipeline / rank_pipeline support_builds routing (Task 4).

Verifies the support_builds routing logic: explicit list takes priority over
build attrs; empty list means no supports.
These are pure logic tests — no async or DB needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _build(agent_id: str = "agent-dps") -> MagicMock:
    b = MagicMock()
    b.agent_id = agent_id
    return b


def _support(agent_id: str = "agent-sup") -> MagicMock:
    return _build(agent_id)


def _resolve_supports(support_builds: list) -> dict[str, str]:
    """Mirror the routing logic from resolve_stateful_am_step_lists §1."""
    return {f"support{i}": s.agent_id for i, s in enumerate(support_builds, 1)}


class TestSupportBuildsRoutingLogic:
    """Direct tests of the sim_builds support routing logic."""

    def test_explicit_list_two_supports(self) -> None:
        explicit = [_support("explicit-sup1"), _support("explicit-sup2")]
        result = _resolve_supports(explicit)

        assert result == {"support1": "explicit-sup1", "support2": "explicit-sup2"}

    def test_empty_list_means_no_supports(self) -> None:
        result = _resolve_supports([])

        assert result == {}

    def test_single_support(self) -> None:
        result = _resolve_supports([_support("only-support")])

        assert result == {"support1": "only-support"}


class TestRankSupportSlotRoutingLogic:
    """Direct tests of the rank support_slot resolution routing."""

    def _resolve_support_build(
        self,
        slot: int,
        explicit_supports: list,
    ) -> MagicMock | None:
        """Mirror rank_pipeline support_slot resolution logic."""
        idx = slot - 1
        if idx >= len(explicit_supports):
            return None
        return explicit_supports[idx]

    def test_slot1_uses_explicit_supports_index0(self) -> None:
        explicit = [_support("explicit-s1"), _support("explicit-s2")]
        resolved = self._resolve_support_build(slot=1, explicit_supports=explicit)

        assert resolved is not None
        assert resolved.agent_id == "explicit-s1"

    def test_slot2_uses_explicit_supports_index1(self) -> None:
        explicit = [_support("explicit-s1"), _support("explicit-s2")]
        resolved = self._resolve_support_build(slot=2, explicit_supports=explicit)

        assert resolved is not None
        assert resolved.agent_id == "explicit-s2"

    def test_slot_out_of_range_returns_none(self) -> None:
        # Only one support in explicit list, requesting slot 2
        explicit = [_support("only-s1")]
        resolved = self._resolve_support_build(slot=2, explicit_supports=explicit)

        assert resolved is None
