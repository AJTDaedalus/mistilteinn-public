"""The rotation library — sharing, finding, liking, copying.

`TASKS_rotation_library.md` Track A and Track B.

These tests are about the things that would go wrong **quietly**. A library is a feature whose
failure modes are silence: a private rotation that leaks, a filter that returns a rotation the
asker's team cannot run, a like that 500s on the second click. None of those announce
themselves the way a broken endpoint does.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database import get_db
from app.main import create_app
from app.models.build import Build
from app.models.character import Character
from app.models.enums import Element, Rarity, UserStatus, WeaponType
from app.models.team import Team
from app.models.user import User
from app.services.password import hash_password
from tests.conftest import make_session_for

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

ROTATIONS = "/api/v1/rotations"
LIBRARY = f"{ROTATIONS}/library"

AYAKA, BARBARA, GANYU = "10000002", "10000014", "10000037"


@dataclass
class Party:
    """One user's team, and the client that speaks for them."""

    client: AsyncClient
    team_id: str


async def _roster(db_session: AsyncSession) -> dict[str, str]:
    """Three characters, created once and shared — the catalogue is not per-user."""
    made: dict[str, str] = {}
    for nanoka_id, name, element in (
        (AYAKA, "Kamisato Ayaka", Element.CRYO),
        (BARBARA, "Barbara", Element.HYDRO),
        (GANYU, "Ganyu", Element.CRYO),
    ):
        existing = await db_session.execute(
            Character.__table__.select().where(Character.nanoka_id == nanoka_id),
        )
        row = existing.first()
        if row is not None:
            made[nanoka_id] = str(row.id)
            continue
        character = Character(
            nanoka_id=nanoka_id, name=name, element=element,
            weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
            base_hp=1000.0, base_atk=26.0, base_def=60.0,
            base_crit_rate=0.05, base_crit_dmg=0.5,
        )
        db_session.add(character)
        await db_session.flush()
        made[nanoka_id] = str(character.id)
    return made


async def _party(
    db_session: AsyncSession, characters: dict[str, str], *, holding: tuple[str, ...],
) -> Party:
    """A fresh approved user with their own team, and a client authenticated as them.

    A second real user is the only way to test the thing that matters here. Asserting that a
    query filters on `visibility` proves the query does; only a second account proves the
    *feature* does.
    """
    user = User(
        email=f"lib_{secrets.token_hex(4)}@test.example",
        label="Library User",
        password_hash=hash_password("TestPassword123!"),
        status=UserStatus.APPROVED,
    )
    db_session.add(user)
    await db_session.flush()
    token = await make_session_for(user, db_session)

    builds = {}
    for nanoka_id in holding:
        build = Build(owner_id=str(user.id), character_id=characters[nanoka_id])
        db_session.add(build)
        await db_session.flush()
        builds[nanoka_id] = str(build.id)

    slots = dict(zip(("build1_id", "build2_id", "build3_id", "build4_id"),
                     [builds[c] for c in holding], strict=False))
    team = Team(owner_id=str(user.id), name="Party", **slots)
    db_session.add(team)
    await db_session.flush()

    app = create_app()
    app.dependency_overrides[get_settings] = get_settings

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )
    return Party(client=client, team_id=str(team.id))


def _step(character: str, action: str = "burst") -> dict:
    return {"character": character, "action": action, "repeat": 1}


async def _rotation(party: Party, name: str, *characters: str, publish: bool = False) -> str:
    created = await party.client.post(ROTATIONS, json={
        "name": name, "team_id": party.team_id,
        "steps": [_step(c) for c in characters],
    })
    assert created.status_code == 201, created.text
    rotation_id = created.json()["id"]
    if publish:
        patched = await party.client.patch(
            f"{ROTATIONS}/{rotation_id}", json={"visibility": "published"},
        )
        assert patched.status_code == 200, patched.text
    return rotation_id


@pytest.fixture
async def alice(db_session: AsyncSession) -> AsyncGenerator[Party, None]:
    party = await _party(db_session, await _roster(db_session), holding=(AYAKA, BARBARA))
    yield party
    await party.client.aclose()


