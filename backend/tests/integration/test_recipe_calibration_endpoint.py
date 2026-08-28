"""R.3 — the configs a damage recipe is calibrated from.

One calibration per **4-piece state**. `RESEARCH_conditional_sets.md`: every 4-piece bonus in
the game is conditional, so only a run with the set equipped can hold it — and R.2 measured
the cost of not doing so at **15-25 % understated**.

Two things are easy to get wrong and both are tested here rather than left to the browser:
the calibration must carry **no stat but ER**, because anything else would be counted twice
once a candidate's own stats are applied; and the probe must move **exactly one** stat, or
`resolveConversions` cannot tell which one a frozen term came from.
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


async def _calibrate(client: AsyncClient, scene: Scene, **over):
    body = {"rotation_id": scene.rotation_id, **over}
    return await client.post(f"/api/v1/builds/{scene.build_id}/calibrate", json=body)


async def test_it_emits_a_baseline_and_a_probe(authed_client: AsyncClient, scene: Scene):
    response = await _calibrate(authed_client, scene)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["baseline"]
    assert body["probe"]
    assert body["baseline"] != body["probe"]


async def test_the_baseline_carries_no_stat_but_energy_recharge(
    authed_client: AsyncClient, scene: Scene,
):
    """Anything else would be counted twice once a candidate's own stats are applied."""
    body = (await _calibrate(authed_client, scene)).json()
    stats_lines = [ln for ln in body["baseline"].splitlines() if "add stats" in ln]

    assert len(stats_lines) == 1
    assert "er=0.3" in stats_lines[0]
    assert "atk%" not in stats_lines[0]


async def test_the_probe_moves_exactly_one_stat(authed_client: AsyncClient, scene: Scene):
    """`resolveConversions` compares the two runs. A probe that moved two stats by the same
    factor could not say which a frozen term came from, and the recipe would report it
    unresolved rather than guess."""
    body = (await _calibrate(authed_client, scene)).json()
    baseline = next(ln for ln in body["baseline"].splitlines() if "add stats" in ln)
    probe = next(ln for ln in body["probe"].splitlines() if "add stats" in ln)

    assert probe == baseline.replace(";", " def%=0.5;")


async def test_the_energy_recharge_is_not_zero_by_default(
    authed_client: AsyncClient, scene: Scene,
):
    """ER is an artifact stat, so a zero-ER calibration lands on a different burst count —
    measured at 2 against a real candidate's 3."""
    body = (await _calibrate(authed_client, scene)).json()

    assert body["energy_recharge"] == 0.30


