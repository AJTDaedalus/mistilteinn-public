"""The teapot tracker end to end — `TASKS_account_tracking.md` 3.6 to 3.8."""
from __future__ import annotations

import pytest
from httpx import AsyncClient  # noqa: TC002 — a fixture type, resolved at runtime
from sqlalchemy import select

from app.models.base import generate_uuid7
from app.models.build import Build
from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType
from app.models.teapot import FurnishingSuite, FurnishingSuiteFavorite

TEAPOT = "/api/v1/teapot"
pytestmark = pytest.mark.asyncio


async def _suite(session, name: str, favorites: list[str]) -> FurnishingSuite:
    suite = FurnishingSuite(
        id=generate_uuid7(), nanoka_id=f"n-{name}", name=name, placement="I",
        icon="UI_Home_Suite_X", units={"1": 2},
    )
    session.add(suite)
    await session.flush()
    for character in favorites:
        session.add(FurnishingSuiteFavorite(
            suite_id=suite.id, character_nanoka_id=character,
        ))
    await session.commit()
    return suite


async def _character(session, nanoka_id: str) -> Character:
    """A catalogue row. **Made here rather than looked up**: the test database holds no
    seeded catalogue, and a test that silently found none would pass by testing nothing."""
    existing = (await session.execute(
        select(Character).where(Character.nanoka_id == nanoka_id),
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    character = Character(
        nanoka_id=nanoka_id, name=f"Character {nanoka_id}", element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1000.0, base_atk=26.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    session.add(character)
    await session.flush()
    return character


async def _own(session, authed_user, nanoka_id: str, *, owned: bool = True) -> None:
    """Give the user a build for that character."""
    user, _ = authed_user
    character = await _character(session, nanoka_id)
    session.add(Build(
        id=generate_uuid7(), owner_id=str(user.id), character_id=str(character.id),
        character_level=90, ascension_phase=6, weapon_level=90, refinement=1,
        constellation_level=0, talent_levels={}, notes="", owned=owned,
    ))
    await session.commit()


async def _any_characters(session, count: int) -> list[str]:
    """Nanoka ids to build the scenario from, created if the catalogue lacks them."""
    ids = [f"9000{index:04d}" for index in range(count)]
    for nanoka_id in ids:
        await _character(session, nanoka_id)
    await session.commit()
    return ids


async def test_a_set_favoured_by_nobody_you_have_is_worth_nothing(
    authed_client: AsyncClient, db_session, authed_user,
):
    """The whole reason `builds.owned` exists."""
    ids = await _any_characters(db_session, 2)
    await _suite(db_session, "Unreachable", [ids[0]])

    body = (await authed_client.get(f"{TEAPOT}/suites")).json()
    row = next(s for s in body["suites"] if s["name"] == "Unreachable")

    assert row["remaining"] == 0
    assert row["unowned_favorites"] == [ids[0]]


async def test_owning_the_character_makes_the_set_worth_doing(
    authed_client: AsyncClient, db_session, authed_user,
):
    ids = await _any_characters(db_session, 1)
    await _suite(db_session, "Reachable", ids)
    await _own(db_session, authed_user, ids[0])

    body = (await authed_client.get(f"{TEAPOT}/suites")).json()
    row = next(s for s in body["suites"] if s["name"] == "Reachable")

    assert row["remaining"] == 1
    assert row["owned_favorites"] == ids


async def test_a_test_build_does_not_count_as_owning_the_character(
    authed_client: AsyncClient, db_session, authed_user,
):
    """`owned=False` is exactly the distinction the owner asked for — *"which units they
    actually have… and which they've just made to test"*."""
    ids = await _any_characters(db_session, 1)
    await _suite(db_session, "TestOnly", ids)
    await _own(db_session, authed_user, ids[0], owned=False)

    body = (await authed_client.get(f"{TEAPOT}/suites")).json()
    row = next(s for s in body["suites"] if s["name"] == "TestOnly")

    assert row["remaining"] == 0


async def test_the_most_worth_doing_comes_first(
    authed_client: AsyncClient, db_session, authed_user,
):
    ids = await _any_characters(db_session, 3)
    await _suite(db_session, "AaOne", ids[:1])
    await _suite(db_session, "AaThree", ids[:3])
    for nanoka_id in ids:
        await _own(db_session, authed_user, nanoka_id)

    listed = [s["name"] for s in (await authed_client.get(f"{TEAPOT}/suites")).json()["suites"]]

    assert listed.index("AaThree") < listed.index("AaOne")


async def test_marking_a_set_done_takes_it_off_the_top(
    authed_client: AsyncClient, db_session, authed_user,
):
    ids = await _any_characters(db_session, 1)
    suite = await _suite(db_session, "Finished", ids)
    await _own(db_session, authed_user, ids[0])

    assert (await authed_client.put(f"{TEAPOT}/suites/{suite.id}/done")).status_code == 204

    body = (await authed_client.get(f"{TEAPOT}/suites")).json()
    row = next(s for s in body["suites"] if s["name"] == "Finished")
    assert row["done"] is True
    assert row["remaining"] == 0


async def test_a_finished_set_can_be_un_ticked(
    authed_client: AsyncClient, db_session, authed_user,
):
    """Which is why finished sets sink rather than disappear: a user has to be able to undo a
    tick, and that means being able to see it."""
    ids = await _any_characters(db_session, 1)
    suite = await _suite(db_session, "Oops", ids)
    await _own(db_session, authed_user, ids[0])
    await authed_client.put(f"{TEAPOT}/suites/{suite.id}/done")

    assert (await authed_client.delete(f"{TEAPOT}/suites/{suite.id}/done")).status_code == 204

    body = (await authed_client.get(f"{TEAPOT}/suites")).json()
    assert next(s for s in body["suites"] if s["name"] == "Oops")["done"] is False


async def test_ticking_twice_is_not_an_error(
    authed_client: AsyncClient, db_session, authed_user,
):
    """A client retrying a request it is not sure landed should not have to care."""
    ids = await _any_characters(db_session, 1)
    suite = await _suite(db_session, "Twice", ids)

    await authed_client.put(f"{TEAPOT}/suites/{suite.id}/done")

    assert (await authed_client.put(f"{TEAPOT}/suites/{suite.id}/done")).status_code == 204


async def test_ticking_a_set_that_does_not_exist_says_so(authed_client: AsyncClient):
    response = await authed_client.put(f"{TEAPOT}/suites/nope/done")

    assert response.status_code == 404


async def test_the_reward_constant_is_published_so_a_client_can_show_its_working(
    authed_client: AsyncClient, db_session, authed_user,
):
    """20 Primogems per character, cited at the constant (OQ-A4, answered 2026-09-03).

    Published rather than hard-coded in the client for the same reason every other vocabulary
    here is: a second copy would be the one that drifted when a patch changed it.
    """
    ids = await _any_characters(db_session, 2)
    await _suite(db_session, "Worth Forty", ids)
    for nanoka_id in ids:
        await _own(db_session, authed_user, nanoka_id)

    body = (await authed_client.get(f"{TEAPOT}/suites")).json()

    assert body["reward_per_character"] == 20
    row = next(s for s in body["suites"] if s["name"] == "Worth Forty")
    assert row["remaining_primogems"] == 40
