"""R.4 — the rotation API.

The write path's job is to make a rotation that cannot compile impossible to save. A step
naming a character the team does not hold is refused **here**, not discovered later at
simulation time, far from the edit that caused it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from app.models.build import Build, EnemyProfile
from app.models.character import Character
from app.models.enums import Element, Rarity, StatType, WeaponType
from app.models.team import Team
from app.models.weapon import Weapon

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
    ayaka_build: str
    barbara_build: str


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
    return Scene(
        team_id=str(team.id), ayaka="10000002", barbara="10000014",
        ayaka_build=made["10000002"], barbara_build=made["10000014"],
    )


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


# ── What the editor is offered ───────────────────────────────────────────────


async def test_options_offer_exactly_the_actions_the_validator_accepts(
    authed_client: AsyncClient, scene: Scene,
):
    """The picker and the validator must not be able to disagree.

    Not "the offered list looks sensible" — every offered action is *posted*, and every
    action the endpoint withheld is posted too and must be refused. A UI list that drifted
    would tell a user their own selection was invalid.
    """
    from app.services.gcsim_keys import gcsim_actions

    offered = (await authed_client.get(f"{ROTATIONS}/options")).json()["actions"]
    assert offered, "an empty list would pass every assertion below vacuously"

    for action in offered:
        accepted = await authed_client.post(ROTATIONS, json={
            "name": f"try {action}", "team_id": scene.team_id,
            "steps": [_step(scene.ayaka, action)],
        })
        assert accepted.status_code == 201, f"offered but refused: {action}"

    for hidden in set(gcsim_actions()) - set(offered):
        refused = await authed_client.post(ROTATIONS, json={
            "name": f"try {hidden}", "team_id": scene.team_id,
            "steps": [_step(scene.ayaka, hidden)],
        })
        assert refused.status_code == 422, f"withheld but accepted: {hidden}"


async def test_options_carry_each_team_and_who_is_on_it(
    authed_client: AsyncClient, scene: Scene,
):
    teams = (await authed_client.get(f"{ROTATIONS}/options")).json()["teams"]

    assert [t["name"] for t in teams] == ["Party"]
    roster = teams[0]["characters"]
    assert {c["nanoka_id"] for c in roster} == {scene.ayaka, scene.barbara}
    assert {c["element"] for c in roster} == {"Cryo", "Hydro"}


async def test_options_publish_each_characters_burst_energy_cost(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
):
    """A burst that costs no energy publishes `None`, and that is the load-bearing case.

    Owner, 2026-08-31: *"Skirk has no burst energy cost, she has a unique burst effect.
    Something is very wrong there."* The client compares burst counts against a free-energy
    counterfactual, which moves the whole team's timing — so without this field it read a
    character who cannot be starved of energy as starved of energy.
    """
    from sqlalchemy import select

    from app.models.character import Character

    for nanoka_id, cost in ((scene.ayaka, 80), (scene.barbara, None)):
        character = (await db_session.execute(
            select(Character).where(Character.nanoka_id == nanoka_id),
        )).scalar_one()
        character.burst_energy_cost = cost
    await db_session.flush()

    teams = (await authed_client.get(f"{ROTATIONS}/options")).json()["teams"]
    roster = {c["nanoka_id"]: c["burst_energy_cost"] for c in teams[0]["characters"]}

    assert roster == {scene.ayaka: 80, scene.barbara: None}


async def test_options_offer_only_the_callers_own_teams(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
):
    from app.models.user import User

    stranger = User(email="other@example.com", password_hash="not-a-hash")  # noqa: S106
    db_session.add(stranger)
    await db_session.flush()
    db_session.add(Team(owner_id=str(stranger.id), name="Not yours"))
    await db_session.flush()

    teams = (await authed_client.get(f"{ROTATIONS}/options")).json()["teams"]

    assert [t["name"] for t in teams] == ["Party"]


async def test_the_options_path_is_not_read_as_a_rotation_id(
    authed_client: AsyncClient, scene: Scene,
):
    """`/options` is declared above `/{rotation_id}`. Below it, FastAPI would match this as
    a rotation whose id is the word "options" and return 404 — which looks like an empty
    editor rather than a routing mistake."""
    response = await authed_client.get(f"{ROTATIONS}/options")

    assert response.status_code == 200
    assert "actions" in response.json()


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


# ── The cache key — R.6 ───────────────────────────────────────────────────────


async def _key(client: AsyncClient, rotation_id: str, build_id: str) -> dict:
    response = await client.post(
        f"{ROTATIONS}/{rotation_id}/context-key", json={"build_id": build_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _rotation(client: AsyncClient, scene: Scene, steps: list[dict]) -> str:
    created = await client.post(ROTATIONS, json={
        "name": "keyed", "team_id": scene.team_id, "steps": steps,
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_one_step_different_is_a_different_key(
    authed_client: AsyncClient, scene: Scene,
):
    """R.6's first acceptance criterion.

    A cached run is only reusable if it simulated the same rotation. If a key survived a
    changed step, the cache would answer with a number computed for a rotation the user is
    no longer asking about — and it would look like a hit.
    """
    base = [_step(scene.ayaka, "burst"), _step(scene.barbara, "skill")]
    changed = [_step(scene.ayaka, "burst"), _step(scene.barbara, "attack")]

    first = await _key(authed_client, await _rotation(authed_client, scene, base),
                       scene.ayaka_build)
    second = await _key(authed_client, await _rotation(authed_client, scene, changed),
                        scene.ayaka_build)

    assert first["context_key"] != second["context_key"]


async def test_the_same_steps_reordered_is_a_different_key(
    authed_client: AsyncClient, scene: Scene,
):
    """R.6's second. Order *is* the rotation — bursting before a skill is not the same fight
    as skilling before a burst, and `context_key` hashes `rotation` as a sequence. This test
    is what proves the signature agrees with it rather than sorting on the way in."""
    forwards = [_step(scene.ayaka, "burst"), _step(scene.barbara, "skill")]
    backwards = [_step(scene.barbara, "skill"), _step(scene.ayaka, "burst")]

    first = await _key(authed_client, await _rotation(authed_client, scene, forwards),
                       scene.ayaka_build)
    second = await _key(authed_client, await _rotation(authed_client, scene, backwards),
                        scene.ayaka_build)

    assert first["context_key"] != second["context_key"]
    assert first["rotation"] != second["rotation"]
    assert sorted(first["rotation"]) == sorted(second["rotation"]), (
        "the same steps, so only their order may differ"
    )


async def test_repeat_is_part_of_the_key(authed_client: AsyncClient, scene: Scene):
    """`attack:3` is not `attack`, and a run of one is not a run of the other."""
    once = await _key(
        authed_client,
        await _rotation(authed_client, scene, [_step(scene.ayaka, "attack", 1)]),
        scene.ayaka_build,
    )
    thrice = await _key(
        authed_client,
        await _rotation(authed_client, scene, [_step(scene.ayaka, "attack", 3)]),
        scene.ayaka_build,
    )

    assert once["context_key"] != thrice["context_key"]


async def test_the_same_rotation_keys_the_same_twice(
    authed_client: AsyncClient, scene: Scene,
):
    """Guards the guard. Every assertion above is about keys *differing*, and all of them
    would pass if the key were simply random."""
    steps = [_step(scene.ayaka, "burst"), _step(scene.barbara, "skill")]
    rotation_id = await _rotation(authed_client, scene, steps)

    first = await _key(authed_client, rotation_id, scene.ayaka_build)
    second = await _key(authed_client, rotation_id, scene.ayaka_build)

    assert first["context_key"] == second["context_key"]


async def test_two_builds_on_one_team_key_differently(
    authed_client: AsyncClient, scene: Scene,
):
    """A key is per-character within a team: it hashes one character's own levels and weapon
    alongside the team it sits in. Ayaka's run is not Barbara's."""
    rotation_id = await _rotation(
        authed_client, scene, [_step(scene.ayaka, "burst"), _step(scene.barbara, "skill")],
    )

    ayaka = await _key(authed_client, rotation_id, scene.ayaka_build)
    barbara = await _key(authed_client, rotation_id, scene.barbara_build)

    assert ayaka["context_key"] != barbara["context_key"]
    assert ayaka["team"] == barbara["team"], "the same team, listed the same way"


async def test_the_key_reports_what_it_hashed(authed_client: AsyncClient, scene: Scene):
    """A hash is opaque by design, so the parts come back with it. A caller meeting an
    unexpected miss can see what was hashed rather than guess."""
    rotation_id = await _rotation(
        authed_client, scene, [_step(scene.ayaka, "attack", 3)],
    )

    body = await _key(authed_client, rotation_id, scene.ayaka_build)

    assert body["rotation"] == ["kamisatoayaka attack:3"]
    assert body["team"] == ["barbara", "kamisatoayaka"]
    assert body["target"] == {"lvl": 90, "resist": 0.1, "pos": "0,1"}
    assert len(body["context_key"]) == 64


async def test_the_signature_names_who_the_compiler_names(
    authed_client: AsyncClient, scene: Scene,
):
    """The key and the config gcsim actually receives must agree about who a step names.

    Two readings of the steps would eventually differ, and the difference would surface as a
    cached number for a rotation nobody ran. Both go through `_resolve`, and this checks the
    result rather than the intention.
    """
    rotation_id = await _rotation(
        authed_client, scene, [_step(scene.barbara, "skill"), _step(scene.ayaka, "burst")],
    )

    body = await _key(authed_client, rotation_id, scene.ayaka_build)
    config = (await authed_client.post(f"{ROTATIONS}/{rotation_id}/compile")).json()["config"]

    for entry in body["rotation"]:
        key, action = entry.split(" ")[0], entry.split(" ")[1].split(":")[0]
        assert f"{key} {action}" in config, f"{entry} is not in the config gcsim receives"


async def test_a_build_from_another_team_is_refused(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
    authed_user: tuple[User, str],
):
    user, _ = authed_user
    outsider = Build(owner_id=str(user.id), character_id=None)
    db_session.add(outsider)
    await db_session.flush()
    rotation_id = await _rotation(authed_client, scene, [_step(scene.ayaka, "burst")])

    response = await authed_client.post(
        f"{ROTATIONS}/{rotation_id}/context-key", json={"build_id": str(outsider.id)},
    )

    assert response.status_code == 422
    assert "not on this rotation's team" in response.json()["detail"]


async def test_a_stale_rotation_has_no_key(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
):
    """Refused, not silently keyed without the missing step. A key computed from a rotation
    that cannot run would name a cached result for a simulation nobody could perform."""
    rotation_id = await _rotation(
        authed_client, scene, [_step(scene.ayaka, "burst"), _step(scene.barbara, "skill")],
    )
    team = await db_session.get(Team, scene.team_id)
    team.build2_id = None
    await db_session.flush()

    response = await authed_client.post(
        f"{ROTATIONS}/{rotation_id}/context-key", json={"build_id": scene.ayaka_build},
    )

    assert response.status_code == 422
    assert "does not have" in response.json()["detail"]


async def test_an_enemy_supplies_the_target(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
):
    """Untested until the R.6 self-review, and broken: `enemy_nanoka_id` was typed as a
    string against an Integer column, so the branch reached asyncpg as text and raised."""
    dummy = EnemyProfile(
        nanoka_id=21010101, name="Hilichurl", level=93,
        base_hp=13.584, base_atk=1.0, base_def=1.0,
        physical_res=0.25, anemo_res=0.25, cryo_res=0.25, dendro_res=0.25,
        electro_res=0.25, geo_res=0.25, hydro_res=0.25, pyro_res=0.25,
    )
    db_session.add(dummy)
    await db_session.flush()
    rotation_id = await _rotation(authed_client, scene, [_step(scene.ayaka, "burst")])

    body = (await authed_client.post(
        f"{ROTATIONS}/{rotation_id}/context-key",
        json={"build_id": scene.ayaka_build, "enemy_nanoka_id": 21010101},
    )).json()

    assert body["target"] == {"lvl": 93, "resist": 0.25, "pos": "0,1"}


async def test_the_enemy_changes_the_key(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
):
    """A run against a level-93 quarter-resist target is not a run against the default."""
    db_session.add(EnemyProfile(
        nanoka_id=21010102, name="Tougher", level=100,
        base_hp=1.0, base_atk=1.0, base_def=1.0,
        physical_res=0.5, anemo_res=0.5, cryo_res=0.5, dendro_res=0.5,
        electro_res=0.5, geo_res=0.5, hydro_res=0.5, pyro_res=0.5,
    ))
    await db_session.flush()
    rotation_id = await _rotation(authed_client, scene, [_step(scene.ayaka, "burst")])

    default = await _key(authed_client, rotation_id, scene.ayaka_build)
    against = (await authed_client.post(
        f"{ROTATIONS}/{rotation_id}/context-key",
        json={"build_id": scene.ayaka_build, "enemy_nanoka_id": 21010102},
    )).json()

    assert default["context_key"] != against["context_key"]


async def test_an_unevenly_resistant_enemy_is_refused_not_averaged(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
):
    """gcsim's target takes one `resist=`, and an average is a number for an enemy that does
    not exist. The refusal already existed in the config renderer; sharing `target_fields`
    means the key inherits it rather than quietly hashing an averaged target."""
    db_session.add(EnemyProfile(
        nanoka_id=21010103, name="Lopsided", level=90,
        base_hp=1.0, base_atk=1.0, base_def=1.0,
        physical_res=0.1, anemo_res=0.9, cryo_res=0.1, dendro_res=0.1,
        electro_res=0.1, geo_res=0.1, hydro_res=0.1, pyro_res=0.1,
    ))
    await db_session.flush()
    rotation_id = await _rotation(authed_client, scene, [_step(scene.ayaka, "burst")])

    response = await authed_client.post(
        f"{ROTATIONS}/{rotation_id}/context-key",
        json={"build_id": scene.ayaka_build, "enemy_nanoka_id": 21010103},
    )

    assert response.status_code == 422
    assert "uneven resistances" in response.json()["detail"]


async def test_an_unknown_enemy_is_a_404(authed_client: AsyncClient, scene: Scene):
    rotation_id = await _rotation(authed_client, scene, [_step(scene.ayaka, "burst")])

    response = await authed_client.post(
        f"{ROTATIONS}/{rotation_id}/context-key",
        json={"build_id": scene.ayaka_build, "enemy_nanoka_id": 999999999},
    )

    assert response.status_code == 404


async def test_a_character_gcsim_does_not_implement_is_refused_with_its_reason(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    """A character released after the pin has no gcsim key. That is a refusal with a written
    explanation — most likely released after the pin, re-pin deliberately — and it escaped as
    a 500 in the first version of this handler, where nobody would ever have read it."""
    user, _ = authed_user
    unknown = Character(
        nanoka_id="99999999", name="Someone Unreleased", element=Element.PYRO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1000.0, base_atk=26.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    db_session.add(unknown)
    await db_session.flush()
    build = Build(owner_id=str(user.id), character_id=str(unknown.id))
    db_session.add(build)
    await db_session.flush()
    team = Team(owner_id=str(user.id), name="Unsimulatable", build1_id=str(build.id))
    db_session.add(team)
    await db_session.flush()
    created = await authed_client.post(ROTATIONS, json={
        "name": "keyed", "team_id": str(team.id), "steps": [_step("99999999", "burst")],
    })
    assert created.status_code == 201, created.text

    response = await authed_client.post(
        f"{ROTATIONS}/{created.json()['id']}/context-key",
        json={"build_id": str(build.id)},
    )

    assert response.status_code == 422, response.text
    assert "gcsim has no character key" in response.json()["detail"]


# ── importing a gcsim config ─────────────────────────────────────────────────


async def test_a_config_this_app_emitted_imports_back_to_its_steps(
    authed_client: AsyncClient, scene: Scene,
):
    """Tier 1 of the import, end to end: compile a rotation, import the text, get the steps.

    Round-tripping through the real endpoints rather than the two functions is the point —
    it proves the roster the importer maps keys against is the same one the compiler used.
    """
    created = (await authed_client.post(ROTATIONS, json={
        "name": "Round trip", "team_id": scene.team_id,
        "steps": [_step(scene.barbara, "skill"), _step(scene.ayaka, "attack", 3)],
    })).json()
    config = (await authed_client.post(f"{ROTATIONS}/{created['id']}/compile")).json()["config"]

    imported = await authed_client.post(
        f"{ROTATIONS}/import", json={"team_id": scene.team_id, "config": config},
    )

    assert imported.status_code == 200
    assert [(s["character"], s["action"], s["repeat"]) for s in imported.json()["steps"]] == [
        (scene.barbara, "skill", 1),
        (scene.ayaka, "attack", 3),
    ]


async def test_importing_creates_nothing(authed_client: AsyncClient, scene: Scene):
    """`import` is a preview. Saving it is a separate, deliberate act — a config that parses
    is not automatically a rotation someone wants, and the undo for an unasked-for write is a
    delete."""
    before = (await authed_client.get(ROTATIONS, params={"team_id": scene.team_id})).json()
    config = (
        "active barbara;\n"
        "while 1 {\n"
        "    if .barbara.skill.ready { barbara skill; }\n"
        "}\n"
    )

    await authed_client.post(
        f"{ROTATIONS}/import", json={"team_id": scene.team_id, "config": config},
    )

    after = (await authed_client.get(ROTATIONS, params={"team_id": scene.team_id})).json()
    assert after["total"] == before["total"]


async def test_a_config_using_gcsim_features_we_cannot_express_is_refused(
    authed_client: AsyncClient, scene: Scene,
):
    """**The refusal that is the whole feature.** Importing this without the energy guard
    would produce a rotation that looks like the author's and bursts on a different schedule
    — same name, different number, no way for the user to tell."""
    config = (
        "active barbara;\n"
        "while 1 {\n"
        "    if .barbara.energy > 40 { barbara burst; }\n"
        "    wait 30;\n"
        "}\n"
    )

    response = await authed_client.post(
        f"{ROTATIONS}/import", json={"team_id": scene.team_id, "config": config},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "energy" in detail
    assert "wait" in detail


async def test_a_config_naming_someone_off_the_team_is_refused_by_name(
    authed_client: AsyncClient, scene: Scene,
):
    """A rotation written for another team is the ordinary case for a shared config, and the
    message has to be specific enough to act on."""
    config = (
        "active barbara;\n"
        "while 1 {\n"
        "    if .bennett.burst.ready { bennett burst; }\n"
        "}\n"
    )

    response = await authed_client.post(
        f"{ROTATIONS}/import", json={"team_id": scene.team_id, "config": config},
    )

    assert response.status_code == 422
    assert "bennett" in response.json()["detail"]


# ── previewing what unsaved steps compile to (B.5) ───────────────────────────


async def test_preview_compiles_steps_that_were_never_saved(
    authed_client: AsyncClient, scene: Scene,
):
    """The whole reason this endpoint exists.

    `POST /{id}/compile` reads the **stored** rotation, so an editor showing a live preview of
    unsaved work would either show the saved version — worse than no preview, because it looks
    current — or grow a second compiler in TypeScript. The second compiler is the hazard: the
    readiness gates are what stop gcsim's two silent failures, and two implementations of them
    would eventually disagree about a config nobody reads.
    """
    previewed = await authed_client.post(f"{ROTATIONS}/preview", json={
        "team_id": scene.team_id,
        "steps": [_step(scene.ayaka, "burst"), _step(scene.barbara, "skill")],
    })

    assert previewed.status_code == 200, previewed.text
    config = previewed.json()["config"]
    assert "while 1" in config
    assert ".ready" in config


async def test_preview_saves_nothing(authed_client: AsyncClient, scene: Scene):
    """A POST because the steps are a body, not because it changes anything."""
    await authed_client.post(f"{ROTATIONS}/preview", json={
        "team_id": scene.team_id, "steps": [_step(scene.ayaka)],
    })

    listed = await authed_client.get(ROTATIONS)
    assert listed.json()["items"] == []


async def test_preview_refuses_exactly_what_a_save_refuses(
    authed_client: AsyncClient, scene: Scene,
):
    """A preview that accepted a step the save would refuse is a preview of a rotation that
    cannot exist — which is a worse lie than showing nothing."""
    refused = await authed_client.post(f"{ROTATIONS}/preview", json={
        "team_id": scene.team_id, "steps": [_step("10000037", "burst")],
    })

    assert refused.status_code == 422
    assert "10000037" in refused.text


async def test_preview_of_an_empty_rotation_is_refused_rather_than_empty(
    authed_client: AsyncClient, scene: Scene,
):
    """`compile_rotation` refuses an empty action block, because gcsim would accept a config
    with nothing in it and report a plausible zero."""
    previewed = await authed_client.post(f"{ROTATIONS}/preview", json={
        "team_id": scene.team_id, "steps": [],
    })

    assert previewed.status_code == 422


# ── the runnable preview (T.8) ───────────────────────────────────────────────


async def test_the_default_preview_is_the_action_block_only(
    authed_client: AsyncClient, scene: Scene,
):
    """What an author reads: the loop and the gates, and nothing else.

    This is what `/{id}/compile` has always returned and what "Show gcsim config" shows.
    """
    response = await authed_client.post(f"{ROTATIONS}/preview", json={
        "team_id": scene.team_id, "steps": [_step(scene.ayaka)],
    })

    config = response.json()["config"]
    assert config.startswith("active ")
    assert "options" not in config


async def test_a_runnable_preview_is_a_config_gcsim_could_run(
    authed_client: AsyncClient, db_session: AsyncSession, scene: Scene,
):
    """**The action block is not a config**, and "Run once" was handed one that could not run.

    No `options`, no character lines, no weapon, no target — `sample()` refuses it. The block
    is the author's view; this is the simulator's, and both come from the same compile so they
    cannot describe different rotations.
    """
    # Both builds need a weapon: gcsim cannot simulate a character holding nothing, and the
    # endpoint refuses before it gets there — which the test below is about.
    sword = Weapon(
        nanoka_id=11509, name="Mistsplitter Reforged", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=48.0, sub_stat_type=StatType.CRIT_DMG,
        sub_stat_base_value=0.096,
    )
    db_session.add(sword)
    await db_session.flush()
    for build_id in (scene.ayaka_build, scene.barbara_build):
        await authed_client.patch(f"/api/v1/builds/{build_id}", json={
            "weapon_id": str(sword.id),
        })

    response = await authed_client.post(f"{ROTATIONS}/preview", json={
        "team_id": scene.team_id, "steps": [_step(scene.ayaka)], "runnable": True,
    })

    config = response.json()["config"]
    assert config.startswith("options ")
    assert "target lvl=" in config
    # The block is inside it, verbatim — one compile, not two.
    assert "while 1 {" in config


async def test_a_runnable_preview_names_the_builds_with_no_weapon(
    authed_client: AsyncClient, scene: Scene,
):
    """gcsim's own answer is `unrecognized weapon  for character kamisatoayaka`.

    True, and arriving from a simulator the user did not know they had started. Naming the
    build is the difference between "something went wrong" and "go and equip Ayaka" — and the
    scene's builds carry no weapon, which is why this is the case that runs here.
    """
    response = await authed_client.post(f"{ROTATIONS}/preview", json={
        "team_id": scene.team_id, "steps": [_step(scene.ayaka)], "runnable": True,
    })

    assert response.status_code == 422
    assert "Kamisato Ayaka" in response.json()["detail"]
    assert "no weapon" in response.json()["detail"]
