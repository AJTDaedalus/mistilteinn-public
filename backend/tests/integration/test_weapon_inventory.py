"""The weapon inventory: what a GOOD export says you own, not what the catalogue describes.

**This did not exist.** `ParsedWeapon`'s own docstring said *"Unheld weapons are parsed and
simply unused"* — a real Irminsul export carries 320 weapons, of which the importer read the 68
naming a holder purely to set `builds.weapon_id`, and discarded the other 252.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.build import Build
from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType
from app.models.weapon import OwnedWeapon

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio

OWNED = "/api/v1/weapons/owned"


@pytest.fixture
async def build(db_session: AsyncSession, authed_user: tuple[User, str]) -> Build:
    """One real build to hang an equipped weapon off.

    Made here rather than skipped when absent: three of these tests skipped for want of a
    build on the first run, and **a skipped check is never a pass** in this repo — a test that
    quietly does not run is indistinguishable from one that passed.
    """
    user, _ = authed_user
    character = Character(
        nanoka_id="10000002", name="Kamisato Ayaka", element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1000.0, base_atk=26.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    db_session.add(character)
    await db_session.flush()
    row = Build(owner_id=str(user.id), character_id=str(character.id))
    db_session.add(row)
    await db_session.flush()
    return row


async def test_the_route_is_not_swallowed_by_the_catalogue_lookup(
    authed_client: AsyncClient,
):
    """**`/weapons/owned` must be declared before `/weapons/{nanoka_id}`.**

    FastAPI matches in declaration order, so with this route below the parameterised one,
    `owned` was parsed as a nanoka id and the endpoint answered `422 int_parsing` — a route
    that exists and is unreachable. Found by calling it, not by reading it, which is why this
    test asks for a status code rather than for a shape.
    """
    response = await authed_client.get(OWNED)

    assert response.status_code == 200, response.text


async def test_an_empty_inventory_is_an_empty_list_not_an_error(authed_client: AsyncClient):
    body = (await authed_client.get(OWNED)).json()

    assert body["items"] == []
    assert body["total"] == 0


async def test_equipped_weapons_come_first(
    authed_client: AsyncClient, db_session: AsyncSession, build: Build,
):
    """The default order, not a sort option.

    It is what answers "what am I actually using" without the user having to ask for it, and
    the owner asked for it by name.
    """
    db_session.add_all([
        OwnedWeapon(owner_id=build.owner_id, weapon_id=None, level=1, refinement=1),
        OwnedWeapon(
            owner_id=build.owner_id, weapon_id=None, build_id=str(build.id),
            level=90, refinement=5,
        ),
    ])
    await db_session.flush()

    items = (await authed_client.get(OWNED)).json()["items"]

    assert [row["build_id"] is not None for row in items][:2] == [True, False]


async def test_the_filter_narrows_and_the_total_agrees(
    authed_client: AsyncClient, db_session: AsyncSession, build: Build,
):
    """`total` is counted with the same `WHERE` the list used.

    Counting the unfiltered table beside a filtered list is how a page ends up saying
    "showing 3 of 320" about three of three.
    """
    db_session.add_all([
        OwnedWeapon(owner_id=build.owner_id, weapon_id=None, level=1, refinement=1),
        OwnedWeapon(
            owner_id=build.owner_id, weapon_id=None, build_id=str(build.id),
            level=90, refinement=5,
        ),
    ])
    await db_session.flush()

    spare = (await authed_client.get(f"{OWNED}?equipped=false")).json()
    equipped = (await authed_client.get(f"{OWNED}?equipped=true")).json()

    assert spare["total"] == len(spare["items"]) == 1
    assert equipped["total"] == len(equipped["items"]) == 1


async def test_a_weapon_the_catalogue_lost_is_still_listed(
    authed_client: AsyncClient, db_session: AsyncSession, build: Build,
):
    """`weapon_id` is `SET NULL`, not cascade.

    A re-pin that retires a weapon should leave the user's copy visible and unresolved, not
    silently delete part of their inventory — the same reasoning `unresolved_weapons` uses on
    import.
    """
    db_session.add(OwnedWeapon(owner_id=build.owner_id, weapon_id=None, level=1, refinement=1))
    await db_session.flush()

    items = (await authed_client.get(OWNED)).json()["items"]

    assert len(items) == 1
    assert items[0]["weapon"] is None
