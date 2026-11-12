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
from app.repositories.rotation import RotationRepository
from app.services.gcsim_keys import pinned_commit
from app.services.password import hash_password
from app.services.rotation_compiler import rotation_signature, signature_digest
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


# ── your DPS, and the version it belongs to ──────────────────────────────────


async def _store_run(
    party: Party, rotation_id: str, signature: str, dps: float, *, key: str = "a" * 64,
) -> int:
    """Submit a cached run labelled with a rotation and the version of it that ran."""
    posted = await party.client.post(
        "/api/v1/sim-runs",
        params={"gcsim_pin": pinned_commit()},
        json={
            "context_key": key,
            "er_bucket": 100,
            "result": {"statistics": {"dps": {"mean": dps}}},
            "rotation_id": rotation_id,
            "rotation_signature": signature,
        },
    )
    return posted.status_code


async def _signature(db_session: AsyncSession, rotation_id: str) -> str:
    """The digest the library will compute for this rotation, from the app's own functions.

    Not reimplemented here: `signature_digest` is the one definition, and a test hashing its
    own way would pass while the feature silently returned `None` for everything.
    """
    repo = RotationRepository(db_session)
    rotation = await repo.get_by_id(rotation_id)
    roster = await repo.character_rows(rotation.team_id)
    return signature_digest(rotation_signature(rotation.steps or [], roster))


async def test_a_run_labels_the_rotation_and_the_version_it_simulated(
    db_session: AsyncSession, alice: Party,
):
    rotation_id = await _rotation(alice, "Mine", AYAKA, publish=True)
    signature = await _signature(db_session, rotation_id)

    assert await _store_run(alice, rotation_id, signature, 12_345.0) in (200, 201)

    listed = await alice.client.get(LIBRARY)
    assert listed.json()["items"][0]["your_dps"] == 12_345.0


async def test_editing_the_rotation_drops_the_number_that_described_its_old_version(
    db_session: AsyncSession, alice: Party,
):
    """**The whole reason `rotation_signature` exists.**

    Edit a rotation and `context_key` changes, so the next run writes a new row — while the
    old row keeps its `rotation_id` and its DPS. Matching on `rotation_id` alone would sort
    this rotation by a number computed for a version the user can no longer see.
    """
    rotation_id = await _rotation(alice, "Mine", AYAKA, publish=True)
    signature = await _signature(db_session, rotation_id)
    await _store_run(alice, rotation_id, signature, 12_345.0)

    await alice.client.patch(
        f"{ROTATIONS}/{rotation_id}", json={"steps": [_step(AYAKA, "skill")]},
    )

    listed = await alice.client.get(LIBRARY)
    assert listed.json()["items"][0]["your_dps"] is None


async def test_another_users_rotation_reports_no_dps_of_yours(
    db_session: AsyncSession, alice: Party, bob: Party,
):
    """And this is correct, not missing.

    You cannot simulate a rotation on a team you do not own, so you have no run for it. The
    number under a stranger's rotation would have to be *theirs*, on their gear, which is the
    ranking `DESIGN_rotation_library.md` §3 refuses.
    """
    rotation_id = await _rotation(alice, "Shared", AYAKA, publish=True)
    await _store_run(alice, rotation_id, await _signature(db_session, rotation_id), 12_345.0)

    listed = await bob.client.get(LIBRARY)

    assert listed.json()["items"][0]["your_dps"] is None


async def test_a_run_labelled_with_a_rotation_but_no_version_is_refused(alice: Party):
    """One without the other labels a run with a rotation but not with *which* version, which
    is exactly how a stale number gets shown as current."""
    rotation_id = await _rotation(alice, "Mine", AYAKA, publish=True)

    refused = await alice.client.post(
        "/api/v1/sim-runs",
        params={"gcsim_pin": pinned_commit()},
        json={
            "context_key": "b" * 64, "er_bucket": 100,
            "result": {"statistics": {"dps": {"mean": 1.0}}},
            "rotation_id": rotation_id,
        },
    )

    assert refused.status_code == 422
    assert "travel together" in refused.text


