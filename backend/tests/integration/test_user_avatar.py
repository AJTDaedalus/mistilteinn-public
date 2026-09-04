"""A character as the account's avatar, end to end — `DESIGN_user_avatar.md`.

These drive the routes rather than the column. The one failure worth designing against is not
visible in a schema diagram: `characters` rows are deleted whenever a seed run finds one
retracted upstream, and every *other* reference to `characters.id` in this schema cascades. A
cascading avatar would delete accounts during a routine re-seed, pass every unit test, and be
discovered by a user who could no longer log in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient  # noqa: TC002 — a fixture type, resolved at runtime
from sqlalchemy import select

from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType
from app.models.user import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ME = "/api/v1/auth/me"
AVATAR = "/api/v1/auth/me/avatar"
pytestmark = pytest.mark.asyncio


async def _character(
    session: AsyncSession, nanoka_id: str, name: str, icon: str | None,
) -> Character:
    row = Character(
        nanoka_id=nanoka_id, name=name, element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1000.0, base_atk=26.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5, icon=icon,
    )
    session.add(row)
    await session.flush()
    return row


async def test_an_account_that_has_picked_nobody_says_so(authed_client: AsyncClient) -> None:
    """`null`, not an absent key — every account that existed before this feature is here, and
    the client has to render the state rather than crash on a missing field."""
    body = (await authed_client.get(ME)).json()

    assert body["avatar"] is None


async def test_picking_a_character_answers_with_the_headshot_to_draw(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """The response carries the icon basename and the name, so the page can draw and label the
    choice without a second request against the catalogue."""
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka", "UI_AvatarIcon_Ayaka")
    await db_session.commit()

    resp = await authed_client.put(AVATAR, json={"character_id": str(ayaka.id)})

    assert resp.status_code == 200
    assert resp.json()["avatar"] == {
        "character_id": str(ayaka.id),
        "name": "Kamisato Ayaka",
        "icon": "UI_AvatarIcon_Ayaka",
    }


async def test_the_choice_survives_the_request_that_made_it(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """`PUT` then `GET` — the write is committed rather than merely echoed back."""
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka", "UI_AvatarIcon_Ayaka")
    await db_session.commit()
    await authed_client.put(AVATAR, json={"character_id": str(ayaka.id)})

    body = (await authed_client.get(ME)).json()

    assert body["avatar"]["name"] == "Kamisato Ayaka"


async def test_a_character_with_no_published_art_is_still_a_choice(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """A null `icon` is a seeding gap, not a reason to refuse the pick. `CatalogueIcon` renders
    nothing at all for one, which is the same thing it does for an account with no avatar."""
    nobody = await _character(db_session, "10000099", "Unreleased", None)
    await db_session.commit()

    resp = await authed_client.put(AVATAR, json={"character_id": str(nobody.id)})

    assert resp.status_code == 200
    assert resp.json()["avatar"] == {
        "character_id": str(nobody.id), "name": "Unreleased", "icon": None,
    }


async def test_null_clears_it(authed_client: AsyncClient, db_session: AsyncSession) -> None:
    """The *Clear* button. One code path with setting, which is why it is not a `DELETE` route."""
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka", "UI_AvatarIcon_Ayaka")
    await db_session.commit()
    await authed_client.put(AVATAR, json={"character_id": str(ayaka.id)})

    resp = await authed_client.put(AVATAR, json={"character_id": None})

    assert resp.status_code == 200
    assert resp.json()["avatar"] is None
    assert (await authed_client.get(ME)).json()["avatar"] is None


async def test_an_id_that_names_nothing_is_refused_and_changes_nothing(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """**404 rather than a quiet no-op.** A 200 that changed nothing would leave the page
    showing the avatar the user had just replaced, with no indication why."""
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka", "UI_AvatarIcon_Ayaka")
    await db_session.commit()
    await authed_client.put(AVATAR, json={"character_id": str(ayaka.id)})

    resp = await authed_client.put(AVATAR, json={"character_id": "not-a-character"})

    assert resp.status_code == 404
    assert (await authed_client.get(ME)).json()["avatar"]["name"] == "Kamisato Ayaka"


async def test_an_anonymous_caller_cannot_set_one(client: AsyncClient) -> None:
    resp = await client.put(AVATAR, json={"character_id": None})

    assert resp.status_code == 401


async def test_retiring_a_character_costs_a_user_their_picture_and_not_their_account(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """**The test this file exists for.** `ON DELETE SET NULL`, where `builds.character_id` and
    `character_roster.character_id` both cascade.

    A seed run deletes a character the moment upstream retracts one. Under `CASCADE` that
    `DELETE` would reach the users table, and the symptom — accounts vanishing during a routine
    re-seed — would look like anything but an avatar.
    """
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka", "UI_AvatarIcon_Ayaka")
    await db_session.commit()
    await authed_client.put(AVATAR, json={"character_id": str(ayaka.id)})
    user, _ = authed_user

    await db_session.delete(ayaka)
    await db_session.commit()

    survivor = (
        await db_session.execute(select(User).where(User.id == user.id))
    ).scalar_one_or_none()
    assert survivor is not None, "deleting a catalogue row deleted an account"
    await db_session.refresh(survivor)
    assert survivor.avatar_character_id is None
    assert (await authed_client.get(ME)).json()["avatar"] is None


async def test_a_misspelled_field_is_refused_rather_than_read_as_a_clear(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """**The dangerous shape of a nullable field.** With Pydantic's default `extra="ignore"`
    and a `None` default, `{"characterId": ...}` — one camelCase slip — would validate, land in
    the clear branch, and erase the avatar with a 200 the caller reads as success."""
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka", "UI_AvatarIcon_Ayaka")
    await db_session.commit()
    await authed_client.put(AVATAR, json={"character_id": str(ayaka.id)})

    resp = await authed_client.put(AVATAR, json={"characterId": str(ayaka.id)})

    assert resp.status_code == 422
    assert (await authed_client.get(ME)).json()["avatar"]["name"] == "Kamisato Ayaka"


async def test_an_empty_body_is_refused_too(authed_client: AsyncClient) -> None:
    """Clearing is `{"character_id": null}` said out loud, never an omission."""
    assert (await authed_client.put(AVATAR, json={})).status_code == 422


async def test_a_practice_mannequin_is_not_somebody_you_can_be(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """The 14 mannequin rows are hidden from every catalogue list and count by owner ruling,
    so the picker cannot offer one — but `get_by_id` is the plain primary-key fetch and skips
    that exclusion. Accepted, the page would read "Manekin" above a picker whose trigger still
    said "Choose a character…", because no card in it matches the saved value."""
    manekin = await _character(db_session, "10000117-2", "Manekin", "UI_AvatarIcon_Manekin")
    await db_session.commit()

    resp = await authed_client.put(AVATAR, json={"character_id": str(manekin.id)})

    assert resp.status_code == 404
    assert (await authed_client.get(ME)).json()["avatar"] is None
