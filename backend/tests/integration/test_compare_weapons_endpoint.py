"""D.5 — comparing weapons over real catalogue rows.

The number this endpoint produces is easy. The hard part is that it is a **precise-looking
ordering built on an incomplete model**: weapon passives are stored and not applied, and for
weapons the unmodelled part is often the entire reason to equip one. So most of what is
tested is whether the response makes that impossible to miss.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from app.models.artifact import Artifact, ArtifactSet, ArtifactSetAffix
from app.models.build import Build
from app.models.character import Character
from app.models.enums import ArtifactSlot, Element, Rarity, StatType, WeaponType
from app.models.weapon import Weapon, WeaponRefinement

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio

_MAINS = {
    ArtifactSlot.FLOWER: StatType.HP_FLAT,
    ArtifactSlot.PLUME: StatType.ATK_FLAT,
    ArtifactSlot.SANDS: StatType.ATK_PCT,
    ArtifactSlot.GOBLET: StatType.CRYO_DMG_BONUS,
    ArtifactSlot.CIRCLET: StatType.CRIT_DMG,
}

CRYO_BURST = {"multiplier": 2.0, "channel": "cryo", "scope": "burst"}
ENEMY = {"level": 90, "default_resistance": 0.1}

R1_TEXT = "Elemental DMG Bonus increased by 12%."
PASSIVE_TEXT = "Elemental DMG Bonus increased by 28%."


def _weapon(nanoka_id: int, name: str, base_atk: float) -> Weapon:
    return Weapon(
        nanoka_id=nanoka_id, name=name, weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=base_atk,
        base_atk_curve="GROW_CURVE_ATTACK_101",
        sub_stat_type=StatType.CRIT_DMG, sub_stat_base_value=0.096,
        sub_stat_curve="GROW_CURVE_CRITICAL_101",
        ascension_atk={
            str(phase): {"fight_prop_base_attack": 31.1 * phase} for phase in range(1, 7)
        },
    )


@dataclass
class Scene:
    build_id: str
    equipped_weapon_id: str
    strong_id: str
    plain_id: str


@pytest.fixture
async def scene(db_session: AsyncSession, authed_user: tuple[User, str]) -> Scene:
    user, _ = authed_user
    character = Character(
        nanoka_id="10000002", name="Ayaka", element=Element.CRYO,
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
    equipped = _weapon(11101, "Dull Blade", 23.0)
    # Carries a stored passive; nothing applies it, which is the whole point of the caveat.
    strong = _weapon(11509, "Mistsplitter Reforged", 48.0)
    plain = _weapon(11201, "Silver Sword", 33.0)
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db_session.add_all([character, equipped, strong, plain, artifact_set])
    await db_session.flush()
    db_session.add_all([
        # Two steps with different text. The build sits at R5, so a lookup that ignored
        # the refinement level would quote R1 and look entirely plausible doing it.
        WeaponRefinement(
            weapon_id=str(strong.id), level=1, name="Mistsplitter's Edge",
            description=R1_TEXT, param_list=[0.12],
        ),
        WeaponRefinement(
            weapon_id=str(strong.id), level=5, name="Mistsplitter's Edge",
            description=PASSIVE_TEXT, param_list=[0.28],
        ),
        ArtifactSetAffix(
            artifact_set_id=str(artifact_set.id), position=0, pieces_required=2,
            name="Blizzard Strayer", description="Cryo DMG Bonus +15%.",
            add_props=[{"prop_type": "FIGHT_PROP_ICE_ADD_HURT", "value": 0.15}],
        ),
    ])
    build = Build(
        owner_id=str(user.id), character_id=str(character.id), weapon_id=str(equipped.id),
        character_level=90, ascension_phase=6, weapon_level=90, refinement=5,
    )
    db_session.add(build)
    await db_session.flush()
    for slot, main in _MAINS.items():
        db_session.add(Artifact(
            owner_id=str(user.id), artifact_set_id=str(artifact_set.id),
            build_id=str(build.id), slot=slot, rarity=Rarity.FIVE_STAR, level=20,
            main_stat_type=main, main_stat_value=0.0, substats=[],
        ))
    await db_session.flush()
    return Scene(
        build_id=str(build.id), equipped_weapon_id=str(equipped.id),
        strong_id=str(strong.id), plain_id=str(plain.id),
    )


async def _compare(client: AsyncClient, build_id: str, weapon_ids: list[str]):
    return await client.post(
        f"/api/v1/builds/{build_id}/compare-weapons",
        json={"hit": CRYO_BURST, "enemy": ENEMY, "weapon_ids": weapon_ids},
    )


# ── The ranking ───────────────────────────────────────────────────────────────


async def test_candidates_are_scored_and_ranked(authed_client: AsyncClient, scene: Scene):
    response = await _compare(authed_client, scene.build_id, [scene.strong_id, scene.plain_id])
    assert response.status_code == 200, response.text
    body = response.json()

    assert next(w["weapon_id"] for w in body["weapons"]) == scene.strong_id
    assert body["equipped_weapon_id"] == scene.equipped_weapon_id
    assert all(w["damage"] > 0 for w in body["weapons"])


async def test_the_equipped_weapon_is_always_a_candidate(
    authed_client: AsyncClient, scene: Scene,
):
    """The baseline is what is worn. Without it every delta is against an arbitrary weapon
    while the response still looks exactly like a ranking."""
    body = (await _compare(authed_client, scene.build_id, [scene.strong_id])).json()

    equipped = next(w for w in body["weapons"] if w["is_equipped"])
    assert equipped["weapon_id"] == scene.equipped_weapon_id
    assert equipped["delta"] == 0.0


async def test_a_candidate_says_why_it_won_not_only_that_it_did(
    authed_client: AsyncClient, scene: Scene,
):
    body = (await _compare(authed_client, scene.build_id, [scene.strong_id])).json()
    winner = body["weapons"][0]

    atk = next(d for d in winner["differences"] if d["quantity"] == "base_atk")
    assert atk["delta"] > 0
    assert any("Mistsplitter" in p["note"] for p in atk["gained"])
    assert any("Dull Blade" in p["note"] for p in atk["lost"])


async def test_listing_the_equipped_weapon_explicitly_does_not_duplicate_it(
    authed_client: AsyncClient, scene: Scene,
):
    body = (await _compare(
        authed_client, scene.build_id, [scene.equipped_weapon_id, scene.strong_id],
    )).json()
    ids = [w["weapon_id"] for w in body["weapons"]]
    assert len(ids) == len(set(ids)) == 2


# ── What the ranking does not know ────────────────────────────────────────────


async def test_a_stored_but_unapplied_passive_is_named(
    authed_client: AsyncClient, scene: Scene,
):
    """`weapon_refinements` holds the text and nothing reads it (Chunk H)."""
    body = (await _compare(authed_client, scene.build_id, [scene.strong_id])).json()

    assert body["is_complete"] is False
    named = body["unmodelled_passives"]
    assert len(named) == 1
    assert named[0]["passive_name"] == "Mistsplitter's Edge"
    assert named[0]["text"] == PASSIVE_TEXT
    assert named[0]["text"] != R1_TEXT, "the build is R5; quoting R1 would look plausible"


async def test_the_caveat_says_the_order_can_be_wrong_not_merely_imprecise(
    authed_client: AsyncClient, scene: Scene,
):
    """For weapons the unmodelled part is frequently the reason to equip one."""
    body = (await _compare(authed_client, scene.build_id, [scene.strong_id])).json()
    assert "can be wrong" in body["caveat"]
    assert "Mistsplitter" in body["caveat"]


async def test_a_comparison_of_fully_modelled_weapons_says_so(
    authed_client: AsyncClient, scene: Scene,
):
    """Empty is a real answer, and a permanent doubt beside a complete comparison would
    teach a reader to ignore the field."""
    body = (await _compare(authed_client, scene.build_id, [scene.plain_id])).json()
    assert body["is_complete"] is True
    assert body["unmodelled_passives"] == []


async def test_even_a_complete_comparison_states_the_fixed_artifacts_limit(
    authed_client: AsyncClient, scene: Scene,
):
    """"Best in this build" is not "best" — a weapon wanting different pieces loses a
    comparison it would win with its own."""
    body = (await _compare(authed_client, scene.build_id, [scene.plain_id])).json()
    assert "held fixed" in body["caveat"]


# ── Refusals ──────────────────────────────────────────────────────────────────


async def test_an_unknown_weapon_is_refused(authed_client: AsyncClient, scene: Scene):
    response = await _compare(
        authed_client, scene.build_id, ["01a02987-dead-beef-0000-000000000000"],
    )
    assert response.status_code == 404
    assert "no such weapons" in response.json()["detail"]


async def test_an_empty_candidate_list_is_refused(authed_client: AsyncClient, scene: Scene):
    response = await _compare(authed_client, scene.build_id, [])
    assert response.status_code == 422


async def test_comparing_requires_auth(client: AsyncClient, scene: Scene):
    assert (await _compare(client, scene.build_id, [scene.strong_id])).status_code == 401
