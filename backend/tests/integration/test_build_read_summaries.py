"""T.2 — a build carries what a row needs.

`BuildRead` returned `character_id` and `weapon_id` as bare UUIDs. A builds list showing
"Kamisato Ayaka · Mistsplitter" therefore needed one catalogue fetch per build, and had to map
a UUID `character_id` to the `nanoka_id` the catalogue is keyed by — a conversion the client
has no business performing. Same shape R.5 met and answered with `/rotations/options`: the
server returns what the page needs to draw a row.

**Every test here expires the session before the request.** Without it the identity map serves
the handler and a missing eager load emits no SQL, so the test passes for a reason a real
request does not have — the T.1a finding, one chunk old.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.character import Character
from app.models.enums import Element, Rarity, StatType, WeaponType
from app.models.weapon import Weapon

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

BUILDS = "/api/v1/builds"
WEAPONS = "/api/v1/weapons"


@pytest.fixture
async def catalogue(db_session: AsyncSession) -> dict[str, str]:
    ayaka = Character(
        nanoka_id="10000002", name="Kamisato Ayaka", element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1001.0, base_atk=26.6, base_def=61.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    sword = Weapon(
        nanoka_id=11509, name="Mistsplitter Reforged", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=48.0, sub_stat_type=StatType.CRIT_DMG,
        sub_stat_base_value=0.096,
    )
    bow = Weapon(
        nanoka_id=15502, name="Amos' Bow", weapon_type=WeaponType.BOW,
        rarity=Rarity.FIVE_STAR, base_atk=46.0, sub_stat_type=StatType.ATK_PCT,
        sub_stat_base_value=0.108,
    )
    db_session.add_all([ayaka, sword, bow])
    await db_session.flush()
    return {"character": str(ayaka.id), "sword": str(sword.id), "bow": str(bow.id)}


async def _saved(client: AsyncClient, catalogue: dict[str, str], **overrides) -> dict:
    body = {"character_id": catalogue["character"], "weapon_id": catalogue["sword"]}
    body.update(overrides)
    created = await client.post(BUILDS, json=body)
    assert created.status_code == 201, created.text
    return created.json()


# ── the row draws itself ─────────────────────────────────────────────────────


async def test_a_listed_build_names_its_character_and_weapon(
    authed_client: AsyncClient, db_session: AsyncSession, catalogue,
):
    """One request. The point of the task: no catalogue fetch per row, and no UUID-to-
    `nanoka_id` mapping on the client."""
    await _saved(authed_client, catalogue)
    db_session.expire_all()

    listed = (await authed_client.get(BUILDS)).json()

    assert len(listed["items"]) == 1
    row = listed["items"][0]
    assert row["character"]["name"] == "Kamisato Ayaka"
    assert row["character"]["element"] == "Cryo"
    assert row["weapon"]["name"] == "Mistsplitter Reforged"


async def test_the_ids_are_still_there(
    authed_client: AsyncClient, db_session: AsyncSession, catalogue,
):
    """Added beside the ids, not instead of them. A client that stores `character_id` keeps
    working, and the summaries are for drawing rather than for referring."""
    saved = await _saved(authed_client, catalogue)
    db_session.expire_all()

    assert saved["character_id"] == catalogue["character"]
    assert saved["weapon_id"] == catalogue["sword"]


async def test_a_single_read_carries_them_too(
    authed_client: AsyncClient, db_session: AsyncSession, catalogue,
):
    """`get_by_id` does not eager-load, so this is the read most likely to have been missed.

    Expired first: with the identity map primed, a missing `selectinload` resolves without
    SQL and this passes while a real request raises `MissingGreenlet` (T.1a).
    """
    saved = await _saved(authed_client, catalogue)
    db_session.expire_all()

    body = (await authed_client.get(f"{BUILDS}/{saved['id']}")).json()

    assert body["character"]["name"] == "Kamisato Ayaka"
    assert body["weapon"]["name"] == "Mistsplitter Reforged"


async def test_the_write_paths_return_them_as_well(
    authed_client: AsyncClient, db_session: AsyncSession, catalogue,
):
    """A create or a patch returns `BuildRead`, so it has to be able to fill it.

    The freshly-created row has nothing loaded, which is why this is the same trap wearing a
    different coat: the object is in the session, so the relationship resolves for free in a
    test and not in production.
    """
    saved = await _saved(authed_client, catalogue)
    assert saved["character"]["name"] == "Kamisato Ayaka"

    db_session.expire_all()
    patched = await authed_client.patch(
        f"{BUILDS}/{saved['id']}", json={"character_level": 80},
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["weapon"]["name"] == "Mistsplitter Reforged"


async def test_a_build_with_no_weapon_says_so_rather_than_omitting_it(
    authed_client: AsyncClient, db_session: AsyncSession, catalogue,
):
    """`weapon_id` is nullable by design (OQ-T3), so `weapon` has to be explicitly null. An
    absent key would read as "we did not look"."""
    saved = await _saved(authed_client, catalogue, weapon_id=None)
    db_session.expire_all()

    body = (await authed_client.get(f"{BUILDS}/{saved['id']}")).json()

    assert "weapon" in body
    assert body["weapon"] is None


# ── the picker can be given only what the validator accepts ──────────────────


async def test_weapons_can_be_filtered_to_what_a_character_can_hold(
    authed_client: AsyncClient, catalogue,
):
    """The T.3 picker's whole guarantee, and it was never exercised through the API.

    T.1 refuses a weapon whose type does not match the character's. A picker offering the
    other five classes would let a user select something the server then refuses, citing
    their own choice back at them — so the filtering is the server's, not a rule the page
    re-implements.
    """
    listed = await authed_client.get(
        WEAPONS, params={"weapon_type": WeaponType.SWORD.value},
    )

    assert listed.status_code == 200, listed.text
    names = [w["name"] for w in listed.json()["items"]]
    assert "Mistsplitter Reforged" in names
    assert "Amos' Bow" not in names
    assert listed.json()["total"] == len(names), "the count must match the filter"


async def test_a_weapon_class_reads_as_a_name_a_person_would_use(
    authed_client: AsyncClient, catalogue,
):
    """`WEAPON_SWORD_ONE_HAND` is the source's internal spelling, and it is why `Element`
    reads well in API output while `WeaponType` does not. The label comes from
    `WeaponType.display` so a page does not have to reimplement the mapping."""
    listed = await authed_client.get(
        WEAPONS, params={"weapon_type": WeaponType.SWORD.value},
    )

    entry = listed.json()["items"][0]
    assert entry["weapon_type"] == "WEAPON_SWORD_ONE_HAND", "the raw value stays"
    assert entry["weapon_type_display"] == "Sword"
