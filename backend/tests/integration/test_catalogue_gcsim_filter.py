"""Task 3: the `gcsim` block on the catalogue lists, and the `?gcsim=` filter.

The status is computed on read (D-F1), so SQL cannot filter on it and the route narrows after
reading. What this pins is the part that can go wrong there: `total` counting the narrowed
list rather than the table, and pagination applying after the filter rather than before it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.artifact import ArtifactSet
from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType
from app.models.weapon import Weapon

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


def _character(nanoka_id: str, name: str, element: Element, weapon: WeaponType) -> Character:
    return Character(
        nanoka_id=nanoka_id, name=name, element=element, weapon_type=weapon,
        rarity=Rarity.FIVE_STAR, base_hp=1.0, base_atk=1.0, base_def=1.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )


async def _roster(db: AsyncSession) -> None:
    """One of each status, real at the pin (`test_gcsim_status.py` pins why)."""
    db.add_all([
        _character("10000002", "Kamisato Ayaka", Element.CRYO, WeaponType.SWORD),  # full
        _character("10000016", "Diluc", Element.PYRO, WeaponType.CLAYMORE),  # partial: charge
        _character("10000100", "Kachina", Element.GEO, WeaponType.POLEARM),  # none
    ])
    await db.flush()


async def test_every_list_entry_carries_the_block(client: AsyncClient, db_session: AsyncSession):
    await _roster(db_session)

    items = (await client.get("/api/v1/characters")).json()["items"]
    by_name = {row["name"]: row["gcsim"] for row in items}

    assert by_name["Kamisato Ayaka"]["status"] == "full"
    assert by_name["Diluc"] == {
        "status": "partial", "key": "diluc", "pin": by_name["Diluc"]["pin"],
        "missing_actions": ["charge"], "reason": None,
    }
    assert by_name["Kachina"]["status"] == "none"
    assert by_name["Kachina"]["key"] is None
    assert "Kachina" in by_name["Kachina"]["reason"]


async def test_the_filter_narrows_and_the_total_counts_the_narrowing(
    client: AsyncClient, db_session: AsyncSession,
):
    await _roster(db_session)

    for status, name in (("full", "Kamisato Ayaka"), ("partial", "Diluc"), ("none", "Kachina")):
        body = (await client.get("/api/v1/characters", params={"gcsim": status})).json()
        names = [row["name"] for row in body["items"]]
        assert name in names
        assert all(row["gcsim"]["status"] == status for row in body["items"])
        assert body["total"] == len(names)


async def test_pagination_applies_after_the_filter(client: AsyncClient, db_session: AsyncSession):
    """Paginating first would hand back a page of three with one survivor on it."""
    await _roster(db_session)

    page = (await client.get(
        "/api/v1/characters", params={"gcsim": "none", "limit": 1, "offset": 0},
    )).json()

    assert [row["name"] for row in page["items"]] == ["Kachina"]
    assert page["total"] == 1


async def test_the_filter_combines_with_the_others(client: AsyncClient, db_session: AsyncSession):
    await _roster(db_session)

    body = (await client.get(
        "/api/v1/characters", params={"gcsim": "full", "element": "Pyro"},
    )).json()

    assert body == {"items": [], "total": 0, "offset": 0, "limit": 50}


async def test_an_unknown_status_is_refused(client: AsyncClient):
    response = await client.get("/api/v1/characters", params={"gcsim": "half"})
    assert response.status_code == 422


async def test_weapons_filter_by_status(client: AsyncClient, db_session: AsyncSession):
    db_session.add_all([
        Weapon(nanoka_id=11501, name="Aquila Favonia", weapon_type=WeaponType.SWORD,
               rarity=Rarity.FIVE_STAR),
        Weapon(nanoka_id=999999, name="Weapon Nobody Implements", weapon_type=WeaponType.SWORD,
               rarity=Rarity.FIVE_STAR),
    ])
    await db_session.flush()

    full = (await client.get("/api/v1/weapons", params={"gcsim": "full"})).json()
    none = (await client.get("/api/v1/weapons", params={"gcsim": "none"})).json()

    assert "Aquila Favonia" in [row["name"] for row in full["items"]]
    assert [row["name"] for row in none["items"]] == ["Weapon Nobody Implements"]
    assert none["items"][0]["gcsim"]["reason"]


async def test_sets_filter_by_status_and_simulable_agrees(
    client: AsyncClient, db_session: AsyncSession,
):
    db_session.add_all([
        ArtifactSet(nanoka_id=15003, name="Blizzard Strayer"),
        ArtifactSet(nanoka_id=999001, name="Adventurer"),
    ])
    await db_session.flush()

    none = (await client.get("/api/v1/artifact-sets", params={"gcsim": "none"})).json()

    assert [row["name"] for row in none["items"]] == ["Adventurer"]
    assert none["items"][0]["simulable"] is False
    every = (await client.get("/api/v1/artifact-sets")).json()["items"]
    assert all(row["simulable"] == (row["gcsim"]["status"] == "full") for row in every)