@pytest.fixture
async def bob(db_session: AsyncSession) -> AsyncGenerator[Party, None]:
    party = await _party(db_session, await _roster(db_session), holding=(AYAKA, BARBARA))
    yield party
    await party.client.aclose()


# ── private by default ───────────────────────────────────────────────────────


async def test_a_new_rotation_is_private(alice: Party):
    """OQ-4. A rotation becoming visible by default is not a mistake anyone can take back."""
    rotation_id = await _rotation(alice, "Mine", AYAKA)

    read = await alice.client.get(f"{ROTATIONS}/{rotation_id}")

    assert read.json()["visibility"] == "private"


async def test_another_user_cannot_see_an_unpublished_rotation(alice: Party, bob: Party):
    await _rotation(alice, "Secret", AYAKA)

    listed = await bob.client.get(LIBRARY)

    assert listed.status_code == 200
    assert [r["name"] for r in listed.json()["items"]] == []


async def test_publishing_makes_it_visible_to_another_user(alice: Party, bob: Party):
    await _rotation(alice, "Shared", AYAKA, publish=True)

    listed = await bob.client.get(LIBRARY)

    assert [r["name"] for r in listed.json()["items"]] == ["Shared"]


async def test_unpublishing_takes_it_back_out(alice: Party, bob: Party):
    """The door opens both ways. Someone who shared by mistake needs it to."""
    rotation_id = await _rotation(alice, "Oops", AYAKA, publish=True)

    await alice.client.patch(f"{ROTATIONS}/{rotation_id}", json={"visibility": "private"})

    assert (await bob.client.get(LIBRARY)).json()["items"] == []


async def test_a_stranger_cannot_publish_someone_elses_rotation(alice: Party, bob: Party):
    """404, not 403 — the existing convention, which does not confirm the row exists."""
    rotation_id = await _rotation(alice, "Mine", AYAKA)

    refused = await bob.client.patch(
        f"{ROTATIONS}/{rotation_id}", json={"visibility": "published"},
    )

    assert refused.status_code == 404


# ── finding one ──────────────────────────────────────────────────────────────


async def test_the_character_filter_matches_the_set_exactly(alice: Party, bob: Party):
    """**Not a superset.** A four-character rotation surfacing for a three-character query
    would be a recommendation wearing a filter's clothes — `DESIGN_rotation_library.md` §3
    calls this a filter that claims nothing, and that is only true if it means it."""
    await _rotation(alice, "Solo", AYAKA, publish=True)
    await _rotation(alice, "Duo", AYAKA, BARBARA, publish=True)

    solo = await bob.client.get(LIBRARY, params={"characters": [AYAKA]})
    duo = await bob.client.get(LIBRARY, params={"characters": [AYAKA, BARBARA]})

    assert [r["name"] for r in solo.json()["items"]] == ["Solo"]
    assert [r["name"] for r in duo.json()["items"]] == ["Duo"]


async def test_the_character_index_follows_an_edit(alice: Party, bob: Party):
    """The index is rebuilt whole on every write, so a rotation cannot be found under a
    character it no longer names."""
    rotation_id = await _rotation(alice, "Changing", AYAKA, BARBARA, publish=True)

    await alice.client.patch(
        f"{ROTATIONS}/{rotation_id}", json={"steps": [_step(AYAKA)]},
    )

    stale = await bob.client.get(LIBRARY, params={"characters": [AYAKA, BARBARA]})
    fresh = await bob.client.get(LIBRARY, params={"characters": [AYAKA]})
    assert stale.json()["items"] == []
    assert [r["name"] for r in fresh.json()["items"]] == ["Changing"]


async def test_a_listing_carries_the_character_set_it_was_matched_on(alice: Party, bob: Party):
    await _rotation(alice, "Duo", AYAKA, BARBARA, publish=True)

    listed = await bob.client.get(LIBRARY)

    assert sorted(listed.json()["items"][0]["characters"]) == sorted([AYAKA, BARBARA])


