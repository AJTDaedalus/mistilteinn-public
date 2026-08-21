"""Integration tests for TeamRepository eager-load completeness (Task 1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.agent import Agent
from app.models.build import Build
from app.models.enums import Element, Rarity, Specialty
from app.models.team import Team
from app.repositories.team import TeamRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_agent(db_session: AsyncSession, name: str = "Agent") -> Agent:
    a = Agent(
        hakushin_id=hash(name) % 100_000,
        name=name,
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_hp=800,
        base_atk=150,
        base_def=60,
        hp_growth=500000,
        atk_growth=40000,
        def_growth=50000,
        base_crit_rate=500,
        base_crit_dmg=5000,
    )
    db_session.add(a)
    await db_session.flush()
    return a


async def _make_build(db_session: AsyncSession, agent: Agent) -> Build:
    b = Build(agent_id=agent.id)
    db_session.add(b)
    await db_session.flush()
    return b


async def _make_team(
    db_session: AsyncSession,
    b1: Build,
    b2: Build,
    b3: Build,
) -> Team:
    t = Team(name="Test Team", build1_id=b1.id, build2_id=b2.id, build3_id=b3.id)
    db_session.add(t)
    await db_session.flush()
    return t


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTeamRepositoryEagerLoads:
    """TeamRepository.get_by_id must eager-load everything snapshot_builder needs."""

    async def test_all_members_have_agent_core_skills(self, db_session: AsyncSession) -> None:
        a1 = await _make_agent(db_session, "A1")
        a2 = await _make_agent(db_session, "A2")
        a3 = await _make_agent(db_session, "A3")
        b1 = await _make_build(db_session, a1)
        b2 = await _make_build(db_session, a2)
        b3 = await _make_build(db_session, a3)
        team = await _make_team(db_session, b1, b2, b3)

        repo = TeamRepository(db_session)
        loaded = await repo.get_by_id(str(team.id))

        assert loaded is not None
        # core_skills must be loaded (not lazy) — access should not raise
        # MissingGreenlet or trigger additional DB round trips.
        for member in (loaded.build1, loaded.build2, loaded.build3):
            _ = member.agent.core_skills  # list access, not attribute error

    async def test_all_members_have_agent_mindscapes(self, db_session: AsyncSession) -> None:
        a1 = await _make_agent(db_session, "B1")
        a2 = await _make_agent(db_session, "B2")
        a3 = await _make_agent(db_session, "B3")
        b1 = await _make_build(db_session, a1)
        b2 = await _make_build(db_session, a2)
        b3 = await _make_build(db_session, a3)
        team = await _make_team(db_session, b1, b2, b3)

        repo = TeamRepository(db_session)
        loaded = await repo.get_by_id(str(team.id))

        assert loaded is not None
        for member in (loaded.build1, loaded.build2, loaded.build3):
            _ = member.agent.mindscapes

    async def test_all_members_have_discs_with_disc_set(self, db_session: AsyncSession) -> None:
        a1 = await _make_agent(db_session, "C1")
        a2 = await _make_agent(db_session, "C2")
        a3 = await _make_agent(db_session, "C3")
        b1 = await _make_build(db_session, a1)
        b2 = await _make_build(db_session, a2)
        b3 = await _make_build(db_session, a3)
        team = await _make_team(db_session, b1, b2, b3)

        repo = TeamRepository(db_session)
        loaded = await repo.get_by_id(str(team.id))

        assert loaded is not None
        # discs list + disc_set per disc must be accessible
        for member in (loaded.build1, loaded.build2, loaded.build3):
            for disc in member.discs:
                _ = disc.disc_set

    async def test_all_members_have_w_engine(self, db_session: AsyncSession) -> None:
        a1 = await _make_agent(db_session, "D1")
        a2 = await _make_agent(db_session, "D2")
        a3 = await _make_agent(db_session, "D3")
        b1 = await _make_build(db_session, a1)
        b2 = await _make_build(db_session, a2)
        b3 = await _make_build(db_session, a3)
        team = await _make_team(db_session, b1, b2, b3)

        repo = TeamRepository(db_session)
        loaded = await repo.get_by_id(str(team.id))

        assert loaded is not None
        for member in (loaded.build1, loaded.build2, loaded.build3):
            # w_engine may be None (no weapon equipped) but must not be lazy
            _ = member.w_engine
