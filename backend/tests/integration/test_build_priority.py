"""The build ranking — `BACKLOG_frontend.md` §3.

**`optimizer_priority` has been on the model, indexed, since the build model was written, and
nothing has ever read or written it.** It is the fifth subsystem in this repo found built and
wired to nothing, after `createGpuKernel`, `POST /sim-runs`, `stats.TOTALS` and the gcsim
rotation importer. A column with an index is a claim that something queries it.

The ranking answers "who gets the piece" when two builds want the same artifact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.build import Build

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User


def _auth(authed: tuple[User, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {authed[1]}"}


async def _builds(db: AsyncSession, user: User, count: int) -> list[str]:
    made = []
    for _ in range(count):
        build = Build(owner_id=str(user.id), character_level=90, weapon_level=90)
        db.add(build)
        made.append(build)
    await db.flush()
    return [str(b.id) for b in made]


@pytest.mark.asyncio
async def test_the_order_sent_is_the_order_stored(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    ids = await _builds(db_session, authed_user[0], 3)

    response = await client.put(
        "/api/v1/builds/priority",
        json={"build_ids": [ids[2], ids[0], ids[1]]},
        headers=_auth(authed_user),
    )

    assert response.status_code == 200
    assert response.json()["ranked"] == 3
    ranks = {
        row["id"]: row["optimizer_priority"]
        for row in (await client.get("/api/v1/builds?limit=50", headers=_auth(authed_user))
                    ).json()["items"]
    }
    assert ranks[ids[2]] == 0
    assert ranks[ids[0]] == 1
    assert ranks[ids[1]] == 2


@pytest.mark.asyncio
async def test_a_build_left_out_becomes_unranked(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """A ranking is a permutation of what the user arranged, not an edit to one row.

    Leaving old values behind would mix two orderings and produce ties nothing can break.
    """
    ids = await _builds(db_session, authed_user[0], 3)
    await client.put("/api/v1/builds/priority", json={"build_ids": ids},
                     headers=_auth(authed_user))

    await client.put("/api/v1/builds/priority", json={"build_ids": [ids[1]]},
                     headers=_auth(authed_user))

    ranks = {
        row["id"]: row["optimizer_priority"]
        for row in (await client.get("/api/v1/builds?limit=50", headers=_auth(authed_user))
                    ).json()["items"]
    }
    assert ranks[ids[1]] == 0
    assert ranks[ids[0]] is None
    assert ranks[ids[2]] is None


@pytest.mark.asyncio
async def test_an_unknown_id_is_ignored_rather_than_refusing_the_whole_ranking(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """A list gone stale in another tab should still rank what survives."""
    ids = await _builds(db_session, authed_user[0], 2)

    response = await client.put(
        "/api/v1/builds/priority",
        json={"build_ids": [ids[0], "01a00000-0000-7000-8000-000000000000", ids[1]]},
        headers=_auth(authed_user),
    )

    assert response.status_code == 200
    assert response.json()["ranked"] == 2


@pytest.mark.asyncio
async def test_a_build_cannot_hold_two_places(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    ids = await _builds(db_session, authed_user[0], 1)

    response = await client.put(
        "/api/v1/builds/priority", json={"build_ids": [ids[0], ids[0]]},
        headers=_auth(authed_user),
    )

    assert response.status_code == 422
    assert "twice" in response.text


@pytest.mark.asyncio
async def test_priority_is_not_read_as_a_build_id(
    client: AsyncClient, authed_user: tuple[User, str],
):
    """FastAPI matches in declaration order.

    Registered after `/{build_id}`, this route would be unreachable — `/priority` would arrive
    as `build_id="priority"` and 404 as a missing build. That is a silent routing bug rather
    than an error, so it is asserted rather than left to the order of two decorators.
    """
    response = await client.put(
        "/api/v1/builds/priority", json={"build_ids": []}, headers=_auth(authed_user),
    )

    assert response.status_code == 200, response.text
