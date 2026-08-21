"""Unit tests for combo_step_resolver member_builds kwarg (Task 3 team-decoupling).

Tests that member_builds maps dps/support1/support2 keys to Build objects,
and that missing-support steps raise the correct HTTPException.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.combo_step_resolver import resolve_combo_sequence, resolve_combo_step


def _build(agent_id: str = "dps-agent") -> MagicMock:
    b = MagicMock()
    b.agent_id = agent_id
    b.skill_levels = "12,12,12,12,12"
    return b


def _attack(agent_id: str = "dps-agent") -> MagicMock:
    a = MagicMock()
    a.id = "att-1"
    a.name = "Basic Attack 1"
    a.skill_key = "Basic"
    a.element = "fire"
    a.damage_growth = []
    a.agent_id = agent_id
    a.hit_mode = "atomic"
    a.variant_label = None
    return a


def _repo(agent_id: str = "dps-agent") -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_id.return_value = _attack(agent_id)
    repo.get_by_agent_and_name.return_value = [_attack(agent_id)]
    return repo


class TestMemberBuildsKeyMapping:
    """member_builds maps dps/support1/support2 keys to Build objects."""

    @pytest.mark.asyncio
    async def test_dps_key_uses_build_param(self) -> None:
        """Step with agent_id='dps' (or absent) resolves to the build param."""
        dps = _build("dps-agent")
        raw = {"attack_id": "att-1", "label": "BA1"}  # no agent_id → defaults to dps
        repo = _repo("dps-agent")

        member_builds = {"dps": dps}
        steps = await resolve_combo_step(
            raw, build=dps, attack_repo=repo, member_builds=member_builds
        )

        assert len(steps) == 1

    @pytest.mark.asyncio
    async def test_support1_key_resolves_from_member_builds(self) -> None:
        """support1 step uses member_builds['support1'], not build.support1."""
        dps = _build("dps-agent")
        sup1 = _build("sup1-agent")

        raw = {"agent_id": "support1", "attack_id": "att-sup1", "label": "S1 BA"}
        repo = AsyncMock()
        sup1_attack = _attack("sup1-agent")
        repo.get_by_id.return_value = sup1_attack
        repo.get_by_agent_and_name.return_value = [sup1_attack]

        member_builds = {"dps": dps, "support1": sup1}
        steps = await resolve_combo_step(
            raw, build=dps, attack_repo=repo, member_builds=member_builds
        )

        assert len(steps) == 1
        # The attack lookup should use sup1's agent_id
        repo.get_by_id.assert_called_once_with("att-sup1")

    @pytest.mark.asyncio
    async def test_support2_key_resolves_from_member_builds(self) -> None:
        """support2 step uses member_builds['support2'], not build.support2."""
        dps = _build("dps-agent")
        sup2 = _build("sup2-agent")

        raw = {"agent_id": "support2", "attack_id": "att-sup2", "label": "S2 BA"}
        repo = AsyncMock()
        sup2_attack = _attack("sup2-agent")
        repo.get_by_id.return_value = sup2_attack

        member_builds = {"dps": dps, "support2": sup2}
        steps = await resolve_combo_step(
            raw, build=dps, attack_repo=repo, member_builds=member_builds
        )

        assert len(steps) == 1
        repo.get_by_id.assert_called_once_with("att-sup2")

    @pytest.mark.asyncio
    async def test_member_builds_none_raises_for_support_step(self) -> None:
        """When member_builds=None and step is support1, raises 422 (no fallback)."""
        from fastapi import HTTPException

        dps = _build("dps-agent")
        raw = {"agent_id": "support1", "attack_id": "att-sup1", "label": "S1 BA"}
        repo = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await resolve_combo_step(raw, build=dps, attack_repo=repo, member_builds=None)

        assert exc_info.value.status_code == 422
        assert "Support 1" in exc_info.value.detail


class TestMissingSupport:
    """Missing support key raises 422 with clear message."""

    @pytest.mark.asyncio
    async def test_missing_support1_in_member_builds_raises_422(self) -> None:
        from fastapi import HTTPException

        dps = _build("dps-agent")
        raw = {"agent_id": "support1", "attack_id": "att-1", "label": "S1 step"}
        repo = _repo()

        # member_builds has no support1
        member_builds: dict = {"dps": dps}

        with pytest.raises(HTTPException) as exc_info:
            await resolve_combo_step(raw, build=dps, attack_repo=repo, member_builds=member_builds)

        assert exc_info.value.status_code == 422
        assert "Support 1" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_support2_in_member_builds_raises_422(self) -> None:
        from fastapi import HTTPException

        dps = _build("dps-agent")
        raw = {"agent_id": "support2", "attack_id": "att-1", "label": "S2 step"}
        repo = _repo()

        member_builds: dict = {"dps": dps, "support1": _build("sup1")}

        with pytest.raises(HTTPException) as exc_info:
            await resolve_combo_step(raw, build=dps, attack_repo=repo, member_builds=member_builds)

        assert exc_info.value.status_code == 422
        assert "Support 2" in exc_info.value.detail


class TestResolveComboSequenceMemberBuilds:
    """resolve_combo_sequence passes member_builds to each step."""

    @pytest.mark.asyncio
    async def test_sequence_with_mixed_agents(self) -> None:
        dps = _build("dps-agent")
        sup1 = _build("sup1-agent")

        dps_attack = _attack("dps-agent")
        sup_attack = _attack("sup1-agent")

        repo = AsyncMock()

        async def get_by_id(attack_id: str) -> MagicMock:
            if attack_id == "att-dps":
                return dps_attack
            return sup_attack

        repo.get_by_id.side_effect = get_by_id

        sequence = [
            {"attack_id": "att-dps", "label": "DPS BA"},
            {"agent_id": "support1", "attack_id": "att-sup1", "label": "S1 BA"},
        ]
        member_builds = {"dps": dps, "support1": sup1}

        steps = await resolve_combo_sequence(
            sequence, build=dps, attack_repo=repo, member_builds=member_builds
        )

        assert len(steps) == 2
