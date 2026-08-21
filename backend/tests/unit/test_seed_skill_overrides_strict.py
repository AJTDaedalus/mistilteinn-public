"""Unit tests for apply_skill_overrides' --strict mode (Task 7,
docs/TASKS_move_key_resolution.md).

Pure logic, mocked DB (AsyncSession.execute stubbed with AsyncMock), matching this
directory's convention — the DB-backed happy paths (sequential/variant actually landing
on real Attack rows) are already covered by
tests/integration/test_seed_skill_overrides.py.

Default (strict=False) is the existing warn-and-skip behavior, unchanged — these tests
pin that both an unresolvable agent_name and an unresolvable move key raise
UnresolvableOverrideError under strict=True, and are silent no-ops (just a log line)
under the default.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.data.loaders.skill_overrides import AgentOverride, MoveOverride, VariantSpec
from app.models.enums import HitMode
from scripts.seed_skill_overrides import UnresolvableOverrideError, apply_skill_overrides


def _mock_session(*execute_results: MagicMock) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=list(execute_results))
    return session


def _agent_lookup_miss() -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    return result


def _agent_lookup_hit(agent_id: str = "agent-1") -> MagicMock:
    agent = MagicMock()
    agent.id = agent_id
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=agent)
    return result


def _update_result(rowcount: int) -> MagicMock:
    result = MagicMock()
    result.rowcount = rowcount
    return result


def _select_attacks_result(attacks: list) -> MagicMock:
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=attacks)))
    return result


_UNKNOWN_AGENT_OVERRIDES = {
    "x": AgentOverride(
        agent_name="Nonexistent Agent",
        moves={"Some Move": MoveOverride(hit_mode=HitMode.SEQUENTIAL)},
    )
}

_UNKNOWN_SEQUENTIAL_MOVE_OVERRIDES = {
    "x": AgentOverride(
        agent_name="Test Agent",
        moves={"Dead Move": MoveOverride(hit_mode=HitMode.SEQUENTIAL)},
    )
}

_UNKNOWN_VARIANT_MOVE_OVERRIDES = {
    "x": AgentOverride(
        agent_name="Test Agent",
        moves={
            "Dead Variant Move": MoveOverride(
                hit_mode=HitMode.VARIANT,
                variants=[VariantSpec(label="A", hit_indices=[0])],
            )
        },
    )
}


class TestUnresolvableAgentName:
    @pytest.mark.asyncio
    async def test_default_warns_and_skips(self) -> None:
        session = _mock_session(_agent_lookup_miss())
        await apply_skill_overrides(session, _UNKNOWN_AGENT_OVERRIDES)  # must not raise

    @pytest.mark.asyncio
    async def test_strict_raises(self) -> None:
        session = _mock_session(_agent_lookup_miss())
        with pytest.raises(UnresolvableOverrideError, match="Nonexistent Agent"):
            await apply_skill_overrides(session, _UNKNOWN_AGENT_OVERRIDES, strict=True)


class TestUnresolvableSequentialMoveKey:
    @pytest.mark.asyncio
    async def test_default_warns_and_skips(self) -> None:
        session = _mock_session(_agent_lookup_hit(), _update_result(rowcount=0))
        await apply_skill_overrides(session, _UNKNOWN_SEQUENTIAL_MOVE_OVERRIDES)  # must not raise

    @pytest.mark.asyncio
    async def test_strict_raises(self) -> None:
        session = _mock_session(_agent_lookup_hit(), _update_result(rowcount=0))
        with pytest.raises(UnresolvableOverrideError, match="Dead Move"):
            await apply_skill_overrides(session, _UNKNOWN_SEQUENTIAL_MOVE_OVERRIDES, strict=True)


class TestUnresolvableVariantMoveKey:
    @pytest.mark.asyncio
    async def test_default_warns_and_skips(self) -> None:
        session = _mock_session(_agent_lookup_hit(), _select_attacks_result([]))
        await apply_skill_overrides(session, _UNKNOWN_VARIANT_MOVE_OVERRIDES)  # must not raise

    @pytest.mark.asyncio
    async def test_strict_raises(self) -> None:
        session = _mock_session(_agent_lookup_hit(), _select_attacks_result([]))
        with pytest.raises(UnresolvableOverrideError, match="Dead Variant Move"):
            await apply_skill_overrides(session, _UNKNOWN_VARIANT_MOVE_OVERRIDES, strict=True)
