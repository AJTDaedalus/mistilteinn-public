"""Math-fallback P1, tasks 6 and 7 — `/formula/set-effects` and `/formula/resonance`.

The unit tests hold the curation and the tally rules. These hold the wiring: that the route
resolves against the **seeded** `param_list` (not the pin), reports a changed list as stale,
and reads each member's element from the catalogue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.artifact import ArtifactSet, ArtifactSetAffix
from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

_NONE = {"prop_type": "FIGHT_PROP_NONE", "value": 0}


async def _crimson_witch(db: AsyncSession, four_piece_params: list[float]) -> None:
    witch = ArtifactSet(nanoka_id=15006, name="Crimson Witch of Flames",
                        piece_thresholds=[2, 4], available_ranks=[4, 5])
    db.add(witch)
    await db.flush()
    db.add(ArtifactSetAffix(
        artifact_set_id=str(witch.id), position=0, pieces_required=2, name="", description="",
        add_props=[{"prop_type": "FIGHT_PROP_FIRE_ADD_HURT", "value": 0.15}, _NONE],
        param_list=[0.15, 0, 0, 0, 0, 0, 0, 0],
    ))
    db.add(ArtifactSetAffix(
        artifact_set_id=str(witch.id), position=1, pieces_required=4, name="", description="",
        add_props=[_NONE, _NONE], param_list=four_piece_params,
    ))
    await db.flush()


@pytest.mark.asyncio
async def test_set_effects_resolve_against_the_seeded_params(
    client: AsyncClient, db_session: AsyncSession,
):
    await _crimson_witch(db_session, [0.4, 0.15, 0.15, 0.5, 10, 0, 0, 0])

    response = await client.get("/api/v1/formula/set-effects")

    assert response.status_code == 200
    body = response.json()
    tiers = [t for t in body["tiers"] if t["set_id"] == 15006]
    # The static 2-piece is the kernel's already; only the conditional 4-piece is here.
    assert [t["pieces"] for t in tiers] == [4]
    witch = tiers[0]
    assert witch["status"] == "partial"
    assert witch["set_name"] == "Crimson Witch of Flames"
    assert "CrimsonWitchOfFlames/index.tsx" in witch["citation"]
    stack = next(e for e in witch["bonus"]["effects"] if e["stat"] == "dmg_bonus")
    assert stack["value"] == pytest.approx(0.075)
    assert witch["bonus"]["conditions"][0]["default"] == 3
    assert witch["bonus"]["unmodelled"][0]["reason"].startswith("transformative")


@pytest.mark.asyncio
async def test_a_reseeded_list_that_changed_is_withheld(
    client: AsyncClient, db_session: AsyncSession,
):
    await _crimson_witch(db_session, [0.4, 0.15, 0.15, 0.6, 10, 0, 0, 0])

    body = (await client.get("/api/v1/formula/set-effects")).json()

    witch = next(t for t in body["tiers"] if t["set_id"] == 15006)
    assert witch["status"] == "stale"
    assert witch["bonus"]["effects"] == []
    assert "param_list changed" in witch["problem"]


async def _member(db: AsyncSession, nanoka_id: str, element: Element | None) -> str:
    character = Character(
        nanoka_id=nanoka_id, name=f"member {nanoka_id}", element=element,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FOUR_STAR,
        base_hp=1.0, base_atk=1.0, base_def=1.0, base_crit_rate=0.05, base_crit_dmg=0.5,
        prop_curves={}, ascension_stats=[],
    )
    db.add(character)
    await db.flush()
    return str(character.id)


@pytest.mark.asyncio
async def test_resonance_reads_each_members_element(
    client: AsyncClient, db_session: AsyncSession,
):
    ids = [
        await _member(db_session, "90000001", Element.PYRO),
        await _member(db_session, "90000002", Element.PYRO),
        await _member(db_session, "90000003", Element.CRYO),
        await _member(db_session, "90000004", Element.CRYO),
    ]

    response = await client.get("/api/v1/formula/resonance", params={"character_id": ids})

    assert response.status_code == 200
    body = response.json()
    assert body["team_size"] == 4
    assert body["elements"] == {"pyro": 2, "cryo": 2}
    assert [r["key"] for r in body["active"]] == ["fervent_flames", "shattering_ice"]
    ice = body["active"][1]
    assert ice["bonus"]["conditions"][0]["default"] == 0
    assert body["note"] is None


@pytest.mark.asyncio
async def test_a_short_team_says_why_it_has_none(
    client: AsyncClient, db_session: AsyncSession,
):
    ids = [
        await _member(db_session, "90000011", Element.PYRO),
        await _member(db_session, "90000012", Element.PYRO),
        await _member(db_session, "90000013", None),
    ]

    body = (await client.get("/api/v1/formula/resonance", params={"character_id": ids})).json()

    assert body["active"] == []
    assert body["team_size"] == 2
    assert "needs 4" in body["note"]


@pytest.mark.asyncio
async def test_a_repeated_member_is_refused(client: AsyncClient, db_session: AsyncSession):
    one = await _member(db_session, "90000021", Element.HYDRO)

    response = await client.get(
        "/api/v1/formula/resonance", params={"character_id": [one, one]},
    )

    assert response.status_code == 422
