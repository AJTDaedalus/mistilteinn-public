"""Integration tests: owner-scoped repository isolation.

Verifies that repository instances initialised with owner_id only
see/mutate rows that belong to that owner. Cross-owner reads return
None; cross-owner deletes return False; list methods exclude foreign rows.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING

from app.models.agent import Agent
from app.models.build import Build, Combo
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType, UserStatus
from app.models.optimization_job import OptimizationJob
from app.models.team import Team
from app.models.user import User
from app.repositories.build import BuildRepository, ComboRepository
from app.repositories.disc import DiscRepository
from app.repositories.optimization_job import OptimizationJobRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── helpers ──────────────────────────────────────────────────────────────────


async def _make_user(db_session: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        label="Test User",
        password_hash=hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest(),
        status=UserStatus.APPROVED,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_agent(db_session: AsyncSession, hakushin_id: int = 99001) -> Agent:
    agent = Agent(
        hakushin_id=hakushin_id,
        name=f"OwnerAgent_{hakushin_id}",
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


async def _make_disc_set(db_session: AsyncSession, hakushin_id: int = 99002) -> DiscSet:
    disc_set = DiscSet(
        hakushin_id=hakushin_id,
        name=f"OwnerSet_{hakushin_id}",
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


async def _make_disc(db_session: AsyncSession, disc_set: DiscSet, owner: User) -> Disc:
    disc = Disc(
        disc_set_id=str(disc_set.id),
        owner_id=str(owner.id),
        slot=DiscSlot.ONE,
        rarity=Rarity.S,
        level=15,
        main_stat_type=StatType.ATK,
        main_stat_value=798,
    )
    db_session.add(disc)
    await db_session.flush()
    return disc


async def _make_combo(
    db_session: AsyncSession, build: Build, owner: User, name: str = "Combo"
) -> Combo:
    team = Team(build1_id=str(build.id), owner_id=str(owner.id))
    db_session.add(team)
    await db_session.flush()
    combo = Combo(
        name=name,
        team_id=str(team.id),
        owner_id=str(owner.id),
    )
    db_session.add(combo)
    await db_session.flush()
    return combo


async def _make_job(db_session: AsyncSession, owner: User) -> OptimizationJob:
    job = OptimizationJob(
        owner_id=str(owner.id),
        job_type="optimizer",
        status="queued",
        request={},
    )
    db_session.add(job)
    await db_session.flush()
    return job


# ── BuildRepository ───────────────────────────────────────────────────────────


async def test_build_get_by_id_own(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "build_own@test.com")
    agent = await _make_agent(db_session, 99010)
    build = await _make_build(db_session, agent, user_a)

    repo = BuildRepository(db_session, owner_id=str(user_a.id))
    result = await repo.get_by_id(str(build.id))
    assert result is not None


async def test_build_get_by_id_cross_owner_returns_none(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "build_xa@test.com")
    user_b = await _make_user(db_session, "build_xb@test.com")
    agent = await _make_agent(db_session, 99011)
    build = await _make_build(db_session, agent, user_a)

    repo_b = BuildRepository(db_session, owner_id=str(user_b.id))
    assert await repo_b.get_by_id(str(build.id)) is None


async def test_build_update_cross_owner_returns_none(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "build_ua@test.com")
    user_b = await _make_user(db_session, "build_ub@test.com")
    agent = await _make_agent(db_session, 99012)
    build = await _make_build(db_session, agent, user_a)

    repo_b = BuildRepository(db_session, owner_id=str(user_b.id))
    result = await repo_b.update(str(build.id), {"notes": "Stolen"})
    assert result is None


async def test_build_delete_cross_owner_returns_false(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "build_da@test.com")
    user_b = await _make_user(db_session, "build_db@test.com")
    agent = await _make_agent(db_session, 99013)
    build = await _make_build(db_session, agent, user_a)

    repo_b = BuildRepository(db_session, owner_id=str(user_b.id))
    assert await repo_b.delete(str(build.id)) is False

    repo_a = BuildRepository(db_session, owner_id=str(user_a.id))
    assert await repo_a.get_by_id(str(build.id)) is not None


async def test_build_get_all_scoped_to_owner(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "build_la@test.com")
    user_b = await _make_user(db_session, "build_lb@test.com")
    agent = await _make_agent(db_session, 99014)
    build_a = await _make_build(db_session, agent, user_a)
    await _make_build(db_session, agent, user_b)

    repo_a = BuildRepository(db_session, owner_id=str(user_a.id))
    builds = await repo_a.get_all()
    ids = {str(b.id) for b in builds}
    assert str(build_a.id) in ids
    for b in builds:
        assert str(b.owner_id) == str(user_a.id)


# ── DiscRepository ────────────────────────────────────────────────────────────


async def test_disc_get_by_id_cross_owner_returns_none(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "disc_xa@test.com")
    user_b = await _make_user(db_session, "disc_xb@test.com")
    disc_set = await _make_disc_set(db_session, 99020)
    disc = await _make_disc(db_session, disc_set, user_a)

    repo_b = DiscRepository(db_session, owner_id=str(user_b.id))
    assert await repo_b.get_by_id(str(disc.id)) is None


async def test_disc_delete_cross_owner_returns_false(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "disc_da@test.com")
    user_b = await _make_user(db_session, "disc_db@test.com")
    disc_set = await _make_disc_set(db_session, 99021)
    disc = await _make_disc(db_session, disc_set, user_a)

    repo_b = DiscRepository(db_session, owner_id=str(user_b.id))
    assert await repo_b.delete(str(disc.id)) is False

    repo_a = DiscRepository(db_session, owner_id=str(user_a.id))
    assert await repo_a.get_by_id(str(disc.id)) is not None


async def test_disc_list_filtered_scoped_to_owner(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "disc_la@test.com")
    user_b = await _make_user(db_session, "disc_lb@test.com")
    disc_set = await _make_disc_set(db_session, 99022)
    disc_a = await _make_disc(db_session, disc_set, user_a)
    await _make_disc(db_session, disc_set, user_b)

    repo_a = DiscRepository(db_session, owner_id=str(user_a.id))
    discs = await repo_a.list_filtered()
    ids = {str(d.id) for d in discs}
    assert str(disc_a.id) in ids
    for d in discs:
        assert str(d.owner_id) == str(user_a.id)


# ── ComboRepository ───────────────────────────────────────────────────────────


async def test_combo_get_by_id_cross_owner_returns_none(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "combo_xa@test.com")
    user_b = await _make_user(db_session, "combo_xb@test.com")
    agent = await _make_agent(db_session, 99030)
    build = await _make_build(db_session, agent, user_a)
    combo = await _make_combo(db_session, build, user_a)

    repo_b = ComboRepository(db_session, owner_id=str(user_b.id))
    assert await repo_b.get_by_id(str(combo.id)) is None


async def test_combo_delete_cross_owner_returns_false(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "combo_da@test.com")
    user_b = await _make_user(db_session, "combo_db@test.com")
    agent = await _make_agent(db_session, 99031)
    build = await _make_build(db_session, agent, user_a)
    combo = await _make_combo(db_session, build, user_a)

    repo_b = ComboRepository(db_session, owner_id=str(user_b.id))
    assert await repo_b.delete(str(combo.id)) is False


# ── OptimizationJobRepository ─────────────────────────────────────────────────


async def test_job_get_by_id_cross_owner_returns_none(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "job_xa@test.com")
    user_b = await _make_user(db_session, "job_xb@test.com")
    job = await _make_job(db_session, user_a)

    repo_b = OptimizationJobRepository(db_session, owner_id=str(user_b.id))
    assert await repo_b.get_by_id(str(job.id)) is None


async def test_job_list_scoped_to_owner(db_session: AsyncSession) -> None:
    user_a = await _make_user(db_session, "job_la@test.com")
    user_b = await _make_user(db_session, "job_lb@test.com")
    job_a = await _make_job(db_session, user_a)
    await _make_job(db_session, user_b)

    repo_a = OptimizationJobRepository(db_session, owner_id=str(user_a.id))
    jobs = await repo_a.list()
    ids = {str(j.id) for j in jobs}
    assert str(job_a.id) in ids
    for j in jobs:
        assert str(j.owner_id) == str(user_a.id)
