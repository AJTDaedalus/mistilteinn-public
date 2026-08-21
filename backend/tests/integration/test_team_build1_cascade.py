"""Regression tests for D-IM1: deleting a Team's build1 must degrade the team,
not cascade-delete it (and its Combos) — the live prod data-loss bug.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.agent import Agent
from app.models.build import Build, Combo
from app.models.enums import Element, Rarity, Specialty
from app.models.team import Team

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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


class TestTeamBuild1Cascade:
    """A build occupying team slot 1 must not take the team down with it."""

    async def test_deleting_slot1_build_survives_team_and_combo(
        self, db_session: AsyncSession
    ) -> None:
        agent = await _make_agent(db_session, "Slot1Agent")
        build1 = await _make_build(db_session, agent)
        team = Team(name="Slot1 Team", build1_id=build1.id)
        db_session.add(team)
        await db_session.flush()
        combo = Combo(name="Rotation", team_id=team.id, sequence=[])
        db_session.add(combo)
        await db_session.flush()
        team_id, combo_id = team.id, combo.id

        await db_session.delete(build1)
        await db_session.flush()
        db_session.expire_all()

        refreshed_team = await db_session.get(Team, team_id)
        assert refreshed_team is not None
        assert refreshed_team.build1_id is None

        refreshed_combo = await db_session.get(Combo, combo_id)
        assert refreshed_combo is not None

    async def test_deleting_slot2_build_survives_team_and_combo(
        self, db_session: AsyncSession
    ) -> None:
        """Control: slot 2 already SET NULLs today (migration 0ffce792bc1e)."""
        agent1 = await _make_agent(db_session, "Slot2DPS")
        agent2 = await _make_agent(db_session, "Slot2Support")
        build1 = await _make_build(db_session, agent1)
        build2 = await _make_build(db_session, agent2)
        team = Team(name="Slot2 Team", build1_id=build1.id, build2_id=build2.id)
        db_session.add(team)
        await db_session.flush()
        combo = Combo(name="Rotation", team_id=team.id, sequence=[])
        db_session.add(combo)
        await db_session.flush()
        team_id, combo_id = team.id, combo.id

        await db_session.delete(build2)
        await db_session.flush()
        db_session.expire_all()

        refreshed_team = await db_session.get(Team, team_id)
        assert refreshed_team is not None
        assert refreshed_team.build2_id is None

        refreshed_combo = await db_session.get(Combo, combo_id)
        assert refreshed_combo is not None

    async def test_deleting_last_build_leaves_team_memberless(
        self, db_session: AsyncSession
    ) -> None:
        """A team with only a slot-1 build, once that build is gone, has no
        members left — this is allowed at the DB level (no CHECK); the
        ≥1-member invariant is enforced only on the save path (D-IM1)."""
        agent = await _make_agent(db_session, "OnlyMember")
        build1 = await _make_build(db_session, agent)
        team = Team(name="Solo Team", build1_id=build1.id)
        db_session.add(team)
        await db_session.flush()
        team_id = team.id

        await db_session.delete(build1)
        await db_session.flush()
        db_session.expire_all()

        refreshed_team = await db_session.get(Team, team_id)
        assert refreshed_team is not None
        assert refreshed_team.build1_id is None
        assert refreshed_team.build2_id is None
        assert refreshed_team.build3_id is None
