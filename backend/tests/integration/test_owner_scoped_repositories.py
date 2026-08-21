"""Owner scoping is a security boundary — cross-owner reads and writes must not resolve.

**Port state.** B.12 rewrote this file. fairy's version covered `BuildRepository`,
`DiscRepository`, `ComboRepository` and `OptimizationJobRepository`; the first three were
deleted in B.7 along with their models. What remains is the same property tested against the
two owner-scoped repositories that survive — `TeamRepository` and
`OptimizationJobRepository` — plus the `get_all` scoping that `BaseRepository` subclasses
rely on.

This is not a formality: the owner filter lives in each repository rather than in the route,
so a repository that forgets it leaks another user's rows through a perfectly ordinary
handler. Chunk G re-adds cases here as it re-adds owner-scoped repositories (builds,
artifacts).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING

from app.models.enums import UserStatus
from app.models.optimization_job import OptimizationJob
from app.models.team import Team
from app.models.user import User
from app.repositories.optimization_job import OptimizationJobRepository
from app.repositories.team import TeamRepository

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


async def _make_team(db_session: AsyncSession, owner: User, name: str = "Team") -> Team:
    team = Team(name=name, owner_id=str(owner.id))
    db_session.add(team)
    await db_session.flush()
    return team


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


# ── TeamRepository ────────────────────────────────────────────────────────────


async def test_team_get_by_id_own(db_session: AsyncSession) -> None:
    owner = await _make_user(db_session, f"own_{uuid.uuid4().hex[:8]}@test.example")
    team = await _make_team(db_session, owner)

    repo = TeamRepository(db_session, owner_id=str(owner.id))

    assert (await repo.get_by_id(str(team.id))) is not None


async def test_team_get_by_id_cross_owner_returns_none(db_session: AsyncSession) -> None:
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    team = await _make_team(db_session, owner)

    repo = TeamRepository(db_session, owner_id=str(other.id))

    assert (await repo.get_by_id(str(team.id))) is None


async def test_team_update_cross_owner_returns_none(db_session: AsyncSession) -> None:
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    team = await _make_team(db_session, owner, name="Original")

    repo = TeamRepository(db_session, owner_id=str(other.id))
    result = await repo.update(str(team.id), {"name": "Hijacked"})

    assert result is None
    await db_session.refresh(team)
    assert team.name == "Original"


async def test_team_delete_cross_owner_returns_false(db_session: AsyncSession) -> None:
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    team = await _make_team(db_session, owner)

    repo = TeamRepository(db_session, owner_id=str(other.id))

    assert (await repo.delete(str(team.id))) is False
    survivor = await TeamRepository(db_session, owner_id=str(owner.id)).get_by_id(str(team.id))
    assert survivor is not None


async def test_team_get_all_scoped_to_owner(db_session: AsyncSession) -> None:
    """`get_all` is overridden on TeamRepository, so it needs its own scoping test."""
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    await _make_team(db_session, owner, name="Mine")
    await _make_team(db_session, other, name="Theirs")

    teams = await TeamRepository(db_session, owner_id=str(owner.id)).get_all()

    assert [t.name for t in teams] == ["Mine"]


# ── OptimizationJobRepository ─────────────────────────────────────────────────


async def test_job_get_by_id_cross_owner_returns_none(db_session: AsyncSession) -> None:
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    job = await _make_job(db_session, owner)

    repo = OptimizationJobRepository(db_session, owner_id=str(other.id))

    assert (await repo.get_by_id(str(job.id))) is None


async def test_job_list_scoped_to_owner(db_session: AsyncSession) -> None:
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    mine = await _make_job(db_session, owner)
    await _make_job(db_session, other)

    jobs = await OptimizationJobRepository(db_session, owner_id=str(owner.id)).get_all()

    assert [str(j.id) for j in jobs] == [str(mine.id)]
