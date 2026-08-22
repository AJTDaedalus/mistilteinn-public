"""Owner scoping is a security boundary — cross-owner reads and writes must not resolve.

**Port state.** B.12 rewrote this file for the surviving repositories, and C.6 moved its
second half again: `OptimizationJobRepository` went with the endpoints it served, so its
cases now cover **`SimRunRepository`** instead.

That is an upgrade rather than a substitution. The job repository was owner-scoped as
housekeeping; the sim-run cache is owner-scoped as its **entire threat model** — the browser
computes those numbers, so a tampered client can submit whatever it likes, and scoping is
what confines the damage to the caller's own cache (`app/models/sim_run.py`). A leak there
serves another user a confident damage figure for a build they never asked about.

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
from app.models.sim_run import SimRun
from app.models.team import Team
from app.models.user import User
from app.repositories.sim_run import SimRunRepository
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


async def _make_run(db_session: AsyncSession, owner: User, *, bucket: int = 180) -> SimRun:
    run = SimRun(
        owner_id=str(owner.id),
        context_key=hashlib.sha256(f"{owner.id}:{bucket}".encode()).hexdigest(),
        er_bucket=bucket,
        gcsim_pin="0" * 40,
        result={"statistics": {"iterations": 1, "dps": {"mean": 1.0, "sd": 0.0}}},
        dps_mean=1.0,
    )
    db_session.add(run)
    await db_session.flush()
    return run


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


async def test_team_count_scoped_to_owner(db_session: AsyncSession) -> None:
    """`count()` feeds `total` in the pagination envelope, so it leaks if unscoped.

    Regression test: `BaseRepository.count()` was a bare `SELECT count(*)` with no owner
    filter, so `GET /api/v1/teams` answered one user's page of items alongside the whole
    table's row count.
    """
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    await _make_team(db_session, owner, name="Mine")
    await _make_team(db_session, other, name="Theirs1")
    await _make_team(db_session, other, name="Theirs2")

    assert (await TeamRepository(db_session, owner_id=str(owner.id)).count()) == 1
    assert (await TeamRepository(db_session, owner_id=str(other.id)).count()) == 2
    # No owner_id at all still means "every row" — admin/global callers rely on it.
    assert (await TeamRepository(db_session).count()) == 3


# ── SimRunRepository ──────────────────────────────────────────────────────────


async def test_sim_run_get_by_id_cross_owner_returns_none(db_session: AsyncSession) -> None:
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    run = await _make_run(db_session, owner)

    repo = SimRunRepository(db_session, owner_id=str(other.id))

    assert (await repo.get_by_id(str(run.id))) is None


async def test_sim_run_list_scoped_to_owner(db_session: AsyncSession) -> None:
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    mine = await _make_run(db_session, owner)
    await _make_run(db_session, other)

    runs = await SimRunRepository(db_session, owner_id=str(owner.id)).get_all()

    assert [str(r.id) for r in runs] == [str(mine.id)]


async def test_sim_run_cache_lookup_does_not_cross_owners(db_session: AsyncSession) -> None:
    """The one that matters most: a *cache hit* for someone else's run.

    `get_by_id` leaking is bad and obvious. This is the quiet version — the cache is read by
    `(context_key, er_bucket, pin)`, and two users optimising the same character at the same
    ER produce **the same context key**. Without the owner filter, one user's submitted
    numbers would answer the other's search and look exactly like a legitimate hit.
    """
    owner = await _make_user(db_session, f"a_{uuid.uuid4().hex[:8]}@test.example")
    other = await _make_user(db_session, f"b_{uuid.uuid4().hex[:8]}@test.example")
    run = await _make_run(db_session, owner)

    theirs = SimRunRepository(db_session, owner_id=str(other.id))

    assert (await theirs.get(
        context_key=run.context_key, er_bucket=run.er_bucket, gcsim_pin=run.gcsim_pin,
    )) is None
    assert (await theirs.get_buckets(
        context_key=run.context_key, gcsim_pin=run.gcsim_pin,
    )) == []
