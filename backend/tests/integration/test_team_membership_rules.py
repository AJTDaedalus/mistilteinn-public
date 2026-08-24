"""T.1a — what a team may hold, now that a user may own several builds per character.

`uq_builds_owner_character` is gone (owner decision, 2026-08-24): comparing a C0 against a
C6, or a Physical Eula against a Cryo one, is an ordinary thing to want and the constraint
forbade it.

**That moves a rule rather than deleting one.** gcsim refuses a party with the same character
twice — `pkg/simulation/setup.go:94` at the pin `3647a07`:

    if _, ok := dup[chars[i].Base.Key]; ok {
        return fmt.Errorf("duplicated character %v", chars[i].Base.Key)
    }

So two builds of one character can coexist in a user's collection and cannot coexist on a
team. The team is where the rule belongs, and it is checked here rather than discovered when
a simulation fails.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.build import Build
from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType
from app.models.user import User

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

TEAMS = "/api/v1/teams"
BUILDS = "/api/v1/builds"
ABSENT = "00000000-0000-0000-0000-000000000001"


async def _character(db: AsyncSession, nanoka_id: str, name: str) -> Character:
    character = Character(
        nanoka_id=nanoka_id, name=name, element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1000.0, base_atk=26.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    db.add(character)
    await db.flush()
    return character


# ── a user may now own several builds of one character ───────────────────────


async def test_two_builds_of_one_character_can_be_owned(
    authed_client: AsyncClient, db_session: AsyncSession,
):
    """The owner decision, end to end. A C0 and a C6 of the same character, side by side."""
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka")

    first = await authed_client.post(BUILDS, json={
        "character_id": str(ayaka.id), "constellation_level": 0,
    })
    second = await authed_client.post(BUILDS, json={
        "character_id": str(ayaka.id), "constellation_level": 6,
    })

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]


# ── a team may not ───────────────────────────────────────────────────────────


async def test_a_team_refuses_two_builds_of_the_same_character(
    authed_client: AsyncClient, db_session: AsyncSession,
):
    """gcsim errors `duplicated character` on such a party, so it cannot be simulated.

    Refused when the team is saved, rather than at the point of simulation — which is both
    later and further from the edit that caused it.
    """
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka")
    c0 = (await authed_client.post(BUILDS, json={"character_id": str(ayaka.id)})).json()
    c6 = (await authed_client.post(BUILDS, json={
        "character_id": str(ayaka.id), "constellation_level": 6,
    })).json()

    response = await authed_client.post(TEAMS, json={
        "name": "Two Ayakas", "build1_id": c0["id"], "build2_id": c6["id"],
    })

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "Kamisato Ayaka" in detail
    assert "twice" in detail


async def test_a_patch_cannot_smuggle_a_duplicate_character_in(
    authed_client: AsyncClient, db_session: AsyncSession,
):
    """The merged team is what must be legal, not the patch body."""
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka")
    barbara = await _character(db_session, "10000014", "Barbara")
    first = (await authed_client.post(BUILDS, json={"character_id": str(ayaka.id)})).json()
    other = (await authed_client.post(BUILDS, json={"character_id": str(barbara.id)})).json()
    second_ayaka = (await authed_client.post(BUILDS, json={
        "character_id": str(ayaka.id), "constellation_level": 6,
    })).json()
    team = (await authed_client.post(TEAMS, json={
        "name": "Fine", "build1_id": first["id"], "build2_id": other["id"],
    })).json()

    response = await authed_client.patch(
        f"{TEAMS}/{team['id']}", json={"build3_id": second_ayaka["id"]},
    )

    assert response.status_code == 422
    assert "twice" in response.json()["detail"]


async def test_two_different_characters_are_fine(
    authed_client: AsyncClient, db_session: AsyncSession,
):
    """Guards the guard: every assertion above is a refusal."""
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka")
    barbara = await _character(db_session, "10000014", "Barbara")
    one = (await authed_client.post(BUILDS, json={"character_id": str(ayaka.id)})).json()
    two = (await authed_client.post(BUILDS, json={"character_id": str(barbara.id)})).json()

    response = await authed_client.post(TEAMS, json={
        "name": "Freeze", "build1_id": one["id"], "build2_id": two["id"],
    })

    assert response.status_code == 201, response.text


# ── a team's slots must name builds the caller owns ──────────────────────────


async def test_a_team_naming_an_absent_build_is_refused_not_a_500(
    authed_client: AsyncClient,
):
    """`create_team` was a bare `repo.create`, so this reached the foreign key."""
    response = await authed_client.post(TEAMS, json={"name": "Ghosts", "build1_id": ABSENT})

    assert response.status_code == 422, response.text
    assert ABSENT in response.json()["detail"]


async def test_a_team_cannot_be_built_from_someone_elses_build(
    authed_client: AsyncClient, db_session: AsyncSession,
):
    """Worse than a wrong answer: it would put a stranger's build in the caller's team, and
    every read of that team afterwards would show it."""
    stranger = User(email="stranger@example.com", password_hash="not-a-hash")  # noqa: S106
    db_session.add(stranger)
    await db_session.flush()
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka")
    theirs = Build(owner_id=str(stranger.id), character_id=str(ayaka.id))
    db_session.add(theirs)
    await db_session.flush()

    response = await authed_client.post(TEAMS, json={
        "name": "Borrowed", "build1_id": str(theirs.id),
    })

    assert response.status_code == 422


async def test_the_roster_refuses_a_duplicate_rather_than_collapsing_it(
    db_session: AsyncSession, authed_user: tuple[User, str],
):
    """Written directly, bypassing the API refusal.

    The rule lives in the application, not the schema, so a row from a script or a fixture
    can still hold one character twice. Keyed by `nanoka_id`, the roster would collapse it —
    a four-build team compiling a rotation against three characters, with nothing reporting a
    problem. Reached at the repository because that is where such a row would arrive.
    """
    from app.models.team import Team
    from app.repositories.rotation import DuplicateTeamMemberError, RotationRepository

    user, _ = authed_user
    ayaka = await _character(db_session, "10000002", "Kamisato Ayaka")
    c0 = Build(owner_id=str(user.id), character_id=str(ayaka.id))
    c6 = Build(owner_id=str(user.id), character_id=str(ayaka.id), constellation_level=6)
    db_session.add_all([c0, c6])
    await db_session.flush()
    team = Team(
        owner_id=str(user.id), name="Impossible",
        build1_id=str(c0.id), build2_id=str(c6.id),
    )
    db_session.add(team)
    await db_session.flush()

    repo = RotationRepository(db_session, owner_id=str(user.id))

    with pytest.raises(DuplicateTeamMemberError, match="Kamisato Ayaka"):
        await repo.character_rows(str(team.id))
