"""T.5 — build → build → team → rotation → compiled config, in one flow.

**Deliberately end-to-end rather than five unit tests.** Every piece below already passes its
own tests, and has done since the rotation chunk — while the app was unusable, because nothing
connected them: there was no way to make a build, so no way to make a team, so the rotation
editor's empty state told users to do something with no page behind it.

What needs proving is therefore not that each endpoint works. It is that the output of each
one is accepted by the next: that a build id from `POST /builds` is a build id
`POST /teams` will take, that a team's roster is keyed the way a rotation step names
characters, and that the whole chain ends in a config gcsim would run.
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


@pytest.fixture
async def catalogue(db_session: AsyncSession) -> dict[str, str]:
    ayaka = Character(
        nanoka_id="10000002", name="Kamisato Ayaka", element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1001.0, base_atk=26.6, base_def=61.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    barbara = Character(
        nanoka_id="10000014", name="Barbara", element=Element.HYDRO,
        weapon_type=WeaponType.CATALYST, rarity=Rarity.FOUR_STAR,
        base_hp=821.0, base_atk=13.0, base_def=56.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    sword = Weapon(
        nanoka_id=11509, name="Mistsplitter Reforged", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=48.0, sub_stat_type=StatType.CRIT_DMG,
        sub_stat_base_value=0.096,
    )
    db_session.add_all([ayaka, barbara, sword])
    await db_session.flush()
    return {
        "ayaka": str(ayaka.id), "barbara": str(barbara.id), "sword": str(sword.id),
    }


async def test_a_user_can_get_from_nothing_to_a_compiled_rotation(
    authed_client: AsyncClient, db_session: AsyncSession, catalogue: dict[str, str],
):
    """The whole path, with each step's output feeding the next verbatim."""
    # 1. Two builds. The weapon is checked against the character's class (T.1).
    ayaka_build = await authed_client.post("/api/v1/builds", json={
        "character_id": catalogue["ayaka"], "weapon_id": catalogue["sword"],
        "talent_levels": {"elemental_burst": 9},
    })
    assert ayaka_build.status_code == 201, ayaka_build.text
    barbara_build = await authed_client.post("/api/v1/builds", json={
        "character_id": catalogue["barbara"],
    })
    assert barbara_build.status_code == 201, barbara_build.text

    # The row carries what a page draws it with, in the same response (T.2).
    assert ayaka_build.json()["character"]["name"] == "Kamisato Ayaka"
    assert ayaka_build.json()["weapon"]["name"] == "Mistsplitter Reforged"

    # 2. A team, from those build ids exactly as returned.
    team = await authed_client.post("/api/v1/teams", json={
        "name": "Freeze",
        "build1_id": ayaka_build.json()["id"],
        "build2_id": barbara_build.json()["id"],
    })
    assert team.status_code == 201, team.text
    team_id = team.json()["id"]

    # 3. The rotation editor's options, from that team.
    options = await authed_client.get("/api/v1/rotations/options")
    assert options.status_code == 200
    roster = next(t for t in options.json()["teams"] if t["id"] == team_id)
    by_name = {c["name"]: c["nanoka_id"] for c in roster["characters"]}
    assert set(by_name) == {"Kamisato Ayaka", "Barbara"}

    # 4. A rotation, whose steps name characters by the ids the roster just published.
    rotation = await authed_client.post("/api/v1/rotations", json={
        "name": "Melt opener", "team_id": team_id,
        "steps": [
            {"character": by_name["Barbara"], "action": "skill"},
            {"character": by_name["Kamisato Ayaka"], "action": "burst"},
            {"character": by_name["Kamisato Ayaka"], "action": "attack", "repeat": 3},
        ],
    })
    assert rotation.status_code == 201, rotation.text

    # 5. A config, gated and looped, naming gcsim's own keys.
    config = await authed_client.post(f"/api/v1/rotations/{rotation.json()['id']}/compile")
    assert config.status_code == 200, config.text
    text = config.json()["config"]
    assert text.startswith("active barbara;")
    assert "while 1 {" in text
    assert "if .kamisatoayaka.burst.ready { kamisatoayaka burst; }" in text
    assert "if .kamisatoayaka.attack.ready { kamisatoayaka attack:3; }" in text

    # 6. And a cache key that identifies this build running this rotation.
    key = await authed_client.post(
        f"/api/v1/rotations/{rotation.json()['id']}/context-key",
        json={"build_id": ayaka_build.json()["id"]},
    )
    assert key.status_code == 200, key.text
    assert key.json()["team"] == ["barbara", "kamisatoayaka"]
    assert len(key.json()["context_key"]) == 64


async def test_the_chain_refuses_at_the_first_step_that_cannot_hold(
    authed_client: AsyncClient, catalogue: dict[str, str],
):
    """The counterpart: each link refuses rather than passing something broken along.

    Without this the test above proves only that the happy path is wired. What makes the
    chain worth having is that a mistake stops at the step that can name it, rather than
    surfacing three steps later as a config gcsim rejects.
    """
    # A catalyst user cannot hold a sword — refused at the build, not at the simulation.
    mismatched = await authed_client.post("/api/v1/builds", json={
        "character_id": catalogue["barbara"], "weapon_id": catalogue["sword"],
    })
    assert mismatched.status_code == 422
    assert "Catalyst" in mismatched.json()["detail"]

    # A team cannot be built from a build that was never created.
    orphan = await authed_client.post("/api/v1/teams", json={
        "name": "Ghosts", "build1_id": "00000000-0000-0000-0000-000000000001",
    })
    assert orphan.status_code == 422

    # A rotation cannot name someone the team does not have.
    build = await authed_client.post("/api/v1/builds", json={
        "character_id": catalogue["ayaka"],
    })
    team = await authed_client.post("/api/v1/teams", json={
        "name": "Solo", "build1_id": build.json()["id"],
    })
    stranger = await authed_client.post("/api/v1/rotations", json={
        "name": "Wrong", "team_id": team.json()["id"],
        "steps": [{"character": "10000014", "action": "skill"}],
    })
    assert stranger.status_code == 422
    assert "not on that team" in stranger.json()["detail"]