async def test_it_equips_the_requested_four_piece_set(
    authed_client: AsyncClient, scene: Scene, db_session: AsyncSession,
):
    """The whole reason a calibration exists: only a run with the set equipped holds its
    conditional 4-piece, and every 4-piece in the game is conditional."""
    from app.models.artifact import ArtifactSet

    blizzard = ArtifactSet(
        nanoka_id=15014, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add(blizzard)
    await db_session.flush()
    set_id = str(blizzard.id)
    db_session.expire_all()

    body = (await _calibrate(authed_client, scene, artifact_set_id=set_id)).json()

    assert 'add set="blizzardstrayer" count=4;' in body["baseline"]
    assert body["artifact_set_id"] == set_id


async def test_a_set_gcsim_does_not_implement_is_refused(
    authed_client: AsyncClient, scene: Scene, db_session: AsyncSession,
):
    """Refused rather than dropped. Calibrating without the set would produce a recipe that
    silently understates it by its whole 4-piece bonus — 15-25 % per R.2."""
    from app.models.artifact import ArtifactSet

    unknown = ArtifactSet(
        nanoka_id=99999, name="Not A Real Set", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add(unknown)
    await db_session.flush()
    set_id = str(unknown.id)
    db_session.expire_all()

    response = await _calibrate(authed_client, scene, artifact_set_id=set_id)

    assert response.status_code == 422
    assert "gcsim does not implement" in response.json()["detail"]


async def test_no_set_is_a_valid_calibration(authed_client: AsyncClient, scene: Scene):
    """The state a combination reaching no 4-piece is scored against."""
    body = (await _calibrate(authed_client, scene, artifact_set_id=None)).json()

    assert "add set=" not in body["baseline"]


async def test_an_unknown_set_is_a_404(authed_client: AsyncClient, scene: Scene):
    response = await _calibrate(
        authed_client, scene, artifact_set_id="00000000-0000-0000-0000-000000000009",
    )

    assert response.status_code == 404


async def test_a_rotation_that_never_acts_on_this_build_is_refused(
    authed_client: AsyncClient, scene: Scene,
):
    """A calibration against it would describe a rotation this build does not perform."""
    response = await authed_client.post(
        f"/api/v1/builds/{scene.build_id}/calibrate",
        json={"rotation_id": scene.foreign_rotation_id},
    )

    assert response.status_code == 422
    assert "does not include" in response.json()["detail"]


async def test_an_unknown_rotation_is_a_404(authed_client: AsyncClient, scene: Scene):
    response = await authed_client.post(
        f"/api/v1/builds/{scene.build_id}/calibrate",
        json={"rotation_id": "00000000-0000-0000-0000-000000000009"},
    )

    assert response.status_code == 404


async def test_the_config_carries_the_compiled_rotation(
    authed_client: AsyncClient, scene: Scene,
):
    """`while 1` and a `.ready` gate, or gcsim runs the rotation once or deadlocks."""
    body = (await _calibrate(authed_client, scene)).json()

    assert "while 1" in body["baseline"]
    assert ".ready" in body["baseline"]


async def _named_set(db_session: AsyncSession, nanoka_id: int, name: str) -> str:
    """A catalogue set, returned by the id `/calibrate` resolves."""
    from app.models.artifact import ArtifactSet

    row = ArtifactSet(
        nanoka_id=nanoka_id, name=name, piece_thresholds=[2, 4], available_ranks=[4, 5],
    )
    db_session.add(row)
    await db_session.flush()
    return str(row.id)


async def test_a_two_plus_two_equips_both_sets_at_two_pieces(
    authed_client: AsyncClient, scene: Scene, db_session: AsyncSession,
):
    """B.3, owner ruling 1.

    Nine of the sixty 2-piece bonuses are conditional and six are ability-scoped — Noblesse
    Oblige's burst +20 %. A flat stat pool cannot say *only on burst hits*, so the set is
    equipped and gcsim applies the real bonus. The alternative was deriving it from
    `param_list`, which `docs/DECISIONS.md` rejected for weapon passives on the same grounds.
    """
    noblesse = await _named_set(db_session, 15007, "Noblesse Oblige")
    gladiator = await _named_set(db_session, 15001, "Gladiator's Finale")
    db_session.expire_all()

    body = (await _calibrate(
        authed_client, scene, two_piece_set_ids=[noblesse, gladiator],
    )).json()

    assert 'add set="noblesseoblige" count=2;' in body["baseline"]
    assert 'add set="gladiatorsfinale" count=2;' in body["baseline"]
    assert "count=4" not in body["baseline"]
    # Echoed for the cache key: a pair keyed by only its first set would serve one pair's
    # recipe for another's.
    assert body["two_piece_set_ids"] == [noblesse, gladiator]


async def test_a_four_piece_and_a_two_plus_two_together_are_refused(
    authed_client: AsyncClient, scene: Scene, db_session: AsyncSession,
):
    """Five slots cannot hold both, and emitting it would describe a build that cannot exist."""
    four = await _named_set(db_session, 15014, "Blizzard Strayer")
    two = await _named_set(db_session, 15007, "Noblesse Oblige")
    db_session.expire_all()

    response = await _calibrate(
        authed_client, scene, artifact_set_id=four, two_piece_set_ids=[two],
    )

    assert response.status_code == 422
    assert "4-piece" in response.json()["detail"]


async def test_more_than_two_two_piece_sets_is_refused_by_the_schema(
    authed_client: AsyncClient, scene: Scene, db_session: AsyncSession,
):
    """Three 2-piece sets need six slots. Refused at the schema, before any set is resolved."""
    ids = [
        await _named_set(db_session, 15001, "Gladiator's Finale"),
        await _named_set(db_session, 15007, "Noblesse Oblige"),
        await _named_set(db_session, 15014, "Blizzard Strayer"),
    ]
    db_session.expire_all()

    response = await _calibrate(authed_client, scene, two_piece_set_ids=ids)

    assert response.status_code == 422


async def test_a_two_piece_set_gcsim_does_not_implement_is_refused(
    authed_client: AsyncClient, scene: Scene, db_session: AsyncSession,
):
    """Same rule as the 4-piece: refused rather than dropped, because a recipe missing the
    bonus the caller asked for understates itself and looks ordinary."""
    unknown = await _named_set(db_session, 99998, "Also Not A Real Set")
    db_session.expire_all()

    response = await _calibrate(authed_client, scene, two_piece_set_ids=[unknown])

    assert response.status_code == 422
    assert "gcsim does not implement" in response.json()["detail"]
