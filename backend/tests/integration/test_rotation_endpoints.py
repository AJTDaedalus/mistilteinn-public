"""R.4 — the rotation API.

The write path's job is to make a rotation that cannot compile impossible to save. A step
naming a character the team does not hold is refused **here**, not discovered later at
simulation time, far from the edit that caused it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from app.models.build import Build
from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType
from app.models.team import Team

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio

ROTATIONS = "/api/v1/rotations"


@dataclass
class Scene:
    team_id: str
    ayaka: str
    barbara: str


@pytest.fixture
async def scene(db_session: AsyncSession, authed_user: tuple[User, str]) -> Scene:
    user, _ = authed_user
    made = {}
    for nanoka_id, name, element in (
        ("10000002", "Kamisato Ayaka", Element.CRYO),
        ("10000014", "Barbara", Element.HYDRO),
    ):
        character = Character(
            nanoka_id=nanoka_id, name=name, element=element,
            weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
            base_hp=1000.0, base_atk=26.0, base_def=60.0,
            base_crit_rate=0.05, base_crit_dmg=0.5,
        )
        db_session.add(character)
        await db_session.flush()
        build = Build(owner_id=str(user.id), character_id=str(character.id))
        db_session.add(build)
        await db_session.flush()
        made[nanoka_id] = str(build.id)

    team = Team(
        owner_id=str(user.id), name="Party",
        build1_id=made["10000002"], build2_id=made["10000014"],
    )
    db_session.add(team)
    await db_session.flush()
    return Scene(team_id=str(team.id), ayaka="10000002", barbara="10000014")


def _step(character: str, action: str = "burst", repeat: int = 1) -> dict:
    return {"character": character, "action": action, "repeat": repeat}


# ── CRUD ──────────────────────────────────────────────────────────────────────


async def test_a_rotation_saves_and_reads_back(authed_client: AsyncClient, scene: Scene):
    created = await authed_client.post(ROTATIONS, json={
        "name": "Melt opener", "team_id": scene.team_id,
        "steps": [_step(scene.barbara, "skill"), _step(scene.ayaka, "burst")],
    })

    assert created.status_code == 201, created.text
    body = created.json()
    assert [s["action"] for s in body["steps"]] == ["skill", "burst"]

    read = await authed_client.get(f"{ROTATIONS}/{body['id']}")
    assert read.json()["name"] == "Melt opener"


async def test_listing_can_be_scoped_to_a_team(authed_client: AsyncClient, scene: Scene):
    await authed_client.post(ROTATIONS, json={
        "name": "One", "team_id": scene.team_id, "steps": [_step(scene.ayaka)],
    })

    listed = await authed_client.get(ROTATIONS, params={"team_id": scene.team_id})

    assert listed.status_code == 200
    assert [r["name"] for r in listed.json()["items"]] == ["One"]


async def test_a_team_scoped_page_reports_the_total_not_the_page_size(
    authed_client: AsyncClient, scene: Scene,
):
    """The envelope has to describe the page it returned.

    The first version ignored `offset`/`limit` for a team-scoped list and returned every
    row while declaring `limit=50` — a client paging through it would loop forever on
    page one and never learn there was more.
    """
    for n in range(3):
        await authed_client.post(ROTATIONS, json={
            "name": f"R{n}", "team_id": scene.team_id, "steps": [_step(scene.ayaka)],
        })

    page = (await authed_client.get(
        ROTATIONS, params={"team_id": scene.team_id, "offset": 1, "limit": 1},
    )).json()

    assert len(page["items"]) == 1
    assert page["total"] == 3
    assert (page["offset"], page["limit"]) == (1, 1)


async def test_steps_are_replaced_wholesale(authed_client: AsyncClient, scene: Scene):
    """A rotation is an ordered list, so "change step 3" and "insert before step 3" are the
    same edit to a client and different ones to a per-index API. The ambiguity would land on
    whoever wrote the UI."""
    created = (await authed_client.post(ROTATIONS, json={
        "name": "Draft", "team_id": scene.team_id,
        "steps": [_step(scene.ayaka, "burst"), _step(scene.ayaka, "skill")],
    })).json()

    patched = await authed_client.patch(f"{ROTATIONS}/{created['id']}", json={
        "steps": [_step(scene.ayaka, "attack", 3)],
    })

    assert [s["action"] for s in patched.json()["steps"]] == ["attack"]
    assert patched.json()["steps"][0]["repeat"] == 3


async def test_a_rotation_can_be_deleted(authed_client: AsyncClient, scene: Scene):
    created = (await authed_client.post(ROTATIONS, json={
        "name": "Doomed", "team_id": scene.team_id, "steps": [],
    })).json()

    assert (await authed_client.delete(f"{ROTATIONS}/{created['id']}")).status_code == 204
    assert (await authed_client.get(f"{ROTATIONS}/{created['id']}")).status_code == 404


# ── The write path refuses what cannot compile ───────────────────────────────


async def test_a_step_naming_someone_off_the_team_is_refused(
    authed_client: AsyncClient, scene: Scene,
):
    """Refused on **write**. A rotation that cannot compile is not a rotation, and letting
    one be saved moves the error to whenever someone next simulates."""
    response = await authed_client.post(ROTATIONS, json={
        "name": "Wrong", "team_id": scene.team_id,
        "steps": [_step(scene.ayaka), _step("10000030")],
    })

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "10000030" in detail
    assert "not on that team" in detail


async def test_the_refusal_says_who_is_available(authed_client: AsyncClient, scene: Scene):
    """A user who mistyped an id should be told what the team has, not only that they erred."""
    response = await authed_client.post(ROTATIONS, json={
        "name": "Wrong", "team_id": scene.team_id, "steps": [_step("10000030")],
    })

    assert scene.ayaka in response.json()["detail"]


async def test_a_patch_is_checked_too(authed_client: AsyncClient, scene: Scene):
    """The create path is not the only way steps get in."""
    created = (await authed_client.post(ROTATIONS, json={
        "name": "Fine", "team_id": scene.team_id, "steps": [_step(scene.ayaka)],
    })).json()

    patched = await authed_client.patch(f"{ROTATIONS}/{created['id']}", json={
        "steps": [_step("10000030")],
    })

    assert patched.status_code == 422


async def test_an_unknown_action_is_refused_by_the_schema(
    authed_client: AsyncClient, scene: Scene,
):
    response = await authed_client.post(ROTATIONS, json={
        "name": "Bad", "team_id": scene.team_id,
        "steps": [{"character": scene.ayaka, "action": "ultimate"}],
    })

    assert response.status_code == 422


async def test_an_empty_team_is_422_not_404(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """The team is there; it just holds nobody. Reporting that as 404 would send the user
    looking for a missing team instead of an empty one."""
    user, _ = authed_user
    empty = Team(owner_id=str(user.id), name="Nobody")
    db_session.add(empty)
    await db_session.flush()

    response = await authed_client.post(ROTATIONS, json={
        "name": "Hopeful", "team_id": str(empty.id), "steps": [_step("10000002")],
    })

    assert response.status_code == 422
    assert "no builds yet" in response.json()["detail"]


async def test_an_unknown_team_is_a_404(authed_client: AsyncClient, scene: Scene):
    response = await authed_client.post(ROTATIONS, json={
        "name": "Orphan", "team_id": "00000000-0000-0000-0000-000000000001", "steps": [],
    })

    assert response.status_code == 404


async def test_someone_elses_rotation_is_a_404(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
):
    """Owned by a real second account, not by nobody. A NULL owner would pass an
    owner-scoped filter for the wrong reason and prove nothing about tenancy."""
    from app.models.rotation import Rotation
    from app.models.user import User

    stranger = User(email="stranger@example.com", password_hash="not-a-hash")  # noqa: S106
    db_session.add(stranger)
    await db_session.flush()
    theirs = Rotation(
        owner_id=str(stranger.id), team_id=scene.team_id, name="Theirs", steps=[],
    )
    db_session.add(theirs)
    await db_session.flush()

    assert (await authed_client.get(f"{ROTATIONS}/{theirs.id}")).status_code == 404
    listed = await authed_client.get(ROTATIONS, params={"team_id": scene.team_id})
    assert [r["name"] for r in listed.json()["items"]] == []
    assert listed.json()["total"] == 0, "a leaked count is a leak"


# ── Compiling ─────────────────────────────────────────────────────────────────


async def test_a_rotation_compiles_to_a_gated_loop(authed_client: AsyncClient, scene: Scene):
    """Offered because a compiler nobody can inspect is a compiler nobody can check."""
    created = (await authed_client.post(ROTATIONS, json={
        "name": "Real", "team_id": scene.team_id,
        "steps": [_step(scene.barbara, "skill"), _step(scene.ayaka, "attack", 3)],
    })).json()

    config = (await authed_client.post(f"{ROTATIONS}/{created['id']}/compile")).json()["config"]

    assert config.startswith("active barbara;")
    assert "while 1 {" in config
    assert "if .kamisatoayaka.attack.ready { kamisatoayaka attack:3; }" in config
    assert " swap" not in config


async def test_an_empty_rotation_will_not_compile(authed_client: AsyncClient, scene: Scene):
    """Saving a draft is fine; simulating one is not. gcsim would accept it and simulate a
    character standing still."""
    created = (await authed_client.post(ROTATIONS, json={
        "name": "Empty", "team_id": scene.team_id, "steps": [],
    })).json()

    response = await authed_client.post(f"{ROTATIONS}/{created['id']}/compile")

    assert response.status_code == 422
    assert "nothing to do" in response.json()["detail"]


async def test_a_rotation_gone_stale_is_refused_not_repaired(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
):
    """OQ-R2, end to end.

    The rotation was valid when saved. Removing the character from the team afterwards makes
    it uncompilable — and the steps stay exactly as authored, because dropping them would
    delete the user's work to make a compile succeed.
    """
    created = (await authed_client.post(ROTATIONS, json={
        "name": "Was fine", "team_id": scene.team_id,
        "steps": [_step(scene.ayaka, "burst"), _step(scene.barbara, "skill")],
    })).json()

    team = await db_session.get(Team, scene.team_id)
    team.build2_id = None          # Barbara leaves the party
    await db_session.flush()

    response = await authed_client.post(f"{ROTATIONS}/{created['id']}/compile")

    assert response.status_code == 422
    assert "does not have" in response.json()["detail"]

    intact = await authed_client.get(f"{ROTATIONS}/{created['id']}")
    assert len(intact.json()["steps"]) == 2, "the authored steps must survive the refusal"