async def test_sorting_puts_a_rotation_you_have_run_above_one_you_have_not(
    db_session: AsyncSession, alice: Party,
):
    """A rotation with no run sorts **below** every one that has a number — not as zero, which
    would rank it against figures rather than admitting there is none."""
    unrun = await _rotation(alice, "Never run", BARBARA, publish=True)
    run = await _rotation(alice, "Ran it", AYAKA, publish=True)
    await _store_run(alice, run, await _signature(db_session, run), 999.0)

    listed = await alice.client.get(LIBRARY, params={"sort": "dps"})

    assert [r["name"] for r in listed.json()["items"]] == ["Ran it", "Never run"]
    assert unrun  # the unrun rotation is present, just last


# ── security audit F2: a condition is gcsim script, so it is checked on every path ─────────

#: Closes the guarded block and appends statements of its own. Emitted verbatim, this ran in
#: the browser of anyone who compiled a copy of the rotation.
_INJECTED = '1 { } while 1 { print("x"); } if 0'


def _guarded(character: str, condition: str) -> dict:
    return {**_step(character), "group": "g", "group_condition": condition}


async def _plant(db_session: AsyncSession, rotation_id: str, condition: str) -> None:
    """Write a condition straight to the row — what a rotation saved before the check holds."""
    from app.models.rotation import Rotation

    row = await db_session.get(Rotation, rotation_id)
    assert row is not None
    row.steps = [_guarded(AYAKA, condition)]
    await db_session.flush()


async def test_creating_a_rotation_with_an_injected_condition_is_refused(alice: Party):
    refused = await alice.client.post(ROTATIONS, json={
        "name": "Hostile", "team_id": alice.team_id, "steps": [_guarded(AYAKA, _INJECTED)],
    })

    assert refused.status_code == 422
    assert "not a condition" in refused.text


async def test_updating_a_rotation_to_an_injected_condition_is_refused(alice: Party):
    rotation_id = await _rotation(alice, "Mine", AYAKA)

    refused = await alice.client.patch(
        f"{ROTATIONS}/{rotation_id}", json={"steps": [_guarded(AYAKA, _INJECTED)]},
    )

    assert refused.status_code == 422


async def test_a_condition_in_the_vocabulary_is_accepted(alice: Party):
    created = await alice.client.post(ROTATIONS, json={
        "name": "Guarded", "team_id": alice.team_id,
        "steps": [_guarded(AYAKA, ".ayaka.energy >= 30")],
    })

    assert created.status_code == 201, created.text


async def test_copying_a_published_rotation_revalidates_its_steps(
    db_session: AsyncSession, alice: Party, bob: Party,
):
    """A row stored before the check existed must not spread to another user's account."""
    rotation_id = await _rotation(alice, "Shared", AYAKA, publish=True)
    await _plant(db_session, rotation_id, _INJECTED)

    refused = await bob.client.post(
        f"{ROTATIONS}/{rotation_id}/copy", json={"team_id": bob.team_id},
    )

    assert refused.status_code == 422


async def test_the_compiler_refuses_a_stored_injected_condition(
    db_session: AsyncSession, alice: Party,
):
    rotation_id = await _rotation(alice, "Mine", AYAKA)
    await _plant(db_session, rotation_id, _INJECTED)

    refused = await alice.client.post(f"{ROTATIONS}/{rotation_id}/compile")

    assert refused.status_code == 422
    assert "config" not in refused.json()


async def test_one_bad_published_row_does_not_break_the_library(
    db_session: AsyncSession, alice: Party, bob: Party,
):
    """The library validates every row it lists; a single stored bad one must not 500 it."""
    good = await _rotation(alice, "Fine", BARBARA, publish=True)
    bad = await _rotation(alice, "Hostile", AYAKA, publish=True)
    await _plant(db_session, bad, _INJECTED)

    listed = await bob.client.get(LIBRARY)

    assert listed.status_code == 200
    ids = [r["id"] for r in listed.json()["items"]]
    assert good in ids
    assert bad not in ids
