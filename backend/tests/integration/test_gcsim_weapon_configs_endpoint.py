"""W.6 — the gcsim tier's configs, over real catalogue rows.

`POST /compare-weapons` ranks on base ATK and the substat. **242 of 260 weapons carry a
passive and 5 are expressible in the Chunk F chain**, so that ordering can be wrong rather
than merely imprecise — which is what `unmodelled_passives` has been saying. This endpoint is
the tier that fixes it, by handing the browser configs gcsim can simulate.

The server emits configs and never simulates: `RESEARCH_gcsim_embed.md` §6 put gcsim in the
browser, and W.4 measured a full sword pool at ~96 s across four workers.

Most of what is tested here is the **negative space** — a rotation that does not act on this
build, a candidate gcsim cannot key, an unknown weapon — because each of those has a failure
mode that produces a plausible answer rather than an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from app.models.build import Build
from app.models.character import Character
from app.models.enums import Element, Rarity, StatType, WeaponType
from app.models.rotation import Rotation
from app.models.team import Team
from app.models.weapon import Weapon

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio


def _weapon(nanoka_id: int, name: str, base_atk: float) -> Weapon:
    return Weapon(
        nanoka_id=nanoka_id, name=name, weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=base_atk,
        base_atk_curve="GROW_CURVE_ATTACK_101",
        sub_stat_type=StatType.CRIT_DMG, sub_stat_base_value=0.096,
        sub_stat_curve="GROW_CURVE_CRITICAL_101",
        ascension_atk={str(p): {"fight_prop_base_attack": 31.1 * p} for p in range(1, 7)},
    )


def _character(nanoka_id: str, name: str) -> Character:
    return Character(
        nanoka_id=nanoka_id, name=name, element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1001.0, base_atk=26.6, base_def=61.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
        prop_curves={
            "FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_S5",
            "FIGHT_PROP_BASE_ATTACK": "GROW_CURVE_ATTACK_S5",
            "FIGHT_PROP_BASE_DEFENSE": "GROW_CURVE_HP_S5",
        },
        ascension_stats=[{"fight_prop_critical_hurt": 0.096}] * 6,
    )


@dataclass
class Scene:
    build_id: str
    rotation_id: str
    equipped_id: str
    candidate_id: str
    other_id: str
    foreign_rotation_id: str


@pytest.fixture
async def scene(db_session: AsyncSession, authed_user: tuple[User, str]) -> Scene:
    user, _ = authed_user
    ayaka = _character("10000002", "Kamisato Ayaka")
    # A second character, on a team the build's character is not in — the rotation that
    # never acts on this build.
    barbara = _character("10000014", "Barbara")
    equipped = _weapon(11101, "Dull Blade", 23.0)
    candidate = _weapon(11509, "Mistsplitter Reforged", 48.0)
    other = _weapon(11201, "The Flute", 33.0)
    db_session.add_all([ayaka, barbara, equipped, candidate, other])
    await db_session.flush()

    build = Build(
        owner_id=str(user.id), character_id=str(ayaka.id), weapon_id=str(equipped.id),
        character_level=90, ascension_phase=6, weapon_level=90, refinement=5,
    )
    barb_build = Build(owner_id=str(user.id), character_id=str(barbara.id))
    db_session.add_all([build, barb_build])
    await db_session.flush()

    team = Team(owner_id=str(user.id), name="Party", build1_id=str(build.id))
    foreign_team = Team(owner_id=str(user.id), name="Others", build1_id=str(barb_build.id))
    db_session.add_all([team, foreign_team])
    await db_session.flush()

    rotation = Rotation(
        owner_id=str(user.id), team_id=str(team.id), name="Burst",
        steps=[{"character": "10000002", "action": "burst", "repeat": 1}],
    )
    foreign = Rotation(
        owner_id=str(user.id), team_id=str(foreign_team.id), name="Not Ayaka's",
        steps=[{"character": "10000014", "action": "burst", "repeat": 1}],
    )
    db_session.add_all([rotation, foreign])
    await db_session.flush()

    ids = Scene(
        build_id=str(build.id), rotation_id=str(rotation.id),
        equipped_id=str(equipped.id), candidate_id=str(candidate.id),
        other_id=str(other.id), foreign_rotation_id=str(foreign.id),
    )
    db_session.expire_all()
    return ids


async def _ask(client: AsyncClient, scene: Scene, weapon_ids: list[str], **over):
    body = {"rotation_id": scene.rotation_id, "weapon_ids": weapon_ids, **over}
    return await client.post(
        f"/api/v1/builds/{scene.build_id}/compare-weapons/gcsim", json=body,
    )


async def test_it_returns_one_config_per_candidate_plus_the_worn_baseline(
    authed_client: AsyncClient, scene: Scene,
):
    response = await _ask(authed_client, scene, [scene.candidate_id, scene.other_id])

    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["weapon_id"] for c in body["candidates"]] == [
        scene.candidate_id, scene.other_id,
    ]
    assert body["equipped"]["weapon_id"] == scene.equipped_id
    assert body["refused"] == []


async def test_each_candidates_config_names_that_candidate(
    authed_client: AsyncClient, scene: Scene,
):
    """The no-op check, at the endpoint. Two candidates must not produce one config twice."""
    body = (await _ask(authed_client, scene, [scene.candidate_id, scene.other_id])).json()
    first, second = body["candidates"]

    assert 'weapon="mistsplitterreforged"' in first["config"]
    assert 'weapon="theflute"' in second["config"]
    assert first["config"] != second["config"]


async def test_the_baseline_wears_what_the_build_wears(
    authed_client: AsyncClient, scene: Scene,
):
    body = (await _ask(authed_client, scene, [scene.candidate_id])).json()

    assert 'weapon="dullblade"' in body["equipped"]["config"]
    assert "mistsplitter" not in body["equipped"]["config"]


async def test_the_config_carries_the_compiled_rotation_not_a_bare_action(
    authed_client: AsyncClient, scene: Scene,
):
    """The rotation as written: the steps, in order, with nothing wrapped around them.

    Both failures are silent and produce a plausible config with exactly one burst in it.
    """
    body = (await _ask(authed_client, scene, [scene.candidate_id])).json()
    config = body["candidates"][0]["config"]

    assert "while 1" not in config
    # Bursts, and only bursts, carry a gate: energy is the one readiness condition a rotation
    # cannot make true on its own, and an ungated one hangs gcsim outright.
    assert config.count("if .") == config.count(".burst.ready")


async def test_the_iteration_count_reaches_the_config(
    authed_client: AsyncClient, scene: Scene,
):
    body = (await _ask(authed_client, scene, [scene.candidate_id], iterations=25)).json()

    assert body["iterations"] == 25
    assert "iteration=25" in body["candidates"][0]["config"]


async def test_a_rotation_that_never_acts_on_this_build_is_refused(
    authed_client: AsyncClient, scene: Scene,
):
    """Otherwise every candidate scores the same team damage with this build standing still.

    That is a flat ranking, and a flat ranking reads as "these weapons are equivalent" rather
    than as the wrong question having been asked.
    """
    response = await authed_client.post(
        f"/api/v1/builds/{scene.build_id}/compare-weapons/gcsim",
        json={"rotation_id": scene.foreign_rotation_id, "weapon_ids": [scene.candidate_id]},
    )

    assert response.status_code == 422
    assert "does not include" in response.json()["detail"]


async def test_an_unknown_weapon_is_refused_by_name_never_dropped(
    authed_client: AsyncClient, scene: Scene,
):
    """A dropped candidate is a ranking missing a weapon the user asked about."""
    missing = "00000000-0000-0000-0000-000000000009"
    body = (await _ask(authed_client, scene, [scene.candidate_id, missing])).json()

    assert [c["weapon_id"] for c in body["candidates"]] == [scene.candidate_id]
    assert [r["weapon_id"] for r in body["refused"]] == [missing]
    assert "catalogue" in body["refused"][0]["reason"]


async def test_an_unknown_rotation_is_a_404(authed_client: AsyncClient, scene: Scene):
    response = await authed_client.post(
        f"/api/v1/builds/{scene.build_id}/compare-weapons/gcsim",
        json={
            "rotation_id": "00000000-0000-0000-0000-000000000009",
            "weapon_ids": [scene.candidate_id],
        },
    )

    assert response.status_code == 404


async def test_an_unknown_enemy_is_a_404_rather_than_the_default_target(
    authed_client: AsyncClient, scene: Scene,
):
    """Falling back to the default target would simulate a different scenario silently."""
    response = await _ask(
        authed_client, scene, [scene.candidate_id],
        enemy_id="00000000-0000-0000-0000-000000000009",
    )

    assert response.status_code == 404


async def test_at_least_one_candidate_is_required(authed_client: AsyncClient, scene: Scene):
    response = await _ask(authed_client, scene, [])

    assert response.status_code == 422
