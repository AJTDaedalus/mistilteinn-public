"""D.1 / OQ-S3 — the inventory the browser holds, and how it knows it is still current.

The decision this pins: the browser **holds** the inventory and revalidates it, rather than
fetching it per search. The transfer is not what decides that — a 2,000-piece account is
~234 KB gzipped either way — **staleness** is. An inventory held across a GOOD re-import
contains artifacts the user no longer owns, and a search over it would recommend wearing
them. So the tests below are about the version: what must change it, and what must not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.artifact import Artifact
from app.models.enums import ArtifactSlot, Rarity, StatType

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio

INVENTORY = "/api/v1/artifacts/inventory"


async def _add(db: AsyncSession, user: User, *, level: int = 20, count: int = 1) -> list[Artifact]:
    rows = [
        Artifact(
            owner_id=str(user.id), slot=ArtifactSlot.GOBLET, rarity=Rarity.FIVE_STAR,
            level=level, main_stat_type=StatType.CRYO_DMG_BONUS, main_stat_value=0.466,
            substats=[{"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.1 * (i + 1)}],
        )
        for i in range(count)
    ]
    db.add_all(rows)
    await db.flush()
    return rows


async def test_the_whole_inventory_comes_back_in_one_response(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """A search needs every piece at one instant — paged offsets have no such instant."""
    user, _ = authed_user
    await _add(db_session, user, count=7)

    response = await authed_client.get(INVENTORY)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 7
    assert len(body["artifacts"]) == 7
    assert body["truncated"] is False
    assert response.headers["ETag"] == f'"{body["version"]}"'


async def test_an_unchanged_inventory_revalidates_to_304(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """This is what makes holding it cheap; without it, holding is just a stale copy."""
    user, _ = authed_user
    await _add(db_session, user, count=3)

    first = await authed_client.get(INVENTORY)
    again = await authed_client.get(INVENTORY, headers={"If-None-Match": first.headers["ETag"]})
    assert again.status_code == 304
    assert again.headers["ETag"] == first.headers["ETag"]
    assert not again.content


async def test_adding_a_piece_changes_the_version(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    user, _ = authed_user
    await _add(db_session, user, count=2)
    before = (await authed_client.get(INVENTORY)).json()["version"]

    await _add(db_session, user, count=1)
    assert (await authed_client.get(INVENTORY)).json()["version"] != before


async def test_removing_a_piece_changes_the_version(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """The re-import case, and the reason a held inventory needs a version at all."""
    user, _ = authed_user
    rows = await _add(db_session, user, count=3)
    before = (await authed_client.get(INVENTORY)).json()["version"]

    await db_session.delete(rows[0])
    await db_session.flush()
    assert (await authed_client.get(INVENTORY)).json()["version"] != before


async def test_levelling_a_piece_changes_the_version(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """The version is over what a search reads, so a stat change must invalidate it."""
    user, _ = authed_user
    rows = await _add(db_session, user, level=0, count=1)
    before = (await authed_client.get(INVENTORY)).json()["version"]

    rows[0].level = 20
    await db_session.flush()
    assert (await authed_client.get(INVENTORY)).json()["version"] != before


async def test_a_stale_etag_gets_the_new_inventory_rather_than_a_304(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """The failure the whole design is about: a 304 here would serve a deleted artifact."""
    user, _ = authed_user
    rows = await _add(db_session, user, count=2)
    stale = (await authed_client.get(INVENTORY)).headers["ETag"]

    await db_session.delete(rows[0])
    await db_session.flush()

    response = await authed_client.get(INVENTORY, headers={"If-None-Match": stale})
    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_the_version_is_stable_across_identical_reads(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """A version that flipped on row order would make every revalidation a full transfer."""
    user, _ = authed_user
    await _add(db_session, user, count=5)
    versions = {(await authed_client.get(INVENTORY)).json()["version"] for _ in range(3)}
    assert len(versions) == 1


async def test_the_inventory_is_owner_scoped(
    authed_client: AsyncClient, client: AsyncClient, db_session: AsyncSession,
    authed_user: tuple[User, str],
):
    user, _ = authed_user
    await _add(db_session, user, count=2)
    assert (await authed_client.get(INVENTORY)).json()["total"] == 2
    assert (await client.get(INVENTORY)).status_code == 401


async def test_inventory_is_not_swallowed_by_the_artifact_id_route(
    authed_client: AsyncClient,
):
    """`/artifacts/{artifact_id}` would happily match `inventory` and 404 on it."""
    response = await authed_client.get(INVENTORY)
    assert response.status_code == 200, "route order regressed; see the comment above it"
