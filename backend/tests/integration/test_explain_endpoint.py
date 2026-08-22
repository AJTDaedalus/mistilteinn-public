"""D.4 — the explanation endpoint, over real rows.

An explanation reads like prose, which is exactly why it is the most dangerous place in this
codebase for a number with nothing behind it: a reader's guard is down. So these tests are
mostly about what the endpoint **refuses to say**.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.models.artifact import Artifact, ArtifactSet, ArtifactSetAffix
from app.models.build import Build
from app.models.character import Character
from app.models.enums import ArtifactSlot, Element, Rarity, StatType, WeaponType
from app.models.weapon import Weapon
from app.services import artifact_optimizer
from app.services.gcsim_keys import pinned_commit
from app.services.sim_context import context_key

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

#: The affix text the catalogue publishes, which the explanation must quote rather than
#: compose. Two-piece only, on purpose: the four-piece has none, so one set effect is cited
#: and the other lands in `uncited` within a single response.
TWO_PIECE_TEXT = "Cryo DMG Bonus +15%."


async def _catalogue(db: AsyncSession) -> tuple[Character, Weapon, ArtifactSet]:
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
    weapon = Weapon(
        nanoka_id=11509, name="Mistsplitter", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=48.0, base_atk_curve="GROW_CURVE_ATTACK_101",
        sub_stat_type=StatType.CRIT_DMG, sub_stat_base_value=0.096,
        sub_stat_curve="GROW_CURVE_CRITICAL_101",
        ascension_atk={
            str(phase): {"fight_prop_base_attack": 31.1 * phase} for phase in range(1, 7)
        },
    )
    artifact_set = ArtifactSet(
        nanoka_id=15025, name="Blizzard Strayer", piece_thresholds=[2, 4],
        available_ranks=[4, 5],
    )
    db.add_all([character, weapon, artifact_set])
    await db.flush()
    db.add(ArtifactSetAffix(
        artifact_set_id=str(artifact_set.id), position=0, pieces_required=2,
        name="Blizzard Strayer", description=TWO_PIECE_TEXT,
        add_props=[{"prop_type": "FIGHT_PROP_ICE_ADD_HURT", "value": 0.15}],
    ))
    await db.flush()
    return character, weapon, artifact_set


async def _build(
    db: AsyncSession, user: User, character: Character, weapon: Weapon, sets: ArtifactSet,
) -> tuple[Build, Artifact]:
    build = Build(
        owner_id=str(user.id), character_id=str(character.id), weapon_id=str(weapon.id),
        character_level=90, ascension_phase=6, weapon_level=90,
    )
    db.add(build)
    await db.flush()
    for slot, main in _MAINS.items():
        db.add(Artifact(
            owner_id=str(user.id), artifact_set_id=str(sets.id), build_id=str(build.id),
            slot=slot, rarity=Rarity.FIVE_STAR, level=20, main_stat_type=main,
            main_stat_value=0.0, substats=[],
        ))
    spare = Artifact(
        owner_id=str(user.id), artifact_set_id=str(sets.id), slot=ArtifactSlot.CIRCLET,
        rarity=Rarity.FIVE_STAR, level=20, main_stat_type=StatType.CRIT_DMG,
        main_stat_value=0.0,
        substats=[{"stat": "FIGHT_PROP_CRITICAL_HURT", "value": 0.35}],
    )
    db.add(spare)
    await db.flush()
    return build, spare


async def _explain(client: AsyncClient, build_id: str, **body):
    return await client.post(
        f"/api/v1/builds/{build_id}/explain",
        json={"hit": CRYO_BURST, "enemy": ENEMY, **body},
    )


@dataclass
class Scene:
    """The ids the tests need, read while the session still has them.

    Ids rather than ORM rows: `Build.artifacts` is `lazy="raise_on_sql"` (G.11), so touching
    it from a test after the request has run raises — which is the guard working, and the
    reason this fixture resolves everything up front.
    """

    build_id: str
    equipped_ids: list[str]
    worn_circlet_id: str
    spare_id: str


@pytest.fixture
async def scene(db_session: AsyncSession, authed_user: tuple[User, str]) -> Scene:
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build, spare = await _build(db_session, user, character, weapon, sets)
    rows = (await db_session.execute(
        select(Artifact).where(Artifact.build_id == str(build.id))
    )).scalars().all()
    return Scene(
        build_id=str(build.id),
        equipped_ids=[str(r.id) for r in rows],
        worn_circlet_id=next(str(r.id) for r in rows if r.slot == ArtifactSlot.CIRCLET),
        spare_id=str(spare.id),
    )


# ── The account ───────────────────────────────────────────────────────────────


async def test_a_build_accounts_for_itself(authed_client: AsyncClient, scene: Scene):
    response = await _explain(authed_client, scene.build_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["damage"] > 0
    quantities = {s["quantity"] for s in body["stats"]}
    assert {"base_atk", "crit_dmg"} <= quantities
    assert all(s["parts"] for s in body["stats"]), "no quantity is listed with no parts"


async def test_every_part_names_where_it_came_from(authed_client: AsyncClient, scene: Scene):
    body = (await _explain(authed_client, scene.build_id)).json()
    for account in body["stats"]:
        for part in account["parts"]:
            assert part["source"], f"{account['quantity']} has an unattributed part"


async def test_the_sum_is_labelled_sum_of_parts_not_total(
    authed_client: AsyncClient, scene: Scene,
):
    """`base * (1 + pct) + flat` is not the sum of its parts, and the field says so."""
    account = (await _explain(authed_client, scene.build_id)).json()["stats"][0]
    assert "sum_of_parts" in account
    assert "total" not in account


# ── The catalogue's own words ─────────────────────────────────────────────────


async def test_a_set_effect_quotes_the_catalogue(authed_client: AsyncClient, scene: Scene):
    body = (await _explain(authed_client, scene.build_id)).json()
    cited = [e for e in body["set_effects"] if e["description"] is not None]
    assert cited, "the 2pc has published text and must be quoted"
    assert cited[0]["description"] == TWO_PIECE_TEXT


async def test_an_effect_without_catalogue_text_is_uncited_not_invented(
    authed_client: AsyncClient, scene,
):
    """The 4pc has no affix row. Silence plus a note, never a fluent paraphrase."""
    body = (await _explain(authed_client, scene.build_id)).json()
    silent = [e for e in body["set_effects"] if e["description"] is None]
    if silent:
        assert body["uncited"], "a silent set effect must appear in uncited"
        assert any(e["note"] in u["what"] for e in silent for u in body["uncited"])


async def test_the_join_survives_a_change_to_the_note_format(
    authed_client: AsyncClient, scene: Scene, monkeypatch: pytest.MonkeyPatch,
):
    """Both sides must call `set_bonus_note`, not merely agree with it today.

    The first version of this test asserted the resulting *string*, which a hand-built key
    on the reader side passes — verified by injecting exactly that, and watching all twelve
    tests stay green. Agreeing today is not the property worth having; **not being able to
    drift** is.

    So the format is changed at its one definition. A reader that builds the key itself now
    joins nothing and the description comes back null.
    """
    monkeypatch.setattr(
        artifact_optimizer,
        "set_bonus_note",
        lambda set_id, set_name, pieces: f"~{set_name}~{pieces}~{set_id}~",
    )
    body = (await _explain(authed_client, scene.build_id)).json()
    cited = [e for e in body["set_effects"] if e["description"] is not None]
    assert cited, "the writer and the reader no longer agree on the note format"
    assert cited[0]["note"].startswith("~"), "the patched format really was used"


# ── The comparison ────────────────────────────────────────────────────────────


async def test_swapping_a_piece_explains_what_changed(authed_client: AsyncClient, scene: Scene):
    proposal = [
        *(aid for aid in scene.equipped_ids if aid != scene.worn_circlet_id),
        scene.spare_id,
    ]

    body = (await _explain(authed_client, scene.build_id, artifact_ids=proposal)).json()
    assert body["differences"] is not None
    assert body["equipped_damage"] is not None
    crit = next(d for d in body["differences"] if d["quantity"] == "crit_dmg")
    assert crit["delta"] == pytest.approx(0.35)
    assert crit["gained"], "the piece that arrived is named"


async def test_explaining_the_equipped_build_compares_against_nothing(
    authed_client: AsyncClient, scene,
):
    """"Why is this better" needs a *this*. With no proposal there is nothing to be better
    than, and inventing a comparison against itself would report every quantity unchanged as
    though that were a finding."""
    body = (await _explain(authed_client, scene.build_id)).json()
    assert body["differences"] is None
    assert body["equipped_damage"] is None


async def test_an_artifact_from_another_account_is_refused(
    authed_client: AsyncClient, scene,
):
    """Four pieces explained as five is wrong in the way that is hardest to see."""
    response = await _explain(
        authed_client,
        scene.build_id,
        artifact_ids=[
            *scene.equipped_ids[:4],
            "01a02987-dead-beef-0000-000000000000",
        ],
    )
    assert response.status_code == 404
    assert "not in this account" in response.json()["detail"]


async def test_the_same_piece_twice_is_refused(authed_client: AsyncClient, scene: Scene):
    """Nothing downstream checks this. `build_combination_log` iterates what it is handed,
    so a duplicated goblet counts twice and inflates a build the user cannot wear."""
    duplicated = [*scene.equipped_ids[:4], scene.equipped_ids[0]]
    response = await _explain(authed_client, scene.build_id, artifact_ids=duplicated)
    assert response.status_code == 422
    assert "more than once" in response.json()["detail"]


async def test_a_short_proposal_is_refused(authed_client: AsyncClient, scene: Scene):
    """Three pieces scored against a five-piece build reports two slots of "losses" as
    though the user had chosen them."""
    response = await _explain(
        authed_client, scene.build_id, artifact_ids=scene.equipped_ids[:3],
    )
    assert response.status_code == 422
    assert "one per slot" in response.json()["detail"]


# ── The simulation, joined in ─────────────────────────────────────────────────


async def test_a_retrieved_run_arrives_with_its_caveat(authed_client: AsyncClient, scene: Scene):
    key = context_key(
        character_key="kamisatoayaka", weapon_key="mistsplitterreforged",
        character_level=90, constellation=0, weapon_level=90, refinement=1,
        talent_levels={"elemental_burst": 9}, rotation=["burst"],
        target={"lvl": 90}, gcsim_pin=pinned_commit(),
    )
    for bucket, dps in ((180, 100.0), (185, 113.0)):
        stored = await authed_client.post(
            "/api/v1/sim-runs", params={"gcsim_pin": pinned_commit()},
            json={
                "context_key": key, "er_bucket": bucket,
                "result": {"statistics": {"iterations": 50, "dps": {"mean": dps, "sd": 0.0}}},
            },
        )
        assert stored.status_code in (200, 201), stored.text

    body = (await _explain(
        authed_client, scene.build_id, context_key=key, energy_recharge=1.82,
    )).json()
    assert body["simulation"]["is_exact_bucket"] is True
    assert body["simulation"]["divergence_pct"] == pytest.approx(13.0)
    assert "lower bound" in body["simulation"]["caveat"]


async def test_half_the_retrieval_pair_is_refused(authed_client: AsyncClient, scene: Scene):
    """A key with no ER cannot pick a bucket; an ER with no key has no context."""
    response = await _explain(authed_client, scene.build_id, energy_recharge=1.82)
    assert response.status_code == 422
    assert "go together" in response.json()["detail"]


async def test_no_retrieval_asked_for_means_no_simulation_note(
    authed_client: AsyncClient, scene,
):
    assert (await _explain(authed_client, scene.build_id)).json()["simulation"] is None


async def test_explaining_requires_auth(client: AsyncClient, scene: Scene):
    assert (await _explain(client, scene.build_id)).status_code == 401
