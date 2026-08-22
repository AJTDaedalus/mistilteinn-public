"""B.4 — the gcsim result cache.

A cached result is only reusable if the thing it simulated is the thing being asked about.
Every test here is about a way that could stop being true while the cache still looks like it
is working — which is the dangerous shape, because a cache miss costs three seconds and a
wrong hit costs a wrong recommendation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.repositories.sim_run import SimRunRepository
from app.services.sim_context import context_key, er_bucket

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

PIN = "3647a07a7cc3004bc1e79d9bb5f7444de20dceaa"
OTHER_PIN = "0000000000000000000000000000000000000000"

_CONTEXT = {
    "character_key": "kamisatoayaka",
    "weapon_key": "mistsplitterreforged",
    "character_level": 90,
    "constellation": 0,
    "weapon_level": 90,
    "refinement": 1,
    "talent_levels": {"normal_attack": 9, "elemental_skill": 9, "elemental_burst": 9},
    "rotation": ["burst", "skill", "attack:3"],
    "target": {"lvl": 90, "resist": 0.1},
}


def _repo(db: AsyncSession, user: User) -> SimRunRepository:
    return SimRunRepository(db, owner_id=str(user.id))


async def _store(repo: SimRunRepository, key: str, *, bucket: int = 180, pin: str = PIN,
                 dps: float = 1234.5):
    return await repo.store(
        context_key=key, er_bucket=bucket, gcsim_pin=pin,
        result={"dps": {"mean": dps}}, dps_mean=dps,
    )


# ---- The property the cache exists for -------------------------------------

@pytest.mark.asyncio
async def test_a_repeat_lookup_hits(db_session: AsyncSession, authed_user: tuple[User, str]):
    user, _ = authed_user
    repo = _repo(db_session, user)
    key = context_key(**_CONTEXT, gcsim_pin=PIN)
    await _store(repo, key)

    hit = await repo.get(context_key=key, er_bucket=180, gcsim_pin=PIN)

    assert hit is not None
    assert hit.dps_mean == pytest.approx(1234.5)


@pytest.mark.asyncio
async def test_a_different_pin_misses(db_session: AsyncSession, authed_user: tuple[User, str]):
    """The failure this cache is keyed to prevent.

    A hit across pins would serve a number from a different simulator — fast, confident, and
    about a different game version. The pin is in the hash *and* in the lookup, so forgetting
    either still misses rather than returning the wrong thing.
    """
    user, _ = authed_user
    repo = _repo(db_session, user)
    key = context_key(**_CONTEXT, gcsim_pin=PIN)
    await _store(repo, key)

    assert await repo.get(context_key=key, er_bucket=180, gcsim_pin=OTHER_PIN) is None
    # And the key itself differs, so even a pin-blind lookup could not collide.
    assert context_key(**_CONTEXT, gcsim_pin=OTHER_PIN) != key


@pytest.mark.asyncio
async def test_a_different_er_bucket_misses(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Buckets are the point: a build below the burst-uptime cliff must not read a run from
    above it."""
    user, _ = authed_user
    repo = _repo(db_session, user)
    key = context_key(**_CONTEXT, gcsim_pin=PIN)
    await _store(repo, key, bucket=180)

    assert await repo.get(context_key=key, er_bucket=175, gcsim_pin=PIN) is None


@pytest.mark.asyncio
async def test_a_different_rotation_misses(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """A rotation is a sequence. Reordering it is a different simulation."""
    user, _ = authed_user
    repo = _repo(db_session, user)
    await _store(repo, context_key(**_CONTEXT, gcsim_pin=PIN))

    reordered = {**_CONTEXT, "rotation": ["skill", "burst", "attack:3"]}
    other = context_key(**reordered, gcsim_pin=PIN)

    assert await repo.get(context_key=other, er_bucket=180, gcsim_pin=PIN) is None


@pytest.mark.asyncio
async def test_a_reordered_team_hits(db_session: AsyncSession, authed_user: tuple[User, str]):
    """A team is a set. Listing the same members in another order is the same team, and
    caching it twice would waste the three seconds this exists to save."""
    user, _ = authed_user
    repo = _repo(db_session, user)
    one = context_key(**_CONTEXT, gcsim_pin=PIN, team=["kazuha", "kokomi"])
    await _store(repo, one)

    other = context_key(**_CONTEXT, gcsim_pin=PIN, team=["kokomi", "kazuha"])

    assert other == one
    assert await repo.get(context_key=other, er_bucket=180, gcsim_pin=PIN) is not None


# ---- Ownership -------------------------------------------------------------

@pytest.mark.asyncio
async def test_another_owners_run_is_not_visible(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """The browser produces these numbers, so a tampered client could submit anything.

    Owner-scoping means that only poisons the caller's own cache. Sharing results is a
    separate feature with its own threat model — see `models/sim_run.py`.
    """
    user, _ = authed_user
    key = context_key(**_CONTEXT, gcsim_pin=PIN)
    await _store(_repo(db_session, user), key)

    stranger = SimRunRepository(db_session, owner_id="00000000-0000-0000-0000-000000000000")

    assert await stranger.get(context_key=key, er_bucket=180, gcsim_pin=PIN) is None


# ---- Concurrency -----------------------------------------------------------

@pytest.mark.asyncio
async def test_storing_the_same_key_twice_replaces_rather_than_raising(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Two tabs can finish the same context run at once. A unique violation surfacing as an
    error would be a worse answer than keeping either — they simulate the same thing."""
    user, _ = authed_user
    repo = _repo(db_session, user)
    key = context_key(**_CONTEXT, gcsim_pin=PIN)

    await _store(repo, key, dps=1000.0)
    await _store(repo, key, dps=1100.0)

    hit = await repo.get(context_key=key, er_bucket=180, gcsim_pin=PIN)
    assert hit is not None
    assert hit.dps_mean == pytest.approx(1100.0)
    assert len(await repo.get_buckets(context_key=key, gcsim_pin=PIN)) == 1


@pytest.mark.asyncio
async def test_buckets_come_back_in_order(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    user, _ = authed_user
    repo = _repo(db_session, user)
    key = context_key(**_CONTEXT, gcsim_pin=PIN)
    for bucket in (200, 100, 150):
        await _store(repo, key, bucket=bucket)

    assert [r.er_bucket for r in await repo.get_buckets(context_key=key, gcsim_pin=PIN)] == [
        100, 150, 200,
    ]


# ---- Bucketing -------------------------------------------------------------

def test_er_rounds_down_so_a_hit_never_claims_uptime_it_has_not_earned():
    """179% must not read a run from 180% that got its burst off when this build may not."""
    assert er_bucket(1.79) == 175
    assert er_bucket(1.80) == 180
    assert er_bucket(1.0) == 100
