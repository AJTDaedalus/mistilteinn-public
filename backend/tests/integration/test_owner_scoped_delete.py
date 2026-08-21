"""Integration tests for DiscRepository/BuildRepository.delete_all_for_owner (Task 3)."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent
from app.models.build import Build
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.models.user import User
from app.repositories.build import BuildRepository
from app.repositories.disc import DiscRepository
from app.services.password import hash_password

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _make_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"owner_{secrets.token_hex(4)}@test.example",
        label="Owner",
        password_hash=hash_password("alpha-test-password-1234"),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_agent(db_session: AsyncSession) -> Agent:
    agent = Agent(
        hakushin_id=secrets.randbelow(1_000_000),
        name="DeleteAllAgent",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=800,
        base_hp=7000,
        base_def=500,
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _make_disc_set(db_session: AsyncSession) -> DiscSet:
    disc_set = DiscSet(
        hakushin_id=secrets.randbelow(1_000_000),
        name="DeleteAllSet",
        two_piece_text="ATK+10%",
        four_piece_text="DMG+15%",
    )
    db_session.add(disc_set)
    await db_session.flush()
    return disc_set


async def _make_build(db_session: AsyncSession, agent: Agent, owner: User) -> Build:
    build = Build(agent_id=str(agent.id), owner_id=str(owner.id))
    db_session.add(build)
    await db_session.flush()
    return build


async def _make_disc(
    db_session: AsyncSession,
    disc_set: DiscSet,
    owner: User,
    build: Build | None = None,
) -> Disc:
    disc = Disc(
        disc_set_id=str(disc_set.id),
        owner_id=str(owner.id),
        rarity=Rarity.S,
        slot=DiscSlot.ONE,
        level=15,
        main_stat_type=StatType.HP,
        main_stat_value=1000,
        substats=[],
        build_id=str(build.id) if build else None,
    )
    db_session.add(disc)
    await db_session.flush()
    return disc


class TestDiscRepositoryDeleteAllForOwner:
    async def test_deletes_only_owner_discs_and_returns_count(
        self,
        db_session: AsyncSession,
    ) -> None:
        owner_a = await _make_user(db_session)
        owner_b = await _make_user(db_session)
        disc_set = await _make_disc_set(db_session)

        await _make_disc(db_session, disc_set, owner_a)
        await _make_disc(db_session, disc_set, owner_a)
        disc_b = await _make_disc(db_session, disc_set, owner_b)

        repo = DiscRepository(db_session, owner_id=str(owner_a.id))
        deleted = await repo.delete_all_for_owner()

        assert deleted == 2
        remaining = await DiscRepository(db_session, owner_id=str(owner_a.id)).get_all()
        assert list(remaining) == []
        survivor = await DiscRepository(db_session, owner_id=str(owner_b.id)).get_all()
        assert [str(d.id) for d in survivor] == [str(disc_b.id)]

    async def test_raises_without_owner_id(self, db_session: AsyncSession) -> None:
        repo = DiscRepository(db_session, owner_id=None)
        with pytest.raises(ValueError, match="owner_id"):
            await repo.delete_all_for_owner()


class TestBuildRepositoryDeleteAllForOwner:
    async def test_deletes_only_owner_builds_and_returns_count(
        self,
        db_session: AsyncSession,
    ) -> None:
        owner_a = await _make_user(db_session)
        owner_b = await _make_user(db_session)
        agent1 = await _make_agent(db_session)
        agent2 = await _make_agent(db_session)
        agent3 = await _make_agent(db_session)

        await _make_build(db_session, agent1, owner_a)
        await _make_build(db_session, agent2, owner_a)
        build_b = await _make_build(db_session, agent3, owner_b)

        repo = BuildRepository(db_session, owner_id=str(owner_a.id))
        deleted = await repo.delete_all_for_owner()

        assert deleted == 2
        remaining = await BuildRepository(db_session, owner_id=str(owner_a.id)).get_all()
        assert list(remaining) == []
        survivor = await BuildRepository(db_session, owner_id=str(owner_b.id)).get_all()
        assert [str(b.id) for b in survivor] == [str(build_b.id)]

    async def test_raises_without_owner_id(self, db_session: AsyncSession) -> None:
        repo = BuildRepository(db_session, owner_id=None)
        with pytest.raises(ValueError, match="owner_id"):
            await repo.delete_all_for_owner()