async def test_search_matches_the_name(alice: Party, bob: Party):
    await _rotation(alice, "Freeze opener", AYAKA, publish=True)
    await _rotation(alice, "Melt cycle", BARBARA, publish=True)

    found = await bob.client.get(LIBRARY, params={"q": "freeze"})

    assert [r["name"] for r in found.json()["items"]] == ["Freeze opener"]


# ── likes ────────────────────────────────────────────────────────────────────


async def test_liking_twice_is_a_no_op_rather_than_a_500(alice: Party, bob: Party):
    """A unique constraint plus a read-then-write loses the race it exists to handle."""
    rotation_id = await _rotation(alice, "Good one", AYAKA, publish=True)

    first = await bob.client.post(f"{ROTATIONS}/{rotation_id}/like")
    second = await bob.client.post(f"{ROTATIONS}/{rotation_id}/like")

    assert (first.status_code, second.status_code) == (204, 204)
    listed = await bob.client.get(LIBRARY)
    assert listed.json()["items"][0]["like_count"] == 1


async def test_a_like_says_whether_it_is_yours(alice: Party, bob: Party):
    """A count alone cannot answer *have I liked this*, which is why likes are a table."""
    rotation_id = await _rotation(alice, "Good one", AYAKA, publish=True)
    await bob.client.post(f"{ROTATIONS}/{rotation_id}/like")

    theirs = (await bob.client.get(LIBRARY)).json()["items"][0]
    authors = (await alice.client.get(LIBRARY)).json()["items"][0]

    assert theirs["liked_by_me"] is True
    assert authors["liked_by_me"] is False
    assert authors["like_count"] == 1


async def test_unliking_what_you_never_liked_is_not_an_error(alice: Party, bob: Party):
    rotation_id = await _rotation(alice, "Good one", AYAKA, publish=True)

    removed = await bob.client.delete(f"{ROTATIONS}/{rotation_id}/like")

    assert removed.status_code == 204


async def test_an_unpublished_rotation_cannot_be_liked(alice: Party, bob: Party):
    rotation_id = await _rotation(alice, "Secret", AYAKA)

    refused = await bob.client.post(f"{ROTATIONS}/{rotation_id}/like")

    assert refused.status_code == 404


# ── copying ──────────────────────────────────────────────────────────────────


async def test_copying_lands_a_private_rotation_on_your_own_team(alice: Party, bob: Party):
    rotation_id = await _rotation(alice, "Shared", AYAKA, BARBARA, publish=True)

    copied = await bob.client.post(
        f"{ROTATIONS}/{rotation_id}/copy", json={"team_id": bob.team_id},
    )

    assert copied.status_code == 201, copied.text
    body = copied.json()
    assert body["team_id"] == bob.team_id
    assert body["visibility"] == "private"
    assert [s["character"] for s in body["steps"]] == [AYAKA, BARBARA]


async def test_copying_onto_a_team_missing_a_character_refuses_and_creates_nothing(
    db_session: AsyncSession, alice: Party,
):
    """**Named, never dropped.** Silently discarding the step would hand the copier a rotation
    that is a different rotation — the rule `app/models/rotation.py` already applies to a
    rotation gone stale."""
    rotation_id = await _rotation(alice, "Shared", AYAKA, BARBARA, publish=True)
    short = await _party(db_session, await _roster(db_session), holding=(GANYU,))

    refused = await short.client.post(
        f"{ROTATIONS}/{rotation_id}/copy", json={"team_id": short.team_id},
    )

    assert refused.status_code == 422
    assert AYAKA in refused.json()["detail"]
    assert (await short.client.get(ROTATIONS)).json()["items"] == []
    await short.client.aclose()


async def test_an_unpublished_rotation_cannot_be_copied(alice: Party, bob: Party):
    rotation_id = await _rotation(alice, "Secret", AYAKA)

    refused = await bob.client.post(
        f"{ROTATIONS}/{rotation_id}/copy", json={"team_id": bob.team_id},
    )

    assert refused.status_code == 404
