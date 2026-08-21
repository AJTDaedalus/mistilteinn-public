"""Integration tests for BuildRepository priority methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent
from app.models.build import Build
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.repositories.build import BuildRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def repo(db_session: AsyncSession) -> BuildRepository:
    return BuildRepository(db_session)


async def _make_agent(db_session: AsyncSession) -> Agent:
    agent = Agent(
        hakushin_id=9900,
        name="PriorityAgent",
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
        hakushin_id=9901,
        name="PrioSet",
        two_piece_text="ATK+10%",
        four_piece_text="DMG+15%",
    )
    db_session.add(disc_set)
    await db_session.flush()
    return disc_set


async def _make_build(
    db_session: AsyncSession,
    agent: Agent,
    priority: int | None = None,
) -> Build:
    build = Build(agent_id=str(agent.id), optimizer_priority=priority)
    db_session.add(build)
    await db_session.flush()
    return build


async def _make_disc(
    db_session: AsyncSession,
    disc_set: DiscSet,
    slot: DiscSlot,
    build: Build | None = None,
) -> Disc:
    disc = Disc(
        disc_set_id=str(disc_set.id),
        rarity=Rarity.S,
        slot=slot,
        level=15,
        main_stat_type=StatType.HP,
        main_stat_value=1000,
        substats=[],
        build_id=str(build.id) if build else None,
    )
    db_session.add(disc)
    await db_session.flush()
    return disc


class TestSetPriorityOrder:
    async def test_assigns_dense_ranks(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        agent = await _make_agent(db_session)
        b1 = await _make_build(db_session, agent)
        b2 = await _make_build(db_session, agent)
        b3 = await _make_build(db_session, agent)

        await repo.set_priority_order([str(b2.id), str(b1.id), str(b3.id)])

        await db_session.refresh(b1)
        await db_session.refresh(b2)
        await db_session.refresh(b3)

        assert b2.optimizer_priority == 1
        assert b1.optimizer_priority == 2
        assert b3.optimizer_priority == 3

    async def test_nulls_omitted_builds(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        agent = await _make_agent(db_session)
        b1 = await _make_build(db_session, agent, priority=1)
        b2 = await _make_build(db_session, agent, priority=2)
        b3 = await _make_build(db_session, agent, priority=3)

        # Only include b1 → b2 and b3 should be NULLed
        await repo.set_priority_order([str(b1.id)])

        await db_session.refresh(b1)
        await db_session.refresh(b2)
        await db_session.refresh(b3)

        assert b1.optimizer_priority == 1
        assert b2.optimizer_priority is None
        assert b3.optimizer_priority is None

    async def test_raises_on_unknown_id(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        agent = await _make_agent(db_session)
        b1 = await _make_build(db_session, agent)
        fake_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(ValueError, match="Unknown build"):
            await repo.set_priority_order([str(b1.id), fake_id])

    async def test_returns_builds_in_priority_order(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        agent = await _make_agent(db_session)
        b1 = await _make_build(db_session, agent)
        b2 = await _make_build(db_session, agent)

        result = await repo.set_priority_order([str(b2.id), str(b1.id)])

        assert [str(r.id) for r in result] == [str(b2.id), str(b1.id)]

    async def test_empty_list_nulls_all(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        agent = await _make_agent(db_session)
        b1 = await _make_build(db_session, agent, priority=1)
        b2 = await _make_build(db_session, agent, priority=2)

        result = await repo.set_priority_order([])

        await db_session.refresh(b1)
        await db_session.refresh(b2)

        assert b1.optimizer_priority is None
        assert b2.optimizer_priority is None
        assert list(result) == []


class TestHigherPriorityEquippedDiscIds:
    async def test_ranked_target_excludes_strictly_higher(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        """Priority-1 build's discs excluded; priority-3 build's discs are not."""
        agent = await _make_agent(db_session)
        disc_set = await _make_disc_set(db_session)

        b_high = await _make_build(db_session, agent, priority=1)
        b_target = await _make_build(db_session, agent, priority=2)
        b_low = await _make_build(db_session, agent, priority=3)

        d_high = await _make_disc(db_session, disc_set, DiscSlot.ONE, b_high)
        d_own = await _make_disc(db_session, disc_set, DiscSlot.TWO, b_target)
        d_low = await _make_disc(db_session, disc_set, DiscSlot.THREE, b_low)

        excluded = await repo.higher_priority_equipped_disc_ids(b_target)

        assert str(d_high.id) in excluded  # priority 1 < 2 → excluded
        assert str(d_own.id) not in excluded  # self → never excluded
        assert str(d_low.id) not in excluded  # priority 3 > 2 → not excluded

    async def test_self_excluded_from_result(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        agent = await _make_agent(db_session)
        disc_set = await _make_disc_set(db_session)

        b_target = await _make_build(db_session, agent, priority=1)
        d_own = await _make_disc(db_session, disc_set, DiscSlot.ONE, b_target)

        excluded = await repo.higher_priority_equipped_disc_ids(b_target)

        assert str(d_own.id) not in excluded

    async def test_unranked_target_all_ranked_excluded(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        """Unranked target: every ranked build's discs are excluded."""
        agent = await _make_agent(db_session)
        disc_set = await _make_disc_set(db_session)

        b_ranked = await _make_build(db_session, agent, priority=1)
        b_unranked = await _make_build(db_session, agent, priority=None)

        d_ranked = await _make_disc(db_session, disc_set, DiscSlot.ONE, b_ranked)
        d_own = await _make_disc(db_session, disc_set, DiscSlot.TWO, b_unranked)

        excluded = await repo.higher_priority_equipped_disc_ids(b_unranked)

        assert str(d_ranked.id) in excluded
        assert str(d_own.id) not in excluded

    async def test_no_ranked_builds_returns_empty(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        """No other ranked builds → nothing to exclude."""
        agent = await _make_agent(db_session)
        disc_set = await _make_disc_set(db_session)

        b_target = await _make_build(db_session, agent, priority=1)
        await _make_disc(db_session, disc_set, DiscSlot.ONE, b_target)

        excluded = await repo.higher_priority_equipped_disc_ids(b_target)

        assert excluded == set()

    async def test_unequipped_discs_not_in_excluded(
        self,
        repo: BuildRepository,
        db_session: AsyncSession,
    ) -> None:
        """Discs with no build_id are never excluded regardless of priority."""
        agent = await _make_agent(db_session)
        disc_set = await _make_disc_set(db_session)

        b_target = await _make_build(db_session, agent, priority=2)
        d_free = await _make_disc(db_session, disc_set, DiscSlot.ONE, None)

        excluded = await repo.higher_priority_equipped_disc_ids(b_target)

        assert str(d_free.id) not in excluded
