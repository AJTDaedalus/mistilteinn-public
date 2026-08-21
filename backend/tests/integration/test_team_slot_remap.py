"""Integration tests for TeamRepository's D-IM3 slot snapshot / re-map / sweep.

`build_mode="clean"` deletes every owner build, so team slots go NULL via
D-IM1's `ondelete="SET NULL"`. These three methods let the importer carry
hand-authored team composition across that wipe: snapshot the slots by
`agent_id` before it, re-point them to the freshly created builds after it,
and delete only the teams that ended up with nothing left.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.build import Build, Combo
from app.models.enums import Element, Rarity, Specialty
from app.models.team import Team
from app.models.user import User
from app.repositories.build import BuildRepository
from app.repositories.team import TeamRepository
from app.services.password import hash_password

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _make_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"remap_{secrets.token_hex(4)}@test.example",
        label="Owner",
        password_hash=hash_password("alpha-test-password-1234"),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_agent(db_session: AsyncSession) -> Agent:
    agent = Agent(
        hakushin_id=secrets.randbelow(1_000_000),
        name=f"RemapAgent{secrets.token_hex(3)}",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _make_build(db_session: AsyncSession, agent: Agent, owner: User) -> Build:
    build = Build(agent_id=str(agent.id), owner_id=str(owner.id))
    db_session.add(build)
    await db_session.flush()
    return build


async def _wipe_builds(db_session: AsyncSession, owner: User) -> None:
    """Owner-scoped build wipe, matching what `build_mode="clean"` performs."""
    await BuildRepository(db_session, owner_id=str(owner.id)).delete_all_for_owner()


async def _make_team(db_session: AsyncSession, owner: User, *builds: Build | None) -> Team:
    slots = list(builds) + [None] * (3 - len(builds))
    team = Team(
        owner_id=str(owner.id),
        name="Remap Team",
        build1_id=str(slots[0].id) if slots[0] else None,
        build2_id=str(slots[1].id) if slots[1] else None,
        build3_id=str(slots[2].id) if slots[2] else None,
    )
    db_session.add(team)
    await db_session.flush()
    return team


class TestSnapshotSlotsForOwner:
    async def test_records_slot_number_and_agent_for_each_populated_slot(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session)
        agent1, agent2 = await _make_agent(db_session), await _make_agent(db_session)
        build1 = await _make_build(db_session, agent1, owner)
        build3 = await _make_build(db_session, agent2, owner)
        # Slot 2 deliberately empty — a snapshot must not invent it.
        team = Team(
            owner_id=str(owner.id),
            name="Gapped",
            build1_id=str(build1.id),
            build3_id=str(build3.id),
        )
        db_session.add(team)
        await db_session.flush()

        repo = TeamRepository(db_session, owner_id=str(owner.id))
        snapshot = await repo.snapshot_slots_for_owner()

        assert sorted(snapshot) == sorted(
            [
                (str(team.id), 1, str(agent1.id)),
                (str(team.id), 3, str(agent2.id)),
            ]
        )

    async def test_ignores_other_owners_teams(self, db_session: AsyncSession) -> None:
        owner_a, owner_b = await _make_user(db_session), await _make_user(db_session)
        agent = await _make_agent(db_session)
        build_b = await _make_build(db_session, agent, owner_b)
        await _make_team(db_session, owner_b, build_b)

        repo = TeamRepository(db_session, owner_id=str(owner_a.id))
        assert await repo.snapshot_slots_for_owner() == []

    async def test_ignores_slots_holding_another_owners_build(
        self, db_session: AsyncSession
    ) -> None:
        # Only slots the wipe will actually null are worth snapshotting; a
        # foreign build survives `delete_all_for_owner`, so re-mapping over it
        # would clobber a slot nobody touched.
        owner_a, owner_b = await _make_user(db_session), await _make_user(db_session)
        agent = await _make_agent(db_session)
        foreign_build = await _make_build(db_session, agent, owner_b)
        await _make_team(db_session, owner_a, foreign_build)

        repo = TeamRepository(db_session, owner_id=str(owner_a.id))
        assert await repo.snapshot_slots_for_owner() == []

    async def test_raises_without_owner_id(self, db_session: AsyncSession) -> None:
        repo = TeamRepository(db_session, owner_id=None)
        with pytest.raises(ValueError, match="owner_id"):
            await repo.snapshot_slots_for_owner()


class TestRemapSlots:
    async def test_repoints_slots_to_new_builds_for_the_same_agents(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session)
        agent1, agent2 = await _make_agent(db_session), await _make_agent(db_session)
        old1 = await _make_build(db_session, agent1, owner)
        old2 = await _make_build(db_session, agent2, owner)
        team = await _make_team(db_session, owner, old1, old2)
        team_id = str(team.id)

        repo = TeamRepository(db_session, owner_id=str(owner.id))
        snapshot = await repo.snapshot_slots_for_owner()

        # Simulate the clean wipe + re-import: same agents, brand-new build rows.
        await _wipe_builds(db_session, owner)
        new1_id = str((await _make_build(db_session, agent1, owner)).id)
        new2_id = str((await _make_build(db_session, agent2, owner)).id)

        assert await repo.remap_slots(snapshot) == 2

        db_session.expire_all()
        refreshed = await db_session.get(Team, team_id)
        assert refreshed.build1_id == new1_id
        assert refreshed.build2_id == new2_id
        assert refreshed.build3_id is None

    async def test_slots_whose_agent_is_absent_stay_null(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session)
        agent1, agent2 = await _make_agent(db_session), await _make_agent(db_session)
        old1 = await _make_build(db_session, agent1, owner)
        old2 = await _make_build(db_session, agent2, owner)
        team = await _make_team(db_session, owner, old1, old2)
        team_id = str(team.id)

        repo = TeamRepository(db_session, owner_id=str(owner.id))
        snapshot = await repo.snapshot_slots_for_owner()

        await _wipe_builds(db_session, owner)
        # agent2 is not re-imported, so its slot has nothing to point at.
        new1_id = str((await _make_build(db_session, agent1, owner)).id)

        assert await repo.remap_slots(snapshot) == 1

        db_session.expire_all()
        refreshed = await db_session.get(Team, team_id)
        assert refreshed.build1_id == new1_id
        assert refreshed.build2_id is None

    async def test_does_not_touch_another_owners_team(self, db_session: AsyncSession) -> None:
        owner_a, owner_b = await _make_user(db_session), await _make_user(db_session)
        agent = await _make_agent(db_session)
        build_b = await _make_build(db_session, agent, owner_b)
        team_b = await _make_team(db_session, owner_b, build_b)
        team_b_id, build_b_id = str(team_b.id), str(build_b.id)

        # owner_a re-imports the same agent; owner_b's team must not follow.
        await _make_build(db_session, agent, owner_a)
        repo_a = TeamRepository(db_session, owner_id=str(owner_a.id))
        assert await repo_a.remap_slots([(team_b_id, 1, str(agent.id))]) == 0

        db_session.expire_all()
        refreshed = await db_session.get(Team, team_b_id)
        assert refreshed.build1_id == build_b_id

    async def test_raises_without_owner_id(self, db_session: AsyncSession) -> None:
        repo = TeamRepository(db_session, owner_id=None)
        with pytest.raises(ValueError, match="owner_id"):
            await repo.remap_slots([])


class TestDeleteAllNullTeams:
    async def test_deletes_empty_teams_and_their_combos(self, db_session: AsyncSession) -> None:
        owner = await _make_user(db_session)
        agent = await _make_agent(db_session)
        build = await _make_build(db_session, agent, owner)

        empty = await _make_team(db_session, owner)
        populated = await _make_team(db_session, owner, build)
        db_session.add_all(
            [
                Combo(name="Doomed A", team_id=str(empty.id), sequence=[]),
                Combo(name="Doomed B", team_id=str(empty.id), sequence=[]),
                Combo(name="Survivor", team_id=str(populated.id), sequence=[]),
            ]
        )
        await db_session.flush()
        empty_id, populated_id = str(empty.id), str(populated.id)

        repo = TeamRepository(db_session, owner_id=str(owner.id))
        teams_deleted, combos_deleted = await repo.delete_all_null_teams_for_owner()

        assert (teams_deleted, combos_deleted) == (1, 2)
        assert await db_session.get(Team, empty_id) is None
        assert await db_session.get(Team, populated_id) is not None
        surviving = (
            await db_session.execute(select(Combo).where(Combo.team_id == populated_id))
        ).scalars().all()
        assert len(surviving) == 1

    async def test_restricted_to_the_given_team_ids(self, db_session: AsyncSession) -> None:
        # The importer only sweeps teams it actually emptied. A team that was
        # already all-NULL before the import is outside the blast radius.
        owner = await _make_user(db_session)
        untouched = await _make_team(db_session, owner)
        swept = await _make_team(db_session, owner)
        untouched_id, swept_id = str(untouched.id), str(swept.id)

        repo = TeamRepository(db_session, owner_id=str(owner.id))
        teams_deleted, _ = await repo.delete_all_null_teams_for_owner(team_ids=[swept_id])

        assert teams_deleted == 1
        assert await db_session.get(Team, swept_id) is None
        assert await db_session.get(Team, untouched_id) is not None

    async def test_ignores_other_owners_empty_teams(self, db_session: AsyncSession) -> None:
        owner_a, owner_b = await _make_user(db_session), await _make_user(db_session)
        empty_b = await _make_team(db_session, owner_b)
        empty_b_id = str(empty_b.id)

        repo = TeamRepository(db_session, owner_id=str(owner_a.id))
        assert await repo.delete_all_null_teams_for_owner() == (0, 0)
        assert await db_session.get(Team, empty_b_id) is not None

    async def test_empty_team_ids_deletes_nothing(self, db_session: AsyncSession) -> None:
        owner = await _make_user(db_session)
        empty = await _make_team(db_session, owner)
        empty_id = str(empty.id)

        repo = TeamRepository(db_session, owner_id=str(owner.id))
        assert await repo.delete_all_null_teams_for_owner(team_ids=[]) == (0, 0)
        assert await db_session.get(Team, empty_id) is not None

    async def test_raises_without_owner_id(self, db_session: AsyncSession) -> None:
        repo = TeamRepository(db_session, owner_id=None)
        with pytest.raises(ValueError, match="owner_id"):
            await repo.delete_all_null_teams_for_owner()
